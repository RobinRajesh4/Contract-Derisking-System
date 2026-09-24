from app.chat_router import execute_spec, sources_for_rows
from app.schemas import ChatQuerySpec


def record(i, filename, value, currency="USD", lender="FINANCIAL BANK OF AMERICA Inc", customer="X", end=None):
    return {
        "analysis_id": f"id{i}",
        "filename": filename,
        "header": {"text": f"header of {filename}", "page": 1},
        "contract_metadata": {
            "contract_value": value, "currency": currency, "lender_name": lender,
            "customer_name": customer, "end_date": end,
        },
    }


# Values seen in the real chat transcripts.
DATA = [
    record(1, "Contract_1.pdf", 82437),
    record(2, "Contract_12.pdf", 1203432, customer="Carlos Brown", end="2027-03-01"),
    record(3, "Contract_3.pdf", 75546, end="2026-01-10"),
    record(4, "Contract_31.pdf", 76877),
    record(5, "Contract_5.pdf", 45892, customer="Julia Miller"),
    record(6, "test.txt", None, lender=None),
]


def run(**spec):
    return execute_spec(ChatQuerySpec(kind="structured", **spec), DATA)


def test_highest_amount():
    r = run(sort_by="contract_value", order="desc", limit=1)
    assert [a["filename"] for a in r["rows"]] == ["Contract_12.pdf"]
    assert "**Contract_12.pdf** has the highest amount: **$1,203,432.00**" in r["answer"]


def test_lowest_amount():
    r = run(sort_by="contract_value", order="asc", limit=1)
    assert [a["filename"] for a in r["rows"]] == ["Contract_5.pdf"]


def test_full_ranking_is_strictly_ordered():
    # The chatbot once listed 76,877 below 75,546 in a "descending" table.
    r = run(sort_by="contract_value", order="desc")
    values = [a["contract_metadata"]["contract_value"] for a in r["rows"]]
    assert values == sorted(values, reverse=True)
    assert "test.txt" in r["answer"]  # named as having no amount, not silently dropped


def test_ties_at_the_cut_off_are_all_shown():
    data = DATA + [record(7, "Contract_9.pdf", 45892)]
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="asc", limit=1), data)
    assert {a["filename"] for a in r["rows"]} == {"Contract_5.pdf", "Contract_9.pdf"}
    assert "tied" in r["answer"]


def test_currencies_are_never_compared():
    data = DATA + [record(8, "India_loan.pdf", 5000000, currency="INR")]
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", limit=1), data)
    assert {a["filename"] for a in r["rows"]} == {"Contract_12.pdf", "India_loan.pdf"}
    assert "aren't compared" in r["answer"]
    r = execute_spec(ChatQuerySpec(kind="structured", operation="sum"), data)
    assert "$1,484,184.00" in r["answer"] and "₹5,000,000.00" in r["answer"]


def test_named_contract_lookup_does_not_match_similar_names():
    r = run(filters=[{"field": "filename", "op": "contains", "value": "Contract_3"}])
    assert [a["filename"] for a in r["rows"]] == ["Contract_3.pdf"]


def test_count_with_filter_reports_unknowns():
    r = run(operation="count", filters=[{"field": "lender_name", "op": "contains", "value": "financial bank of america"}])
    assert "**5** contracts match" in r["answer"]
    assert "test.txt" in r["answer"]


def test_date_filter():
    r = run(sort_by="end_date", order="asc", filters=[{"field": "end_date", "op": "before", "value": "2027"}])
    assert [a["filename"] for a in r["rows"]] == ["Contract_3.pdf"]


def test_amount_filter():
    r = run(sort_by="contract_value", filters=[{"field": "contract_value", "op": "greater_than", "value": "$80,000"}])
    assert [a["filename"] for a in r["rows"]] == ["Contract_12.pdf", "Contract_1.pdf"]


def test_sources_point_to_headers_in_answer_order():
    r = run(sort_by="contract_value", order="desc", limit=2)
    sources = sources_for_rows(r["rows"])
    assert [(s["source_number"], s["filename"], s["clause_id"]) for s in sources] == [
        (1, "Contract_12.pdf", "header"), (2, "Contract_1.pdf", "header"),
    ]
