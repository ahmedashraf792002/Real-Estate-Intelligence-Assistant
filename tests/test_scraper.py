import json

from scraper import fetcher, wasalt
from scraper.fetcher import Fetcher, JsonlStore, explain_page


def page(props):
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": props}})}</script></html>'


GOOD = page({"compoundDetails": {"data": {
    "id": 5, "projectInfo": {"title": " شمس الرياض ", "city": "الرياض", "salePriceMin": 100, "salePriceMax": 200, "labels": [{"name": "للبيع"}]},
    "unitsAvailable": {"available": 3, "total": 4}, "contactDetails": {"arSellerName": "دار الأركان"}}},
    "compoundUnitListDetails": {"properties": [{"id": 1, "propertyInfo": {"title": "أرض", "salePrice": 100}, "attributes": []}]}})
SOFT_BLOCK = page({"statusCode": 200})  # status 200 and __NEXT_DATA__, but no project inside


def test_parse_project():
    p = wasalt.parse_project(GOOD, "u")
    assert p["name"] == "شمس الرياض" and p["developer"] == "دار الأركان" and p["units_available"] == 3 and len(p["units"]) == 1


def test_parse_project_after_a_layout_change():
    assert wasalt.parse_project(page({"deep": {"x": {"id": 9, "projectInfo": {"title": "X"}}}}), "u")["name"] == "X"


def test_blocked_page_is_none_and_explained():
    assert wasalt.parse_project(SOFT_BLOCK, "u") is None
    assert "soft-blocked" in explain_page(SOFT_BLOCK)
    assert "Cloudflare" in explain_page("<html>Just a moment...</html>")
    assert "no __NEXT_DATA__" in explain_page("<html></html>")


def test_parse_listing_and_doc():
    html = page({"listing": {"propertyInfo": {"title": "شقة", "salePrice": 500000, "propertyFor": "sale", "propertySubType": "apartment"},
                             "attributes": [{"key": "noOfBedrooms", "value": 3}]}})
    listing = wasalt.parse_listing(html, "u")
    assert listing["bedrooms"] == 3 and "500,000" in wasalt.listing_to_doc(listing)["text"]


def test_listing_group_ignores_language_prefix():
    assert wasalt.listing_group("https://wasalt.sa/en/property/sale/villa/x-1") == ("sale", "villa")
    assert wasalt.listing_group("https://wasalt.sa/ar/property/rent/apartment/y") == ("rent", "apartment")
    assert wasalt.listing_group("https://wasalt.sa/project/riyadh/z") is None


class Reply:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.headers = status, text, {}


def fake_session(monkeypatch, replies):
    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            return replies.pop(0)
    monkeypatch.setattr(fetcher.requests, "Session", Session)


def test_waits_longer_after_each_failure_then_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(fetcher, "RAW", tmp_path)
    sleeps = []
    monkeypatch.setattr(fetcher.time, "sleep", sleeps.append)
    fake_session(monkeypatch, [Reply(200, SOFT_BLOCK), Reply(429), Reply(200, GOOD)])
    project, reason = Fetcher(delay=(0, 0)).get("u", lambda html: wasalt.parse_project(html, "u"))
    assert project["name"] == "شمس الرياض" and reason == ""
    assert sleeps[0] >= 8 and sleeps[1] >= 16
    assert not (tmp_path / "debug").exists()  # nothing is written to disk for bad pages


def test_404_is_not_retried(monkeypatch):
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
    replies = [Reply(404)]
    fake_session(monkeypatch, replies)
    data, reason = Fetcher().get("u", lambda html: html)
    assert data is None and reason == "HTTP 404" and replies == []


def test_store_continues_after_a_stop(tmp_path):
    path = tmp_path / "x.jsonl"
    JsonlStore(path).add({"url": "1", "v": 1})
    again = JsonlStore(path)
    assert "1" in again and len(again) == 1


def test_projects_finds_links_itself_and_saves_them(monkeypatch, tmp_path, capsys):
    from scraper import wasalt, fetcher as fe
    monkeypatch.setattr(wasalt, "RAW", tmp_path / "raw"); monkeypatch.setattr(wasalt, "URLS", tmp_path / "raw" / "urls")
    monkeypatch.setattr(wasalt, "PAGES", tmp_path / "raw" / "data")
    monkeypatch.setattr(wasalt, "find_project_links", lambda: ["https://wasalt.sa/project/a/b-1"])

    class Fake:
        def get(self, url, parse):
            return None, "test"
    wasalt.scrape_projects(Fake())
    assert (tmp_path / "raw" / "urls" / "wasalt_project_urls.txt").read_text() == "https://wasalt.sa/project/a/b-1"
    assert "FAILED https://wasalt.sa/project/a/b-1" in capsys.readouterr().out
    assert not (tmp_path / "raw" / "debug").exists()


def test_projects_without_any_link_says_so(monkeypatch, tmp_path, capsys):
    from scraper import wasalt
    monkeypatch.setattr(wasalt, "URLS", tmp_path / "urls")
    monkeypatch.setattr(wasalt, "find_project_links", lambda: [])
    wasalt.scrape_projects(object())
    assert "No project links found" in capsys.readouterr().out


# ---- pages, listings in full, robots.txt, sitemap kinds

def test_parse_page_keeps_text_and_drops_menus():
    from scraper.pages import parse_page
    html = ("<html><head><title>About Wasalt</title><meta name='description' content='Saudi property platform'></head><body>"
            "<nav>HOME MENU</nav><h1>About us</h1><p>" + "Wasalt connects buyers and sellers across Saudi Arabia. " * 4 + "</p>"
            "<script>var x=1</script><footer>FOOTER LINKS</footer></body></html>")
    row = parse_page(html, "https://wasalt.sa/about")
    assert row["title"] == "About Wasalt" and "Wasalt connects buyers" in row["text"] and "Saudi property platform" in row["text"]
    assert "HOME MENU" not in row["text"] and "FOOTER" not in row["text"] and "var x" not in row["text"]
    assert parse_page("<html><body><p>Just a moment</p></body></html>", "u") is None  # empty shell / block page


def test_all_listings_one_language_no_duplicates(monkeypatch, tmp_path):
    from scraper import wasalt
    monkeypatch.setattr(wasalt, "URLS", tmp_path)
    urls = [f"https://wasalt.sa/en/property/sale/villa/v-{i}0000" for i in range(1, 6)]
    urls += [f"https://wasalt.sa/property/sale/فيلا/ف-{i}0000" for i in range(1, 6)]      # same ads in Arabic
    urls += ["https://wasalt.sa/en/property/rent/apartment/a-90000", "https://wasalt.sa/about"]
    (tmp_path / "wasalt.txt").write_text("\n".join(urls), encoding="utf-8")
    assert len(wasalt.pick_listing_urls(0)) == 6                       # english only, all of them
    assert len(wasalt.pick_listing_urls(0, "both")) == 6               # ids already seen in english are not repeated
    assert len(wasalt.pick_listing_urls(0, "ar")) == 5
    assert len(wasalt.pick_listing_urls(2)) == 2


def test_robots_txt_is_obeyed(monkeypatch):
    f = Fetcher()

    class R:
        status_code, text = 200, "User-agent: *\nDisallow: /private/\n"
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: R())
    data, reason = f.get("https://wasalt.sa/private/x", lambda html: "never")
    assert data is None and reason == "disallowed by robots.txt"
    assert f.allowed("https://wasalt.sa/about")


def test_sitemap_urls_are_saved_per_kind(monkeypatch, tmp_path):
    from scraper import sitemaps
    monkeypatch.setattr(sitemaps, "URLS", tmp_path)
    maps = {"https://cdn.wasalt.sa/sitemap/static_sitemap_en_sa.xml.gz": ["https://wasalt.sa/en/about"],
            "https://cdn.wasalt.sa/sitemap/rental_srp_sitemap_ar_sa.xml.gz": ["https://wasalt.sa/ar/rent/riyadh"]}
    monkeypatch.setattr(sitemaps, "robots_sitemaps", lambda base: list(maps) if "wasalt" in base else [])
    monkeypatch.setattr(sitemaps, "walk", lambda m, *a: maps.get(m, []))
    sitemaps.collect_urls()
    assert (tmp_path / "wasalt_static.txt").read_text() == "https://wasalt.sa/en/about"
    assert (tmp_path / "wasalt_rental_srp.txt").exists()



def test_human_verification_page_stops_the_run_without_retrying(monkeypatch):
    import pytest
    page_html = "<html><title>لحظة…</title>إجراء التحقق من الأمان cloudflare</html>"
    assert "Cloudflare" in explain_page(page_html)
    fake_session(monkeypatch, [Reply(200, page_html)])
    f = Fetcher(retries=4)
    monkeypatch.setattr(f, "allowed", lambda url: True)
    with pytest.raises(fetcher.Blocked):
        f.get("https://wasalt.sa/x", lambda html: None)


def test_all_skips_wasalt_steps_after_a_block_but_runs_the_rest(monkeypatch, tmp_path):
    # run `python -m scraper all` with fake steps: projects is blocked, pages/listings are skipped, darglobal and push still run
    import runpy, sys
    from scraper import fetcher as fe
    calls = []
    import scraper.sitemaps, scraper.darglobal, scraper.wasalt, scraper.pages
    monkeypatch.setattr(scraper.sitemaps, "collect_urls", lambda: calls.append("urls"))
    monkeypatch.setattr(scraper.darglobal, "scrape_darglobal", lambda limit=None: calls.append("darglobal"))
    def blocked(*a, **k):
        calls.append("projects"); raise fe.Blocked("verification page")
    monkeypatch.setattr(scraper.wasalt, "scrape_projects", blocked)
    monkeypatch.setattr(scraper.pages, "scrape_pages", lambda *a, **k: calls.append("pages"))
    monkeypatch.setattr(scraper.wasalt, "scrape_listings", lambda *a, **k: calls.append("listings"))
    monkeypatch.setattr(sys, "argv", ["scraper", "all"])
    import pytest
    with pytest.raises(SystemExit) as e:
        runpy.run_module("scraper", run_name="__main__")
    assert e.value.code == 2
    assert calls == ["urls", "darglobal", "projects"]   # pages and listings skipped; push skipped (no DATABASE_URL)


# ---- stored rows, dead links, launcher

def test_store_reads_text_with_unicode_line_separators(tmp_path):
    # U+2028 / U+2029 / U+0085 inside a page text must not cut the json line (str.splitlines() would)
    path = tmp_path / "x.jsonl"
    JsonlStore(path).add({"url": "1", "text": "a\u2028b\u2029c\x85d"})
    again = JsonlStore(path)
    assert len(again) == 1 and again.rows["1"]["text"] == "a\u2028b\u2029c\x85d"


def test_store_drops_a_line_cut_by_a_stopped_run(tmp_path, capsys):
    path = tmp_path / "x.jsonl"
    path.write_text(json.dumps({"url": "1"}) + "\n" + '{"url": "2", "text": "cut he', encoding="utf-8")
    store = JsonlStore(path)
    assert "1" in store and "2" not in store
    assert "broken line" in capsys.readouterr().out
    store.add({"url": "3"})
    assert len(JsonlStore(path)) == 2   # the file was repaired: the new row did not stick to the cut line


def test_404_is_retried_and_not_remembered(monkeypatch):
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
    replies = [Reply(404), Reply(404)]
    fake_session(monkeypatch, replies)
    f = Fetcher()
    monkeypatch.setattr(f, "allowed", lambda url: True)
    url = "https://wasalt.sa/gone"
    assert f.get(url, lambda html: html) == (None, "HTTP 404")
    assert f.get(url, lambda html: html) == (None, "HTTP 404")
    assert len(replies) == 0
    assert url not in f.dead


def test_many_404_in_a_row_do_not_cause_a_long_rest(monkeypatch):
    sleeps = []
    monkeypatch.setattr(fetcher.time, "sleep", sleeps.append)
    fake_session(monkeypatch, [Reply(404) for _ in range(8)])
    f = Fetcher()
    monkeypatch.setattr(f, "allowed", lambda url: True)
    for i in range(8):
        assert f.get(f"https://wasalt.sa/x{i}", lambda html: html)[0] is None
    assert sleeps == []


def test_project_text_has_no_wrong_unit_area_and_no_repeated_units():
    unit = {"title": "دوبلكس 182 متر مربع", "price": 800000, "currency": "ر.س", "area": 6, "area_unit": "م²"}
    text = wasalt.project_to_doc({"name": "X", "url": "u", "address": "الأحساء", "units": [dict(unit)] * 3})["text"]
    assert text.count("دوبلكس 182 متر مربع") == 1 and "المساحة" not in text


def test_launcher_script_runs_the_scraper_command_line(monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path

    import pytest
    monkeypatch.setattr(sys, "argv", ["scrape.py", "--help"])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "scrape.py"), run_name="__main__")
    assert e.value.code == 0 and "listings" in capsys.readouterr().out


def test_cloudflare_check_page_is_not_saved_as_a_page():
    from scraper.pages import parse_page
    check = ("<html><head><title>لحظة…</title></head><body><p>إجراء التحقق من الأمان</p><p>"
             "يستخدم هذا الموقع خدمة أمنية للحماية من برامج الروبوتات الضارة. يتم عرض هذه الصفحة بينما يتحقق الموقع.</p>"
             "<p>Ray ID: a5d6d4541e155da5</p><p>الأداء والأمان من Cloudflare</p></body></html>")
    assert parse_page(check, "https://auction.wasalt.sa/x", "Wasalt auction") is None

