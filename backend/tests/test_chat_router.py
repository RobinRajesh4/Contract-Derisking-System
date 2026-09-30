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


# ------------------------------------------- risk, second-highest, grouping
# From a real session: "highest risks" was answered by amount, "second
# highest" repeated the highest, "top lender" listed contracts.

def analyzed(i, filename, value, levels, lender="FINANCIAL BANK OF AMERICA Inc", score=None):
    r = record(i, filename, value, lender=lender)
    r["status"] = "analyzed"
    r["results"] = [{"id": n, "classification": {"risk_level": lvl}} for n, lvl in enumerate(levels, 1)]
    r["policy_summary"] = {"total_policy_score": score} if score is not None else {}
    return r


RISKY = [
    analyzed(1, "Contract_1.pdf", 82437, ["High", "Medium", "Low", "Low"]),
    analyzed(2, "Contract_2.pdf", 38384, ["High", "High", "Medium", "Low"]),        # riskiest
    analyzed(3, "Contract_3.pdf", 45892, ["High", "Medium", "Medium", "Medium"]),   # ties C1 on high, more medium
    analyzed(4, "Contract_11.pdf", 1201349, ["Low", "Low", "Low"], lender="Other Bank"),
    record(5, "Contract_12.pdf", 83400),                                           # not analyzed
]


def run_risky(**spec):
    return execute_spec(ChatQuerySpec(kind="structured", **spec), RISKY)


def test_riskiest_contracts_are_ranked_by_risk_not_amount():
    r = run_risky(sort_by="high_risk_clauses", order="desc")
    assert [a["filename"] for a in r["rows"]] == ["Contract_2.pdf", "Contract_3.pdf", "Contract_1.pdf", "Contract_11.pdf"]
    assert "Not risk-analyzed yet, so left out: Contract_12.pdf" in r["answer"]
    assert "| High-risk clauses |" in r["answer"] and "| Medium-risk clauses |" in r["answer"]


def test_most_medium_risks():
    r = run_risky(sort_by="medium_risk_clauses", order="desc", limit=1)
    assert "**Contract_3.pdf** has the most medium-risk clauses: **3**" in r["answer"]


def test_second_highest_amount():
    r = run_risky(sort_by="contract_value", order="desc", limit=1, offset=1)
    assert "**Contract_12.pdf** has the second highest amount: **$83,400.00**" in r["answer"]


def test_lender_with_most_contracts():
    r = run_risky(operation="group", group_by="lender_name")
    assert "**FINANCIAL BANK OF AMERICA Inc** is the lender with the most contracts: **4** of 5" in r["answer"]
    assert "| Other Bank | 1 |" in r["answer"]
    assert {a["filename"] for a in r["rows"]} == {"Contract_1.pdf", "Contract_2.pdf", "Contract_3.pdf", "Contract_12.pdf"}


def test_unanalyzed_contract_has_unknown_not_zero_risk():
    r = run_risky(sort_by="high_risk_clauses", order="asc", limit=1)
    assert "Contract_11.pdf" in r["answer"] and "Contract_12.pdf** has" not in r["answer"]


MIXED = [
    record(1, "01_Auto_Loan_Okafor.pdf", 38750),
    record(2, "02_Home_Mortgage_Rahman.pdf", 412000),
    record(9, "09_Commercial_Real_Estate_Harbor_Point.pdf", 1250000),
    record(10, "10_Home_Loan_Raghavan_INR.pdf", 4850000, currency="INR"),
]


def test_second_highest_with_a_single_contract_in_another_currency():
    # The one INR contract has no second place; it used to leave the
    # answer titled "Highest amount in each currency".
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", limit=1, offset=1), MIXED)
    assert "**02_Home_Mortgage_Rahman.pdf** has the second highest amount: **$412,000.00**" in r["answer"]
    assert "Highest amount" not in r["answer"]
    assert "Only 1 INR contract, so no second one in INR." in r["answer"]


def test_second_highest_in_each_currency():
    data = MIXED + [record(11, "11_Car_Loan_INR.pdf", 950000, currency="INR")]
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", limit=1, offset=1), data)
    assert r["answer"].startswith("Second highest amount in each currency:")
    assert [a["filename"] for a in r["rows"]] == ["11_Car_Loan_INR.pdf", "02_Home_Mortgage_Rahman.pdf"]


def test_ordinal_beyond_the_number_of_contracts():
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", limit=1, offset=4),
                     MIXED[:3])
    assert r["answer"] == "There are only 3 contracts with this information, so there is no fifth one."


def test_the_rest_after_the_highest_in_each_currency():
    data = MIXED + [record(11, "11_Car_Loan_INR.pdf", 950000, currency="INR")]
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", offset=1), data)
    assert r["answer"].startswith("The other contracts in each currency, after the first 1")
    assert [a["filename"] for a in r["rows"]] == ["11_Car_Loan_INR.pdf", "02_Home_Mortgage_Rahman.pdf",
                                                   "01_Auto_Loan_Okafor.pdf"]


def test_the_rest_when_a_currency_has_no_more():
    r = execute_spec(ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", offset=1), MIXED)
    assert "No other INR contracts." in r["answer"]
    assert "so no second one" not in r["answer"]
