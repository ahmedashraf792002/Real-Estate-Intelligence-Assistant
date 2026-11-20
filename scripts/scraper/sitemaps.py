import gzip
import re
from collections import Counter, defaultdict

import requests

from .fetcher import URLS


def read(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    data = r.content
    try:
        data = gzip.decompress(data)
    except Exception:
        pass
    return data.decode("utf-8", "ignore")


def walk(url, seen=None, depth=0):
    # urls of a sitemap, following nested sitemaps (.xml and .xml.gz)
    seen = seen if seen is not None else set()
    if url in seen or depth > 3:
        return []
    seen.add(url)
    try:
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", read(url))
    except Exception as e:
        print("  failed:", url, e)
        return []
    pages = []
    for loc in locs:
        pages += walk(loc, seen, depth + 1) if re.search(r"\.xml(\.gz)?$", loc) else [loc]
    return pages


def robots_sitemaps(base):
    try:
        return re.findall(r"(?im)^sitemap:\s*(\S+)", read(base + "/robots.txt"))
    except Exception:
        return []


def save(name, urls):
    # remove duplicates (with and without www)
    unique, seen = [], set()
    for u in urls:
        key = u.replace("://www.", "://").rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(u)
    URLS.mkdir(parents=True, exist_ok=True)
    (URLS / f"{name}.txt").write_text("\n".join(unique), encoding="utf-8")
    print(f"saved {len(unique):>6}  data/raw/urls/{name}.txt")
    return unique


def collect_urls():
    dar = ["https://www.darglobal.co.uk/sitemap.xml"] + robots_sitemaps("https://www.darglobal.co.uk")
    save("darglobal", [u for m in dict.fromkeys(dar) for u in walk(m)])

    wasalt_maps = robots_sitemaps("https://wasalt.sa") + ["https://cdn.wasalt.sa/sitemap/product_sitemap_en_sa.xml.gz"]
    everything, by_kind = [], defaultdict(list)
    for m in dict.fromkeys(wasalt_maps):
        found = walk(m)
        everything += found
        kind = re.search(r"/([a-z_]+?)_sitemap", m)  # .../static_sitemap_en_sa.xml.gz -> static
        by_kind[kind.group(1) if kind else "other"] += found
    wasalt = save("wasalt", everything)
    for kind, found in by_kind.items():
        save(f"wasalt_{kind}", found)
    save("wasalt_projects", [u for u in wasalt if "/project/" in u])
    print("wasalt url shapes:", Counter(re.sub(r"\d+", "N", "/".join(u.split("/")[3:6])) for u in wasalt).most_common(8))
