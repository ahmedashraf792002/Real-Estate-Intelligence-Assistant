import re
import time

from .fetcher import PAGES, URLS, JsonlStore

# text of the page without menus and footers
JS = """() => {
  document.querySelectorAll('script,style,noscript,svg,nav,footer,header,form').forEach(e=>e.remove());
  return document.body.innerText;
}"""


def clean(text):
    text = re.sub(r"[ \t]+", " ", text or "")
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def scrape_darglobal(limit=None):
    from playwright.sync_api import sync_playwright

    source = URLS / "darglobal.txt"
    if not source.exists():
        raise SystemExit("data/raw/urls/darglobal.txt is missing, run: python -m scraper urls")
    urls = [u.strip() for u in source.read_text(encoding="utf-8").splitlines() if u.strip()]
    store = JsonlStore(PAGES / "darglobal.jsonl")
    seen_text = {r["text"] for r in store.all()}
    todo = [u for u in urls if u not in store][:limit]
    print(f"DarGlobal: {len(store)} saved, {len(todo)} to fetch")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36")
        for i, url in enumerate(todo, 1):
            # open the page (3 tries)
            opened = False
            for attempt in range(3):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                    opened = True
                    break
                except Exception as e:
                    print("   retry", attempt + 1, str(e).splitlines()[0][:80])
                    time.sleep(3)
            if not opened:
                print(f"[{i}/{len(todo)}] FAILED {url}")
                continue
            # save it
            text = clean(page.evaluate(JS))
            if len(text) < 200 or text in seen_text:
                print(f"[{i}/{len(todo)}] skipped (short or duplicate) {url}")
                continue
            seen_text.add(text)
            store.add({"source": "DarGlobal", "url": url, "title": page.title(), "text": text})
            print(f"[{i}/{len(todo)}] saved {len(store)}: {url}")
            time.sleep(1)
        browser.close()

    print("DarGlobal pages saved:", len(store))
