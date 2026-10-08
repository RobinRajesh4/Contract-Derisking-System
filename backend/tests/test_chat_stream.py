"""
Answers written word by word (/chat/stream): same content as /chat, sent
as the model writes it, with the reasoning hidden and model fallback kept.
"""
import json

import pytest
import requests

from conftest import fixture_text, upload
from test_chat_template_contracts import load_template_portfolio

import app.llm_providers as providers
import app.mcp.llm_agent as agent
from app.llm_providers import LLMError, OllamaProvider, _ThinkFilter


def events(client, message, **kw):
    r = client.post("/chat/stream", json={"message": message, **kw})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


# ------------------------------------------------------------ endpoint

def test_written_answer_arrives_in_pieces_then_done(client, fake_llm, monkeypatch):
    load_template_portfolio(client)
    # Independent of the chat model in the live settings.json.
    monkeypatch.setitem(providers._settings, "ollama_chat_model", "gpt-oss:20b")
    monkeypatch.setitem(providers._settings, "ollama_chat_fallback_models", [])

    class Streaming:
        model = "gpt-oss:20b"

        def stream(self, prompt, system=None, temperature=0):
            yield "Late interest is "
            yield "1% per month "
            yield "[Source 1 | x | clause 6]."

    monkeypatch.setattr(agent, "provider_for_model", lambda m: Streaming())
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    ev = events(client, "what is the late interest?")
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "status" and "Writing the answer" in [e.get("text") for e in ev]
    assert [e["text"] for e in ev if e["type"] == "delta"] == ["Late interest is ", "1% per month ", "[Source 1 | x | clause 6]."]
    done = ev[-1]
    assert done["type"] == "done" and done["model"] == "gpt-oss:20b"
    # The finished answer has its citation linked and its source attached.
    assert done["reply"].endswith("[Source 1](#source-1).")
    assert [s["source_number"] for s in done["sources"]] == [1]


def test_exact_answer_is_sent_whole(client, fake_llm):
    load_template_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps(
        {"kind": "structured", "operation": "list", "sort_by": "contract_value", "order": "desc", "limit": 1})
    ev = events(client, "which contract has the highest amount?")
    assert not [e for e in ev if e["type"] == "delta"]
    assert ev[-1]["type"] == "done" and ev[-1]["route"] == "structured"


def test_model_that_fails_before_writing_hands_over(client, fake_llm, monkeypatch):
    load_template_portfolio(client)
    monkeypatch.setitem(providers._settings, "ollama_chat_model", "gpt-oss:20b")
    monkeypatch.setitem(providers._settings, "ollama_chat_fallback_models", ["qwen3:8b"])

    class Model:
        def __init__(self, name):
            self.model = name

        def stream(self, prompt, system=None, temperature=0):
            if self.model == "gpt-oss:20b":
                raise LLMError("did not start answering within 240s")
            yield "From qwen [Source 1]."

    monkeypatch.setattr(agent, "provider_for_model", Model)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    ev = events(client, "what does the insurance clause require?")
    assert ev[-1]["type"] == "done" and ev[-1]["model"] == "qwen3:8b"


def test_errors_come_as_an_event(client, fake_llm):
    upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))
    ev = events(client, "what is the rate?", analysis_id="does-not-exist")
    assert ev[-1]["type"] == "error" and ev[-1]["status"] == 404


def test_model_without_streaming_still_answers(client, fake_llm):
    # The test model (and Groq) only answer whole: sent as one piece.
    load_template_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    ev = events(client, "what does the insurance clause require?")
    assert len([e for e in ev if e["type"] == "delta"]) == 1 and ev[-1]["type"] == "done"


# ----------------------------------------------------- reading the stream

@pytest.mark.parametrize("pieces, shown", [
    (["Hello ", "world"], "Hello world"),
    (["<think>plan</think>Answer"], "Answer"),
    (["<thi", "nk>plan", " more</thi", "nk>Ans", "wer"], "Answer"),
    (["a < b and ", "<", "think>x</think>c"], "a < b and c"),
])
def test_reasoning_is_hidden_even_when_tags_are_split(pieces, shown):
    f = _ThinkFilter()
    assert "".join(f.feed(p) for p in pieces) + f.flush() == shown


class _Streamed:
    def __init__(self, lines, status=200, text=""):
        self.status_code, self.text, self._lines = status, text, lines

    def iter_lines(self):
        for line in self._lines:
            yield json.dumps(line).encode()

    def close(self):
        pass


def test_ollama_stream_yields_content_and_skips_thinking(monkeypatch):
    lines = [
        {"message": {"thinking": "Let me check the clause"}},
        {"message": {"content": "The rate "}},
        {"message": {"content": "is 1.2%."}},
        {"done": True, "prompt_eval_count": 100},
    ]
    monkeypatch.setattr(requests, "post", lambda url, **kw: _Streamed(lines))
    assert list(OllamaProvider(model="gpt-oss:20b").stream("q")) == ["The rate ", "is 1.2%."]


def test_ollama_stream_out_of_memory_fails_at_once(monkeypatch):
    calls = []

    def post(url, **kw):
        calls.append(1)
        return _Streamed([], status=500, text='{"error":"model requires more system memory"}')
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(LLMError, match="memory"):
        list(OllamaProvider(model="qwen3:32b").stream("q"))
    assert len(calls) == 1


def test_ollama_stream_reports_a_cut_prompt(monkeypatch):
    lines = [{"message": {"content": "partial"}}, {"done": True, "prompt_eval_count": 999999}]
    monkeypatch.setattr(requests, "post", lambda url, **kw: _Streamed(lines))
    with pytest.raises(LLMError, match="context window"):
        list(OllamaProvider(model="qwen3:8b").stream("q"))
