# when one api key reaches its limit, the next key answers
import pytest

from rag import config, generation


class Response:
    def __init__(self, status, lines=(), text=""):
        self.status_code, self.lines, self.text = status, lines, text

    def iter_lines(self):
        return iter(self.lines)

    def close(self):
        pass


def good(word):
    return Response(200, [f'data: {{"choices":[{{"delta":{{"content":"{word}"}}}}]}}'.encode(), b"data: [DONE]"])


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    generation.cooldown.clear()
    monkeypatch.setattr(config, "MODELS", ["m1", "m2"])
    monkeypatch.setattr(config, "OPENROUTER_KEYS", ["key-a", "key-b"])
    monkeypatch.setattr(config, "FALLBACK_BASE_URL", "")


def fake_server(monkeypatch, answer):
    calls = []

    def post(url, headers, json, **kw):
        key = headers["Authorization"].split()[-1]
        calls.append((key, json["model"]))
        return answer(key, json["model"])

    monkeypatch.setattr(generation.requests, "post", post)
    return calls


def text_of(events):
    return "".join(t for kind, t in events if kind == "delta")


def test_daily_limit_moves_to_backup_key_and_remembers(monkeypatch):
    calls = fake_server(monkeypatch, lambda k, m: Response(429, text="Rate limit exceeded: free-models-per-day") if k == "key-a" else good("hi"))
    assert text_of(generation.stream_chat([])) == "hi"
    assert calls == [("key-a", "m1"), ("key-b", "m1")]  # no wasted call on the second model of key-a
    calls.clear()
    list(generation.stream_chat([]))
    assert [c[0] for c in calls] == ["key-b"]  # key-a is resting


def test_busy_model_tries_next_model_with_same_key(monkeypatch):
    calls = fake_server(monkeypatch, lambda k, m: Response(429, text="busy") if m == "m1" else good("ok"))
    list(generation.stream_chat([]))
    assert calls == [("key-a", "m1"), ("key-a", "m2")]


def test_backup_provider_is_used_last(monkeypatch):
    monkeypatch.setattr(config, "FALLBACK_BASE_URL", "https://other.test/v1")
    monkeypatch.setattr(config, "FALLBACK_KEYS", ["bk"])
    monkeypatch.setattr(config, "FALLBACK_MODELS", ["fm"])
    calls = fake_server(monkeypatch, lambda k, m: Response(402, text="no credits") if k != "bk" else good("backup"))
    assert text_of(generation.stream_chat([])) == "backup" and calls[-1] == ("bk", "fm")


def test_error_when_everything_fails(monkeypatch):
    fake_server(monkeypatch, lambda k, m: Response(500, text="boom"))
    with pytest.raises(RuntimeError):
        list(generation.stream_chat([]))


def test_error_without_keys(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_KEYS", [])
    with pytest.raises(RuntimeError, match="no API key"):
        list(generation.stream_chat([]))


def test_403_for_one_model_does_not_rest_the_key(monkeypatch):
    # a model that is restricted (403) must not block the other models of the same key
    calls = fake_server(monkeypatch, lambda k, m: Response(403, text="agent tools only") if m == "m1" else good("ok"))
    assert text_of(generation.stream_chat([])) == "ok"
    assert calls == [("key-a", "m1"), ("key-a", "m2")] and not generation.cooldown


def test_403_about_the_key_rests_it(monkeypatch):
    calls = fake_server(monkeypatch, lambda k, m: Response(403, text="Invalid API key") if k == "key-a" else good("ok"))
    assert text_of(generation.stream_chat([])) == "ok"
    assert calls == [("key-a", "m1"), ("key-b", "m1")]
