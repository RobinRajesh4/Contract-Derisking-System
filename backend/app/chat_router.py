"""
Answers chat questions that are really database questions - highest,
lowest, totals, counts, "which contracts are with bank X", "what is
the financed amount of Contract_7" - exactly, in code, from the stored
contract directory.

A language model is used only to translate the question into a small,
validated query spec (ChatQuerySpec). It never sorts, compares or adds
numbers itself: those steps are ordinary Python below, so the answer is
the same every time and can't contradict itself.

Anything that needs clause wording is marked "semantic" and goes to
the normal retrieval + LLM path in main.py.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from .schemas import ChatQuerySpec, QueryFilter, parse_money

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FIELD_LABELS = {
    "filename": "Contract",
    "customer_name": "Borrower / customer",
    "lender_name": "Lender",
    "contract_about": "Type",
    "governing_law": "Governing law",
    "currency": "Currency",
    "contract_value": "Amount",
    "start_date": "Start date",
    "end_date": "End date",
    "indemnification_clause_present": "Indemnification clause",
    "ip_shared_with_customer": "IP shared with customer",
    "high_risk_clauses": "High-risk clauses",
    "medium_risk_clauses": "Medium-risk clauses",
    "low_risk_clauses": "Low-risk clauses",
    "total_clauses": "Clauses",
    "policy_risk_score": "Policy risk score",
}

RISK_FIELDS = {"high_risk_clauses", "medium_risk_clauses", "low_risk_clauses", "total_clauses", "policy_risk_score"}
_RISK_LEVEL = {"high_risk_clauses": "high", "medium_risk_clauses": "medium", "low_risk_clauses": "low"}


def _is_analyzed(a: Dict[str, Any]) -> bool:
    return a.get("status") == "analyzed" and bool(a.get("results"))


def _risk_value(a: Dict[str, Any], field: str) -> Optional[float]:
    """Risk figures from the stored analysis; None (unknown) when the
    contract hasn't been risk-analyzed - never 0."""
    if not _is_analyzed(a):
        return None
    results = a.get("results") or []
    if field == "total_clauses":
        return len(results)
    if field == "policy_risk_score":
        score = (a.get("policy_summary") or {}).get("total_policy_score")
        return float(score) if isinstance(score, (int, float)) else None
    level = _RISK_LEVEL[field]
    return sum(1 for r in results if str((r.get("classification") or {}).get("risk_level", "")).lower() == level)

_CURRENCY_SYMBOL = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}


# ------------------------------------------------------------------ routing

ROUTER_SYSTEM = (
    "You translate questions about a set of contracts into a JSON query "
    "spec. Return only the JSON object."
)


def build_router_prompt(question: str, history: List[Dict[str, str]]) -> str:
    convo = ""
    if history:
        lines = [
            f"{turn.get('role', 'user')}: {str(turn.get('content', ''))[:400]}"
            for turn in history[-4:]
        ]
        convo = "Conversation so far (use it to resolve follow-ups such as 'and the lowest?'):\n" + "\n".join(lines) + "\n\n"

    return f"""Decide how to answer the question below.

Each contract has these directory fields:
filename, customer_name (borrower / customer), lender_name, contract_about
(type of contract), governing_law, currency, contract_value (financed amount /
total contract value), start_date, end_date (YYYY-MM-DD),
indemnification_clause_present, ip_shared_with_customer,
and from its risk analysis: high_risk_clauses, medium_risk_clauses,
low_risk_clauses (number of clauses rated at that level), total_clauses,
policy_risk_score.

kind = "structured" ONLY when the answer can be computed from those fields
alone: ranking (highest, lowest, largest, smallest, top N, second/third,
newest, oldest, earliest, latest, riskiest), counting, totals, averages,
grouping (which lender / borrower / type has the most contracts), or
listing / filtering by those fields, or looking up one of those fields for
a named contract.

Use the field the question is about. "Risk" / "risky" / "riskiest" means the
risk fields (sort_by high_risk_clauses unless it names medium, low or the
policy score) - never contract_value. If no field fits the question, use
kind = "semantic".

kind = "semantic" when the answer needs the wording of clauses: what a clause
says, obligations, interest rates, penalties, fees, termination terms, risks,
comparing terms, drafting, or explanations. A structured spec must rank,
count, total, group, filter or pick fields; if it would do none of these,
the question is semantic.

Rules for structured specs:
- "the highest / the lowest / the largest" (singular) -> limit 1.
- plural without a number ("the lowest amounts") -> limit null (list all, sorted).
- "top 3" -> limit 3.
- "second highest" -> offset 1, limit 1; "third lowest" -> offset 2, limit 1.
- "which lender / borrower / type has the most contracts", "contracts per
  lender" -> operation "group" with group_by that field.
- highest / largest / latest / newest -> order "desc"; lowest / smallest /
  earliest / oldest -> order "asc".
- filters use op "contains" for names, "greater_than"/"less_than" for amounts,
  "before"/"after" for dates (value YYYY-MM-DD or YYYY), "is_true"/"is_false"
  for yes/no fields. Copy amounts as written (e.g. "50k", "1.5 million").
- "fields": the directory fields the question asks to see, e.g. "When does
  Contract_3 end?" -> ["end_date"]. Empty when it just asks which contracts.

Rules for every spec (structured and semantic):
- "contracts": every contract the question refers to by file name (Contract_7,
  lease_2024.pdf) or by party name (Julia Miller, Acme Ltd). Empty if none.
- "across_contracts": true when a semantic question needs every contract
  checked ("which contracts ...", "any contract ...", "compare ... across",
  "all contracts ..."); false otherwise.
- "standalone_question": the question rewritten so it makes sense without the
  conversation (resolve "it", "that one", "and for X?", "what about the lowest?").
  Same as the question when it already stands alone.

Examples:
Q: Which contract has the highest financed amount?
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"desc","limit":1,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which contract has the highest financed amount?"}}
Q: which contracts have the least financial amounts
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"asc","limit":null,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which contracts have the lowest financed amounts?"}}
Q: How many contracts are with Financial Bank of America?
A: {{"kind":"structured","operation":"count","sort_by":null,"order":"desc","limit":null,"filters":[{{"field":"lender_name","op":"contains","value":"Financial Bank of America"}}],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"How many contracts are with Financial Bank of America?"}}
Q: What is the total of the 3 largest loans?
A: {{"kind":"structured","operation":"sum","sort_by":"contract_value","order":"desc","limit":3,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"What is the total of the 3 largest loans?"}}
Q: Loans above 50k ending before 2027
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"desc","limit":null,"filters":[{{"field":"contract_value","op":"greater_than","value":"50k"}},{{"field":"end_date","op":"before","value":"2027"}}],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which loans are above 50k and end before 2027?"}}
Q: What's the second highest amount?
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"desc","limit":1,"offset":1,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which contract has the second highest financed amount?"}}
Q: Which contracts have the highest risks?
A: {{"kind":"structured","operation":"list","sort_by":"high_risk_clauses","order":"desc","limit":null,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which contracts have the most high-risk clauses?"}}
Q: Which contract has the most medium risks?
A: {{"kind":"structured","operation":"list","sort_by":"medium_risk_clauses","order":"desc","limit":1,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which contract has the most medium-risk clauses?"}}
Q: Who is the top lender for most contracts?
A: {{"kind":"structured","operation":"group","group_by":"lender_name","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"Which lender has the most contracts?"}}
Q: When does Contract_3 end?
A: {{"kind":"structured","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":["end_date"],"contracts":["Contract_3"],"across_contracts":false,"standalone_question":"When does Contract_3 end?"}}
Q: Who is the lender for Julia Miller?
A: {{"kind":"structured","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":["lender_name"],"contracts":["Julia Miller"],"across_contracts":false,"standalone_question":"Who is the lender in Julia Miller's contract?"}}
Q: anything mentioned about termination
A: {{"kind":"semantic","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":[],"contracts":[],"across_contracts":true,"standalone_question":"What do the contracts say about termination?"}}
Q: What is the interest rate in Contract_5?
A: {{"kind":"semantic","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":[],"contracts":["Contract_5"],"across_contracts":false,"standalone_question":"What is the interest rate in Contract_5?"}}
Q: Which contracts charge more than 1.4% monthly interest?
A: {{"kind":"semantic","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":[],"contracts":[],"across_contracts":true,"standalone_question":"Which contracts charge more than 1.4% monthly interest?"}}
Conversation: user asked "Which contract has the highest amount?"
Q: list the other ones too
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"desc","limit":null,"offset":1,"filters":[],"fields":[],"contracts":[],"across_contracts":false,"standalone_question":"List the other contracts by financed amount, highest first."}}
Conversation: user asked "What is the interest rate in Julia Miller's contract?"
Q: and for Peter Chen?
A: {{"kind":"semantic","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[],"fields":[],"contracts":["Peter Chen"],"across_contracts":false,"standalone_question":"What is the interest rate in Peter Chen's contract?"}}

{convo}Question: {question}
"""


# Topics that live in clause wording, not in the directory fields.
# (Indemnification and governing law are directory fields, so they're
# not here.)
_CLAUSE_TOPIC = re.compile(
    r"\b(terminat\w*|cancel\w*|default\w*|breach\w*|penalt\w*|fines?|fees?|charges?|late|interest|"
    r"install?ments?|repay\w*|prepay\w*|insur\w*|guarant\w*|collateral|lien|"
    r"jurisdiction|courts?|arbitrat\w*|disputes?|notices?|confidential\w*|warrant\w*|obligations?|"
    r"covenants?|assign\w*|force majeure|grace period|mention\w*|say|says)\b",
    re.I,
)
_LIST_ALL = re.compile(
    r"^\s*(?:please\s+)?(?:list|show|display|give me|what are|which are)\b[^?]*\b(?:contracts|loans|agreements|documents)\b",
    re.I,
)


_FOLLOW_UP = re.compile(
    r"\b(others?|other ones|the rest|rest of them|remaining|all of them|all the others|full list|whole list|"
    r"everything|every one|the whole|more|too|also|as well)\b",
    re.I,
)
_REST = re.compile(r"\b(others?|other ones|the rest|rest of them|remaining|all the others)\b", re.I)


def _selects_nothing(spec: ChatQuerySpec) -> bool:
    return (
        spec.operation == "list" and not spec.sort_by and not spec.group_by
        and not spec.filters and not spec.fields and not spec.contracts
    )


def follow_up_spec(
    question: str,
    spec: Optional[ChatQuerySpec],
    previous: Optional[Dict[str, Any]],
    previous_ids: Optional[List[str]] = None,
) -> Tuple[Optional[ChatQuerySpec], set]:
    """
    "list the other ones too" right after an exact answer: the previous
    answer's own query, widened to the whole list, and - for "other",
    "rest", "remaining" - without the contracts that answer already showed
    (ties included, so none is shown twice). Returns (spec, ids to leave
    out). Done in code because the router, which only sees the
    conversation as text, turned it into a query that selected nothing.
    """
    unchanged = (spec, set())
    if not previous or not _FOLLOW_UP.search(question or "") or len((question or "").split()) > 14:
        return unchanged
    if _CLAUSE_TOPIC.search(question or ""):
        return unchanged
    if spec is not None and (
        (spec.kind == "structured" and not _selects_nothing(spec))
        or (spec.kind == "semantic" and spec.contracts)
    ):
        return unchanged  # the router understood it, or it's about a named contract
    try:
        prev = ChatQuerySpec.model_validate(previous)
    except Exception:
        return unchanged
    if prev.kind != "structured":
        return unchanged
    rest = bool(_REST.search(question))
    exclude = {str(i) for i in (previous_ids or []) if i} if rest else set()
    offset = 0
    if rest and not exclude and prev.limit:
        offset = (prev.offset or 0) + prev.limit  # ids unknown: skip what was shown
    widened = prev.model_copy(update={
        "operation": prev.operation if prev.operation == "group" else "list",
        "limit": None,
        "offset": offset,
        "standalone_question": (prev.standalone_question or "") + (" (the rest)" if rest else " (all of them)"),
    })
    return widened, exclude


def check_spec(spec: Optional[ChatQuerySpec], question: str) -> Optional[ChatQuerySpec]:
    """
    Catch structured specs that can't answer the question. The router
    sometimes turns "anything mentioned about termination?" into a list
    with no sort, filter or field, which printed every contract (linked to
    its header) instead of the termination clauses. Clause topics without
    a ranking or grouping, and "list" specs that select nothing, go to the
    clause-text path instead, checked across all contracts.
    """
    if spec is None or spec.kind != "structured":
        return spec
    selects_nothing = _selects_nothing(spec)
    topic = _CLAUSE_TOPIC.search(question or "")
    about_clauses = bool(topic) and not spec.sort_by and not spec.group_by and spec.operation in ("list", "count")
    if (selects_nothing and not (_LIST_ALL.search(question or "") and not topic)) or about_clauses:
        return ChatQuerySpec(
            kind="semantic",
            contracts=spec.contracts,
            across_contracts=not spec.contracts,
            standalone_question=spec.standalone_question,
        )
    return spec


def route_question(llm_client: Any, question: str, history: List[Dict[str, str]]) -> Optional[ChatQuerySpec]:
    """The spec, or None if routing failed (caller then falls back to
    heuristic_spec, then to the semantic path)."""
    try:
        return llm_client.structured_call(
            ChatQuerySpec,
            build_router_prompt(question, history),
            ROUTER_SYSTEM,
            task="quality",
        )
    except Exception as error:
        print(f"[chat] question routing failed: {error}")
        return None


# Words that mean the question is about something other than the
# financed amount (a clause, a rate, a duration, a count of something else).
_NOT_ABOUT_AMOUNT = re.compile(
    r"\b(interest|rate|ratio|ltv|loan-to-value|penalt\w*|fee\w*|fine|clause\w*|terminat\w*|"
    r"insur\w*|guarantee\w*|default|obligation\w*|risk\w*|terms?|condition\w*|warrant\w*|"
    r"indemn\w*|confidential\w*|jurisdiction|law|tenure|duration|period|months?|years?|days?|"
    r"install?ments?|payments?|mention\w*|contain\w*|say|says|include\w*)\b",
    re.I,
)
_AMOUNT_WORDS = re.compile(r"\b(amounts?|value|valuable|financed|principal|money|worth|loans?|contracts?)\b", re.I)
_PLAIN_COUNT = re.compile(
    r"^\s*(?:how many|what is the number of|number of|count(?: of)?)\s+(?:contracts|loans|agreements|documents)"
    r"(?:\s+(?:are there|do (?:we|i) have|in total|have been uploaded|are uploaded|are stored|in the system))?\s*\??\s*$",
    re.I,
)


def heuristic_spec(question: str) -> Optional[ChatQuerySpec]:
    """
    A conservative stand-in when the router can't be reached: the plain
    amount questions ("which contract has the highest amount?", "total
    financed", "how many contracts are there?") are still answered
    exactly instead of being handed to the language model. Anything with
    another condition ("... mention prepayment", "highest interest rate",
    "total tenure") returns None and goes to the semantic path.
    """
    q = question.strip()
    if _PLAIN_COUNT.match(q):
        return ChatQuerySpec(kind="structured", operation="count")
    ql0 = q.lower()
    ordinal = re.search(r"\b(second|2nd|third|3rd|fourth|4th|fifth|5th)\b", ql0)
    offset = {"second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4}[
        ordinal.group(1)] if ordinal else 0
    if re.search(r"\b(riskiest|most risky|highest risks?|most (?:high[- ])?risks?|high[- ]risk)\b", ql0) \
            and re.search(r"\bcontracts?\b", ql0) and not re.search(r"\b(clause|say|mention)", ql0):
        plural = bool(re.search(r"\bcontracts\b", ql0))
        return ChatQuerySpec(kind="structured", sort_by="high_risk_clauses", order="desc",
                             limit=None if plural and not offset else 1, offset=offset)
    if _NOT_ABOUT_AMOUNT.search(q) or not _AMOUNT_WORDS.search(q):
        return None
    ql = q.lower()
    if re.search(r"\b(?:number|count) of (?:contracts|loans|agreements)\b", ql):
        return ChatQuerySpec(kind="structured", operation="count")
    if re.search(r"\b(total|sum|combined|altogether)\b", ql):
        return ChatQuerySpec(kind="structured", operation="sum")
    if re.search(r"\b(average|mean)\b", ql):
        return ChatQuerySpec(kind="structured", operation="average")
    plural = bool(re.search(r"\bcontracts\b|\bloans\b|\bamounts\b", ql))
    top = re.search(r"\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:largest|biggest|highest|smallest|lowest)\b", ql)
    limit = int(top.group(1) or top.group(2)) if top else (None if plural else 1)
    if offset:
        limit = 1
    if re.search(r"\b(highest|largest|biggest|maximum|max|most valuable)\b|\bworth the most\b|\bmost (?:money|expensive)\b", ql):
        return ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", limit=limit, offset=offset)
    if re.search(r"\b(lowest|smallest|minimum|min)\b|(?<!\bat )\bleast\b", ql):
        return ChatQuerySpec(kind="structured", sort_by="contract_value", order="asc", limit=limit, offset=offset)
    if top:
        # "Top 5 contracts by value"
        return ChatQuerySpec(kind="structured", sort_by="contract_value", order="desc", limit=limit)
    return None


_ACROSS_HINT = re.compile(
    r"\b(which|what|any|all|every|each|how many)\b[^?]*\bcontracts\b|\bany contract\b|\bevery contract\b|"
    r"\beach contract\b|\bacross\b|\bcompare\b",
    re.I,
)


def looks_across_contracts(question: str) -> bool:
    return bool(_ACROSS_HINT.search(question or ""))


# ------------------------------------------------------------ named contracts

def _stem(filename: str) -> str:
    return re.sub(r"\.[a-z0-9]{2,4}$", "", str(filename or ""), flags=re.I)


def _contains_name(text_norm: str, name_norm: str) -> bool:
    """Whole-word match; "contract 3" doesn't match "contract 31"."""
    if len(name_norm) < 3:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(name_norm) + r"(?![a-z0-9])", text_norm))


def _named_in_passing(question: str, token: str) -> bool:
    """
    A single first or last name ("Julia", "Omar") counts as naming a
    contract only when it's written like a name: possessive ("Julia's"),
    or capitalised somewhere other than the start of a sentence. Lower
    case ("grace period", "solar equipment", "total amount") never counts,
    and neither does a capital that's only there because a sentence
    starts with the word ("Total amount financed?").
    """
    word = re.escape(token)
    if re.search(r"(?<![A-Za-z])" + word + r"(?:'s|’s)\b", question, re.IGNORECASE):
        return True
    for m in re.finditer(r"(?<![A-Za-z])" + word + r"(?![A-Za-z])", question, re.IGNORECASE):
        found = question[m.start():m.end()]
        if not found[:1].isupper():
            continue
        before = question[:m.start()].rstrip()
        if before and before[-1] not in ".?!:":
            return True
    return False


def _multi_word_file_named(stem: str, question: str) -> bool:
    """
    "Loan Agreement.pdf" / "ACME_LOAN.pdf" is named when the question
    writes it joined the same way ("acme_loan") or as a name, with a
    capital ("the Loan Agreement", "Acme Loan") - but not in ordinary
    lower-case prose ("does any loan agreement ...").
    """
    joined = re.search(r"[_-]", stem)
    if joined and re.search(r"(?<![A-Za-z0-9])" + re.escape(stem) + r"(?![A-Za-z0-9])", question, re.IGNORECASE):
        return True
    spaced = re.sub(r"[_-]+", " ", stem).strip()
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(spaced).replace(r"\ ", r"[\s_-]+") + r"(?![A-Za-z0-9])",
                         question, re.IGNORECASE):
        if re.search(r"[A-Z]", m.group(0)):
            return True
    return False


def resolve_named_contracts(
    question: str, spec: Optional[ChatQuerySpec], analyses: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Contracts the question is about, and whether that rests only on a
    loose match. Found two ways so neither alone has to be perfect:
    - strong: names the router listed (spec.contracts, filename filters);
      a borrower's full name or a distinctive file name ("Contract_7",
      "Lease 2024") written in the question;
    - loose: one first/last name that belongs to a single borrower,
      written like a name (see _named_in_passing).
    Returns (contracts, loose_only). Callers don't let a loose match
    narrow a ranking or total.
    """
    text_norm = _norm(question)
    wanted = [_norm(n) for n in (spec.contracts if spec else [])]
    if spec:
        wanted += [_norm(f.value) for f in spec.filters if f.field == "filename" and f.value]
    wanted = [w for w in wanted if w]

    # First/last-name tokens that identify exactly one contract.
    token_owner: Dict[str, Optional[str]] = {}
    for a in analyses:
        for token in set(_norm((a.get("contract_metadata") or {}).get("customer_name")).split()):
            if len(token) >= 4:
                token_owner[token] = None if token in token_owner else a.get("analysis_id")

    strong: List[Dict[str, Any]] = []
    loose: List[Dict[str, Any]] = []
    for a in analyses:
        stem = _stem(a.get("filename"))
        file_norm = _norm(stem)
        full_file = _norm(a.get("filename"))
        customer = _norm((a.get("contract_metadata") or {}).get("customer_name"))

        hit = any(
            _contains_name(file_norm, w) or _contains_name(w, file_norm) or w == full_file
            or (customer and (_contains_name(customer, w) or _contains_name(w, customer)))
            for w in wanted
        )
        if not hit:
            filename = str(a.get("filename") or "")
            if filename and filename.lower() in question.lower():
                # The full file name, extension included, in any case.
                hit = True
            elif re.search(r"\d", file_norm):
                # "Contract_7", "lease 2024": distinctive in any case.
                hit = _contains_name(text_norm, file_norm)
            elif len(file_norm.split()) >= 2:
                hit = _multi_word_file_named(stem, question)
        if not hit and customer and len(customer.split()) >= 2 and _contains_name(text_norm, customer):
            hit = True
        if hit:
            strong.append(a)
            continue
        if customer and any(
            token_owner.get(t) == a.get("analysis_id") and _named_in_passing(question, t)
            for t in customer.split()
        ):
            loose.append(a)

    if strong:
        return strong + [a for a in loose if a not in strong], False
    return loose, bool(loose)


def is_aggregate(spec: ChatQuerySpec) -> bool:
    """Rankings, counts, totals and field filters are about the whole
    set of contracts, never about whichever one happens to be open."""
    return bool(
        spec.sort_by
        or spec.operation != "list"
        or any(f.field != "filename" for f in spec.filters)
    )


def structured_scope(
    spec: ChatQuerySpec,
    all_analyses: List[Dict[str, Any]],
    named: List[Dict[str, Any]],
    selected: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Which contracts a structured question runs over, and a short note
    saying so when it isn't obvious:
    - contracts the question names -> those;
    - rankings / counts / totals / filters -> all contracts, even if one
      is open in the viewer ("which has the highest amount?" means of all);
    - a plain lookup ("who is the lender?") with a contract open -> that one;
    - otherwise all contracts.
    """
    if named:
        return named, ""
    if is_aggregate(spec) or selected is None:
        note = "Across all contracts (not only the one that's open)." if selected is not None else ""
        return all_analyses, note
    return [selected], ""


# ------------------------------------------------------------------ execution

def _field(a: Dict[str, Any], field: str) -> Any:
    if field == "filename":
        return a.get("filename")
    if field in RISK_FIELDS:
        return _risk_value(a, field)
    value = (a.get("contract_metadata") or {}).get(field)
    if field == "contract_value":
        return parse_money(value)
    if field in ("start_date", "end_date"):
        return value if isinstance(value, str) and _DATE_RE.match(value) else None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _norm(text: Any) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _date_bound(value: str, op: str) -> Optional[str]:
    value = (value or "").strip()
    if _DATE_RE.match(value):
        return value
    if re.fullmatch(r"\d{4}", value):
        return f"{value}-01-01" if op == "before" else f"{value}-12-31"
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return f"{value}-01" if op == "before" else f"{value}-31"
    return None


def _matches(a: Dict[str, Any], f: QueryFilter) -> Optional[bool]:
    """True/False, or None when this contract has no value for the field."""
    value = _field(a, f.field)
    if f.op in ("is_true", "is_false"):
        if value is None:
            return None
        return bool(value) is (f.op == "is_true")
    if value is None:
        return None
    if f.op in ("contains", "equals"):
        want, have = _norm(f.value), _norm(value)
        if f.field == "filename":
            # "Contract_3" must not match "Contract_31"
            return bool(re.search(r"(?<![a-z0-9])" + re.escape(want) + r"(?![0-9])", have))
        return want in have if f.op == "contains" else want == have
    if f.op in ("greater_than", "less_than"):
        limit = parse_money(f.value)
        number = value if isinstance(value, (int, float)) else parse_money(value)
        if limit is None or number is None:
            return None
        return number > limit if f.op == "greater_than" else number < limit
    if f.op in ("before", "after"):
        bound = _date_bound(f.value or "", f.op)
        if bound is None or not isinstance(value, str):
            return None
        return value < bound if f.op == "before" else value > bound
    return None


def format_money(value: Optional[float], currency: Optional[str]) -> str:
    if value is None:
        return "not found"
    code = (currency or "").upper()
    symbol = _CURRENCY_SYMBOL.get(code)
    if symbol:
        return f"{symbol}{value:,.2f}"
    return f"{value:,.2f} {code}".strip()


def _display(a: Dict[str, Any], field: str) -> str:
    if field == "contract_value":
        return format_money(_field(a, "contract_value"), _field(a, "currency"))
    value = _field(a, field)
    if value is None:
        return "not analyzed" if field in RISK_FIELDS else "not found"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _name(a: Dict[str, Any]) -> str:
    return a.get("filename") or f"Contract {a.get('analysis_id')}"


def _names(items: List[Dict[str, Any]]) -> str:
    return ", ".join(_name(a) for a in items)


_ADDRESS = re.compile(
    r"(?:residing at|resident at|domiciled at|with (?:its|their) (?:principal |registered |head )?office at|"
    r"headquartered at|located at)\s+(.+?)(?=,\s*(?:holder|registered|represented|a |an |bearing|CPF|SSN|PAN|EIN)|\.\s|\.$|$)",
    re.I,
)


_GENERIC_NAME_WORDS = {
    "inc", "llc", "ltd", "limited", "the", "and", "bank", "credit", "union", "group", "holdings", "company",
    "corporation", "corp", "capital", "finance", "financial", "trust", "national", "lending", "business",
    "consumer", "housing", "america", "services", "partners", "of", "n.a", "p.c", "aca",
}


def _name_words(name: Optional[str]) -> List[str]:
    return [w for w in _norm(name or "").split() if len(w) > 2 and w not in _GENERIC_NAME_WORDS]


def _mentions(question: str, name: Optional[str]) -> bool:
    """The question names this party: its full name, or a distinctive
    word of it ("Rachel Park", "Park", "Bluewater")."""
    words = _name_words(name)
    q = set(_norm(question).split())
    return bool(words) and any(w in q for w in words)


def lender_names_as_filters(spec: ChatQuerySpec, analyses: List[Dict[str, Any]], named: List[Dict[str, Any]]) -> ChatQuerySpec:
    """ "tell me about Harborline Credit Union": the router lists the lender
    as a contract name, which matches no contract, so every contract was
    listed. A name that is a lender becomes a lender filter instead."""
    if spec.kind != "structured" or not spec.contracts or named:
        return spec
    lenders = {str(_field(a, "lender_name") or "") for a in analyses}
    filters, left = list(spec.filters), []
    for name in spec.contracts:
        if any(_mentions(name, lender) for lender in lenders if lender):
            filters.append(QueryFilter(field="lender_name", op="contains", value=name))
        else:
            left.append(name)
    if len(left) == len(spec.contracts):
        return spec
    return spec.model_copy(update={"filters": filters, "contracts": left})


def _party_address(record: Dict[str, Any], role: str) -> Optional[str]:
    """The party's address as the contract header gives it, e.g.
    "BORROWER: Rachel Park, residing at 6480 Tara Hill Drive, ..."."""
    header = ((record.get("header") or {}).get("text") or "")
    label = "BORROWER|CUSTOMER|CLIENT|DEBTOR" if role == "borrower" else "LENDER|BANK|CREDITOR"
    m = re.search(r"\b(?:" + label + r")\s*:(.{0,400})", header, re.I | re.S)
    if not m:
        return None
    segment = re.split(r"\b(?:BORROWER|LENDER|FINANCED AMOUNT|AMOUNT|CLAUSE)\s*:", m.group(1))[0]
    a = _ADDRESS.search(" ".join(segment.split()))
    return a.group(1).strip(" ,.") if a else None


def describe_named(question: str, rows: List[Dict[str, Any]]) -> Optional[str]:
    """
    One or two plain sentences about the party or contract a lookup
    question names ("who is Rachel Park?"), built from the stored fields
    and the contract header - no model call, so no extra wait.
    """
    if not rows:
        return None
    sentences: List[str] = []

    def contract_bits(a: Dict[str, Any]) -> str:
        kind = _field(a, "contract_about")
        start = _field(a, "start_date")
        end = _field(a, "end_date")
        value = _field(a, "contract_value")
        text = f"**{_name(a)}**"
        if kind:
            text += f" (a {str(kind).strip().rstrip('.').lower()})"
        if value is not None:
            text += f" for **{format_money(value, _field(a, 'currency'))}**"
        if start and end:
            text += f", running {start} to {end}"
        elif end:
            text += f", ending {end}"
        return text

    def risk(a: Dict[str, Any]) -> str:
        if not _is_analyzed(a):
            return " It hasn't been risk-analyzed yet."
        h, m, l = (_risk_value(a, f) for f in ("high_risk_clauses", "medium_risk_clauses", "low_risk_clauses"))
        return f" Risk analysis: {int(h or 0)} high, {int(m or 0)} medium and {int(l or 0)} low-risk clauses."

    borrower_of = [a for a in rows if _mentions(question, _field(a, "customer_name"))]
    lender_of = [a for a in rows if _mentions(question, _field(a, "lender_name")) and a not in borrower_of]

    if borrower_of:
        a = borrower_of[0]
        who = _field(a, "customer_name")
        address = _party_address(a, "borrower")
        lender = _field(a, "lender_name")
        if len(borrower_of) == 1:
            s = f"**{who}** is the borrower in {contract_bits(a)}"
            s += f", with **{lender}** as lender." if lender else "."
            if address:
                s += f" The contract gives the borrower's address as {address}."
            sentences.append(s + risk(a))
        else:
            sentences.append(f"**{who}** is the borrower in {len(borrower_of)} contracts: "
                             + "; ".join(contract_bits(x) for x in borrower_of) + ".")
    if lender_of:
        lender = _field(lender_of[0], "lender_name")
        if len(lender_of) == 1:
            a = lender_of[0]
            borrower = _field(a, "customer_name")
            sentences.append(f"**{lender}** is the lender in {contract_bits(a)}"
                             + (f", lending to **{borrower}**." if borrower else "."))
        else:
            names = [f"**{_field(a, 'customer_name') or _name(a)}**" for a in lender_of]
            listed = ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else names[0]
            sentences.append(f"**{lender}** is the lender in {len(lender_of)} contracts, lending to {listed}.")
    if not sentences and len(rows) == 1:
        a = rows[0]
        who, lender = _field(a, "customer_name"), _field(a, "lender_name")
        s = contract_bits(a)
        if who or lender:
            s += f": borrower **{who or 'not found'}**, lender **{lender or 'not found'}**."
        sentences.append(s + risk(a))
    return " ".join(sentences) or None


def execute_spec(spec: ChatQuerySpec, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run a structured spec over the contract records.

    Returns {"answer": markdown, "rows": [records in answer order],
    "excluded": {...}} - rows are what the answer's references point to.
    """
    notes: List[str] = []
    selected = list(analyses)

    # Filters: a contract with no value for a filtered field can't be
    # checked, so it's reported by name rather than silently treated
    # as a non-match.
    for f in spec.filters:
        kept, unknown = [], []
        for a in selected:
            result = _matches(a, f)
            if result is None:
                unknown.append(a)
            elif result:
                kept.append(a)
        if unknown and f.field != "filename":
            notes.append(
                f"Could not check {FIELD_LABELS.get(f.field, f.field).lower()} for: {_names(unknown)} "
                "(not found in those documents)."
            )
        selected = kept

    value_involved = spec.sort_by == "contract_value" or spec.operation in ("sum", "average") or any(
        f.field == "contract_value" for f in spec.filters
    )

    if not selected:
        answer = "No contracts match that."
        if notes:
            answer += "\n\n" + "\n".join(f"- {n}" for n in notes)
        return {"answer": answer, "rows": [], "notes": notes}

    # Group ("which lender has the most contracts") ----------------------
    if spec.operation == "group" or spec.group_by:
        return _grouped(spec, selected, notes)

    # Aggregates --------------------------------------------------------
    if spec.operation in ("sum", "average"):
        have = [a for a in selected if _field(a, "contract_value") is not None]
        missing = [a for a in selected if _field(a, "contract_value") is None]
        by_currency: Dict[str, List[Dict[str, Any]]] = {}
        for a in have:
            by_currency.setdefault((_field(a, "currency") or "unknown currency").upper(), []).append(a)
        # "total of the 3 largest loans": rank, cut, then add up.
        if spec.limit:
            key_field = spec.sort_by or "contract_value"
            reverse = spec.order == "desc"
            for code in by_currency:
                ranked = [a for a in by_currency[code] if _field(a, key_field) is not None]
                ranked.sort(key=lambda a: _field(a, key_field), reverse=reverse)
                by_currency[code] = ranked[:spec.limit]
            by_currency = {code: items for code, items in by_currency.items() if items}
            have = [a for items in by_currency.values() for a in items]
        lines = []
        for code, items in sorted(by_currency.items()):
            values = [_field(a, "contract_value") for a in items]
            total = sum(values)
            if spec.operation == "sum":
                lines.append(f"- **{format_money(total, code)}** across {len(items)} contract(s)")
            else:
                lines.append(
                    f"- **{format_money(total / len(items), code)}** average across {len(items)} contract(s)"
                )
        title = "Total amount" if spec.operation == "sum" else "Average amount"
        if spec.limit:
            key_field = spec.sort_by or "contract_value"
            which = {
                ("contract_value", "desc"): "largest", ("contract_value", "asc"): "smallest",
                ("end_date", "desc"): "latest-ending", ("end_date", "asc"): "earliest-ending",
                ("start_date", "desc"): "most recent", ("start_date", "asc"): "oldest",
            }.get((key_field, spec.order), "selected")
            title += f" of the {spec.limit} {which} contract{'s' if spec.limit != 1 else ''}"
        answer = f"**{title}**" + (" (per currency; different currencies are not added together)" if len(by_currency) > 1 else "") + ":\n" + "\n".join(lines)
        if missing:
            notes.append(f"No amount found in: {_names(missing)} (not included).")
        rows = sorted(have, key=lambda a: _field(a, "contract_value"), reverse=True)
        answer += "\n\n" + _table(rows, ["contract_value"])
        if notes:
            answer += "\n\n" + "\n".join(f"- {n}" for n in notes)
        return {"answer": answer, "rows": rows, "notes": notes}

    # Sorting -------------------------------------------------------------
    groups: List[Tuple[Optional[str], List[Dict[str, Any]]]] = [(None, selected)]
    if spec.sort_by:
        have = [a for a in selected if _field(a, spec.sort_by) is not None]
        missing = [a for a in selected if _field(a, spec.sort_by) is None]
        if missing:
            if spec.sort_by in RISK_FIELDS:
                notes.append(f"Not risk-analyzed yet, so left out: {_names(missing)}.")
            else:
                notes.append(
                    f"No {FIELD_LABELS[spec.sort_by].lower()} found in: {_names(missing)} (left out of the ranking)."
                )
        reverse = spec.order == "desc"
        if spec.sort_by == "contract_value":
            # Never rank a USD amount against an INR amount by number.
            by_currency: Dict[str, List[Dict[str, Any]]] = {}
            for a in have:
                by_currency.setdefault((_field(a, "currency") or "unknown currency").upper(), []).append(a)
            if len(by_currency) > 1:
                notes.append("Amounts are ranked separately per currency; different currencies aren't compared.")
            groups = [
                (code, sorted(items, key=lambda a: _field(a, "contract_value"), reverse=reverse))
                for code, items in sorted(by_currency.items())
            ]
        elif spec.sort_by in RISK_FIELDS:
            # Ties broken by the next most severe level, then the policy
            # score: of two contracts with 2 high-risk clauses, the one
            # with more medium-risk clauses ranks as riskier.
            tie = {
                "high_risk_clauses": ["high_risk_clauses", "medium_risk_clauses", "policy_risk_score"],
                "medium_risk_clauses": ["medium_risk_clauses", "high_risk_clauses"],
                "low_risk_clauses": ["low_risk_clauses"],
                "total_clauses": ["total_clauses"],
                "policy_risk_score": ["policy_risk_score", "high_risk_clauses"],
            }[spec.sort_by]
            groups = [(None, sorted(have, key=lambda a: tuple(_field(a, f) or 0 for f in tie), reverse=reverse))]
        else:
            groups = [(None, sorted(have, key=lambda a: str(_field(a, spec.sort_by)).lower(), reverse=reverse))]

    # Offset ("second highest") ---------------------------------------------
    if spec.offset and spec.sort_by:
        place = _ordinal(spec.offset + 1)
        too_few = [(code, len(items)) for code, items in groups if len(items) <= spec.offset]
        groups = [(code, items[spec.offset:]) for code, items in groups]
        groups = [(code, items) for code, items in groups if items]
        if not groups:
            total = sum(n for _, n in too_few)
            if not spec.limit:
                return {"answer": "There are no other contracts with this information.", "rows": [], "notes": notes}
            return {
                "answer": f"There {'is' if total == 1 else 'are'} only {total} contract{'s' if total != 1 else ''} "
                          f"with this information, so there is no {place} one.",
                "rows": [], "notes": notes,
            }
        for code, n in too_few:
            if code and spec.limit:
                notes.append(f"Only {n} {code} contract{'s' if n != 1 else ''}, so no {place} one in {code}.")
            elif code:
                notes.append(f"No other {code} contracts.")

    # Limit, keeping ties at the cut-off ------------------------------------
    if spec.limit:
        limited = []
        for code, items in groups:
            if len(items) > spec.limit and spec.sort_by:
                edge = _field(items[spec.limit - 1], spec.sort_by)
                cut = spec.limit
                while cut < len(items) and _field(items[cut], spec.sort_by) == edge:
                    cut += 1
                items = items[:cut]
            elif len(items) > spec.limit:
                items = items[:spec.limit]
            limited.append((code, items))
        groups = limited

    rows = [a for _, items in groups for a in items]
    if not rows:
        answer = "None of the matching contracts have that information recorded."
        if notes:
            answer += "\n\n" + "\n".join(f"- {n}" for n in notes)
        return {"answer": answer, "rows": [], "notes": notes}

    columns: List[str] = [f for f in spec.fields if f != "filename"]
    if (value_involved or spec.sort_by == "contract_value") and "contract_value" not in columns:
        columns.append("contract_value")
    for f in spec.filters:
        if f.field not in columns and f.field not in ("filename", "contract_value"):
            columns.append(f.field)
    if spec.sort_by and spec.sort_by not in columns:
        columns.append(spec.sort_by)
    if spec.sort_by in RISK_FIELDS:
        for extra in ("high_risk_clauses", "medium_risk_clauses", "low_risk_clauses"):
            if extra not in columns:
                columns.append(extra)
    if not columns:
        # Lookup of a named contract, or a plain filter: show the parties
        # and the amount.
        columns = ["customer_name", "lender_name", "contract_value"]

    # Lead sentence -----------------------------------------------------
    if spec.operation == "count":
        lead = f"**{len(rows)}** contract{'s' if len(rows) != 1 else ''} match."
    elif spec.limit == 1 and spec.sort_by and len(groups) == 1 and len(rows) == 1:
        a = rows[0]
        word = {
            ("contract_value", "desc"): "highest amount",
            ("contract_value", "asc"): "lowest amount",
            ("end_date", "asc"): "earliest end date",
            ("end_date", "desc"): "latest end date",
            ("start_date", "asc"): "earliest start date",
            ("start_date", "desc"): "latest start date",
            ("high_risk_clauses", "desc"): "most high-risk clauses",
            ("high_risk_clauses", "asc"): "fewest high-risk clauses",
            ("medium_risk_clauses", "desc"): "most medium-risk clauses",
            ("medium_risk_clauses", "asc"): "fewest medium-risk clauses",
            ("low_risk_clauses", "desc"): "most low-risk clauses",
            ("low_risk_clauses", "asc"): "fewest low-risk clauses",
            ("policy_risk_score", "desc"): "highest policy risk score",
            ("policy_risk_score", "asc"): "lowest policy risk score",
            ("total_clauses", "desc"): "most clauses",
            ("total_clauses", "asc"): "fewest clauses",
        }.get((spec.sort_by, spec.order), f"{spec.order} {FIELD_LABELS.get(spec.sort_by, spec.sort_by)}")
        if spec.offset:
            word = _ordinal(spec.offset + 1) + " " + word  # "second highest amount"
        lead = f"**{_name(a)}** has the {word}: **{_display(a, spec.sort_by)}**."
    elif spec.limit == 1 and spec.sort_by and len(rows) > 1 and len(groups) == 1:
        lead = f"{len(rows)} contracts are tied:"
    elif spec.limit == 1 and spec.sort_by == "contract_value" and len(groups) > 1:
        which = "highest" if spec.order == "desc" else "lowest"
        if spec.offset:
            which = f"{_ordinal(spec.offset + 1)} {which}"
        lead = f"{which[0].upper() + which[1:]} amount in each currency:"
    elif spec.sort_by:
        direction = "highest first" if spec.order == "desc" else "lowest first"
        if spec.sort_by in ("start_date", "end_date"):
            direction = "latest first" if spec.order == "desc" else "earliest first"
        if spec.offset and not spec.limit:
            per = " in each currency" if spec.sort_by == "contract_value" and len(groups) > 1 else ""
            lead = (f"The other contracts{per}, after the first {spec.offset}, by "
                    f"{FIELD_LABELS[spec.sort_by].lower()}, {direction}:")
        else:
            lead = f"Sorted by {FIELD_LABELS[spec.sort_by].lower()}, {direction}:"
    else:
        lead = f"{len(rows)} matching contract{'s' if len(rows) != 1 else ''}:"

    parts = [lead]
    for code, items in groups:
        if not items:
            continue
        if code and len(groups) > 1:
            parts.append(f"\n**{code}**")
        parts.append(_table(items, columns, start=rows.index(items[0]) + 1))
    if notes:
        parts.append("\n".join(f"- {n}" for n in notes))
    return {"answer": "\n\n".join(parts), "rows": rows, "notes": notes}


def _grouped(spec: ChatQuerySpec, selected: List[Dict[str, Any]], notes: List[str]) -> Dict[str, Any]:
    """Contracts counted (and amounts totalled, per currency) for each
    value of spec.group_by, most contracts first."""
    field = spec.group_by or "lender_name"
    label = FIELD_LABELS.get(field, field)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    shown: Dict[str, str] = {}
    unknown: List[Dict[str, Any]] = []
    for a in selected:
        value = _field(a, field)
        if value is None or not str(value).strip():
            unknown.append(a)
            continue
        key = _norm(value)
        groups.setdefault(key, []).append(a)
        shown.setdefault(key, str(value))
    if not groups:
        return {"answer": f"No {label.lower()} is recorded for these contracts.", "rows": [], "notes": notes}

    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), shown[kv[0]].lower()))
    if spec.order == "asc":
        ordered = sorted(groups.items(), key=lambda kv: (len(kv[1]), shown[kv[0]].lower()))
    if spec.limit:
        edge = len(ordered[min(spec.limit, len(ordered)) - 1][1])
        ordered = [kv for i, kv in enumerate(ordered) if i < spec.limit or len(kv[1]) == edge]

    def totals(items: List[Dict[str, Any]]) -> str:
        by_cur: Dict[str, float] = {}
        for a in items:
            v = _field(a, "contract_value")
            if v is not None:
                code = (_field(a, "currency") or "").upper()
                by_cur[code] = by_cur.get(code, 0.0) + v
        return ", ".join(format_money(v, c) for c, v in sorted(by_cur.items())) or "not found"

    top_key, top_items = ordered[0]
    tied = [kv for kv in ordered if len(kv[1]) == len(top_items)]
    most = "most" if spec.order != "asc" else "fewest"
    if len(tied) == 1:
        lead = (f"**{shown[top_key]}** is the {label.lower()} with the {most} contracts: "
                f"**{len(top_items)}** of {len(selected)}.")
    else:
        lead = (f"{len(tied)} {label.lower()}s are tied with {len(top_items)} contract"
                f"{'s' if len(top_items) != 1 else ''} each: " + ", ".join(f"**{shown[k]}**" for k, _ in tied) + ".")
    # References: the contracts in the top group(s), each at its header,
    # linked from their names in the table.
    rows = [a for _, items in tied for a in items]
    number = {id(a): n for n, a in enumerate(rows, start=1)}

    def cite(a: Dict[str, Any]) -> str:
        name = _name(a).replace("|", "/")
        n = number.get(id(a))
        return f"{name} [{n}](#source-{n})" if n else name

    lines = [f"| # | {label} | Contracts | Total amount | Which |", "|---|---|---|---|---|"]
    for i, (key, items) in enumerate(ordered, start=1):
        names = ", ".join(cite(a) for a in items[:6]) + (" …" if len(items) > 6 else "")
        lines.append(f"| {i} | {shown[key].replace('|', '/')} | {len(items)} | {totals(items)} | {names} |")
    if unknown:
        notes.append(f"No {label.lower()} recorded for: {_names(unknown)}.")
    parts = [lead, "\n".join(lines)]
    if notes:
        parts.append("\n".join(f"- {n}" for n in notes))
    return {"answer": "\n\n".join(parts), "rows": rows, "notes": notes}


def _ordinal(n: int) -> str:
    words = {2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}
    return words.get(n, f"{n}th")


def _table(items: List[Dict[str, Any]], columns: List[str], start: int = 1) -> str:
    header = ["#", "Contract"] + [FIELD_LABELS.get(c, c) for c in columns] + ["Source", "Link"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for i, a in enumerate(items, start=start):
        cells = [str(i), _name(a)] + [_display(a, c).replace("|", "/") for c in columns]
        cells.append(f"[{i}](#source-{i})")
        cells.append(f"[View](#contract-{a.get('analysis_id')})")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def sources_for_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    References for a structured answer: each contract's header, which
    is where the parties and the amount are written, so "jump to"
    lands on the actual figure. Numbered to match the table rows.
    """
    sources = []
    for i, a in enumerate(rows, start=1):
        header = a.get("header") or {}
        meta = a.get("contract_metadata") or {}
        text = header.get("text") or meta.get("contract_value_text") or ""
        sources.append({
            "source_number": i,
            "analysis_id": a.get("analysis_id"),
            "filename": _name(a),
            "clause_id": "header" if header.get("text") else None,
            "text": text,
            "score": None,
            "kind": "header",
        })
    return sources
