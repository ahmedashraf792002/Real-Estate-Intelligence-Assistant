# python -m scraper urls | darglobal | projects | pages | listings | push | all
import argparse

from rag import config, database, schema

from .darglobal import scrape_darglobal
from .fetcher import Blocked, Fetcher
from .sitemaps import collect_urls
from .pages import scrape_pages
from .wasalt import scrape_listings, scrape_projects


def push_to_database():
    # upload the scraped pages to supabase postgres (running it again updates the rows)
    schema.create_tables()
    docs, projects = database.read_pages()
    print("documents:", database.save_documents(docs))
    print("projects:", database.save_projects(projects))
    print("next: python -m rag.indexing")


parser = argparse.ArgumentParser(prog="scraper")
parser.add_argument("command", choices=["urls", "darglobal", "projects", "pages", "listings", "push", "all"])
parser.add_argument("--n", type=int, default=3000, help="how many listings (0 = all of them)")
parser.add_argument("--lang", choices=["en", "ar", "both"], default="en", help="listing language (the same ad exists in both)")
parser.add_argument("--kinds", default="static,category", help="pages: sitemap kinds to scrape: static,category,rental_srp,rental_pdp,product")
parser.add_argument("--limit", type=int, help="max pages in this run")
parser.add_argument("--delay", type=float, default=2.0, help="seconds between wasalt requests")
parser.add_argument("--browser", action="store_true", help="retry blocked pages in a real browser")
parser.add_argument("--urls-file", help="text file with project links (one per line), added to the project links")
args = parser.parse_args()

steps = ["urls", "darglobal", "projects", "pages", "listings", "push"] if args.command == "all" else [args.command]
WASALT_STEPS = {"projects", "pages", "listings"}
fetcher = Fetcher(delay=(args.delay, args.delay * 2), use_browser=args.browser)
blocked = None
try:
    for step in steps:
        print(f"\n=== {step} ===")
        if blocked and step in WASALT_STEPS:
            print("skipped: wasalt asked for human verification earlier in this run")
            continue
        if step == "push" and args.command == "all" and not config.DATABASE_URL:
            print("skipped: DATABASE_URL is not set. The data is in data/raw/data, build the local index with:\n"
                  "  python -m rag.indexing --source local --target local")
            continue
        try:
            if step == "urls":
                collect_urls()
            elif step == "darglobal":
                scrape_darglobal(args.limit)
            elif step == "projects":
                scrape_projects(fetcher, args.limit, args.urls_file)
            elif step == "pages":
                scrape_pages(fetcher, [k.strip() for k in args.kinds.split(",") if k.strip()], args.limit)
            elif step == "listings":
                scrape_listings(fetcher, args.n, args.lang)
            elif step == "push":
                push_to_database()
        except Blocked as e:
            # one site refused: do not go on with its other steps, but finish the rest (darglobal, push)
            blocked = e
            print("\nSTOPPED:", e)
finally:
    fetcher.close()
if blocked:
    print("\nFinished with a block: the data collected before it is saved and can be used.")
    raise SystemExit(2)
