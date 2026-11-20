import numpy as np

from rag import evaluation
from rag.generation import build_messages
from rag.pipeline import Pipeline, build_catalog
from rag.retrieval import Retriever
from rag.text import tokens

CHUNKS = [
    {"id": 1, "url": "https://x/dubai", "title": "Marea Dubai", "source": "DarGlobal", "text": "Luxury villas in Dubai with private beach"},
    {"id": 2, "url": "https://x/riyadh", "title": "شمس الرياض", "source": "Wasalt", "text": "مشروع سكني في الرياض فلل وأراضي للبيع"},
    {"id": 3, "url": "https://x/about", "title": "About us", "source": "DarGlobal", "text": "Company history and careers"},
]


class FakeIndex:
    def has_vectors(self):
        return True

    def search(self, vec, k):
        return [(3, 0.9), (1, 0.1)]  # says "About us" is the closest


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail

    def stream_chat(self, messages):
        if self.fail:
            raise RuntimeError("all keys exhausted")
        yield "model", "fake"
        yield "delta", "Hello "
        yield "delta", "world"


def test_arabic_and_english_share_concept_tokens():
    assert "c_villa" in tokens("فلل") and "c_villa" in tokens("villas")
    assert "c_riyadh" in tokens("Riyadh") and "c_riyadh" in tokens("الرياض")


def test_keyword_search_in_both_languages():
    r = Retriever(CHUNKS)
    assert r.search("villas Dubai")[0]["id"] == 1
    assert r.search("فلل في الرياض")[0]["id"] == 2
    assert r.search("submarine") == []


def test_vector_and_keyword_results_are_merged():
    r = Retriever(CHUNKS, FakeIndex(), lambda q: np.zeros(2))
    ids = [c["id"] for c in r.search("villas Dubai", k=3)]
    assert r.dense and ids[0] == 1 and 3 in ids


def test_vector_search_error_falls_back_to_keywords():
    class Broken(FakeIndex):
        def search(self, vec, k):
            raise RuntimeError("database down")
    assert Retriever(CHUNKS, Broken(), lambda q: np.zeros(2)).search("villas Dubai")[0]["id"] == 1


def test_max_two_chunks_per_page():
    same = [{"id": i, "url": "https://x/same", "title": "villa", "source": "S", "text": "villa dubai"} for i in range(5)]
    assert len(Retriever(same).search("villa", k=5)) == 2


def test_catalog_with_missing_prices():
    text = build_catalog([{"name": "A", "price_min": 1000000, "price_max": 2000000, "currency": "SAR"}, {"name": "B"}])
    assert "1,000,000-2,000,000 SAR" in text and "price n/a" in text


def test_prompt_has_context_catalog_and_language_rule():
    messages = build_messages([{"role": "user", "content": "hi"}], CHUNKS[:1], "- Project A", "2026-11-20")
    system = messages[0]["content"]
    assert "Marea Dubai" in system and "Project A" in system and "English by default" in system and "Arabic" in system
    assert messages[-1] == {"role": "user", "content": "hi"}


def test_pipeline_sends_sources_then_text():
    p = Pipeline(Retriever(CHUNKS), "", {"built_at": "d"}, llm=FakeLLM())
    events = list(p.stream([{"role": "user", "content": "villas in Dubai"}]))
    assert [e["type"] for e in events] == ["sources", "model", "delta", "delta", "done"]
    assert events[0]["sources"][0]["url"] == "https://x/dubai"


def test_pipeline_model_failure_gives_an_error_event():
    p = Pipeline(Retriever(CHUNKS), llm=FakeLLM(fail=True))
    events = list(p.stream([{"role": "user", "content": "villas"}]))
    assert events[-2]["type"] == "error" and events[-1]["type"] == "done"


def test_short_follow_up_uses_previous_question():
    history = [{"role": "user", "content": "Tell me about Marea"}, {"role": "assistant", "content": "..."},
               {"role": "user", "content": "its price?"}]
    assert "Marea" in Pipeline.search_query(history)


def test_evaluation_numbers():
    items = [{"question": "villas Dubai", "expected_urls": ["https://x/dubai"]},
             {"question": "careers", "expected_urls": ["https://x/about"]},
             {"question": "villas Dubai", "expected_urls": ["https://x/nowhere"]}]
    result, missed = evaluation.check_search(Retriever(CHUNKS), items)
    assert result["questions"] == 3 and result["hit@1"] == 0.667 and len(missed) == 1


def test_questions_from_titles_group_same_title():
    docs = [{"title": "Marea | Dar Global", "url": "u1"}, {"title": "Marea | Dar Global", "url": "u2"}]
    assert evaluation.make_questions(docs, 5)[0]["expected_urls"] == ["u1", "u2"]
