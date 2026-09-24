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


def parse_money(value: Any) -> Optional[float]:
    """'$1,203,432.00' / '1203432' / 1203432 -> 1203432.0; else None."""
    value = _none_if_blank(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    if not cleaned or cleaned in {".", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


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
]


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
    operation: Literal["list", "count", "sum", "average"] = "list"
    sort_by: Optional[Literal["contract_value", "start_date", "end_date", "customer_name"]] = None
    order: Literal["asc", "desc"] = "desc"
    limit: Optional[int] = Field(default=None, ge=1, le=100)
    filters: List[QueryFilter] = Field(default_factory=list)
