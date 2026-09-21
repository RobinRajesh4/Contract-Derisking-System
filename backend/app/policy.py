import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "policies")
os.makedirs(DATA_DIR, exist_ok=True)


def save_policy(policy: Dict[str, Any]) -> str:
    policy_id = policy.get("policy_id")
    if not policy_id:
        raise ValueError("policy.policy_id is required")
    path = os.path.join(DATA_DIR, f"{policy_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)
    return policy_id


def get_policy(policy_id: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, f"{policy_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_policies() -> List[Dict[str, Any]]:
    res = []
    for name in os.listdir(DATA_DIR):
        if name.lower().endswith(".json"):
            with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
                try:
                    res.append(json.load(f))
                except Exception:
                    continue
    return res


# --- simple evaluators -------------------------------------------------------


def _extract_keywords(check_text: str) -> List[str]:
    # crude keyword extraction from check directive
    words = re.findall(r"[A-Za-z]{4,}", check_text or "")
    # de-duplicate and lower
    seen = set()
    keywords = []
    for w in (w.lower() for w in words):
        if w not in seen:
            seen.add(w)
            keywords.append(w)
    return keywords[:8]


def _policy_match(clause_text: str, check_text: str) -> bool:
    # heuristic: if several keywords from the check appear in the clause
    t = (clause_text or "").lower()
    kws = _extract_keywords(check_text)
    if not kws:
        return False
    hits = sum(1 for k in kws if k in t)
    return hits >= max(2, len(kws) // 3)


def apply_policy(
    clauses: List[Dict[str, Any]],
    policy: Dict[str, Any],
    llm: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Evaluate policy compliance at the CONTRACT level, per check - not
    per clause.

    A check (e.g. "Governing Law Preference") belongs to a domain, and
    every clause classified into that domain is a *candidate* to
    satisfy it - but it is only ever a genuine violation if NO clause
    anywhere in the contract satisfies it. The previous approach
    treated every clause that didn't individually satisfy every check
    in its domain as a separate violation, which produced false
    positives whenever a different clause already covered it (e.g. a
    Term clause getting flagged for not specifying governing law, when
    a separate Jurisdiction clause already does - both are Legal
    clauses, but only one of them was ever going to address that
    check). Aggregating per check across the whole domain instead means
    a violation now means what it should: "this requirement is
    genuinely missing from the contract," not "this particular clause
    wasn't about that requirement."

    This still uses the same one-bundled-LLM-call-per-clause evaluation
    as before (no added cost) - it's the aggregation afterward that
    changes.
    """
    domain_map: Dict[str, Dict[str, Any]] = {}
    for d in policy.get("domains", []):
        domain_map[d.get("domain_name", "")] = d

    # Group clause indices by domain.
    clauses_by_domain: Dict[str, List[int]] = {}
    for idx, c in enumerate(clauses):
        domain = (
            c.get("classification", {}).get("domain")
            or c.get("metadata", {}).get("domain")
            or "Other"
        )
        clauses_by_domain.setdefault(domain, []).append(idx)

    # Step 1: evaluate every clause against its own domain's checks -
    # same per-clause bundled LLM call as before. Store every result
    # keyed by (clause index, check id) so it can be aggregated
    # per-check afterward instead of per-clause.
    clause_check_results: Dict[int, Dict[str, Dict[str, Any]]] = {}

    for domain, idxs in clauses_by_domain.items():
        dspec = domain_map.get(domain) or {}
        mps = dspec.get("micro_policies", [])
        if not mps:
            continue

        for idx in idxs:
            text = clauses[idx].get("text", "")

            llm_results: Optional[List[Optional[Dict[str, Any]]]] = None
            if llm is not None:
                try:
                    llm_results = llm.evaluate_policy_compliance(text, mps)
                except Exception as error:
                    print(f"Policy compliance LLM call raised: {error}")
                    llm_results = None

            per_check: Dict[str, Dict[str, Any]] = {}
            for mp_idx, mp in enumerate(mps):
                pid = mp.get("id")
                check = mp.get("check", "")
                llm_entry = llm_results[mp_idx] if llm_results is not None else None

                if llm_entry is not None:
                    per_check[pid] = {
                        "matched": bool(llm_entry.get("matched")),
                        "reason": llm_entry.get("reason", ""),
                        "method": "llm",
                    }
                else:
                    ok = _policy_match(text, check)
                    per_check[pid] = {
                        "matched": ok,
                        "reason": (
                            "Evaluated by keyword fallback (LLM omitted this check)."
                            if llm_results is not None
                            else "Evaluated by keyword fallback (no LLM available)."
                        ),
                        "method": "keyword",
                    }

            clause_check_results[idx] = per_check

    # Step 2: aggregate per check, across every clause in its domain -
    # satisfied if ANY clause in that domain satisfies it.
    missing_requirements: List[Dict[str, Any]] = []
    non_compliant_items: List[str] = []
    total_score = 0

    for domain, dspec in domain_map.items():
        mps = dspec.get("micro_policies", [])
        idxs = clauses_by_domain.get(domain, [])

        # A domain the contract has NO clauses in at all is only a
        # genuine gap if the policy explicitly says this domain is
        # required for every contract it's applied to (opt-in,
        # defaults to False). Otherwise, a domain with zero clauses
        # just means this contract was never going to touch it - e.g.
        # a personal financing agreement has no reason to contain a
        # PCI-DSS or ESG-reporting clause, so treating that domain's
        # checks as "missing requirements" would be flagging the
        # contract for not being a type of contract it never claimed
        # to be. Domains where the contract DOES have clauses are
        # unaffected by this - those checks are still evaluated
        # normally below, regardless of the required flag.
        domain_is_required = bool(dspec.get("required", False))
        if not idxs and not domain_is_required:
            continue

        for mp in mps:
            pid = mp.get("id")
            name = mp.get("name")
            weight = int(mp.get("risk_weight", 0))

            satisfied = False
            satisfied_by: List[Dict[str, Any]] = []
            fallback_reason = ""

            if not idxs:
                fallback_reason = (
                    f"No clause in this contract was classified under "
                    f"the '{domain}' domain."
                )
            else:
                for idx in idxs:
                    result = clause_check_results.get(idx, {}).get(pid)
                    if result and result.get("matched"):
                        satisfied = True
                        satisfied_by.append(
                            {
                                "clause_id": clauses[idx].get("id"),
                                "reason": result.get("reason", ""),
                            }
                        )
                if not satisfied:
                    for idx in idxs:
                        result = clause_check_results.get(idx, {}).get(pid)
                        if result and result.get("reason"):
                            fallback_reason = result["reason"]
                            break

            if satisfied:
                continue

            total_score += weight
            non_compliant_items.append(pid)
            missing_requirements.append(
                {
                    "id": pid,
                    "name": name,
                    "domain": domain,
                    "risk_weight": weight,
                    "reason": fallback_reason,
                }
            )

    # Step 3: build per-clause info. A clause still usefully shows
    # which checks IT satisfies (that's real, clause-specific
    # information worth surfacing) - but it no longer carries
    # "violations," since failing to address a check that was never
    # its job wasn't a real violation. Genuine violations (nothing in
    # the whole contract satisfies a required check) live in
    # policy_summary.missing_requirements instead, since they're a
    # contract-level fact, not a clause-level one.
    enriched: List[Dict[str, Any]] = []
    for idx, c in enumerate(clauses):
        domain = (
            c.get("classification", {}).get("domain")
            or c.get("metadata", {}).get("domain")
            or "Other"
        )
        per_check = clause_check_results.get(idx, {})
        matched_here = [pid for pid, r in per_check.items() if r.get("matched")]

        enriched.append(
            {
                **c,
                "policy": {
                    "domain": domain,
                    "matched_policies": matched_here,
                    "violations": [],
                },
            }
        )

    risk_threshold = int(policy.get("risk_threshold", 0))
    summary = {
        "policy_id": policy.get("policy_id"),
        "total_policy_score": total_score,
        "is_above_threshold": (
            total_score >= risk_threshold if risk_threshold else False
        ),
        "non_compliant_items": non_compliant_items,
        "missing_requirements": missing_requirements,
        "domains_covered": len(policy.get("domains", [])),
    }
    return enriched, summary