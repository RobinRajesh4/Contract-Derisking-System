"""
Chat answers must be about the right contracts: rankings and totals over
all of them, named contracts read directly, questions across contracts
covering every contract. Each test reproduces a failure found in review.

The portfolio is near-identical financing contracts that differ only in
borrower, amount and interest rate - like the real data, where plain
top-k search returns whichever few contracts happen to score highest.
"""
import json

from conftest import upload

from app.schemas import parse_money

PEOPLE = [
    ("Julia Miller", 45892, "1.2"), ("Peter Chen", 76877, "0.9"), ("Anna Silva", 75546, "1.5"),
    ("Omar Haddad", 1203432, "1.1"), ("Grace Park", 82437, "1.6"), ("Luis Gomez", 9999, "1.3"),
]


def contract(name, amount, rate):
    return (
        "ASSET FINANCING AGREEMENT\n"
        f"BORROWER: {name}, residing at 1 Main Avenue - Boston, MA.\n"
        "LENDER: FINANCIAL BANK OF AMERICA Inc, headquartered in New York, NY.\n"
        f"FINANCED AMOUNT: ${amount:,.2f}.\n"
        "CLAUSE ONE – PURPOSE: This agreement grants financing to the BORROWER for the asset described.\n"
        "CLAUSE TWO – TERM: The financing period shall be up to 60 months.\n"
        f"CLAUSE THREE – PAYMENT: The BORROWER shall pay monthly installments with interest of {rate}% per month.\n"
        "CLAUSE FOUR – DEFAULT: Payment delay results in a penalty of 2% on the installment.\n"
        "CLAUSE FIVE – JURISDICTION: The parties elect the Courts of New York, NY.\n"
    )


def load_portfolio(client):
    ids = {}
    for i, (name, amount, rate) in enumerate(PEOPLE, start=1):
        ids[name] = upload(client, f"Contract_{i}.txt", contract(name, amount, rate))["analysis_id"]
    return ids


def spec(**kw):
    base = {"kind": "structured", "operation": "list", "sort_by": None, "order": "desc", "limit": None,
            "filters": [], "fields": [], "contracts": [], "across_contracts": False, "standalone_question": None}
    return json.dumps(base | kw)


def last_answer_prompt(fake_llm):
    return [c[1] for c in fake_llm.calls if c[0] == "text"][-1]


def chat(client, message, **kw):
    r = client.post("/chat", json={"message": message, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------- structured scope

def test_ranking_covers_all_contracts_even_with_one_open(client, fake_llm):
    ids = load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(sort_by="contract_value", order="desc", limit=1)
    r = chat(client, "Which contract has the highest amount?", analysis_id=ids["Luis Gomez"])
    assert "**Contract_4.txt** has the highest amount: **$1,203,432.00**" in r["reply"]
    assert "Across all contracts" in r["reply"]


def test_count_covers_all_contracts_even_with_one_open(client, fake_llm):
    ids = load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(operation="count")
    r = chat(client, "How many contracts are there?", analysis_id=ids["Julia Miller"])
    assert "**6** contracts match" in r["reply"]


def test_plain_lookup_uses_the_open_contract(client, fake_llm):
    ids = load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(fields=["customer_name"])
    r = chat(client, "Who is the borrower?", analysis_id=ids["Peter Chen"])
    assert "Peter Chen" in r["reply"] and "Julia Miller" not in r["reply"]


def test_lookup_shows_the_field_that_was_asked_for(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(fields=["lender_name"], contracts=["Contract_3"])
    r = chat(client, "Who is the lender of Contract_3?")
    assert "| Lender |" in r["reply"] and "FINANCIAL BANK OF AMERICA" in r["reply"]
    assert "Contract_3.txt" in r["reply"] and "Contract_1.txt" not in r["reply"]


def test_contract_named_by_borrower_is_found_even_if_router_puts_it_in_a_filter(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(
        fields=["contract_value"], filters=[{"field": "filename", "op": "contains", "value": "Anna Silva"}]
    )
    r = chat(client, "What is Anna Silva's financed amount?")
    assert "$75,546.00" in r["reply"] and "No contracts match" not in r["reply"]


def test_total_of_top_three(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(operation="sum", sort_by="contract_value", limit=3)
    r = chat(client, "What is the total of the 3 largest loans?")
    assert "$1,362,746.00" in r["reply"]  # 1,203,432 + 82,437 + 76,877
    assert "3 largest" in r["reply"]


def test_router_down_still_answers_highest_exactly(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: "server error, not json"
    r = chat(client, "which contract has the highest financed amount")
    assert r["route"] == "structured" and r["routed_by"] == "heuristic"
    assert "**Contract_4.txt** has the highest amount" in r["reply"]


def test_router_down_does_not_misread_clause_questions_as_amounts(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: "server error, not json"
    r = chat(client, "which contract has the highest interest rate")
    assert r["route"] == "semantic"


# ------------------------------------------------------------ semantic scope

def test_named_contract_question_reads_only_that_contract(client, fake_llm):
    # Router misses the name entirely; the literal match still finds it.
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "What is the monthly interest rate in Julia Miller's contract?")
    prompt = last_answer_prompt(fake_llm)
    assert "interest of 1.2% per month" in prompt
    for other_rate in ("0.9%", "1.5%", "1.1%", "1.6%", "1.3%"):
        assert f"interest of {other_rate}" not in prompt


def test_first_name_alone_identifies_a_unique_borrower(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "What does Omar's default clause say?")
    prompt = last_answer_prompt(fake_llm)
    assert "Contract_4.txt" in prompt and "Contract_1.txt" not in prompt.split("Sources:")[1]


def test_question_across_contracts_sees_every_contract(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "across_contracts": True})
    chat(client, "Which contracts charge more than 1.4% monthly interest?")
    prompt = last_answer_prompt(fake_llm)
    sources = prompt.split("Sources:")[1]
    for i in range(1, len(PEOPLE) + 1):
        assert f"Contract_{i}.txt" in sources
    assert "each of 6 of the 6 contracts" in prompt


def test_across_is_detected_even_if_router_says_no(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "Which contracts have an interest rate above 1.4%?")
    assert "each of 6 of the 6 contracts" in last_answer_prompt(fake_llm)


def test_generic_question_says_how_much_it_covers(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "What does the jurisdiction clause say?")
    assert "most relevant passages, from" in last_answer_prompt(fake_llm)


def test_follow_up_uses_the_router_rewrite_for_search(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({
        "kind": "semantic", "contracts": ["Peter Chen"],
        "standalone_question": "What is the monthly interest rate in Peter Chen's contract?",
    })
    history = [{"role": "user", "content": "What is the interest rate in Julia Miller's contract?"},
               {"role": "assistant", "content": "1.2% per month [Source 3](#source-3)."}]
    chat(client, "and for Peter?", history=history)
    sources = last_answer_prompt(fake_llm).split("Sources:")[1]
    assert "interest of 0.9% per month" in sources and "interest of 1.2%" not in sources


def test_follow_up_without_router_searches_with_previous_question(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: "not json"
    history = [{"role": "user", "content": "What is the interest rate in Julia Miller's contract?"},
               {"role": "assistant", "content": "1.2% per month."}]
    chat(client, "what about the default penalty?", history=history)
    assert "Julia Miller" in last_answer_prompt(fake_llm).split("Sources:")[1] or \
        "Contract_1.txt" in last_answer_prompt(fake_llm).split("Sources:")[1]


def test_references_are_the_cited_sources(client, fake_llm):
    ids = load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    fake_llm.handlers["text"] = lambda p: "It is 1.2% [Source 4](#source-4)."
    r = chat(client, "What is the interest rate?", analysis_id=ids["Julia Miller"])
    assert [s["source_number"] for s in r["sources"]] == [4]
    assert "1.2%" in r["sources"][0]["text"]


def test_deleted_open_contract_gives_a_clear_message(client, fake_llm):
    load_portfolio(client)
    r = client.post("/chat", json={"message": "hi", "analysis_id": "gone"})
    assert r.status_code == 404 and "no longer exists" in r.json()["detail"]


def test_ai_server_failure_is_a_clear_503(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})

    def boom(prompt):
        raise RuntimeError("HTTP 500 out of memory")
    fake_llm.handlers["text"] = boom
    r = client.post("/chat", json={"message": "What does the default clause say?"})
    assert r.status_code == 503 and "try again" in r.json()["detail"]


# ------------------------------------------------------------------ amounts

def test_amounts_written_with_units_and_local_formats():
    assert parse_money("$50k") == 50000
    assert parse_money("1 million") == 1_000_000
    assert parse_money("1.5M") == 1_500_000
    assert parse_money("Rs. 5,00,000") == 500000
    assert parse_money("EUR 45.892,00") == 45892
    assert parse_money("$1,203,432.00") == 1203432
    assert parse_money("2.5 crore") == 25_000_000
    assert parse_money("no number") is None


def test_amount_filter_with_k(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(
        sort_by="contract_value", filters=[{"field": "contract_value", "op": "greater_than", "value": "80k"}]
    )
    r = chat(client, "Loans above 80k")
    assert "Contract_4.txt" in r["reply"] and "Contract_5.txt" in r["reply"]
    assert "Contract_2.txt" not in r["reply"]


def test_numbers_that_are_not_thousands():
    assert parse_money("2.125") == 2.125
    assert parse_money("0.875%") == 0.875
    assert parse_money("above 1.250 million") == 1_250_000
    assert parse_money("15.01.2024") is None
    assert parse_money("2024-01-15") is None
    assert parse_money("$45,892 360") == 45892
    assert parse_money("12 500 000 EUR") == 12_500_000
    assert parse_money("45.892.000") == 45_892_000


# ------------------------------------ names mentioned in passing (review)

def test_ordinary_word_matching_a_borrower_name_does_not_narrow(client, fake_llm):
    load_portfolio(client)  # includes borrower "Grace Park"
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "across_contracts": True})
    chat(client, "Which contracts have a grace period for late payments?")
    assert "each of 6 of the 6 contracts" in last_answer_prompt(fake_llm)


def test_count_by_lender_is_not_narrowed_by_name_words(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(
        operation="count", filters=[{"field": "lender_name", "op": "contains", "value": "Financial Bank of America"}]
    )
    r = chat(client, "How many contracts are with Financial Bank of America?")
    assert "**6** contracts match" in r["reply"]


def test_company_named_like_a_common_word(client, fake_llm):
    for i, (name, amount) in enumerate([("Total Logistics Ltd", 50000), ("Sunrise Solar", 70000),
                                        ("Peter Chen", 30000)], start=1):
        upload(client, f"Loan_{i}.txt", contract(name, amount, "1.0"))
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(operation="sum")
    r = chat(client, "What is the total amount financed?")
    assert "$150,000.00" in r["reply"] and "across 3 contract" in r["reply"]
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "across_contracts": True})
    chat(client, "Which contracts finance solar equipment?")
    assert "each of 3 of the 3 contracts" in last_answer_prompt(fake_llm)


def test_generic_multi_word_file_name_is_not_matched_in_lower_case(client, fake_llm):
    upload(client, "Loan Agreement.txt", contract("Julia Miller", 45892, "1.2"))
    upload(client, "Other.txt", contract("Peter Chen", 76877, "0.9"))
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "Does any loan agreement require insurance?")
    assert "most relevant passages, from" in last_answer_prompt(fake_llm)
    chat(client, "What does the Loan Agreement say about default?")
    assert "question names: Loan Agreement.txt" in last_answer_prompt(fake_llm)


def test_possessive_first_name_still_counts(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "julia's interest rate?")
    sources = last_answer_prompt(fake_llm).split("Sources:")[1]
    assert "interest of 1.2% per month" in sources and "interest of 0.9%" not in sources


def test_router_down_follow_up_ranking_is_not_about_the_previous_contract(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: "not json"
    history = [{"role": "user", "content": "What is the interest rate for Julia Miller?"},
               {"role": "assistant", "content": "1.2% per month."}]
    r = chat(client, "Which contract has the highest amount?", history=history)
    assert "**Contract_4.txt** has the highest amount" in r["reply"]


import pytest  # noqa: E402

from app.chat_router import heuristic_spec  # noqa: E402


@pytest.mark.parametrize("question", [
    "How many contracts mention prepayment?", "How many months is the loan term?",
    "What is the total loan tenure?", "What is the sum insured?", "Which has the maximum loan-to-value?",
    "Which contract has the most installments?", "Which contract has the highest interest rate?",
])
def test_fallback_leaves_non_amount_questions_to_the_semantic_path(question):
    assert heuristic_spec(question) is None


@pytest.mark.parametrize("question, operation, order", [
    ("How many contracts are there?", "count", None),
    ("which contract has the highest financed amount", "list", "desc"),
    ("Which loan has the least amount?", "list", "asc"),
    ("What is the total amount financed?", "sum", None),
])
def test_fallback_answers_plain_amount_questions(question, operation, order):
    s = heuristic_spec(question)
    assert s is not None and s.operation == operation and (order is None or s.order == order)


# ----------------------------------------------------------- prompt size

import app.main as main_module  # noqa: E402


def test_shortened_passage_keeps_the_sentence_that_answers():
    clause = ("CLAUSE THREE – PAYMENT: " + "The BORROWER shall comply with the schedule agreed. " * 20
              + "Monthly interest is 1.45% on the outstanding balance. " + "Further terms apply. " * 10)
    short = main_module._focus_passage(clause, "Which contracts charge more than 1.4% monthly interest?", 300)
    assert "1.45%" in short and len(short) <= 310


def test_prompt_never_exceeds_the_context_budget(client, fake_llm, monkeypatch):
    load_portfolio(client)
    monkeypatch.setattr(main_module, "_MAX_PROMPT_CHARS", 3000)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "across_contracts": True})
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 1400} for i in range(6)]
    chat(client, "Which contracts charge more than 1.4% monthly interest?", history=history)
    prompt = last_answer_prompt(fake_llm)
    assert len(prompt) <= 3000 + 200
    assert "interest of 1.2%" in prompt  # the answering sentence survived trimming


# ------------------------------------------------ second review round

def test_capitalised_common_phrase_in_an_across_question_does_not_narrow(client, fake_llm):
    load_portfolio(client)  # Grace Park
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    chat(client, "Which contracts have a Grace Period?")
    assert "each of 6 of the 6 contracts" in last_answer_prompt(fake_llm)


from app.chat_router import _multi_word_file_named  # noqa: E402


@pytest.mark.parametrize("stem, question, expected", [
    ("ACME_LOAN", "rate in acme_loan.pdf", True),
    ("ACME_LOAN", "rate in Acme Loan", True),
    ("Loan Agreement", "Does any loan agreement require insurance?", False),
    ("lease agreement", "What does the lease agreement say?", False),
    ("Loan Agreement", "What does the Loan Agreement say?", True),
])
def test_multi_word_file_names(stem, question, expected):
    assert _multi_word_file_named(stem, question) is expected


@pytest.mark.parametrize("question, operation, limit", [
    ("Largest contract?", "list", 1),
    ("Which contract is worth the most?", "list", 1),
    ("Top 5 contracts by value", "list", 5),
    ("Sum of all contracts", "sum", None),
    ("Show the 3 largest contracts", "list", 3),
    ("What is the total number of contracts?", "count", None),
])
def test_fallback_catches_plain_amount_phrasings(question, operation, limit):
    s = heuristic_spec(question)
    assert s is not None and s.operation == operation and s.limit == limit


def test_long_single_sentence_is_shortened_around_the_match():
    clause = ("The BORROWER shall pay monthly installments to the BANK in accordance with the schedule "
              "agreed between the parties and any amendments thereto " * 5 + "with interest at 1.4% per month")
    short = main_module._focus_passage(clause, "monthly interest rate above 1.4%", 200)
    assert "1.4%" in short and len(short) <= 210


# ---------------------------------------------- real-session regressions

def test_structured_answer_says_how_many_contracts_it_covers(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(sort_by="contract_value", order="desc", limit=1)
    r = chat(client, "which contract has the highest financial amounts")
    assert "Based on the 6 contracts currently stored" in r["reply"]


def test_semantic_prompt_carries_risk_counts_and_the_no_inference_rule(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic", "contracts": ["Julia Miller"]})
    chat(client, "why is Julia Miller's contract risky?")
    prompt = last_answer_prompt(fake_llm)
    assert "Risk analysis: not analyzed yet" in prompt
    assert "Never\n   infer risk from the amount" in main_module.CHAT_SYSTEM_PROMPT


@pytest.mark.parametrize("question, sort_by, offset, limit", [
    ("which contracts have the highest risks", "high_risk_clauses", 0, None),
    ("which contract is the riskiest", "high_risk_clauses", 0, 1),
    ("what is the second highest amount", "contract_value", 1, 1),
    ("third lowest loan amount", "contract_value", 2, 1),
])
def test_fallback_understands_risk_and_ordinals(question, sort_by, offset, limit):
    s = heuristic_spec(question)
    assert s is not None and (s.sort_by, s.offset, s.limit) == (sort_by, offset, limit)


# ------------------------------------------- citations in other formats

import pytest  # noqa: E402

from app.main import likely_sources, link_citations  # noqa: E402


@pytest.mark.parametrize("written, linked", [
    ("1.2% [Source 2].", "1.2% [Source 2](#source-2)."),
    ("1.2% [Source 2 | Contract_5.pdf | clause 3].", "1.2% [Source 2](#source-2)."),
    ("1% (Source 4).", "1% ([Source 4](#source-4))."),
    ("Both [Sources 1, 3].", "Both [Source 1](#source-1), [Source 3](#source-3)."),
    ("See (Sources 1 and 2).", "See ([Source 1](#source-1), [Source 2](#source-2))."),
    ("In Sources 2-4.", "In [Source 2](#source-2), [Source 3](#source-3), [Source 4](#source-4)."),
    ("60 months [2].", "60 months [Source 2](#source-2)."),
    ("Per Source 3, 60 months.", "Per [Source 3](#source-3), 60 months."),
    ("Right [Source 2](#source-2).", "Right [Source 2](#source-2)."),
    ("【Source 2】 x", "[Source 2](#source-2) x"),
])
def test_citation_formats_become_links(written, linked):
    assert link_citations(written, 5) == linked


def test_citation_of_a_missing_source_is_not_a_link():
    assert link_citations("See [Source 9] and [Source 9](#source-9) and [12].", 5) == \
        "See Source 9 and Source 9 and [12]."


def test_citations_inside_code_blocks_are_left_alone():
    assert link_citations("```\n[Source 1]\n```", 5) == "```\n[Source 1]\n```"


def test_label_style_citation_on_a_selected_contract_still_gives_references(client, fake_llm):
    # The whole contract is sent (no search), so before the fix an answer
    # citing "[Source 5 | file | clause 4]" came back with no references.
    ids = load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    fake_llm.handlers["text"] = lambda p: "The penalty is 2% [Source 5 | Contract_1.txt | clause 4]."
    r = chat(client, "What is the late interest?", analysis_id=ids["Julia Miller"])
    assert "[Source 5](#source-5)" in r["reply"]
    assert [s["source_number"] for s in r["sources"]] == [5]
    assert "penalty of 2%" in r["sources"][0]["text"]
    assert r["citations"] == "cited"


def test_uncited_answer_shows_its_most_likely_sources(client, fake_llm):
    ids = load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: json.dumps({"kind": "semantic"})
    fake_llm.handlers["text"] = lambda p: "A payment delay results in a 2% penalty on the installment."
    r = chat(client, "What happens if I pay late?", analysis_id=ids["Julia Miller"])
    assert r["citations"] == "inferred"
    assert r["sources"] and "penalty of 2%" in " ".join(r["sources"][0]["text"].split())


def test_likely_sources_prefers_matching_figures():
    sources = [
        {"source_number": 1, "text": "The financing period shall be up to 60 months."},
        {"source_number": 2, "text": "Interest of 1.2% per month, corrected by the CPI."},
    ]
    assert likely_sources("The interest is 1.2% per month.", sources)[0]["source_number"] == 2


def test_copied_header_label_with_parentheses_becomes_a_link():
    written = "Julia Miller [Source 1 | Contract_1.txt | contract header (parties, amounts)]."
    assert link_citations(written, 5) == "Julia Miller [Source 1](#source-1)."


def test_round_brackets_do_not_swallow_the_rest_of_the_sentence():
    assert link_citations("It is 2% (Source 3) and applies (see below).", 5) == \
        "It is 2% ([Source 3](#source-3)) and applies (see below)."


def test_clause_topic_misread_as_a_list_goes_to_the_clause_text(client, fake_llm):
    # The router returned a "list" that selects nothing for "anything
    # mentioned about ...": every contract was printed, each linked to its
    # header, instead of the clause the question is about.
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec()
    fake_llm.handlers["text"] = lambda p: "All contracts: a 2% penalty on late installments [Source 1]."
    r = chat(client, "anything mentioned about default")
    assert r["route"] == "semantic"
    assert r["sources"] and all(s["kind"] == "clause" for s in r["sources"])
    assert "penalty of 2%" in r["sources"][0]["text"]
    # Same wording in every contract: one source that lists the others.
    assert len(r["sources"][0]["also_in"]) == 5


def test_real_listing_request_still_lists_contracts(client, fake_llm):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec()
    r = chat(client, "list all contracts")
    assert r["route"] == "structured" and "6 matching contracts" in r["reply"]


# ------------------------------------------ follow-ups to an exact answer

def _highest_then(client, fake_llm, follow_up, router_reply):
    load_portfolio(client)
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(sort_by="contract_value", order="desc", limit=1)
    first = chat(client, "which contract has the highest number of financial amounts")
    assert first["route"] == "structured"
    fake_llm.handlers["ChatQuerySpec"] = lambda p: router_reply
    return chat(client, follow_up, previous_spec=first["query_spec"],
                previous_ids=[src["analysis_id"] for src in first["sources"]],
                history=[{"role": "user", "content": "which contract has the highest amount"},
                         {"role": "assistant", "content": first["reply"]}])


def test_list_the_other_ones_after_the_highest(client, fake_llm):
    # The router made this a query that selected nothing; it used to go to
    # the language model, which printed internal IDs and no amounts.
    r = _highest_then(client, fake_llm, "list the other ones too", spec())
    assert r["route"] == "structured" and r["routed_by"] == "follow-up"
    amounts = [parse_money(line.split("|")[3]) for line in r["reply"].splitlines() if line.startswith("| ") and "$" in line]
    assert amounts == sorted(amounts, reverse=True) and len(amounts) == 5
    assert 1203432 not in amounts  # the highest one was already shown
    assert "the 1 already shown are left out" in r["reply"]
    assert "Based on the 6 contracts currently stored" in r["reply"]


def test_all_of_them_lists_every_contract(client, fake_llm):
    r = _highest_then(client, fake_llm, "show all of them", json.dumps({"kind": "semantic"}))
    assert r["route"] == "structured" and len(r["sources"]) == 6


def test_follow_up_the_router_understood_is_left_alone(client, fake_llm):
    r = _highest_then(client, fake_llm, "and the lowest one too", spec(sort_by="contract_value", order="asc", limit=1))
    assert "$9,999.00" in r["reply"] and r["routed_by"] == "llm"


def test_clause_follow_up_is_not_widened(client, fake_llm):
    r = _highest_then(client, fake_llm, "what about its default terms too", json.dumps({"kind": "semantic"}))
    assert r["route"] == "semantic"


def test_the_other_ones_after_a_tie_shows_no_contract_twice(client, fake_llm):
    # "Highest" showed every tied contract; "the other ones" must not
    # repeat any of them.
    for i in range(3):
        upload(client, f"Tie_{i}.txt", contract(f"Tie Person{i}", 50000, "1.0"))
    upload(client, "Small.txt", contract("Small Person", 1000, "1.0"))
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec(sort_by="contract_value", order="desc", limit=1)
    first = chat(client, "which contract has the highest amount")
    assert len(first["sources"]) == 3
    fake_llm.handlers["ChatQuerySpec"] = lambda p: spec()
    r = chat(client, "list the other ones", previous_spec=first["query_spec"],
             previous_ids=[src["analysis_id"] for src in first["sources"]])
    assert [src["filename"] for src in r["sources"]] == ["Small.txt"]
