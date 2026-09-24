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
}

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
indemnification_clause_present, ip_shared_with_customer.

kind = "structured" ONLY when the answer can be computed from those fields
alone: ranking (highest, lowest, largest, smallest, top N, newest, oldest,
earliest, latest), counting, totals, averages, or listing / filtering by
those fields, or looking up one of those fields for a named contract.

kind = "semantic" when the answer needs the wording of clauses: what a clause
says, obligations, interest rates, penalties, fees, termination terms, risks,
comparing terms, drafting, or explanations.

Rules for structured specs:
- "the highest / the lowest / the largest" (singular) -> limit 1.
- plural without a number ("the lowest amounts") -> limit null (list all, sorted).
- "top 3" -> limit 3.
- highest / largest / latest / newest -> order "desc"; lowest / smallest /
  earliest / oldest -> order "asc".
- filters use op "contains" for names, "greater_than"/"less_than" for amounts,
  "before"/"after" for dates (value YYYY-MM-DD or YYYY), "is_true"/"is_false"
  for yes/no fields.
- A named contract such as "Contract_7" is a filter on filename (contains).

Examples:
Q: Which contract has the highest financed amount?
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"desc","limit":1,"filters":[]}}
Q: which contracts have the least financial amounts
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"asc","limit":null,"filters":[]}}
Q: How many contracts are with Financial Bank of America?
A: {{"kind":"structured","operation":"count","sort_by":null,"order":"desc","limit":null,"filters":[{{"field":"lender_name","op":"contains","value":"Financial Bank of America"}}]}}
Q: What is the total amount financed?
A: {{"kind":"structured","operation":"sum","sort_by":null,"order":"desc","limit":null,"filters":[]}}
Q: Loans above $50,000 ending before 2027
A: {{"kind":"structured","operation":"list","sort_by":"contract_value","order":"desc","limit":null,"filters":[{{"field":"contract_value","op":"greater_than","value":"50000"}},{{"field":"end_date","op":"before","value":"2027"}}]}}
Q: Who is the lender in Contract_3?
A: {{"kind":"structured","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[{{"field":"filename","op":"contains","value":"Contract_3"}}]}}
Q: What is the interest rate in Contract_5?
A: {{"kind":"semantic","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[]}}
Q: Which contracts have the harshest default penalties?
A: {{"kind":"semantic","operation":"list","sort_by":null,"order":"desc","limit":null,"filters":[]}}

{convo}Question: {question}
"""


def route_question(llm_client: Any, question: str, history: List[Dict[str, str]]) -> Optional[ChatQuerySpec]:
    """The spec, or None if routing failed (caller then uses the semantic path)."""
    try:
        return llm_client.structured_call(
            ChatQuerySpec,
            build_router_prompt(question, history),
            ROUTER_SYSTEM,
            task="quality",
        )
    except Exception as error:
        print(f"[chat] question routing failed, using retrieval instead: {error}")
        return None


# ------------------------------------------------------------------ execution

def _field(a: Dict[str, Any], field: str) -> Any:
    if field == "filename":
        return a.get("filename")
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
        return "not found"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _name(a: Dict[str, Any]) -> str:
    return a.get("filename") or f"Contract {a.get('analysis_id')}"


def _names(items: List[Dict[str, Any]]) -> str:
    return ", ".join(_name(a) for a in items)


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

    # Aggregates --------------------------------------------------------
    if spec.operation in ("sum", "average"):
        have = [a for a in selected if _field(a, "contract_value") is not None]
        missing = [a for a in selected if _field(a, "contract_value") is None]
        by_currency: Dict[str, List[Dict[str, Any]]] = {}
        for a in have:
            by_currency.setdefault((_field(a, "currency") or "unknown currency").upper(), []).append(a)
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
        else:
            groups = [(None, sorted(have, key=lambda a: str(_field(a, spec.sort_by)).lower(), reverse=reverse))]

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

    columns: List[str] = []
    if value_involved or spec.sort_by == "contract_value":
        columns.append("contract_value")
    for f in spec.filters:
        if f.field not in columns and f.field not in ("filename", "contract_value"):
            columns.append(f.field)
    if spec.sort_by and spec.sort_by not in columns:
        columns.append(spec.sort_by)
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
        }.get((spec.sort_by, spec.order), f"{spec.order} {FIELD_LABELS.get(spec.sort_by, spec.sort_by)}")
        lead = f"**{_name(a)}** has the {word}: **{_display(a, spec.sort_by)}**."
    elif spec.limit == 1 and spec.sort_by and len(rows) > 1 and len(groups) == 1:
        lead = f"{len(rows)} contracts are tied:"
    elif spec.limit == 1 and spec.sort_by == "contract_value" and len(groups) > 1:
        which = "Highest" if spec.order == "desc" else "Lowest"
        lead = f"{which} amount in each currency:"
    elif spec.sort_by:
        direction = "highest first" if spec.order == "desc" else "lowest first"
        if spec.sort_by in ("start_date", "end_date"):
            direction = "latest first" if spec.order == "desc" else "earliest first"
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
