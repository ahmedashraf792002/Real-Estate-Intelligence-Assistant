import hashlib
import json
import random
import re
import time

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from rag.config import DATA_DIR

# everything the scraper saves lives in data/raw
RAW = DATA_DIR / "raw"
URLS = RAW / "urls"   # page links
PAGES = RAW / "data"  # scraped pages, one json line per page
DEAD_FILE = None  # 404/410 links are retried; persistent dead-url caching is disabled
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


class Blocked(Exception):
    # the site shows a human-verification page (Cloudflare / captcha): we stop, we do not work around it
    pass


NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def next_data(html):
    m = NEXT_DATA.search(html)
    return json.loads(m.group(1)) if m else None


def explain_page(html):
    # say WHY a page could not be parsed
    low = html[:30000].lower()
    for text, label in (("just a moment", "Cloudflare challenge"), ("cf-chl", "Cloudflare challenge"), ("captcha", "captcha"),
                        ("challenges.cloudflare.com", "Cloudflare challenge"), ("turnstile", "Cloudflare challenge"),
                        ("التحقق من الأمان", "Cloudflare challenge"),
                        ("access denied", "access denied"), ("too many requests", "rate limited")):
        if text in low:
            return "blocked: " + label
    m = NEXT_DATA.search(html)
    if not m:
        return f"no __NEXT_DATA__ ({len(html)} chars)"
    try:
        props = json.loads(m.group(1))["props"]["pageProps"]
    except Exception:
        return "__NEXT_DATA__ is not valid json"
    return "soft-blocked (empty page), pageProps keys: " + (", ".join(list(props)[:8]) or "none")


class Fetcher:
    # downloads pages slowly, waits longer after every failure, can use a real browser as a last try
    def __init__(self, delay=(2, 4), retries=4, use_browser=False):
        self.delay = delay
        self.retries = retries
        self.use_browser = use_browser
        self.session = None
        self.page = None
        self.playwright = None
        self.browser = None
        self.robots = {}
        self.dead = set()  # DEAD_FILE is None, so no URLs are cached as dead

    def allowed(self, url):
        # obey robots.txt of every site (if it can not be read, everything is allowed)
        u = urlparse(url)
        if not u.netloc:
            return True
        host = f"{u.scheme}://{u.netloc}"
        if host not in self.robots:
            rules = None
            try:
                r = requests.get(host + "/robots.txt", headers={"User-Agent": USER_AGENTS[0]}, timeout=20)
                if r.status_code == 200 and "user-agent" in r.text.lower():
                    rules = RobotFileParser()
                    rules.parse(r.text.splitlines())
            except Exception:
                pass
            self.robots[host] = rules
        rules = self.robots[host]
        return True if rules is None else rules.can_fetch("*", url)

    def new_session(self):
        # new cookies and another user agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "ar,en;q=0.8"})

    def try_requests(self, url, parse):
        # returns (data, reason, seconds_to_wait)
        if self.session is None:
            self.new_session()
        try:
            r = self.session.get(url, timeout=40)
        except requests.RequestException as e:
            return None, "network error: " + str(e)[:80], None
        if r.status_code != 200:
            wait = r.headers.get("Retry-After", "")
            return None, f"HTTP {r.status_code}", float(wait) if wait.isdigit() else None
        data = parse(r.text)
        if data is None:
            return None, explain_page(r.text), None
        return data, "", None

    def try_browser(self, url, parse):
        try:
            if self.page is None:
                from playwright.sync_api import sync_playwright
                self.playwright = sync_playwright().start()
                self.browser = self.playwright.chromium.launch()
                self.page = self.browser.new_page(user_agent=USER_AGENTS[0], locale="ar-SA")
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(2500)
            html = self.page.content()
        except Exception as e:
            return None, "browser error: " + str(e).splitlines()[0][:80]
        data = parse(html)
        return data, "" if data is not None else "browser: " + explain_page(html)

    def get(self, url, parse, browser_first=False):
        # returns (data, reason). data is None when every try failed
        if url in self.dead:
            return None, "gone (404/410 before), skipped"
        if not self.allowed(url):
            return None, "disallowed by robots.txt"
        reason = "not tried"
        for attempt in range(self.retries):
            if browser_first and self.use_browser:  # pages drawn by javascript: skip plain requests
                data, reason = self.try_browser(url, parse)
                wait = None
            else:
                data, reason, wait = self.try_requests(url, parse)
                if data is None and self.use_browser and attempt >= 1:
                    data, reason = self.try_browser(url, parse)
            if data is None and ("blocked: Cloudflare" in reason or "blocked: captcha" in reason):
                raise Blocked(f"{urlparse(url).netloc} asks for human verification ({reason}). Stopped on purpose: "
                              "automated access is not allowed there. Use the data you already have, save pages by hand "
                              "from your own browser, or ask the site for data access.")
            if data is not None:
                time.sleep(random.uniform(*self.delay))
                return data, ""
            if reason in ("HTTP 404", "HTTP 410"):
                break
            wait = wait or min(180, 8 * 2 ** attempt)
            print(f"    {reason}, waiting {wait:.0f}s ({attempt + 1}/{self.retries})")
            time.sleep(wait + random.uniform(0, 3))
            self.new_session()
        return None, reason

    def close(self):
        for thing in (self.browser, self.playwright):
            try:
                if thing is self.browser:
                    thing.close()
                elif thing:
                    thing.stop()
            except Exception:
                pass


class JsonlStore:
    # saves one json row per line, so a stopped run can continue where it stopped
    def __init__(self, path, key="url"):
        self.path = path
        self.key = key
        self.rows = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            good, broken = [], 0
            # split on "\n" only: str.splitlines() also cuts at U+2028 / U+2029 / U+0085,
            # which appear inside page texts and would break a valid json line in two
            for line in path.read_text(encoding="utf-8").split("\n"):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    self.rows[row[key]] = row
                    good.append(line)
                except (ValueError, KeyError, TypeError):
                    broken += 1  # a line cut by a stopped run
            if broken:
                print(f"  {path.name}: {broken} broken line(s) dropped (they will be fetched again)")
                path.write_text("\n".join(good) + "\n", encoding="utf-8")

    def __contains__(self, key):
        return key in self.rows

    def __len__(self):
        return len(self.rows)

    def add(self, row):
        self.rows[row[self.key]] = row
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def all(self):
        return list(self.rows.values())

