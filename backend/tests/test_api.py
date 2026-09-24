"""End-to-end through the HTTP API, with fake models."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from conftest import TEST_POLICY, fixture_text, upload

import app.main as main
import app.store as store_module


def spec(**kw):
    return json.dumps({"kind": "structured", "operation": "list", "sort_by": None,
                       "order": "desc", "limit": None, "filters": []} | kw)


def load_three(client):
    ids = {}
    for name in ("contract_1.txt", "julia_miller.txt", "carlos_brown_real_estate.txt"):
        ids[name] = upload(client, name, fixture_text(name))["analysis_id"]
    return ids


def test_upload_stores_header_and_grounded_metadata(client):
    info = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))
    assert info["total_clauses"] == 8
    assert info["parse_quality"]["ok"]
    record = main.store.get_analysis(info["analysis_id"])
    assert record["header"]["text"].endswith("FINANCED AMOUNT: $45,892.00.")
    assert record["contract_metadata"]["contract_value"] == 45892.0
    assert record["contract_metadata"]["lender_name"] == "FINANCIAL BANK OF AMERICA Inc"
    assert main.rag.count() == 9  # header + 8 clauses


def test_header_is_never_risk_scored(client):
    aid = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))["analysis_id"]
    result = client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY}).json()
    assert result["total_clauses"] == 8
    assert all("FINANCED AMOUNT" not in c["text"] for c in result["results"])
    assert main.store.get_analysis(aid)["policy_used"]["policy_id"] == "test_policy"


def test_same_file_uploaded_twice_is_one_record(client):
    first = upload(client, "julia_miller.txt", fixture_text("julia_miller.txt"))
    second = upload(client, "julia_miller (1).txt", fixture_text("julia_miller.txt"))
    assert second["analysis_id"] == first["analysis_id"]
    assert second["reprocessed"] and not second["clauses_changed"]
    assert len(main.store.list_analyses()) == 1
    assert main.rag.count() == 9


def test_structured_question_is_answered_exactly(client, fake_llm):
    load_three(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(sort_by="contract_value", order="desc", limit=1)
    r = client.post("/chat", json={"message": "which contract has the highest financed amount"}).json()
    assert r["route"] == "structured"
    assert "**carlos_brown_real_estate.txt** has the highest amount: **$1,203,432.00**" in r["reply"]
    assert r["sources"][0]["clause_id"] == "header"
    assert "FINANCED AMOUNT: $1,203,432" in r["sources"][0]["text"]
    # no free-text LLM call was needed to produce the answer
    assert [c[0] for c in fake_llm.calls if c[0] == "text"] == []


def test_follow_up_sees_the_conversation(client, fake_llm):
    load_three(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: (
        spec(sort_by="contract_value", order="asc", limit=1) if "highest" in p else json.dumps({"kind": "semantic"})
    )
    history = [
        {"role": "user", "content": "which contract has the highest financed amount"},
        {"role": "assistant", "content": "carlos_brown_real_estate.txt"},
    ]
    r = client.post("/chat", json={"message": "and the lowest?", "history": history}).json()
    assert "**julia_miller.txt** has the lowest amount: **$45,892.00**" in r["reply"]


def test_semantic_question_on_one_contract_uses_whole_contract(client, fake_llm):
    ids = load_three(client)
    r = client.post("/chat", json={
        "message": "what interest applies on late payment?",
        "analysis_id": ids["julia_miller.txt"],
        "history": [{"role": "user", "content": "earlier question"}],
    }).json()
    assert r["route"] == "semantic"
    prompt = [c[1] for c in fake_llm.calls if c[0] == "text"][-1]
    assert "CLAUSE SIX" in prompt and "CLAUSE EIGHT" in prompt and "FINANCED AMOUNT" in prompt
    assert "Conversation so far" in prompt and "earlier question" in prompt
    assert r["sources"][0]["clause_id"] == "header"


def test_router_failure_falls_back_to_search(client, fake_llm):
    load_three(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: "not json at all"
    r = client.post("/chat", json={"message": "what does the insurance clause require?"}).json()
    assert r["route"] == "semantic"
    assert r["sources"]


def test_reasoning_text_is_stripped_from_answers(client, fake_llm):
    load_three(client)
    fake_llm.handlers["text"] = lambda p: "<think>let me think</think>The penalty is 2% [Source 1](#source-1)."
    r = client.post("/chat", json={"message": "what is the default penalty?"}).json()
    assert r["reply"] == "The penalty is 2% [Source 1](#source-1)."


def test_reindex_rebuilds_and_reanalyzes_changed_contracts(client, fake_llm):
    ids = load_three(client)
    aid = ids["contract_1.txt"]
    client.post("/analyze", json={"analysis_id": aid, "policy": TEST_POLICY})
    # Simulate a record made by the old parser: one giant clause.
    main.store.update_analysis(aid, {"clauses": [{"id": 1, "text": fixture_text("contract_1.txt"), "metadata": {}}]})

    assert client.post("/admin/reindex").json()["started"]
    for _ in range(200):
        status = client.get("/admin/reindex/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["phase"] == "finished", status
    assert all(r["ok"] for r in status["results"])
    assert status["reanalyzed"] == ["contract_1.txt"]
    record = main.store.get_analysis(aid)
    assert len(record["clauses"]) == 8 and record["status"] == "analyzed"
    assert main.rag.count() == 27


def test_duplicates_are_reported_and_optionally_removed(client):
    ids = load_three(client)
    # An old duplicate record (made before uploads were de-duplicated).
    dup_id = main.store.save_analysis(dict(main.store.get_analysis(ids["julia_miller.txt"]), analysis_id=None,
                                           created_at="2020-01-01T00:00:00Z", updated_at="2020-01-01T00:00:00Z"))
    client.post("/admin/reindex?remove_duplicates=true&reanalyze=none")
    for _ in range(200):
        status = client.get("/admin/reindex/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["removed_duplicates"] == [dup_id]
    assert main.store.get_analysis(dup_id) is None
    assert len(main.store.list_analyses()) == 3


def test_concurrent_store_updates_are_not_lost(tmp_path):
    store = store_module.Store()
    ids = [store.save_analysis({"filename": f"c{i}"}) for i in range(40)]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: store.update_analysis(i, {"contract_metadata": {"v": 1}}), ids))
    assert all(store.get_analysis(i).get("contract_metadata") for i in ids)
