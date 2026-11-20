# Is the right page found, and is the answer based on it?
#   python -m rag.evaluation                  (search quality, no API key needed)
#   python -m rag.evaluation --generate 5     (also checks 5 full answers)
#   python -m rag.evaluation --set data/eval_set.json
# eval set item: {"question": "...", "expected_urls": ["https://..."], "expected_terms": ["Marea"]}
import argparse
import json
import random
import re
from collections import defaultdict

from . import config, database
from .pipeline import Pipeline


def short_title(title):
    return re.split(r"\s[|\-–—]\s", title)[0].strip()


def make_questions(docs, n=40):
    # quick test set made from page titles (easy questions, only a smoke test)
    urls_by_title = defaultdict(set)
    for d in docs:
        if d.get("title"):
            urls_by_title[short_title(d["title"])].add(d["url"])
    titles = sorted(t for t in urls_by_title if 3 <= len(t) <= 60)
    picked = random.Random(7).sample(titles, min(n, len(titles)))
    return [{"question": f"Tell me about {t}", "expected_urls": sorted(urls_by_title[t]), "expected_terms": [t]}
            for t in picked]


def check_search(retriever, items, ks=(1, 3, 6)):
    hits = {k: 0 for k in ks}
    reciprocal_sum, missed = 0, []
    for item in items:
        urls = list(dict.fromkeys(c["url"] for c in retriever.search(item["question"], k=max(ks))))
        rank = next((i for i, u in enumerate(urls, 1) if u in item["expected_urls"]), None)
        for k in ks:
            hits[k] += bool(rank and rank <= k)
        reciprocal_sum += 1 / rank if rank else 0
        if rank is None:
            missed.append(item["question"])
    n = max(1, len(items))
    result = {"questions": len(items), "mrr": round(reciprocal_sum / n, 3)}
    result.update({f"hit@{k}": round(hits[k] / n, 3) for k in ks})
    return result, missed


def check_answers(pipeline, items):
    # does the answer contain the expected name, and did we return sources?
    has_term = has_sources = 0
    for item in items:
        answer, sources = "", []
        for event in pipeline.stream([{"role": "user", "content": item["question"]}]):
            if event["type"] == "delta":
                answer += event["text"]
            elif event["type"] == "sources":
                sources = event["sources"]
        has_term += any(t.lower() in answer.lower() for t in item.get("expected_terms", []))
        has_sources += bool(sources)
    n = max(1, len(items))
    return {"answers": len(items), "mentions_expected_name": round(has_term / n, 3), "returned_sources": round(has_sources / n, 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set")
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--generate", type=int, default=0)
    args = parser.parse_args()

    pipeline = Pipeline.from_env()
    default_set = config.DATA_DIR / "eval_set.json"
    if args.set:
        items = json.loads(open(args.set, encoding="utf-8").read())
    elif default_set.exists():
        items = json.loads(default_set.read_text(encoding="utf-8"))
    else:
        items = make_questions(database.load_documents()[0], args.n)

    print(f"index={pipeline.backend} vectors={pipeline.retriever.dense} chunks={len(pipeline.retriever.chunks)}")
    result, missed = check_search(pipeline.retriever, items)
    print("search:", json.dumps(result))
    for q in missed[:10]:
        print("  missed:", q)
    if args.generate:
        print("answers:", json.dumps(check_answers(pipeline, items[:args.generate])))


if __name__ == "__main__":
    main()
