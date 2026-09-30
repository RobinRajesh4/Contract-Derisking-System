"""
The shared AI server can be busy, time out or return errors. These tests
pin down what the app does then: retry what's worth retrying, never save
a guessed analysis as if it were real, never throw away good data.
"""
import json
import time

import pytest
import requests

from conftest import TEST_POLICY, fixture_text, upload

import app.llm_providers as providers
import app.main as main
import app.rag as rag_module
from app.llm_providers import LLMError, OllamaProvider
from app.schemas import ContractMetadataExtraction


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


OK = {"message": {"content": "fine"}, "prompt_eval_count": 10}


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(providers, "_RETRY_BACKOFF_SEC", 0)
    monkeypatch.setattr(rag_module, "_EMBED_BACKOFF_SEC", 0)


def script(monkeypatch, steps):
    """requests.post returns / raises each step in turn."""
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        step = steps[min(len(calls) - 1, len(steps) - 1)]
        if isinstance(step, Exception):
            raise step
        return step
    monkeypatch.setattr(requests, "post", fake_post)
    return calls


# ------------------------------------------------------------------ LLM calls

def test_server_error_is_retried_then_succeeds(monkeypatch, no_sleep):
    calls = script(monkeypatch, [FakeResponse(500, "model is loading"), FakeResponse(503, "busy"), FakeResponse(200, OK)])
    assert OllamaProvider(model="qwen3:8b").invoke("hi") == "fine"
    assert len(calls) == 3


def test_server_error_gives_up_after_retries(monkeypatch, no_sleep):
    calls = script(monkeypatch, [FakeResponse(503, "server busy, try again")])
    with pytest.raises(LLMError, match="after 4 attempts"):
        OllamaProvider(model="qwen3:8b").invoke("hi")
    assert len(calls) == 4


def test_timeout_is_not_retried(monkeypatch, no_sleep):
    # Each timeout already cost llm_timeout_sec; retrying doubles the wait.
    calls = script(monkeypatch, [requests.Timeout(), FakeResponse(200, OK)])
    with pytest.raises(LLMError, match="did not answer"):
        OllamaProvider(model="qwen3:8b").invoke("hi")
    assert len(calls) == 1


def test_bad_request_is_not_retried(monkeypatch, no_sleep):
    calls = script(monkeypatch, [FakeResponse(404, "model not found")])
    with pytest.raises(LLMError, match="404"):
        OllamaProvider(model="qwen3:8b").invoke("hi")
    assert len(calls) == 1


def test_failed_availability_check_is_not_remembered_for_long(monkeypatch):
    providers._availability_cache.update({"url": "x", "ok": False, "at": 0})
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, {}))
    p = OllamaProvider(model="qwen3:8b")
    p.base_url = "x"
    providers._availability_cache["at"] = time.time() - 6
    assert p.is_available()


# ------------------------------------------------------------------ embeddings

def test_embedding_server_error_is_retried(monkeypatch, no_sleep):
    calls = script(monkeypatch, [FakeResponse(500, "busy"), FakeResponse(200, {"embeddings": [[0.1, 0.2]]})])
    store = rag_module.RAGStore.__new__(rag_module.RAGStore)
    store.embedding_url, store.embedding_model, store.verify = "http://x", "qwen3-embedding:8b", False
    assert store._post_embed(["a"]) == {"embeddings": [[0.1, 0.2]]}
    assert len(calls) == 2


# ------------------------------------------------------------ analysis quality

def test_analysis_with_ai_down_is_marked_incomplete(client, fake_llm):
    aid = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))["analysis_id"]

    def down(prompt):
        raise LLMError("HTTP 500 out of memory")
    for title in ("ClauseClassification", "ComplianceResponse", "ApplicabilityResponse", "ContractSummary"):
        fake_llm.handlers[title] = down
    r = client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY}).json()
    quality = r["analysis_quality"]
    assert quality["complete"] is False
    assert len(quality["fallback_clauses"]) == 8
    assert "keyword matching" in quality["message"]
    assert main.store.get_analysis(aid)["analysis_quality"]["complete"] is False


def test_clause_that_failed_is_retried_at_the_end(client, fake_llm):
    aid = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))["analysis_id"]
    attempts = {"n": 0}

    def flaky(prompt):
        attempts["n"] += 1
        if attempts["n"] <= 2:  # first clause fails both structured attempts
            raise LLMError("HTTP 500")
        return json.dumps({"domain": "Financial", "risk_level": "High", "reasons": ["x"], "key_metadata": {}})
    fake_llm.handlers["ClauseClassification"] = flaky
    r = client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY}).json()
    assert r["analysis_quality"]["complete"] is True
    assert all(c["classification"]["method"] == "llm" for c in r["results"])


def test_failed_summary_does_not_leave_the_old_one(client, fake_llm):
    aid = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))["analysis_id"]
    client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY})
    assert main.store.get_analysis(aid)["summary"]

    def down(prompt):
        raise LLMError("HTTP 500")
    fake_llm.handlers["ContractSummary"] = down
    client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY})
    assert not main.store.get_analysis(aid).get("summary")


# ------------------------------------------------------------- keeping data

def test_reprocessing_with_ai_down_keeps_the_previous_extraction(client, fake_llm):
    text = fixture_text("julia_miller.txt")
    fake_llm.handlers["ContractMetadataExtraction"] = lambda p: json.dumps(
        {k: None for k in ContractMetadataExtraction.model_fields}
        | {"contract_about": "Health financing", "end_date": "2029-01-01"}
    )
    aid = upload(client, "julia_miller.txt", text)["analysis_id"]
    assert main.store.get_analysis(aid)["contract_metadata"]["contract_about"] == "Health financing"

    def down(prompt):
        raise LLMError("HTTP 500")
    fake_llm.handlers["ContractMetadataExtraction"] = down
    upload(client, "julia_miller.txt", text)  # same file again -> reprocessed
    meta = main.store.get_analysis(aid)["contract_metadata"]
    assert meta["contract_about"] == "Health financing" and meta["end_date"] == "2029-01-01"
    assert any("previous extraction was kept" in w for w in meta["extraction_warnings"])


def test_search_index_failure_is_recorded(client, fake_llm, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("embedding server down")
    monkeypatch.setattr(main.rag, "index_analysis", broken)
    info = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))
    assert info["search_index"]["ok"] is False
    assert "chat search" in main.store.get_analysis(info["analysis_id"])["search_index"]["error"]


def test_retry_pass_is_skipped_when_the_server_is_down(client, fake_llm):
    aid = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))["analysis_id"]
    calls = {"n": 0}

    def down(prompt):
        calls["n"] += 1
        raise LLMError("HTTP 500")
    fake_llm.handlers["ClauseClassification"] = down
    client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY})
    assert calls["n"] == 8  # one failed call per clause, no second round


def test_check_left_out_by_the_model_is_not_a_server_failure(client, fake_llm):
    aid = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))["analysis_id"]
    fake_llm.handlers["ComplianceResponse"] = lambda p: json.dumps({"results": []})
    r = client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY}).json()
    assert r["analysis_quality"]["complete"] is True



def test_out_of_memory_is_not_retried(monkeypatch, no_sleep):
    # A bigger model that doesn't fit won't fit 2 seconds later either;
    # fail fast so the chat can use a smaller one.
    calls = script(monkeypatch, [FakeResponse(500, '{"error":"model requires more system memory (13.5 GiB) than is available (13.0 GiB)"}')])
    with pytest.raises(LLMError, match="memory"):
        OllamaProvider(model="qwen3:32b").invoke("hi")
    assert len(calls) == 1


# ------------------------------------------ search that failed to start

def test_search_starts_later_if_the_embedding_server_was_down_at_start(client, fake_llm, monkeypatch):
    # A dropped connection at start-up used to leave chat search off until
    # a restart, and contracts uploaded meanwhile were never indexed.
    working = main.rag
    working.client.close()          # free the local search folder
    main.rag = None
    real_embed = rag_module.RAGStore.embed

    def down(self, texts, kind="document"):
        raise RuntimeError("Could not get embeddings: SSLEOFError")
    monkeypatch.setattr(rag_module.RAGStore, "embed", down)
    main._rag_init["last_attempt"] = 0.0
    assert main.ensure_rag() is None and "SSLEOFError" in main._rag_init["error"]

    r = client.post("/chat", json={"message": "what does the default clause say?"})
    assert r.status_code in (200, 503)
    if r.status_code == 503:
        assert "retried automatically" in r.json()["detail"]

    # The server is back; the next attempt (after the wait) succeeds and
    # the next upload is indexed.
    monkeypatch.setattr(rag_module.RAGStore, "embed", real_embed)
    main._rag_init["last_attempt"] = time.time() - main._RAG_RETRY_SEC - 1
    info = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))
    assert main.rag is not None and info["search_index"]["ok"] is True


def test_failed_start_does_not_retry_on_every_request(monkeypatch):
    calls = {"n": 0}
    saved = main.rag
    main.rag = None
    try:
        def failing():
            calls["n"] += 1
            raise RuntimeError("down")
        monkeypatch.setattr(main, "RAGStore", failing)
        main._rag_init["last_attempt"] = 0.0
        main.ensure_rag(); main.ensure_rag(); main.ensure_rag()
        assert calls["n"] == 1
    finally:
        main.rag = saved
