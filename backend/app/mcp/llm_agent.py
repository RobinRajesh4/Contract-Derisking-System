from typing import Any, Dict, List, Optional
import json
import re

from .utils import MCPConfig, mcp_post
from ..llm_providers import get_llm_provider


DOMAINS = [
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
]


CLASSIFICATION_KEYS = {
    "domain",
    "risk_level",
    "reasons",
    "key_metadata",
}


SUMMARY_KEYS = {
    "executive_summary",
    "key_obligations",
    "major_risks",
    "recommendations",
    "overall_sentiment",
}


CONTRACT_METADATA_KEYS = {
    "customer_name",
    "lender_name",
    "contract_about",
    "start_date",
    "end_date",
    "contract_value",
    "currency",
    "ip_shared_with_customer",
    "indemnification_clause_present",
    "indemnification_strength",
    "governing_law",
}


def remove_reasoning_traces(content: str) -> str:
    """
    Strip <think>...</think> (and similar) reasoning blocks that
    "thinking" models - Qwen3, DeepSeek-R1, etc. - can prepend before
    their actual JSON answer when thinking mode isn't explicitly
    disabled in the request. Handles both a closed block and one left
    open because the response was cut off mid-thought.
    """

    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # An unclosed <think> at the very start means the model never
    # finished reasoning (or the tag simply wasn't closed) - in that
    # case there is nothing usable before it, so drop everything up to
    # the last </think>-less tag rather than feeding raw reasoning text
    # into the JSON parser.
    cleaned = re.sub(
        r"^\s*<think>.*$",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return cleaned.strip()


def remove_markdown_fences(content: str) -> str:
    """
    Remove Markdown code fences and reasoning-model "thinking" blocks
    surrounding an LLM response.
    """

    cleaned = remove_reasoning_traces(content.strip())

    cleaned = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```\s*$",
        "",
        cleaned,
    )

    return cleaned.strip()


def find_object_with_keys(
    value: Any,
    required_keys: set,
) -> Optional[Dict[str, Any]]:
    """
    Recursively search a Python value for a dictionary containing
    all the required keys.

    This handles Ollama wrapper objects such as:

    {
        "response": "{...}"
    }

    and:

    {
        "message": {
            "content": "{...}"
        }
    }
    """

    if isinstance(value, dict):
        value_keys = set(value.keys())

        if required_keys.issubset(value_keys):
            return value

        preferred_wrapper_keys = [
            "response",
            "message",
            "content",
            "result",
            "output",
            "data",
        ]

        for key in preferred_wrapper_keys:
            if key not in value:
                continue

            found = find_object_with_keys(
                value[key],
                required_keys,
            )

            if found is not None:
                return found

        for nested_value in value.values():
            found = find_object_with_keys(
                nested_value,
                required_keys,
            )

            if found is not None:
                return found

    elif isinstance(value, list):
        for item in value:
            found = find_object_with_keys(
                item,
                required_keys,
            )

            if found is not None:
                return found

    elif isinstance(value, str):
        try:
            return parse_llm_json(
                value,
                required_keys=required_keys,
            )

        except ValueError:
            return None

    return None

def parse_llm_json(
    content: Any,
    required_keys: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Parse JSON returned by Groq, Ollama, or MCP.

    Handles:
    - Direct JSON objects
    - Markdown code fences
    - Ollama /api/generate wrappers
    - Ollama /api/chat wrappers
    - Ollama newline-delimited streaming JSON
    - Additional text before or after the result
    - Multiple JSON objects
    """

    if content is None:
        raise ValueError("LLM returned no content")

    # Handle an already-decoded dictionary.
    if isinstance(content, dict):
        # Ollama /api/generate response.
        response_text = content.get("response")

        if isinstance(response_text, str):
            if not response_text.strip():
                raise ValueError(
                    "Ollama returned an empty response field"
                )

            return parse_llm_json(
                response_text,
                required_keys=required_keys,
            )

        # Ollama /api/chat response.
        message = content.get("message")

        if isinstance(message, dict):
            message_content = message.get("content")

            if isinstance(message_content, str):
                return parse_llm_json(
                    message_content,
                    required_keys=required_keys,
                )

        if required_keys:
            found = find_object_with_keys(
                content,
                required_keys,
            )

            if found is not None:
                return found

        return content

    if not isinstance(content, str):
        content = str(content)

    cleaned = remove_markdown_fences(content)

    if not cleaned:
        raise ValueError(
            "LLM returned an empty response"
        )

    # Handle Ollama newline-delimited JSON streaming responses.
    #
    # Example:
    # {"response":"{","done":false}
    # {"response":"\"domain\"","done":false}
    # {"response":"}","done":true}
    lines = [
        line.strip()
        for line in cleaned.splitlines()
        if line.strip()
    ]

    ollama_chunks: List[str] = []
    parsed_ollama_lines = 0

    for line in lines:
        try:
            line_object = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(line_object, dict):
            continue

        if "response" in line_object:
            parsed_ollama_lines += 1

            response_chunk = line_object.get(
                "response",
                "",
            )

            if isinstance(response_chunk, str):
                ollama_chunks.append(
                    response_chunk
                )

        elif isinstance(
            line_object.get("message"),
            dict,
        ):
            parsed_ollama_lines += 1

            message_chunk = (
                line_object
                .get("message", {})
                .get("content", "")
            )

            if isinstance(message_chunk, str):
                ollama_chunks.append(
                    message_chunk
                )

    if parsed_ollama_lines > 0:
        assembled_response = "".join(
            ollama_chunks
        ).strip()

        if not assembled_response:
            raise ValueError(
                "Ollama response chunks were found, "
                "but the generated content was empty"
            )

        return parse_llm_json(
            assembled_response,
            required_keys=required_keys,
        )

    # Attempt to parse the complete response as one JSON value.
    try:
        parsed = json.loads(cleaned)

        if isinstance(parsed, dict):
            # Unwrap a non-streaming Ollama response.
            if isinstance(
                parsed.get("response"),
                str,
            ):
                return parse_llm_json(
                    parsed["response"],
                    required_keys=required_keys,
                )

            message = parsed.get("message")

            if isinstance(message, dict):
                message_content = message.get(
                    "content"
                )

                if isinstance(
                    message_content,
                    str,
                ):
                    return parse_llm_json(
                        message_content,
                        required_keys=required_keys,
                    )

            if required_keys:
                found = find_object_with_keys(
                    parsed,
                    required_keys,
                )

                if found is not None:
                    return found

                raise ValueError(
                    "LLM returned JSON, but it did not "
                    "contain all required fields. "
                    f"Top-level keys: {sorted(parsed.keys())}"
                )

            return parsed

        if isinstance(parsed, list):
            if required_keys:
                found = find_object_with_keys(
                    parsed,
                    required_keys,
                )

                if found is not None:
                    return found

            raise ValueError(
                "LLM returned a JSON array instead "
                "of the expected JSON object"
            )

    except json.JSONDecodeError:
        pass

    # Search through mixed text for JSON objects.
    decoder = json.JSONDecoder()
    decoded_objects: List[Dict[str, Any]] = []

    for index, character in enumerate(cleaned):
        if character != "{":
            continue

        try:
            candidate, _ = decoder.raw_decode(
                cleaned[index:]
            )
        except json.JSONDecodeError:
            continue

        if not isinstance(candidate, dict):
            continue

        # Unwrap an Ollama response object.
        if isinstance(
            candidate.get("response"),
            str,
        ):
            response_text = candidate[
                "response"
            ]

            if response_text.strip():
                try:
                    return parse_llm_json(
                        response_text,
                        required_keys=required_keys,
                    )
                except ValueError:
                    pass

        message = candidate.get("message")

        if isinstance(message, dict):
            message_content = message.get(
                "content"
            )

            if isinstance(
                message_content,
                str,
            ) and message_content.strip():
                try:
                    return parse_llm_json(
                        message_content,
                        required_keys=required_keys,
                    )
                except ValueError:
                    pass

        decoded_objects.append(candidate)

        if required_keys:
            found = find_object_with_keys(
                candidate,
                required_keys,
            )

            if found is not None:
                return found
        else:
            return candidate

    if decoded_objects:
        available_keys = sorted(
            {
                str(key)
                for item in decoded_objects
                for key in item.keys()
            }
        )

        raise ValueError(
            "LLM returned JSON objects, but no object "
            "contained all required classification fields. "
            f"Available keys: {available_keys}"
        )

    raise ValueError(
        "LLM did not return a valid JSON object. "
        f"Response preview: {cleaned[:500]!r}"
    )


def normalize_classification(
    result: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate and normalize a classification response.
    """

    if not isinstance(result, dict):
        raise ValueError(
            "Clause classification must be a JSON object"
        )

    domain = str(
        result.get("domain", "Other")
    ).strip()

    domain_lookup = {
        item.lower(): item
        for item in DOMAINS
    }

    domain = domain_lookup.get(
        domain.lower(),
        "Other",
    )

    risk_level = str(
        result.get("risk_level", "Low")
    ).strip().capitalize()

    if risk_level not in {
        "Low",
        "Medium",
        "High",
    }:
        risk_level = "Low"

    reasons = result.get(
        "reasons",
        [],
    )

    if reasons is None:
        reasons = []

    elif not isinstance(reasons, list):
        reasons = [str(reasons)]

    else:
        reasons = [
            str(reason).strip()
            for reason in reasons
            if str(reason).strip()
        ]

    if not reasons:
        reasons = [
            "The LLM did not provide a specific "
            "risk explanation"
        ]

    key_metadata = result.get(
        "key_metadata",
        {},
    )

    if not isinstance(key_metadata, dict):
        key_metadata = {}

    merged_metadata = dict(metadata)
    merged_metadata.update(key_metadata)

    return {
        "domain": domain,
        "risk_level": risk_level,
        "reasons": reasons,
        "key_metadata": merged_metadata,
    }


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "unknown", "not stated", "not specified"}:
        return None
    return text


def _clean_optional_date(value: Any) -> Optional[str]:
    text = _clean_optional_str(value)
    if text is None:
        return None
    return text if _DATE_RE.match(text) else text  # keep raw text if not ISO; UI/prompt can still use it


def _clean_optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "y"}:
        return True
    if text in {"false", "no", "n"}:
        return False
    return None


def normalize_contract_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize the contract-level metadata extraction
    response so downstream code (the chat directory, listing
    endpoints) can rely on consistent types.
    """

    if not isinstance(result, dict):
        raise ValueError("Contract metadata must be a JSON object")

    contract_value_raw = result.get("contract_value")
    contract_value: Optional[float] = None
    if contract_value_raw not in (None, "", "null"):
        try:
            contract_value = float(
                str(contract_value_raw).replace(",", "").replace("₹", "").strip()
            )
        except (ValueError, TypeError):
            contract_value = None

    indemnification_strength = _clean_optional_str(
        result.get("indemnification_strength")
    )
    if indemnification_strength and indemnification_strength.capitalize() in {
        "Weak",
        "Standard",
        "Strong",
    }:
        indemnification_strength = indemnification_strength.capitalize()
    elif indemnification_strength:
        indemnification_strength = None

    return {
        "customer_name": _clean_optional_str(result.get("customer_name")),
        "lender_name": _clean_optional_str(result.get("lender_name")),
        "contract_about": _clean_optional_str(result.get("contract_about")),
        "start_date": _clean_optional_date(result.get("start_date")),
        "end_date": _clean_optional_date(result.get("end_date")),
        "contract_value": contract_value,
        "currency": _clean_optional_str(result.get("currency")),
        "ip_shared_with_customer": _clean_optional_bool(
            result.get("ip_shared_with_customer")
        ),
        "indemnification_clause_present": _clean_optional_bool(
            result.get("indemnification_clause_present")
        ),
        "indemnification_strength": indemnification_strength,
        "governing_law": _clean_optional_str(result.get("governing_law")),
        "extraction_method": "llm",
    }


class LLMClient:
    def __init__(self) -> None:
        self.cfg = MCPConfig()

    def _get_provider(self):
        """
        Return the currently configured LLM provider.
        """

        return get_llm_provider()

    def generate_contract_summary(
        self,
        contract_text: str,
        clauses: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Generate an executive summary of the contract.
        """

        provider = self._get_provider()

        if not provider.is_available():
            print("LLM provider not available")
            return None

        try:
            high_risk = sum(
                1
                for clause in clauses
                if (
                    clause
                    .get("classification", {})
                    .get("risk_level", "")
                    .lower()
                    == "high"
                )
            )

            medium_risk = sum(
                1
                for clause in clauses
                if (
                    clause
                    .get("classification", {})
                    .get("risk_level", "")
                    .lower()
                    == "medium"
                )
            )

            low_risk = (
                len(clauses)
                - high_risk
                - medium_risk
            )

            # Keep the prompt manageable for a local model.
            contract_preview = contract_text[:12000]

            prompt = f"""
Analyze the following contract and produce an executive summary.

Contract statistics:
Total clauses: {len(clauses)}
High-risk clauses: {high_risk}
Medium-risk clauses: {medium_risk}
Low-risk clauses: {low_risk}

Contract text:
{contract_preview}

Return exactly one compact JSON object with these keys:

executive_summary
key_obligations
major_risks
recommendations
overall_sentiment

Requirements:

1. executive_summary must be a string.
2. key_obligations must be an array of strings.
3. major_risks must be an array of strings.
4. recommendations must be an array of strings.
5. overall_sentiment must be Favorable, Balanced, or Unfavorable.
6. Do not return Markdown.
7. Do not explain the answer.
8. Do not return text before or after the JSON.
""".strip()

            system = """
You are a legal contract-analysis assistant.

Return exactly one valid JSON object.
Return no reasoning.
Return no Markdown.
Return no text outside the JSON object.
""".strip()

            content = provider.invoke(
                prompt,
                system=system,
                temperature=0,
            )

            result = parse_llm_json(
                content,
                required_keys=SUMMARY_KEYS,
            )

            result["executive_summary"] = str(
                result.get(
                    "executive_summary",
                    "",
                )
            ).strip()

            for field in [
                "key_obligations",
                "major_risks",
                "recommendations",
            ]:
                value = result.get(field, [])

                if value is None:
                    result[field] = []

                elif not isinstance(value, list):
                    result[field] = [
                        str(value).strip()
                    ]

                else:
                    result[field] = [
                        str(item).strip()
                        for item in value
                        if str(item).strip()
                    ]

            sentiment = str(
                result.get(
                    "overall_sentiment",
                    "Balanced",
                )
            ).strip().capitalize()

            if sentiment not in {
                "Favorable",
                "Balanced",
                "Unfavorable",
            }:
                sentiment = "Balanced"

            result["overall_sentiment"] = sentiment

            return result

        except Exception as error:
            print(
                f"Summary generation error: {error}"
            )
            return None

    def extract_contract_metadata(
        self,
        contract_text: str,
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract document-level contract metadata (customer, dates,
        value, IP terms, indemnification strength) so the chat
        assistant can answer listing/filtering questions accurately
        without having to re-read every clause every time.

        Falls back to a conservative local heuristic extraction if
        no LLM provider is available or the LLM call fails, so the
        directory always has a best-effort entry for every contract.
        """

        provider = self._get_provider()

        if provider.is_available():
            try:
                contract_preview = contract_text[:12000]

                prompt = f"""
Extract key metadata from the following contract.

Filename (may hint at the customer/contract type, but the contract
text is authoritative if they disagree):
{filename or "unknown"}

Contract text:
{contract_preview}

Return exactly one compact JSON object with these keys:

customer_name
lender_name
contract_about
start_date
end_date
contract_value
currency
ip_shared_with_customer
indemnification_clause_present
indemnification_strength
governing_law

Requirements:

1. customer_name: the counterparty / client / customer name as a string.
   Use null if it truly cannot be determined.
2. lender_name: for a loan, financing, or credit agreement, the actual
   name of the lender / bank / financial institution extending credit
   (this is usually named in the preamble, e.g. "between Bank Of
   America Inc. (the \"BANK\") and ..."). Use null if the contract is
   not a financing/loan agreement, or if no specific institution name
   is given (a generic label like "the BANK" or "the LENDER" with no
   real name attached does NOT count - use null in that case, don't
   invent a name).
3. contract_about: a short (3-8 word) description of what the contract
   is for, e.g. "IT services agreement" or "Data processing agreement".
4. start_date and end_date: ISO format YYYY-MM-DD if a specific date is
   stated or can be computed (e.g. "3 years from execution"). Use null
   if not determinable. Do not guess a date that is not supported by
   the text.
5. contract_value: the total contract value as a plain number (no
   currency symbols, no commas). Use null if not stated.
6. currency: the ISO currency code (e.g. INR, USD) if determinable,
   else null.
7. ip_shared_with_customer: true if the contract assigns, licenses, or
   otherwise shares intellectual property ownership/rights with the
   customer; false if IP is retained solely by the provider; null if
   the contract has no IP clause at all.
8. indemnification_clause_present: true or false.
9. indemnification_strength: one of "Weak", "Standard", "Strong", or
   null if there is no indemnification clause. "Weak" means the
   clause is one-sided against the drafting party, has low/no caps
   protecting the drafting party, or has narrow/limited coverage.
10. governing_law: the governing law / jurisdiction if stated, else null.
11. Do not invent facts. Use null wherever the text does not support
    a confident answer.
12. Do not return Markdown.
12. Do not return text before or after the JSON.
""".strip()

                system = """
You are a contract metadata-extraction assistant.

Return exactly one valid JSON object.
Return no reasoning.
Return no Markdown.
Return no text outside the JSON object.
Only report facts you can support from the given text.
""".strip()

                content = provider.invoke(
                    prompt,
                    system=system,
                    temperature=0,
                )

                result = parse_llm_json(
                    content,
                    required_keys=CONTRACT_METADATA_KEYS,
                )

                return normalize_contract_metadata(result)

            except Exception as error:
                print(
                    "Contract metadata extraction failed. "
                    f"Using local fallback. Reason: {error}"
                )

        return self._local_metadata_fallback(
            contract_text,
            filename,
        )

    def _local_metadata_fallback(
        self,
        contract_text: str,
        filename: Optional[str],
    ) -> Dict[str, Any]:
        """
        Best-effort regex extraction used only when no LLM provider
        is available. Deliberately conservative: leaves fields null
        rather than guessing, since this data drives contract
        listings and must stay accurate.
        """

        text = contract_text or ""

        # Connector words that can sit right before a name and get
        # mistakenly swallowed by the capitalized-word-run pattern
        # below (e.g. "Between Bank Of America Inc." at a sentence
        # start, where "Between" is capitalized too).
        _LEADING_STOPWORDS_RE = re.compile(
            r"^(?:Between|And|Among|This|Entered|Into|By)\s+", re.IGNORECASE
        )

        customer_name = None
        customer_match = re.search(
            r"(?:Customer|Client|Borrower)\s*[:\-]\s*"
            r"([A-Za-z][A-Za-z .'\-]{1,60}?)(?=\s*[,.(]|\s*$)",
            text,
            re.IGNORECASE,
        )
        if customer_match:
            customer_name = customer_match.group(1).strip().rstrip(".,")

        # Two preamble styles seen in practice:
        # 1. Labeled: "LENDER: Financial Bank Of America Inc., ..."
        # 2. Parenthetical: "between Bank Of America Inc. (the "BANK")
        #    and ...". Try the labeled style first since it gives a
        #    cleaner, more explicit match; fall back to parenthetical.
        # Deliberately conservative either way - only fires when an
        # actual name is present, not on the generic label alone.
        lender_name = None
        lender_label_match = re.search(
            r"(?:Lender|Bank)\s*[:\-]\s*"
            r"([A-Za-z][A-Za-z0-9 .,&'\-]{1,60}?)(?=\s*[,.(]|\s*$)",
            text,
            re.IGNORECASE,
        )
        if lender_label_match:
            lender_name = lender_label_match.group(1).strip().rstrip(".,")
        else:
            lender_paren_match = re.search(
                r"\b((?:[A-Z][A-Za-z0-9&.\-]*\s+){0,5}[A-Z][A-Za-z0-9&.\-]*)\s*"
                r"\(\s*(?:the\s+)?[\"\u201c]?(?:BANK|LENDER)[\"\u201d]?\s*\)",
                text,
            )
            if lender_paren_match:
                lender_name = _LEADING_STOPWORDS_RE.sub(
                    "", lender_paren_match.group(1).strip().rstrip(".,")
                ).strip()

        date_pattern = (
            r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
            r"|\d{4}-\d{2}-\d{2}"
            r"|(?:January|February|March|April|May|June|July|"
            r"August|September|October|November|December)\s+"
            r"\d{1,2},?\s+\d{4})\b"
        )

        end_date = None
        end_date_match = re.search(
            r"(?:end date|expiry|expiration|valid until|terminates on)"
            rf"\D{{0,20}}({date_pattern})",
            text,
            flags=re.IGNORECASE,
        )
        if end_date_match:
            end_date = end_date_match.group(1)

        start_date = None
        start_date_match = re.search(
            r"(?:effective date|commencement date|start date|"
            rf"dated as of)\D{{0,20}}({date_pattern})",
            text,
            flags=re.IGNORECASE,
        )
        if start_date_match:
            start_date = start_date_match.group(1)

        contract_value = None
        currency = None
        value_match = re.search(
            r"(INR|USD|EUR|GBP|Rs\.?|\$|₹)\s?"
            r"([\d,]+(?:\.\d+)?)",
            text,
        )
        if value_match:
            currency_raw = value_match.group(1)
            currency_map = {
                "rs.": "INR",
                "rs": "INR",
                "₹": "INR",
                "$": "USD",
            }
            currency = currency_map.get(
                currency_raw.lower(),
                currency_raw.upper(),
            )
            contract_value_str = value_match.group(2).replace(",", "")
            try:
                # Match normalize_contract_metadata's behavior (the LLM
                # extraction path): store as a real float, not a string.
                # Left as a string here, this silently broke every
                # downstream isinstance(value, (int, float)) check - the
                # chat directory's "Value: ..." display and the sort-
                # by-value fix both treat a non-numeric type as
                # "unknown", so a fallback-extracted contract would
                # always show as unknown even with a real value found.
                contract_value = float(contract_value_str)
            except (TypeError, ValueError):
                contract_value = None

        lowered = text.lower()

        ip_shared_with_customer = None
        if re.search(r"intellectual property|\bIP\b", text, flags=re.IGNORECASE):
            if any(
                phrase in lowered
                for phrase in [
                    "assigns all right",
                    "assign all intellectual property",
                    "license to customer",
                    "grants customer a license",
                    "shall belong to customer",
                    "vest in the customer",
                ]
            ):
                ip_shared_with_customer = True
            elif any(
                phrase in lowered
                for phrase in [
                    "retains all right",
                    "sole and exclusive property",
                    "shall remain the property of",
                ]
            ):
                ip_shared_with_customer = False

        indemnification_present = bool(
            re.search(r"indemnif", text, flags=re.IGNORECASE)
        )

        indemnification_strength = None
        if indemnification_present:
            if any(
                phrase in lowered
                for phrase in [
                    "sole discretion",
                    "no liability",
                    "shall not be liable",
                    "waives all claims",
                    "as-is",
                ]
            ):
                indemnification_strength = "Weak"
            else:
                indemnification_strength = "Standard"

        governing_law = None
        law_match = re.search(
            r"governed by (?:the )?laws? of ([A-Za-z ,]{2,40})",
            text,
            flags=re.IGNORECASE,
        )
        if law_match:
            governing_law = law_match.group(1).strip().rstrip(".,")

        return {
            "customer_name": customer_name,
            "lender_name": lender_name,
            "contract_about": None,
            "start_date": start_date,
            "end_date": end_date,
            "contract_value": contract_value,
            "currency": currency,
            "ip_shared_with_customer": ip_shared_with_customer,
            "indemnification_clause_present": indemnification_present,
            "indemnification_strength": indemnification_strength,
            "governing_law": governing_law,
            "extraction_method": "local_fallback",
        }

    def evaluate_policy_compliance(
        self,
        clause_text: str,
        micro_policies: List[Dict[str, Any]],
        context: str = "",
    ) -> Optional[List[Optional[Dict[str, Any]]]]:
        """
        Judge one clause against all of its domain's micro-policy
        checks in a single call - based on the clause's actual meaning,
        not keyword overlap with each check's description. This
        replaces _policy_match's keyword-counting for the common case;
        callers should fall back to it only when this returns None
        (no provider available, or the call failed outright) or for
        any individual check this returns None for (the model omitted
        that check id from its response).

        Returns a list aligned 1:1 with micro_policies, each entry
        either {"id", "matched", "reason"} or None.
        """

        if not micro_policies:
            return []

        provider = self._get_provider()
        if not provider.is_available():
            return None

        checks_payload = [
            {
                "id": mp.get("id"),
                "name": mp.get("name"),
                "check": mp.get("check"),
            }
            for mp in micro_policies
        ]
        checks_json = json.dumps(checks_payload, ensure_ascii=False)

        context_block = (
            f"Organization context (use it to resolve references such as "
            f"'our primary jurisdiction'):\n{context.strip()}\n\n"
            if context and context.strip()
            else ""
        )

        prompt = f"""
Evaluate this single contract clause against each policy check below.

{context_block}Clause:
{clause_text}

Policy checks (evaluate every one, independently):
{checks_json}

For each check, decide whether the clause actually satisfies its
intent, based on meaning, not shared words. A clause that achieves
the same effect using different wording still counts as satisfied.
A clause that merely shares vocabulary with the check without
actually satisfying its requirement does not count as satisfied.
Consider negation carefully (e.g. "shall not be limited" is the
opposite of "shall be limited").
Be strict about the mechanism a check names. Choosing a court or
forum is NOT binding arbitration; choosing a forum is NOT the same as
naming governing law; a termination clause that removes or waives
notice does NOT satisfy a minimum-notice requirement. If a check
depends on a fact you cannot see (e.g. "the company's primary
jurisdiction" with no context given), do not assume it is met.

Return exactly one compact JSON object of this form:
{{"results": [{{"id": "<check id>", "matched": true, "reason": "<short reason>"}}]}}

Requirements:
1. Include exactly one result per check id given above.
2. matched must be a JSON boolean (true or false), never null or a string.
3. reason must be a short (under 20 words) plain-language justification
   tied to what the clause actually says.
4. Return no text before or after the JSON object.
5. Return no Markdown.
""".strip()

        system = """
You are a contract-compliance assistant.
Judge each policy check strictly on whether the clause's actual
meaning satisfies it, not on shared vocabulary.
Return exactly one JSON object. No reasoning outside it. No Markdown.
""".strip()

        try:
            content = provider.invoke(
                prompt,
                system=system,
                temperature=0,
            )

            result = parse_llm_json(content, required_keys={"results"})
            raw_results = result.get("results")

            if not isinstance(raw_results, list):
                raise ValueError("'results' must be a JSON array")

            by_id: Dict[str, Dict[str, Any]] = {}
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                check_id = item.get("id")
                if check_id is None:
                    continue

                matched = item.get("matched")
                if not isinstance(matched, bool):
                    matched = str(matched).strip().lower() in {"true", "yes", "y"}

                reason = item.get("reason")
                reason = str(reason).strip() if reason else ""

                by_id[str(check_id)] = {"matched": matched, "reason": reason}

            # Align 1:1 with the input order; a missing id becomes None
            # so the caller can fall back to keyword matching for just
            # that one check rather than discarding the whole clause.
            aligned: List[Optional[Dict[str, Any]]] = []
            for mp in micro_policies:
                check_id = str(mp.get("id"))
                if check_id in by_id:
                    aligned.append({"id": mp.get("id"), **by_id[check_id]})
                else:
                    aligned.append(None)

            return aligned

        except Exception as error:
            print(f"LLM policy compliance evaluation failed: {error}")
            return None

    def evaluate_check_applicability(
        self,
        clause_texts: List[str],
        micro_policies: List[Dict[str, Any]],
        context: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Decide, once per contract, which policy checks are even
        applicable to this KIND of contract (e.g. invoice-documentation
        rules do not apply to a consumer loan). One call covers all
        checks, so it adds a single LLM request per analysis.

        Returns {"contract_type": str, "by_id": {id: {"applicable": bool,
        "reason": str}}} or None if no provider / the call failed. Ids
        the model omits are simply absent from by_id; callers should
        treat absent ids as applicable (fail toward flagging).
        """

        if not micro_policies or not clause_texts:
            return None

        provider = self._get_provider()
        if not provider.is_available():
            return None

        clauses_block = "\n".join(
            f"{i + 1}. {(t or '').strip()[:300]}"
            for i, t in enumerate(clause_texts[:40])
        )
        checks_json = json.dumps(
            [
                {"id": mp.get("id"), "name": mp.get("name"), "check": mp.get("check")}
                for mp in micro_policies
            ],
            ensure_ascii=False,
        )
        context_block = (
            f"Organization context:\n{context.strip()}\n\n"
            if context and context.strip()
            else ""
        )

        prompt = f"""
Below are the clauses of one contract, then a list of policy checks.

{context_block}Contract clauses:
{clauses_block}

Policy checks:
{checks_json}

First infer what kind of contract this is (e.g. "consumer asset
financing agreement", "SaaS subscription", "NDA").

Then, for each check, decide whether it is APPLICABLE to that kind of
contract: would a competent lawyer reviewing this type of contract
reasonably expect the check's subject to be addressed in it? Set
applicable to false ONLY when the requirement is clearly irrelevant to
this type of agreement (for example, invoice documentation rules for a
loan, or a mutual-indemnification rule for a one-sided lender
agreement). When unsure, set applicable to true. Whether the contract
currently satisfies the check is NOT your concern here.

Return exactly one compact JSON object of this form:
{{"contract_type": "<short label>", "results": [{{"id": "<check id>", "applicable": true, "reason": "<under 20 words>"}}]}}

Requirements:
1. Include exactly one result per check id.
2. applicable must be a JSON boolean.
3. Return no text before or after the JSON object. No Markdown.
""".strip()

        system = """
You are a contract-review assistant deciding which policy checks are
relevant to a given type of contract.
Return exactly one JSON object. No reasoning outside it. No Markdown.
""".strip()

        try:
            content = provider.invoke(prompt, system=system, temperature=0)
            result = parse_llm_json(content, required_keys={"results"})
            raw = result.get("results")
            if not isinstance(raw, list):
                raise ValueError("'results' must be a JSON array")

            by_id: Dict[str, Dict[str, Any]] = {}
            for item in raw:
                if not isinstance(item, dict) or item.get("id") is None:
                    continue
                applicable = item.get("applicable")
                if not isinstance(applicable, bool):
                    applicable = str(applicable).strip().lower() not in {
                        "false", "no", "n",
                    }
                reason = item.get("reason")
                by_id[str(item["id"])] = {
                    "applicable": applicable,
                    "reason": str(reason).strip() if reason else "",
                }

            return {
                "contract_type": str(result.get("contract_type") or "").strip(),
                "by_id": by_id,
            }
        except Exception as error:
            print(f"LLM check-applicability evaluation failed: {error}")
            return None

    def generate_recommendation(
        self,
        text: str,
        risk_level: str,
        reasons: List[str],
    ) -> Optional[str]: 
        """
        Generate alternative wording for a high-risk clause.
        """

        if risk_level.lower() != "high":
            return None

        provider = self._get_provider()

        if not provider.is_available():
            return None

        try:
            prompt = f"""
Rewrite the following high-risk contract clause to reduce risk
while preserving its original purpose.

Original clause:
{text}

Risk factors:
{"; ".join(reasons)}

Requirements:

1. Address the identified risk factors.
2. Preserve balanced obligations.
3. Use clear and professional language.
4. Protect the reasonable interests of both parties.
5. Return one paragraph only.
6. Do not include a heading.
7. Do not include Markdown.
""".strip()

            content = provider.invoke(
                prompt,
                system=(
                    "You are a contract drafting assistant. "
                    "Return only one paragraph of alternative wording."
                ),
                temperature=0.3,
            )

            if content is None:
                return None

            recommendation = str(
                content
            ).strip()

            return recommendation or None

        except Exception as error:
            print(
                "Recommendation generation error: "
                f"{error}"
            )
            return None

    def classify_clause(
        self,
        text: str,
        metadata: Dict[str, Any],
        context: Optional[
            List[Dict[str, Any]]
        ] = None,
    ) -> Dict[str, Any]:
        """
        Classify one contract clause and assess its risk.
        """

        prompt = self._build_prompt(
            text,
            metadata,
            context,
        )

        system = """
You are a contract clause-classification assistant.

Return exactly one compact JSON object containing exactly these keys:

domain
risk_level
reasons
key_metadata

Requirements:

1. domain must be one of the allowed domains in the user prompt.
2. risk_level must be Low, Medium, or High.
3. reasons must be an array of short strings.
4. key_metadata must be a JSON object.
5. Return no reasoning.
6. Return no Markdown.
7. Return no introduction.
8. Return no text after the JSON.
""".strip()

        provider = self._get_provider()

        if provider.is_available():
            try:
                content = provider.invoke(
                    prompt,
                    system=system,
                    temperature=0,
                )

                response_length = (
                    len(content)
                    if isinstance(content, str)
                    else "non-string"
                )

                print(
                    "LLM classification provider: "
                    f"{provider.__class__.__name__}; "
                    f"response length: {response_length}"
                )

                result = parse_llm_json(
                    content,
                    required_keys=CLASSIFICATION_KEYS,
                )

                return normalize_classification(
                    result,
                    metadata,
                )

            except Exception as error:
                print(
                    "LLM classification failed. "
                    "Using local fallback. "
                    f"Reason: {error}"
                )

        if self.cfg.is_configured():
            payload = {
                "model": self.cfg.model,
                "messages": [
                    {
                        "role": "system",
                        "content": system,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "response_format": {
                    "type": "json_object"
                },
            }

            try:
                response = mcp_post(
                    "/v1/chat/completions",
                    payload,
                    self.cfg,
                )

                if (
                    response
                    and "choices" in response
                    and response["choices"]
                ):
                    content = (
                        response["choices"][0]
                        ["message"]
                        ["content"]
                    )

                    result = parse_llm_json(
                        content,
                        required_keys=CLASSIFICATION_KEYS,
                    )

                    return normalize_classification(
                        result,
                        metadata,
                    )

            except Exception as error:
                print(
                    "MCP classification failed. "
                    "Using local fallback. "
                    f"Reason: {error}"
                )

        return self._local_fallback(
            text,
            metadata,
        )

    def _build_prompt(
        self,
        text: str,
        metadata: Dict[str, Any],
        context: Optional[
            List[Dict[str, Any]]
        ] = None,
    ) -> str:
        """
        Build a compact clause-classification prompt.
        """

        context_snippets = ""

        if context:
            top_context = context[:3]

            joined_context = "\n---\n".join(
                item.get("text", "")
                for item in top_context
                if item.get("text")
            )

            if joined_context:
                context_snippets = (
                    "\n\nReference clauses:\n"
                    "Use these only as context. "
                    "Do not copy their classification.\n"
                    f"{joined_context}"
                )

        metadata_json = json.dumps(
            metadata,
            ensure_ascii=False,
            default=str,
        )

        domains_json = json.dumps(
            DOMAINS,
            ensure_ascii=False,
        )

        return f"""
Classify this single contract clause.

Allowed domains:
{domains_json}

Clause:
{text}

Known metadata:
{metadata_json}
{context_snippets}

Return one compact JSON object.

The object must contain:

- domain
- risk_level
- reasons
- key_metadata

Rules:

- domain must exactly match one allowed domain.
- risk_level must be Low, Medium, or High.
- reasons must be an array of short strings.
- key_metadata must be an object.
- Use an empty object when no metadata is found.
- Return no internal reasoning.
- Return no analysis outside the JSON.
- Return no Markdown.
""".strip()

    def _local_fallback(
        self,
        text: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Classify the clause with local keyword rules when an LLM fails.
        """

        normalized_text = text.lower()
        domain = "Other"

        if any(
            keyword in normalized_text
            for keyword in [
                "payment",
                "invoice",
                "fee",
                "price",
                "pricing",
                "revenue",
                "cost",
            ]
        ):
            domain = "Financial"

        elif any(
            keyword in normalized_text
            for keyword in [
                "confidential",
                "nda",
                "non-disclosure",
                "trade secret",
            ]
        ):
            domain = "Legal"

        elif any(
            keyword in normalized_text
            for keyword in [
                "data protection",
                "data processing",
                "data retention",
                "data deletion",
            ]
        ):
            domain = "Data Protection"

        elif any(
            keyword in normalized_text
            for keyword in [
                "privacy",
                "gdpr",
                "hipaa",
                "personal information",
                "personal data",
            ]
        ):
            domain = "Privacy"

        elif any(
            keyword in normalized_text
            for keyword in [
                "security",
                "breach",
                "encrypt",
                "encryption",
                "vulnerability",
                "patch",
            ]
        ):
            domain = "Security"

        elif any(
            keyword in normalized_text
            for keyword in [
                "termination",
                "renewal",
                "expiry",
                "expiration",
            ]
        ):
            domain = "Operational"

        elif any(
            keyword in normalized_text
            for keyword in [
                "employee",
                "employment",
                "non-compete",
                "personnel",
                "human resources",
            ]
        ):
            domain = "HR"

        elif any(
            keyword in normalized_text
            for keyword in [
                "intellectual property",
                "copyright",
                "trademark",
                "patent",
                "licence",
                "license",
            ]
        ):
            domain = "Intellectual Property"

        elif any(
            keyword in normalized_text
            for keyword in [
                "vendor",
                "supplier",
                "subcontractor",
            ]
        ):
            domain = "Vendor"

        elif any(
            keyword in normalized_text
            for keyword in [
                "compliance",
                "regulatory",
                "audit",
                "anti-bribery",
                "sanctions",
            ]
        ):
            domain = "Compliance"

        elif any(
            keyword in normalized_text
            for keyword in [
                "environmental",
                "emissions",
                "pollution",
                "waste disposal",
            ]
        ):
            domain = "Environmental"

        risk_level = "Low"

        high_risk_keywords = [
            "indemnify",
            "indemnification",
            "penalty",
            "unlimited liability",
            "liquidated damages",
            "warranty disclaimer",
            "sole discretion",
        ]

        medium_risk_keywords = [
            "breach",
            "termination",
            "fine",
            "forfeit",
            "late payment",
            "suspend",
            "automatic renewal",
        ]

        matched_high_risk = [
            keyword
            for keyword in high_risk_keywords
            if keyword in normalized_text
        ]

        matched_medium_risk = [
            keyword
            for keyword in medium_risk_keywords
            if keyword in normalized_text
        ]

        reasons: List[str] = []

        if matched_high_risk:
            risk_level = "High"

            reasons.append(
                "Contains potentially high-risk language: "
                + ", ".join(matched_high_risk)
            )

        elif matched_medium_risk:
            risk_level = "Medium"

            reasons.append(
                "Contains enforcement, termination, or "
                "financial-risk language: "
                + ", ".join(matched_medium_risk)
            )

        else:
            reasons.append(
                "No strong high-risk keywords were detected"
            )

        key_metadata = dict(metadata)

        if re.search(
            r"\b(expires|expiry|expiration)\b",
            normalized_text,
        ):
            key_metadata["expiry_signal"] = True

        if re.search(
            r"\b\d+\s*"
            r"(day|days|month|months|year|years)\b",
            normalized_text,
        ):
            key_metadata["duration_signal"] = True

        if re.search(
            r"\b(invoice|payment|fee|price|cost)\b",
            normalized_text,
        ):
            key_metadata["financial_signal"] = True

        return {
            "domain": domain,
            "risk_level": risk_level,
            "reasons": reasons,
            "key_metadata": key_metadata,
        }