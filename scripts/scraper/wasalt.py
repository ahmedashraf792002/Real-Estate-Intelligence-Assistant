import random
import re
from collections import defaultdict
from urllib.parse import urlparse

from .fetcher import RAW, URLS, PAGES, Blocked, JsonlStore, explain_page, next_data


# small helpers to read the json inside the page

def get(d, *path, default=None):
    # d["a"]["b"][0] without errors
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int) and p < len(d):
            d = d[p]
        else:
            return default
        if d is None:
            return default
    return d


def find_holder(obj, key, kind=dict):
    # first dict (any depth) that has `key` with a value of type `kind`
    if isinstance(obj, dict):
        if isinstance(obj.get(key), kind):
            return obj
        for v in obj.values():
            found = find_holder(v, key, kind)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_holder(v, key, kind)
            if found is not None:
                return found
    return None


def page_props(html):
    return get(next_data(html), "props", "pageProps")


# projects

def parse_project(html, url=""):
    props = page_props(html)
    if not isinstance(props, dict):
        return None
    holder = find_holder(props, "projectInfo")
    if not holder or not holder["projectInfo"]:
        return None  # a blocked page has no projectInfo
    info = holder["projectInfo"]

    units = []
    for u in get(props, "compoundUnitListDetails", "properties", default=[]):
        ui = u.get("propertyInfo", {})
        attrs = {a.get("key"): a.get("value") for a in u.get("attributes", [])}
        units.append({
            "unit_id": u.get("id"), "unit_no": u.get("unitNo"), "title": ui.get("title"), "type": ui.get("propertySubType"),
            "price": ui.get("salePrice") or ui.get("expectedRent"), "currency": ui.get("currencyType"),
            "area": get(u, "attributes", 0, "value"), "area_unit": ui.get("unitType"),
            "bedrooms": attrs.get("noOfBedrooms"), "bathrooms": attrs.get("noOfBathrooms"),
            "possession": ui.get("possessionType"), "description": ui.get("description"), "slug": ui.get("slug")})
    prices = [u["price"] for u in units if isinstance(u["price"], (int, float))]

    return {
        "id": holder.get("id"), "url": url, "name": (info.get("title") or "").strip(),
        "developer": get(holder, "contactDetails", "arSellerName") or get(holder, "developerInfo", "name"),
        "developer_about": get(holder, "developerInfo", "about"),
        "city": info.get("city"), "district": info.get("district"), "zone": info.get("zone"), "address": info.get("address"),
        "lat": get(holder, "location", "lat"), "lon": get(holder, "location", "lon"),
        "purpose": info.get("propertyFor"), "category": info.get("propertyMainTypeSlug"),
        "status": [x.get("name") for x in info.get("labels", [])], "completion_date": info.get("completionDate"),
        "price_min": info.get("salePriceMin"), "price_max": info.get("salePriceMax"), "currency": info.get("currencyType"),
        "units_available": get(holder, "unitsAvailable", "available"), "units_total": get(holder, "unitsAvailable", "total"),
        "description": (info.get("description") or "").strip(),
        "extra": {a.get("label"): a.get("value") for a in holder.get("additionalAttributes", [])},
        "brochures": [f"https://cdn.wasalt.com/{b.get('name')}" for b in get(holder, "propertyFiles", "brochure", default=[])],
        "updated_at": holder.get("updatedAt"), "units": units,
        "units_price_range_listed": [min(prices), max(prices)] if prices else None}


def project_to_doc(p):
    # text block for the knowledge base
    lines = [f"مشروع {p['name']}"]
    if p.get("developer"):
        lines.append(f"المطوّر: {p['developer']}")
    lines.append(f"الموقع: {p.get('address')}")
    if p.get("status"):
        lines.append("الحالة: " + "، ".join(p["status"]))
    if p.get("price_min"):
        lines.append(f"السعر: من {p['price_min']:,} إلى {(p.get('price_max') or p['price_min']):,} {p.get('currency') or ''}")
    if p.get("units_available") is not None:
        lines.append(f"عدد الوحدات المتاحة: {p['units_available']} من {p.get('units_total')}")
    lines += [f"{k}: {v}" for k, v in (p.get("extra") or {}).items() if v]
    if p.get("description"):
        lines.append("\nالوصف: " + p["description"])
    if p.get("units"):
        lines.append("\nأمثلة على الوحدات المتاحة:")
        # the area is in the title ("دوبلكس 182 متر مربع"): the parsed "area" field is really the first attribute
        # (the bedrooms), so it is not printed. Identical units are listed once.
        units = [f"- {u['title']} | السعر: {u['price']} {u['currency'] or ''}" for u in p["units"]]
        lines += list(dict.fromkeys(units))[:40]
    return {"source": "Wasalt", "url": p["url"], "title": p["name"], "text": "\n".join(lines)}


BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def find_project_links():
    # open the search pages in a browser and collect every /project/ link
    from playwright.sync_api import sync_playwright
    search = "https://wasalt.sa/sale/search?countryId=1&propertyFor={pf}&type={t}&project=true"
    links = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=BROWSER_UA, locale="ar-SA", viewport={"width": 1366, "height": 900})
        for pf, t in (("sale", "residential"), ("sale", "commercial"), ("rent", "residential"), ("rent", "commercial")):
            for n in range(1, 30):
                url = search.format(pf=pf, t=t) + (f"&page={n}" if n > 1 else "")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    try:
                        page.wait_for_selector("a[href*='/project/']", timeout=20000)
                    except Exception:
                        pass  # no links (yet): handled below
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print("  fail", url, str(e).splitlines()[0])
                    break
                for _ in range(12):
                    page.mouse.wheel(0, 3500)
                    page.wait_for_timeout(500)
                hrefs = page.eval_on_selector_all("a[href*='/project/']", "els=>els.map(e=>e.href)")
                if explain_page(page.content()).startswith("blocked"):
                    print(f"  {pf}/{t}: the site shows a human-verification page. Stopping the link search here (not bypassed).")
                    browser.close()
                    return list(links)
                if not hrefs and n == 1:
                    print(f"  no project links on {pf}/{t} (page title: {page.title()!r})")
                new = [h for h in hrefs if h not in links]
                links.update({h: 1 for h in hrefs})
                print(f"{pf}/{t} page {n}: +{len(new)} (total {len(links)})")
                if not new:
                    break
        browser.close()
    return list(links)


def scrape_projects(fetcher, limit=None, urls_file=None):
    # 1. find the project links with the browser (every run) and keep them in data/raw/urls/wasalt_project_urls.txt
    links_file = URLS / "wasalt_projects.txt"
    saved = links_file.read_text(encoding="utf-8").split() if links_file.exists() else []
    extra = []
    if urls_file:
        try:
            extra = [u.strip() for u in open(urls_file, encoding="utf-8") if "/project/" in u]
        except OSError:
            print(f"{urls_file} not found, ignored")
    urls = list(dict.fromkeys(saved + extra + find_project_links()))
    if not urls:
        print("No project links found.")
        return
    URLS.mkdir(parents=True, exist_ok=True)
    links_file.write_text("\n".join(urls), encoding="utf-8")
    # backward-compatible name used by older scripts and tests
    (URLS / "wasalt_project_urls.txt").write_text("\n".join(urls), encoding="utf-8")
    print(f"{len(urls)} project links saved in {links_file}")

    # each row = the text for the knowledge base + the structured project
    store = JsonlStore(PAGES / "wasalt_projects.jsonl")
    todo = [u for u in urls if u not in store][:limit]
    print(f"Wasalt projects: {len(store)} saved, {len(todo)} to fetch")

    failed = []
    for i, url in enumerate(todo, 1):
        project, reason = fetcher.get(url, lambda html, url=url: parse_project(html, url))
        if project:
            store.add({**project_to_doc(project), "project": project})
            print(f"[{i}/{len(todo)}] {project['name']} | {project['developer']} | {project['price_min']}-{project['price_max']}")
        else:
            failed.append(url)
            print(f"[{i}/{len(todo)}] FAILED {url}\n    reason: {reason}")

    if failed:
        print(f"{len(failed)} failed. Run the same command again later, only the missing ones are fetched.")
        print("Tip: add --browser to retry them in a real browser.")


# listings

def parse_listing(html, url=""):
    props = page_props(html)
    if not isinstance(props, dict):
        return None
    holder = find_holder(props, "propertyInfo")
    if not holder:
        return None
    info = holder["propertyInfo"]
    attr_holder = find_holder(props, "attributes", list)
    attrs = {x.get("key"): x.get("value") for x in (attr_holder["attributes"] if attr_holder else []) if isinstance(x, dict)}
    return {"url": url, "title": info.get("title"), "purpose": info.get("propertyFor"), "type": info.get("propertySubType"),
            "category": info.get("propertyMainType"), "price": info.get("salePrice") or info.get("expectedRent"),
            "rent_freq": info.get("rentFreq"), "currency": info.get("currencyType"), "city": info.get("city"),
            "district": info.get("district"), "address": info.get("address"),
            "area": attrs.get("carpetArea") or attrs.get("builtUpArea"), "area_unit": info.get("unitType"),
            "bedrooms": attrs.get("noOfBedrooms"), "bathrooms": attrs.get("noOfBathrooms"),
            "furnishing": info.get("furnishingType"), "possession": info.get("possessionType"),
            "description": (info.get("description") or "").strip()}


def listing_to_doc(r):
    lines = [r["title"] or "Listing", f"Purpose: {r['purpose']}  |  Type: {r['type']} ({r['category']})",
             f"Location: {r['address']}"]
    if r["price"]:
        price = f"{r['price']:,}" if isinstance(r["price"], (int, float)) else r["price"]
        lines.append(f"Price: {price} {r['currency'] or 'SAR'}" + (f" per {r['rent_freq']}" if r["rent_freq"] else ""))
    if r["area"]:
        lines.append(f"Area: {r['area']} {r['area_unit'] or ''}")
    if r["bedrooms"]:
        lines.append(f"Bedrooms: {r['bedrooms']}  Bathrooms: {r['bathrooms']}")
    if r["furnishing"]:
        lines.append(f"Furnishing: {r['furnishing']}")
    if r["description"]:
        lines.append("Description: " + r["description"][:800])
    return {"source": "Wasalt listing", "url": r["url"], "title": r["title"] or r["url"], "text": "\n".join(lines)}


def listing_group(url):
    # ("sale", "villa") from .../property/sale/villa/..., whatever the language prefix is
    parts = urlparse(url).path.strip("/").split("/")
    for i, part in enumerate(parts):
        if part in ("property", "properties") and i + 2 < len(parts) and parts[i + 1] in ("sale", "rent"):
            return parts[i + 1], parts[i + 2]
    return None


def listing_id(url):
    # the same ad exists in Arabic and English: the number at the end is the same
    m = re.search(r"(\d{4,})/?$", urlparse(url).path)
    return m.group(1) if m else url


def pick_listing_urls(n, lang="en"):
    # lang: en | ar | both.  n <= 0 means every listing
    source = URLS / "wasalt.txt"
    if not source.exists():
        raise SystemExit("data/raw/urls/wasalt.txt is missing, run: python -m scraper urls")
    urls = [u.strip() for u in source.read_text(encoding="utf-8").splitlines() if u.strip()]
    groups, seen_ids = defaultdict(list), set()
    for u in urls:
        english = urlparse(u).path.startswith("/en/")
        if not listing_group(u) or (lang == "en" and not english) or (lang == "ar" and english):
            continue
        if listing_id(u) in seen_ids:
            continue
        seen_ids.add(listing_id(u))
        groups[listing_group(u)].append(u)

    # nothing matched: show what the urls look like so the pattern can be fixed
    if not groups:
        shapes = defaultdict(int)
        for u in urls:
            shapes[re.sub(r"\d+", "N", "/".join(urlparse(u).path.split("/")[:4]))] += 1
        print("no listing urls like .../property/<sale|rent>/<type>/... The sitemap has these shapes:")
        for shape, count in sorted(shapes.items(), key=lambda x: -x[1])[:10]:
            print(f"  {count:>7}  {shape}")
        raise SystemExit("change listing_group() in scraper/wasalt.py to match one of them")

    # the same number from every group (sale/rent x type)
    print("listing groups:", {k: len(v) for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))})
    if n <= 0:
        return [u for v in groups.values() for u in v]
    rnd = random.Random(7)
    per_group = max(1, n // len(groups))
    picked = [u for v in groups.values() for u in rnd.sample(v, min(per_group, len(v)))]
    rnd.shuffle(picked)
    return picked[:n]


def scrape_listings(fetcher, n=3000, lang="en"):
    store = JsonlStore(PAGES / "wasalt_listings.jsonl")
    todo = [u for u in pick_listing_urls(n, lang) if u not in store]
    hours = len(todo) * (sum(fetcher.delay) / 2 + 1) / 3600
    print(f"Wasalt listings: {len(store)} saved, {len(todo)} to fetch (about {hours:.1f} hours, you can stop and run again)")
    for i, url in enumerate(todo, 1):
        listing, reason = fetcher.get(url, lambda html, url=url: parse_listing(html, url))
        if listing:
            store.add(listing_to_doc(listing))
            print(f"[{i}/{len(todo)}] {listing['type']} | {listing['district']} | {listing['price']}")
        else:
            print(f"[{i}/{len(todo)}] FAILED {url}\n    reason: {reason}")
    print("Wasalt listings saved:", len(store))
