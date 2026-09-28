"""
Schemas for every structured (JSON) LLM call.

Each schema is used twice:
1. Its JSON schema is sent to Ollama as the "format" parameter, which
   constrains generation so the model can only produce JSON of this
   shape (no prose around it, no missing keys, no invented enum values).
2. The reply is validated against it with Pydantic. Anything that
   still doesn't fit is rejected rather than half-used.

The "before" validators only normalize harmless formatting differences
(capitalization, "$45,892.00" -> 45892.0) for servers or providers that
can't constrain output. They never invent a value.
"""
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


DOMAINS = (
    "Legal",
    "Financial",
    "Compliance",
    "HR",
    "Security",
    "Vendor",
    "Operational",
    "Environmental",
    "Intellectual Property",
    "Privacy",
    "Data Protection",
    "Other",
)

_NULL_STRINGS = {"", "null", "none", "n/a", "na", "unknown", "not stated", "not specified"}


def _none_if_blank(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
        return None
    return value


def _pick_case_insensitive(value: Any, allowed, default=None):
    if value is None:
        return default
    lookup = {a.lower(): a for a in allowed}
    return lookup.get(str(value).strip().lower(), default if default is not None else value)


# One written number: digits with , or . separators, or the European
# "45 892,00" form. A plain space only joins groups when a decimal comma
# follows, so "$45,892 360" is 45,892, not 45,892,360.
_MONEY_NUMBER = re.compile(r"-?\d{1,3}(?: \d{3})+,\d{1,2}(?!\d)|-?\d[\d,.]*\d|-?\d")
_DATE_LIKE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")
_MONEY_SCALE = [
    (re.compile(r"^\s*(?:k|thousand)\b", re.I), 1e3),
    (re.compile(r"^\s*(?:m|mn|mm|million)\b", re.I), 1e6),
    (re.compile(r"^\s*(?:b|bn|billion)\b", re.I), 1e9),
    (re.compile(r"^\s*(?:lakh|lac|lakhs|lacs)\b", re.I), 1e5),
    (re.compile(r"^\s*(?:crore|crores|cr)\b", re.I), 1e7),
]


def _number_from_digits(raw: str) -> Optional[float]:
    """Read one written number, whatever its grouping convention:
    1,203,432.00 (US) / 5,00,000 (Indian) / 45.892,00 and 45 892,00
    (European) / 1203432."""
    s = re.sub(r"\s", "", raw)
    negative = s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:
        # Whichever separator comes last is the decimal point.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # "45,50" (two decimals, one comma) is a decimal comma;
        # "5,00,000" / "1,203" are thousands separators.
        head, _, tail = s.rpartition(",")
        if s.count(",") == 1 and len(tail) in (1, 2):
            s = head + "." + tail
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        # "45.892.000" - dots as thousands separators (every group 3 digits).
        head, *groups = s.split(".")
        if not all(len(g) == 3 for g in groups):
            return None
        s = s.replace(".", "")
    # A single dot is a decimal point ("2.125", "0.875"), as in Python.
    try:
        number = float(s)
    except ValueError:
        return None
    return -number if negative else number


def parse_money(value: Any) -> Optional[float]:
    """
    '$1,203,432.00' / '1203432' / 1203432 -> 1203432.0; '$50k' -> 50000;
    '1.5M' / '1.5 million' -> 1500000; 'Rs. 5,00,000' -> 500000;
    'EUR 45.892,00' -> 45892.0. None when there's no number.

    Only the first number is read, so prefixes like "Rs." or "USD" and
    trailing words can't bleed into it.
    """
    value = _none_if_blank(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    # Dates aren't amounts: "2024-01-15" -> None, but "$45,892 as of
    # 01/15/2024" -> 45,892.
    text = _DATE_LIKE.sub(" ", text)
    if not re.search(r"\d", text):
        return None
    # A value that is nothing but one space-grouped number ("12 500 000",
    # "EUR 12 500 000") is unambiguous; inside a sentence it isn't.
    whole = re.fullmatch(r"\s*(?:[A-Za-z$€£₹]{1,3}\.?\s*)?(-?\d{1,3}(?: \d{3})+)\s*(?:[A-Za-z€£₹$]{1,3})?\s*", text)
    if whole:
        return float(whole.group(1).replace(" ", ""))
    match = _MONEY_NUMBER.search(text)
    if not match:
        return None
    number = _number_from_digits(match.group(0))
    if number is None:
        return None
    rest = text[match.end():]
    for pattern, factor in _MONEY_SCALE:
        if pattern.match(rest):
            return number * factor
    return number


# ---------------------------------------------------------------- clauses

class ClauseClassification(BaseModel):
    domain: Literal[DOMAINS]  # type: ignore[valid-type]
    risk_level: Literal["Low", "Medium", "High"]
    reasons: List[str] = Field(
        min_length=1,
        max_length=5,
        description="Short, specific risk factors taken from what the clause says.",
    )
    key_metadata: Dict[str, str] = Field(default_factory=dict)

    @field_validator("domain", mode="before")
    @classmethod
    def _domain(cls, v):
        return _pick_case_insensitive(v, DOMAINS, default="Other")

    @field_validator("risk_level", mode="before")
    @classmethod
    def _risk(cls, v):
        return _pick_case_insensitive(v, ("Low", "Medium", "High"))

    @field_validator("reasons", mode="before")
    @classmethod
    def _reasons(cls, v):
        if isinstance(v, str):
            v = [v]
        return [str(r).strip() for r in (v or []) if str(r).strip()]

    @field_validator("key_metadata", mode="before")
    @classmethod
    def _meta(cls, v):
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items() if val is not None}


# ---------------------------------------------------------------- policy

class CheckResult(BaseModel):
    id: str
    matched: bool
    reason: str

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return str(v)


class ComplianceResponse(BaseModel):
    results: List[CheckResult]


class ApplicabilityItem(BaseModel):
    id: str
    applicable: bool
    reason: str

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, v):
        return str(v)


class ApplicabilityResponse(BaseModel):
    contract_type: str
    results: List[ApplicabilityItem]


# ---------------------------------------------------------------- contract

class ContractSummary(BaseModel):
    executive_summary: str
    key_obligations: List[str]
    major_risks: List[str]
    recommendations: List[str]
    overall_sentiment: Literal["Favorable", "Balanced", "Unfavorable"]

    @field_validator("overall_sentiment", mode="before")
    @classmethod
    def _sentiment(cls, v):
        return _pick_case_insensitive(v, ("Favorable", "Balanced", "Unfavorable"), default="Balanced")


class ContractMetadataExtraction(BaseModel):
    """Every key is required (null allowed), so a constrained model has
    to consider each field instead of silently skipping one."""

    customer_name: Optional[str] = Field(
        description="Counterparty / customer / borrower name exactly as written, or null."
    )
    lender_name: Optional[str] = Field(
        description="Lender / bank named in the contract exactly as written, or null."
    )
    contract_about: Optional[str] = Field(description="3-8 word description.")
    start_date: Optional[str] = Field(description="YYYY-MM-DD or null.")
    end_date: Optional[str] = Field(description="YYYY-MM-DD or null.")
    contract_value: Optional[float] = Field(
        description="Total contract / financed amount as a plain number, or null."
    )
    contract_value_text: Optional[str] = Field(
        description="The amount exactly as written in the contract, e.g. '$45,892.00', or null."
    )
    currency: Optional[str] = Field(description="ISO code such as USD or INR, or null.")
    ip_shared_with_customer: Optional[bool]
    indemnification_clause_present: Optional[bool]
    indemnification_strength: Optional[Literal["Weak", "Standard", "Strong"]]
    governing_law: Optional[str]

    @field_validator(
        "customer_name", "lender_name", "contract_about", "start_date",
        "end_date", "contract_value_text", "currency", "governing_law",
        mode="before",
    )
    @classmethod
    def _blank(cls, v):
        v = _none_if_blank(v)
        return str(v).strip() if v is not None else None

    @field_validator("contract_value", mode="before")
    @classmethod
    def _money(cls, v):
        return parse_money(v)

    @field_validator("indemnification_strength", mode="before")
    @classmethod
    def _strength(cls, v):
        v = _none_if_blank(v)
        picked = _pick_case_insensitive(v, ("Weak", "Standard", "Strong"))
        return picked if picked in ("Weak", "Standard", "Strong") else None

    @field_validator(
        "ip_shared_with_customer", "indemnification_clause_present", mode="before"
    )
    @classmethod
    def _bool(cls, v):
        v = _none_if_blank(v)
        if isinstance(v, str):
            low = v.strip().lower()
            if low in {"true", "yes", "y"}:
                return True
            if low in {"false", "no", "n"}:
                return False
            return None
        return v


# ---------------------------------------------------------------- chat

StructuredField = Literal[
    "filename",
    "customer_name",
    "lender_name",
    "contract_about",
    "governing_law",
    "currency",
    "contract_value",
    "start_date",
    "end_date",
    "indemnification_clause_present",
    "ip_shared_with_customer",
    # From each contract's risk analysis (unknown until it's analyzed).
    "high_risk_clauses",
    "medium_risk_clauses",
    "low_risk_clauses",
    "total_clauses",
    "policy_risk_score",
]

SortField = Literal[
    "contract_value", "start_date", "end_date", "customer_name",
    "high_risk_clauses", "medium_risk_clauses", "low_risk_clauses", "total_clauses", "policy_risk_score",
]
GroupField = Literal["lender_name", "customer_name", "contract_about", "governing_law", "currency"]


class QueryFilter(BaseModel):
    field: StructuredField
    op: Literal["contains", "equals", "greater_than", "less_than", "before", "after", "is_true", "is_false"]
    value: Optional[str] = None


class ChatQuerySpec(BaseModel):
    """How to answer a chat question.

    kind="structured": the question can be answered entirely from the
    contract directory fields (amounts, dates, parties, counts, totals,
    rankings, filters). The app answers it in code, exactly.
    kind="semantic": it needs the wording of clauses (what a clause
    says, whether terms are risky, drafting, comparisons of terms)."""

    kind: Literal["structured", "semantic"]
    operation: Literal["list", "count", "sum", "average", "group"] = "list"
    sort_by: Optional[SortField] = None
    order: Literal["asc", "desc"] = "desc"
    limit: Optional[int] = Field(default=None, ge=1, le=100)
    # Rows to skip after sorting: "second highest" -> offset 1, limit 1.
    offset: int = Field(default=0, ge=0, le=100)
    # operation="group": count contracts (and total their amounts) per
    # value of this field - "which lender has the most contracts".
    group_by: Optional[GroupField] = None
    filters: List[QueryFilter] = Field(default_factory=list)
    # Which fields a lookup asks for ("When does Contract_3 end?" ->
    # ["end_date"]), so the answer shows that field, not a default set.
    fields: List[StructuredField] = Field(default_factory=list)
    # Contracts the question names, by file name or party name
    # ("Contract_3", "Julia Miller"). Used to narrow both paths.
    contracts: List[str] = Field(default_factory=list)
    # True when a clause question must look at every contract ("which
    # contracts charge more than 1.4%?", "compare the penalties").
    across_contracts: bool = False
    # The question rewritten to stand on its own, resolving follow-ups
    # ("and for Peter Chen?" -> "What is the interest rate in Peter
    # Chen's contract?"). Used for search.
    standalone_question: Optional[str] = None

    @field_validator("fields", mode="before")
    @classmethod
    def _known_fields_only(cls, value):
        allowed = set(StructuredField.__args__)
        if not isinstance(value, list):
            return []
        return [v for v in value if isinstance(v, str) and v in allowed]

    @field_validator("contracts", mode="before")
    @classmethod
    def _names_only(cls, value):
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v or "").strip()][:10]
