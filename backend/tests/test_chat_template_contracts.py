"""
A real session over 17 contracts built from one template (regular
interest 1.2%/month in clause 3, late interest 1%/month in clause 6):
- "is the interest fine" saw only clause 6 and said "1% in all 17";
- "why 1 and 1.2" saw only clause 3 and denied the 1% exists;
- "you're wrong in clauses 3 and 6" retrieved clause 2 and the model
  invented a table.
"""
import json

from conftest import fixture_text, upload

import app.main as main_module
from app.main import _clause_numbers

BORROWERS = ["Julia Miller", "Carlos Brown", "Emily Clark", "Peter Wilson", "Richard Taylor", "Anna Silva"]


def load_template_portfolio(client):
    base = fixture_text("car_financing_julia.txt")
    for i, name in enumerate(BORROWERS, start=1):
        upload(client, f"Contract_{i}.txt", base.replace("Julia Miller", name).replace("76,694", f"{70000 + i * 1111:,}"))


def prompt_of(fake_llm):
    return [c[1] for c in fake_llm.calls if c[0] == "text"][-1]


def ask(client, message, **kw):
    r = client.post("/chat", json={"message": message, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_both_interest_clauses_reach_the_model(client, fake_llm):
    load_template_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "across_contracts": True})
    ask(client, "is the interest amount mentioned fine")
    sources = prompt_of(fake_llm).split("Sources:")[1]
    assert "interest of 1.2% per month" in sources
    assert "late\ninterest of 1% per month" in sources or "late interest of 1% per month" in sources


def test_identical_wording_is_sent_once_and_says_where_else_it_appears(client, fake_llm):
    load_template_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "across_contracts": True})
    r = ask(client, "what interest do the contracts charge?")
    sources = prompt_of(fake_llm).split("Sources:")[1]
    assert sources.count("interest of 1.2% per month") == 1
    assert "identical wording also in:" in sources
    assert any(len(s.get("also_in", [])) == len(BORROWERS) - 1 for s in r["sources"]) or not r["sources"]


def test_clauses_named_in_the_question_are_fetched(client, fake_llm):
    load_template_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    ask(client, "youre wrong in clauses 3 and 6 specifically there are different interest rates mentioned")
    sources = prompt_of(fake_llm).split("Sources:")[1]
    first = sources.split("[Source 3")[0]
    assert "CLAUSE THREE" in first and "CLAUSE SIX" in first
    assert "interest of 1.2% per month" in sources and "interest of 1% per month" in sources.replace("\n", " ")


def test_clause_named_in_words_on_the_open_contract(client, fake_llm):
    load_template_portfolio(client)
    rid = main_module.store.list_analyses()[0]["analysis_id"]
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    ask(client, "what does clause six say?", analysis_id=rid)
    assert "[Source 1 | " in prompt_of(fake_llm) and "CLAUSE SIX" in prompt_of(fake_llm).split("[Source 1")[1][:300]


def test_clause_number_parsing():
    assert _clause_numbers("youre wrong in clauses 3 and 6 specifically") == [3, 6]
    assert _clause_numbers("what does clause six say") == [6]
    assert _clause_numbers("sections 2, 4 or 5") == [2, 4, 5]
    assert _clause_numbers("interest rate") == []


def test_prompt_rules_against_inventing_and_judging():
    rules = main_module.CHAT_SYSTEM_PROMPT
    assert "Never move a\n   number from one clause" in rules
    assert "no defined standard" in rules
    assert "regular\n   interest rate and a late-payment interest rate" in rules


def test_answer_says_which_model_wrote_it(client, fake_llm):
    load_template_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    r = ask(client, "what does the insurance clause require?")
    from app.llm_providers import chat_models
    assert r["route"] == "semantic" and r["model"] == chat_models()[0]
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps(
        {"kind": "structured", "sort_by": "contract_value", "order": "desc", "limit": 1})
    r = ask(client, "highest amount?")
    assert r["route"] == "structured" and r["model"] is None and r["router_model"] == "fake"



# ------------------------------------------------ chat model fallback

class _Model:
    def __init__(self, name, fail=None):
        self.model, self.fail = name, fail

    def invoke(self, prompt, system=None, temperature=0, json_schema=None):
        if self.fail:
            raise RuntimeError(self.fail)
        return f"Answer by {self.model} [Source 1](#source-1)."


def test_bigger_chat_model_falls_back_when_it_cannot_load(client, fake_llm, monkeypatch):
    import app.llm_providers as providers
    import app.mcp.llm_agent as agent
    load_template_portfolio(client)
    monkeypatch.setitem(providers._settings, "ollama_chat_model", "qwen3:32b")
    monkeypatch.setitem(providers._settings, "ollama_chat_fallback_models", ["gpt-oss:20b", "qwen3:8b"])
    failing = {"qwen3:32b": "HTTP 500: model requires more system memory (13.5 GiB) than is available",
               "gpt-oss:20b": "did not answer within 240s"}
    monkeypatch.setattr(agent, "provider_for_model", lambda m: _Model(m, failing.get(m)))
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    r = ask(client, "what does the insurance clause require?")
    assert r["model"] == "qwen3:8b" and r["reply"].startswith("Answer by qwen3:8b")


def test_all_chat_models_failing_is_a_clear_error(client, fake_llm, monkeypatch):
    import app.llm_providers as providers
    import app.mcp.llm_agent as agent
    load_template_portfolio(client)
    monkeypatch.setitem(providers._settings, "ollama_chat_model", "qwen3:32b")
    monkeypatch.setattr(agent, "provider_for_model", lambda m: _Model(m, "HTTP 500 busy"))
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    r = client.post("/chat", json={"message": "what does the insurance clause require?"})
    assert r.status_code == 503 and "qwen3:32b" in r.json()["detail"]


def test_chat_model_order_without_duplicates(monkeypatch):
    import app.llm_providers as providers
    monkeypatch.setitem(providers._settings, "ollama_chat_model", "qwen3:32b")
    monkeypatch.setitem(providers._settings, "ollama_chat_fallback_models", "gpt-oss:20b, qwen3:8b")
    monkeypatch.setitem(providers._settings, "ollama_quality_model", "qwen3:8b")
    assert providers.chat_models() == ["qwen3:32b", "gpt-oss:20b", "qwen3:8b"]
