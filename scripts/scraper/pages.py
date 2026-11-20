# Any Wasalt page that is not a project or a listing: static pages, help, categories, rentals
import re

from .fetcher import PAGES, URLS, JsonlStore
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button", "select"}
BLOCK = {"p", "div", "li", "ul", "ol", "tr", "br", "section", "article", "table", "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6"}


class TextReader(HTMLParser):
    # visible text of a page, without menus, footers, scripts
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth, self.parts, self.title, self.description, self.in_title = 0, [], "", "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta" and (a.get("name") == "description" or a.get("property") == "og:description"):
            self.description = self.description or (a.get("content") or "")
        if tag in SKIP:
            self.skip_depth += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip_depth:
            self.parts.append(data)


def page_text(html):
    reader = TextReader()
    reader.feed(html)
    text = re.sub(r"[ \t ]+", " ", "".join(reader.parts))
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return reader.title.strip(), reader.description.strip(), text


def parse_page(html, url="", source="Wasalt page", min_chars=120):
    title, description, text = page_text(html)
    if title.startswith(("لحظة", "Just a moment")) or ("ray id" in text.lower() and "cloudflare" in text.lower()):
        return None  # a Cloudflare check page: the fetcher reports it as blocked and stops, it is not saved as data
    if description and description not in text:
        text = description + "\n" + text
    if len(text) < min_chars:
        return None  # empty shell or a block page: the fetcher explains it and retries
    return {"source": source, "url": url, "title": title or url, "text": text}


def read_urls(kind):
    path = URLS / f"wasalt_{kind}.txt"
    if not path.exists():
        print(f"  {path} is missing (run: python -m scraper urls)")
        return []
    return [u.strip() for u in path.read_text(encoding="utf-8").splitlines() if u.strip()]


def scrape_pages(fetcher, kinds, limit=None, source="Wasalt page", urls=None, name="wasalt_pages"):
    if urls is None:
        urls = list(dict.fromkeys(u for kind in kinds for u in read_urls(kind)))
    store = JsonlStore(PAGES / f"{name}.jsonl")
    seen_text = {r["text"] for r in store.all()}
    todo = [u for u in urls if u not in store][:limit]
    print(f"{source}: {len(urls)} links, {len(store)} saved, {len(todo)} to fetch")
    for i, url in enumerate(todo, 1):
        row, reason = fetcher.get(url, lambda html, url=url: parse_page(html, url, source), browser_first=False)
        if not row:
            print(f"[{i}/{len(todo)}] FAILED {url}\n    reason: {reason}")
        elif row["text"] in seen_text:
            print(f"[{i}/{len(todo)}] duplicate text, skipped {url}")
        else:
            seen_text.add(row["text"])
            store.add(row)
            print(f"[{i}/{len(todo)}] saved {len(store)}: {row['title'][:60]}")
    print(f"{source} saved:", len(store))
