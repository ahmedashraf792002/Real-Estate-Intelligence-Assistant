# One-off: rewrite the "text" of data/raw/data/wasalt_projects.jsonl from the saved project data
# (fixes the wrong unit area and the repeated unit lines without scraping again).
#   uv run python scripts/rebuild_projects.py
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]
from scraper.fetcher import PAGES
from scraper.wasalt import project_to_doc

path = PAGES / "wasalt_projects.jsonl"
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
for row in rows:
    row["text"] = project_to_doc(row["project"])["text"]
path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
print("rewritten:", len(rows))
