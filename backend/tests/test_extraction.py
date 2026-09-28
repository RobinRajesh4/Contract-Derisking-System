import json

from conftest import fixture_text

from app.mcp.llm_agent import LLMClient, ground_metadata
from app.schemas import ClauseClassification, ContractMetadataExtraction

NULLS = {k: None for k in ContractMetadataExtraction.model_fields}


def extract(fake_llm, text, reply):
    fake_llm.handlers["ContractMetadataExtraction"] = lambda prompt: reply
    return LLMClient().extract_contract_metadata(text, "c.pdf")


def test_document_label_overrides_wrong_model_amount(fake_llm):
    meta = extract(fake_llm, fixture_text("julia_miller.txt"),
                   json.dumps(NULLS | {"contract_value": 1201349, "lender_name": "Chase Bank"}))
    assert meta["contract_value"] == 45892.0
    assert meta["lender_name"] == "FINANCIAL BANK OF AMERICA Inc"
    assert meta["field_sources"]["contract_value"] == "document label 'FINANCED AMOUNT'"
    assert any("1,201,349" in w for w in meta["extraction_warnings"])


def test_invented_amount_and_name_are_discarded(fake_llm):
    doc = "Service agreement between Acme Ltd and Beta LLC. Fees total USD 12,500 per year. CLAUSE ONE - SCOPE: services."
    meta = extract(fake_llm, doc, json.dumps(NULLS | {"contract_value": 99999, "customer_name": "Gamma Inc"}))
    assert meta["contract_value"] is None
    assert meta["customer_name"] is None
    assert len(meta["extraction_warnings"]) == 2


def test_model_amount_found_in_text_is_kept(fake_llm):
    doc = "Service agreement between Acme Ltd and Beta LLC. Fees total USD 12,500 per year. CLAUSE ONE - SCOPE: services."
    meta = extract(fake_llm, doc, json.dumps(NULLS | {"contract_value": "12,500", "customer_name": "Beta LLC"}))
    assert meta["contract_value"] == 12500.0
    assert meta["currency"] == "USD"
    assert meta["customer_name"] == "Beta LLC"


def test_invalid_reply_is_retried_once(fake_llm):
    replies = iter(["<think>...</think> not json", json.dumps(NULLS | {"customer_name": "Julia Miller"})])
    fake_llm.handlers["ContractMetadataExtraction"] = lambda prompt: next(replies)
    meta = LLMClient().extract_contract_metadata(fixture_text("julia_miller.txt"))
    calls = [c for c in fake_llm.calls if c[0] == "ContractMetadataExtraction"]
    assert len(calls) == 2
    assert "rejected" in calls[1][1]
    assert meta["extraction_method"] == "llm"


def test_model_failure_falls_back_and_is_still_grounded(fake_llm):
    meta = extract(fake_llm, fixture_text("julia_miller.txt"), "garbage")
    assert meta["extraction_method"] == "local_fallback"
    assert meta["contract_value"] == 45892.0
    assert meta["lender_name"] == "FINANCIAL BANK OF AMERICA Inc"


def test_non_iso_dates_are_discarded():
    meta = ground_metadata({"start_date": "Sept 2024", "end_date": "2027-01-31"}, "no labels here")
    assert meta["start_date"] is None
    assert meta["end_date"] == "2027-01-31"


def test_classification_is_marked_llm_or_fallback(fake_llm):
    result = LLMClient().classify_clause("CLAUSE SIX - DEFAULT: penalty of 2%", {})
    assert result["method"] == "llm"
    fake_llm.handlers["ClauseClassification"] = lambda prompt: "nonsense"
    result = LLMClient().classify_clause("CLAUSE SIX - DEFAULT: penalty of 2%", {})
    assert result["method"] == "keyword_fallback"


def test_schema_normalizes_harmless_formatting():
    c = ClauseClassification.model_validate(
        {"domain": "financial", "risk_level": "high", "reasons": "one reason", "key_metadata": {"rate": 1.2}}
    )
    assert (c.domain, c.risk_level, c.reasons, c.key_metadata) == ("Financial", "High", ["one reason"], {"rate": "1.2"})
    m = ContractMetadataExtraction.model_validate(NULLS | {"contract_value": "$1,203,432.00", "customer_name": "unknown"})
    assert m.contract_value == 1203432.0 and m.customer_name is None


def test_model_name_that_continues_a_short_label_reading_is_kept():
    doc = "Borrower: Julia Maria da Silva Costa Address: 1 Main Road. LENDER: Bank X, NY."
    # Simulate a label reading that stopped early.
    from app import parser
    facts = parser.extract_labeled_facts(doc)
    assert facts["customer_name"] == "Julia Maria da Silva Costa"
    meta = ground_metadata({"customer_name": "Julia Maria da Silva Costa", "lender_name": "Bank X"}, doc)
    assert meta["customer_name"] == "Julia Maria da Silva Costa" and not meta["extraction_warnings"]


def test_longer_model_name_running_into_the_next_field_is_not_used(monkeypatch):
    doc = "Borrower: Julia Miller Address: 1 Main Road."
    meta = ground_metadata({"customer_name": "Julia Miller Address 1 Main Road"}, doc)
    assert meta["customer_name"] == "Julia Miller"


import pytest  # noqa: E402

from app.parser import extract_labeled_facts  # noqa: E402


@pytest.mark.parametrize("text, key, expected", [
    ("Borrower: Julia Maria da Silva Costa Address: 1 Road", "customer_name", "Julia Maria da Silva Costa"),
    ("Borrower: The Smith Family Trust Dated: 2020", "customer_name", "The Smith Family Trust"),
    ("LENDER: Acme Holdings Limited Trading As Acme: Retail, NY", "lender_name", "Acme Holdings Limited Trading As Acme"),
    ("Borrower: Sunrise Solar\nPrivate Limited\nAddress: x", "customer_name", "Sunrise Solar Private Limited"),
    ("Borrower: John Smith Lender: First Bank, NY", "customer_name", "John Smith"),
    ("LENDER: Beta Capital LLC Attn: J. Doe", "lender_name", "Beta Capital LLC"),
    ("Borrower: John Smith\nThis agreement is made", "customer_name", "John Smith"),
])
def test_name_boundaries(text, key, expected):
    assert extract_labeled_facts(text)[key] == expected


@pytest.mark.parametrize("text, value", [
    ("Principal Amount: Rupees Five Lakh Only: Rs. 5,00,000", 500000),
    ("LOAN AMOUNT: $1,250.500", 1250.5),
    ("FINANCED AMOUNT: EUR 45.892", 45892),
])
def test_amount_edge_cases(text, value):
    assert extract_labeled_facts(text)["contract_value"] == value


def test_short_label_reading_does_not_replace_the_full_model_name(monkeypatch):
    import app.mcp.llm_agent as agent
    monkeypatch.setattr(agent, "extract_labeled_facts", lambda text: {"customer_name": "Julia Maria da"})
    doc = "Borrower: Julia Maria da Silva Costa, residing in Rio."
    meta = ground_metadata({"customer_name": "Julia Maria da Silva Costa"}, doc)
    assert meta["customer_name"] == "Julia Maria da Silva Costa"
    assert "continuing the document label" in meta["field_sources"]["customer_name"]
