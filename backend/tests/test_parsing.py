from conftest import fixture_text

from app.parser import (
    coverage_report,
    extract_labeled_facts,
    find_money_amounts,
    split_document,
)


def test_header_is_separated_from_clauses():
    header, clauses = split_document(fixture_text("julia_miller.txt"))
    assert header.startswith("HEALTH FINANCING AGREEMENT BORROWER: Julia Miller")
    assert header.endswith("FINANCED AMOUNT: $45,892.00.")
    assert len(clauses) == 8
    assert clauses[0].startswith("CLAUSE ONE")
    assert clauses[-1].startswith("CLAUSE EIGHT")
    assert all("FINANCED AMOUNT" not in c for c in clauses)


def test_single_line_pdf_text_is_split(  # Contract_1 was once stored as one giant clause
):
    header, clauses = split_document(fixture_text("contract_1.txt"))
    assert "FINANCED AMOUNT: $82,437.00." in header
    assert len(clauses) == 8
    assert all(len(c) < 300 for c in clauses)


def test_cents_are_not_cut_off_before_a_heading():
    header, _ = split_document("FINANCED AMOUNT: $45,892.00.\nCLAUSE ONE – PURPOSE: Financing for the asset described.")
    assert header == "FINANCED AMOUNT: $45,892.00."


def test_document_without_preamble_has_no_header():
    header, clauses = split_document(fixture_text("no_preamble.txt"))
    assert header is None
    assert len(clauses) == 8


def test_title_only_preamble_is_not_a_header():
    header, clauses = split_document(
        "AGREEMENT\nCLAUSE ONE – PURPOSE: This agreement aims to grant financing to the BORROWER.\n"
        "CLAUSE TWO – TERM: The financing period shall be up to 60 months."
    )
    assert header is None
    assert len(clauses) == 2


def test_coverage_is_complete_for_real_template():
    text = fixture_text("julia_miller.txt")
    header, clauses = split_document(text)
    assert coverage_report(text, header, clauses)["ok"]


def test_coverage_flags_dropped_content():
    text = fixture_text("julia_miller.txt")
    header, clauses = split_document(text)
    report = coverage_report(text, header, clauses[:3])
    assert not report["ok"]
    assert "jurisdiction" in report["missing_sample"] or report["ratio"] < 0.95


def test_labeled_facts_from_template():
    facts = extract_labeled_facts(fixture_text("julia_miller.txt"))
    assert facts["contract_value"] == 45892.0
    assert facts["currency"] == "USD"
    assert facts["contract_value_text"] == "$45,892.00"
    assert facts["lender_name"] == "FINANCIAL BANK OF AMERICA Inc"
    assert facts["customer_name"] == "Julia Miller"


def test_labeled_amount_without_cents():
    facts = extract_labeled_facts(fixture_text("carlos_brown_real_estate.txt"))
    assert facts["contract_value"] == 1203432.0
    assert facts["customer_name"] == "Carlos Brown"


def test_generic_party_labels_are_not_names():
    facts = extract_labeled_facts("Agreement between the BANK and the BORROWER. LENDER: the Bank, as defined.")
    assert "lender_name" not in facts


def test_money_amounts_in_several_formats():
    found = {(a["value"], a["currency"]) for a in find_money_amounts("INR 5,00,000 and 1200 USD and ₹1,20,000.50 and $9.99")}
    assert found == {(500000.0, "INR"), (1200.0, "USD"), (120000.5, "INR"), (9.99, "USD")}
