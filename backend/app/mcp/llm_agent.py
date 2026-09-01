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


def remove_markdown_fences(content: str) -> str:
    """
    Remove Markdown code fences surrounding an LLM response.
    """

    cleaned = content.strip()

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