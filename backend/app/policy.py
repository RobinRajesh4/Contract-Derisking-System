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
    return hits >= max(2, len(kws)//3)


def apply_policy(clauses: List[Dict[str, Any]], policy: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    domain_map = {}
    for d in policy.get("domains", []):
        domain_map[d.get("domain_name", "")] = d

    total_score = 0
    non_compliant_items: List[str] = []

    enriched: List[Dict[str, Any]] = []

    for c in clauses:
        text = c.get("text", "")
        domain = (c.get("classification", {}).get("domain") or c.get("metadata", {}).get("domain") or "Other")
        dspec = domain_map.get(domain) or {}
        mps = dspec.get("micro_policies", [])

        matched: List[str] = []
        violations: List[Dict[str, Any]] = []
        score = 0

        for mp in mps:
            pid = mp.get("id")
            check = mp.get("check", "")
            weight = int(mp.get("risk_weight", 0))
            ok = _policy_match(text, check)
            if ok:
                matched.append(pid)
            else:
                # treat as violation and accumulate risk score
                violations.append({"id": pid, "name": mp.get("name"), "risk_weight": weight})
                score += weight

        total_score += score
        if violations:
            non_compliant_items.extend(v.get("id") for v in violations)

        enriched.append({
            **c,
            "policy": {
                "domain": domain,
                "matched_policies": matched,
                "violations": violations,
                "policy_score": score,
            }
        })

    risk_threshold = int(policy.get("risk_threshold", 0))
    summary = {
        "policy_id": policy.get("policy_id"),
        "total_policy_score": total_score,
        "is_above_threshold": total_score >= risk_threshold if risk_threshold else False,
        "non_compliant_items": non_compliant_items,
        "domains_covered": len(policy.get("domains", [])),
    }
    return enriched, summary
