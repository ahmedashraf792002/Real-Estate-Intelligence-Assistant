# One-time data collection. Not part of the app (the app and the Docker image only need src/).
#   uv run python scripts/scrape.py urls | darglobal | projects | pages | listings | push | all
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]   # `scraper` (this folder) and `rag` (src)
runpy.run_module("scraper", run_name="__main__", alter_sys=True)
