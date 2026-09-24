"""
Ask the running backend real questions and check the answers.

1. Start the backend (python run_server.py).
2. Edit eval_questions.json: every expect_contains value must be a fact
   you checked yourself in the documents. Entries still marked TODO are
   skipped.
3. From the backend folder:  python scripts/eval_chat.py

Run it after any change to models, prompts, parsing or settings. A
question that passed before and fails now is a regression.
"""
import json
import os
import sys

import requests

BASE = os.environ.get("PACT_API", "http://127.0.0.1:8001")
HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    with open(os.path.join(HERE, "eval_questions.json"), encoding="utf-8") as f:
        cases = json.load(f)

    passed = failed = skipped = 0
    for case in cases:
        expected = case.get("expect_contains", [])
        if any("TODO" in e for e in expected):
            skipped += 1
            print(f"SKIP  {case['question']}  (expected answer not filled in yet)")
            continue
        try:
            r = requests.post(f"{BASE}/chat", json={"message": case["question"]}, timeout=600)
            data = r.json()
        except Exception as error:
            failed += 1
            print(f"FAIL  {case['question']}\n      request failed: {error}")
            continue
        reply = data.get("reply", "")
        problems = [f"missing '{e}'" for e in expected if e.lower() not in reply.lower()]
        route = data.get("route")
        if case.get("expect_route") and route != case["expect_route"]:
            problems.append(f"route was {route}, expected {case['expect_route']}")
        if problems:
            failed += 1
            print(f"FAIL  {case['question']}\n      " + "; ".join(problems))
            print("      reply: " + reply.replace("\n", " ")[:300])
        else:
            passed += 1
            print(f"PASS  {case['question']}")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
