"""
Test setup: the real app, with the LLM and the embedding model replaced
by deterministic fakes so tests run offline, fast and identically every
time. Data goes to a temporary folder, never to backend/data.

Run from the backend folder:  python -m pytest -q
"""
import hashlib
import json
import math
import os
import re
import sys
import tempfile

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

_TMP = tempfile.mkdtemp(prefix="pact_tests_")
os.environ["QDRANT_DATA_PATH"] = os.path.join(_TMP, "qdrant")

import app.store as store_module  # noqa: E402

store_module.DATA_DIR = _TMP
store_module.DATA_FILE = os.path.join(_TMP, "analyses.json")

import app.rag as rag_module  # noqa: E402


def fake_embed(self, texts, kind="document"):
    """Bag-of-words vectors: similar wording -> similar vectors."""
    vectors = []
    for text in texts:
        text = text.split("Query:")[-1].lower()
        v = [0.0] * 256
        for word in re.findall(r"[a-z]{3,}", text):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / norm for x in v])
    return vectors


rag_module.RAGStore.embed = fake_embed

import app.mcp.llm_agent as llm_agent  # noqa: E402


class FakeLLM:
    """
    Answers by schema: each structured call is identified by the JSON
    schema's title. Tests override behavior through `handlers`:
    handlers["ChatQuerySpec"] = lambda prompt: '{"kind": "semantic"}'
    Every call is recorded in `calls` as (title or "text", prompt).
    """

    def __init__(self):
        self.handlers = {}
        self.calls = []
        self.model = "fake"

    def is_available(self):
        return True

    def invoke(self, prompt, system=None, temperature=0, json_schema=None):
        title = (json_schema or {}).get("title") or "text"
        self.calls.append((title, prompt))
        if title in self.handlers:
            return self.handlers[title](prompt)
        if title == "ChatQuerySpec":
            return json.dumps({"kind": "semantic"})
        if title == "ContractMetadataExtraction":
            return json.dumps({k: None for k in llm_agent.ContractMetadataExtraction.model_fields})
        if title == "ClauseClassification":
            return json.dumps({"domain": "Financial", "risk_level": "Medium", "reasons": ["test"], "key_metadata": {}})
        if title == "ComplianceResponse":
            ids = re.findall(r'"id": "([^"]+)"', prompt)
            return json.dumps({"results": [{"id": i, "matched": False, "reason": "test"} for i in ids]})
        if title == "ApplicabilityResponse":
            return json.dumps({"contract_type": "asset financing agreement", "results": []})
        if title == "ContractSummary":
            return json.dumps({
                "executive_summary": "summary", "key_obligations": [], "major_risks": [],
                "recommendations": [], "overall_sentiment": "Balanced",
            })
        return "Answer from the sources [Source 1](#source-1)."


FAKE = FakeLLM()
llm_agent.get_llm_provider = lambda task="bulk": FAKE

import app.main as main  # noqa: E402


def fixture_text(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def fake_llm():
    FAKE.handlers = {}
    FAKE.calls = []
    return FAKE


@pytest.fixture
def client(fake_llm):
    """A clean app: empty store, empty search index, fake models."""
    from fastapi.testclient import TestClient

    if os.path.exists(store_module.DATA_FILE):
        os.remove(store_module.DATA_FILE)
    main.store = store_module.Store()
    if main.rag is not None:
        main.rag.reset()
    return TestClient(main.app)


TEST_POLICY = {
    "policy_id": "test_policy",
    "risk_threshold": 15,
    "domains": [
        {
            "domain_name": "Financial",
            "micro_policies": [
                {"id": "1", "name": "Payment terms", "check": "payment terms stated", "risk_weight": 3}
            ],
        }
    ],
}


def upload(client, filename: str, text: str) -> dict:
    response = client.post("/upload", files={"file": (filename, text.encode("utf-8"), "text/plain")})
    assert response.status_code == 200, response.text
    return response.json()
