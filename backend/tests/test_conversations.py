"""Saved chat conversations: reopened after the tab is closed."""
import os

import app.main as main
from app.conversations import MAX_CONVERSATIONS, MAX_SOURCE_CHARS

CID = "conv_abc12345"
MESSAGES = [
    {"role": "user", "content": "Which contract has the highest amount?"},
    {"role": "assistant", "content": "**A.pdf** has the highest amount: **$10.00**.", "route": "structured",
     "querySpec": {"kind": "structured", "sort_by": "contract_value"}, "model": None,
     "sources": [{"source_number": 1, "analysis_id": "a1", "filename": "A.pdf", "clause_id": "header",
                  "text": "x" * 5000}]},
]


def test_save_list_open_delete(client):
    assert client.get("/conversations").json() == []
    saved = client.put(f"/conversations/{CID}", json={"messages": MESSAGES}).json()
    assert saved["title"] == "Which contract has the highest amount?" and saved["messages"] == 2

    listed = client.get("/conversations").json()
    assert [c["id"] for c in listed] == [CID] and "messages" in listed[0] and listed[0]["messages"] == 2

    opened = client.get(f"/conversations/{CID}").json()
    assert [m["role"] for m in opened["messages"]] == ["user", "assistant"]
    # What a follow-up needs survives: the route and the exact query.
    assert opened["messages"][1]["querySpec"]["sort_by"] == "contract_value"
    # Quoted clause text is cut, so the history file stays small.
    assert len(opened["messages"][1]["sources"][0]["text"]) <= MAX_SOURCE_CHARS + 2

    assert client.delete(f"/conversations/{CID}").json() == {"deleted": True}
    assert client.get(f"/conversations/{CID}").status_code == 404
    assert client.get("/conversations").json() == []


def test_saving_again_updates_the_same_conversation(client):
    client.put(f"/conversations/{CID}", json={"messages": MESSAGES})
    more = MESSAGES + [{"role": "user", "content": "and the lowest?"}, {"role": "assistant", "content": "B.pdf"}]
    client.put(f"/conversations/{CID}", json={"messages": more, "analysis_id": "a1"})
    listed = client.get("/conversations").json()
    assert len(listed) == 1 and listed[0]["messages"] == 4 and listed[0]["analysis_id"] == "a1"
    assert listed[0]["title"] == "Which contract has the highest amount?"


def test_newest_first_and_long_titles_are_shortened(client):
    client.put("/conversations/conv_first001", json={"messages": [{"role": "user", "content": "first " * 40}]})
    client.put("/conversations/conv_second01", json={"messages": [{"role": "user", "content": "second"}]})
    client.put("/conversations/conv_first001", json={"messages": [{"role": "user", "content": "first " * 40},
                                                                  {"role": "assistant", "content": "ok"}]})
    listed = client.get("/conversations").json()
    assert [c["id"] for c in listed] == ["conv_first001", "conv_second01"]
    assert len(listed[0]["title"]) <= 80 and listed[0]["title"].endswith("…")


def test_bad_ids_and_junk_messages_are_refused_or_dropped(client):
    assert client.put("/conversations/a", json={"messages": MESSAGES}).status_code == 400
    assert client.get("/conversations/..%2Fsettings").status_code in (400, 404)
    junk = [{"role": "system", "content": "x"}, {"role": "user", "content": "   "}, "text", {"role": "user", "content": "real"}]
    client.put(f"/conversations/{CID}", json={"messages": [m for m in junk if isinstance(m, dict)]})
    assert [m["content"] for m in client.get(f"/conversations/{CID}").json()["messages"]] == ["real"]


def test_oldest_conversations_are_dropped_beyond_the_limit(client, monkeypatch):
    import app.conversations as conv
    monkeypatch.setattr(conv, "MAX_CONVERSATIONS", 3)
    for i in range(5):
        client.put(f"/conversations/conv_{i:08d}", json={"messages": [{"role": "user", "content": f"q{i}"}]})
    ids = {c["id"] for c in client.get("/conversations").json()}
    assert len(ids) == 3 and "conv_00000004" in ids


def test_unreadable_history_file_does_not_break_the_list(client):
    client.put(f"/conversations/{CID}", json={"messages": MESSAGES})
    with open(main.conversations.path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert client.get("/conversations").json() == []
    assert client.put(f"/conversations/{CID}", json={"messages": MESSAGES}).status_code == 200
