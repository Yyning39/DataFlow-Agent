"""Run the fixed DB-GPT Text-to-SQL baseline set.

Usage (with a running DB-GPT webserver)::

    python tools/dbgpt_baseline_eval.py --model deepseek-v4-flash

The evaluator uses only the standard library so it can run inside the project
environment without adding development dependencies. It prints per-case SQL,
data, latency, and aggregate conversion/execution/correctness metrics.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class Case:
    case_id: str
    question: str
    checker: Callable[[List[Dict[str, Any]]], bool]


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_row(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    return data[0] if data else {}


def _has_value(data: List[Dict[str, Any]], expected: float, tolerance: float = 0.01) -> bool:
    return any(
        number is not None and abs(number - expected) <= tolerance
        for row in data
        for number in (_number(value) for value in row.values())
    )


CASES = [
    Case("B01", "How many rows are in the Walmart sales table?", lambda d: _has_value(d, 6435, 0)),
    Case("B02", "What is the total Weekly_Sales?", lambda d: _has_value(d, 6737218987.11)),
    Case("B03", "What is the average Weekly_Sales?", lambda d: _has_value(d, 1046964.8775617715)),
    Case("B04", "How many stores are in the dataset?", lambda d: _has_value(d, 45, 0)),
    Case("B05", "Which store has the highest total Weekly_Sales?", lambda d: _has_value(d, 20, 0) and _has_value(d, 301397792.46)),
    Case(
        "B06",
        "What are the total Weekly_Sales for holidays versus non-holidays?",
        lambda d: _has_value(d, 505299551.56) and _has_value(d, 6231919435.55),
    ),
    Case(
        "B07",
        "What is the date range in the dataset?",
        lambda d: {str(v) for row in d for v in row.values()}
        >= {"01-04-2011", "31-12-2010"},
    ),
]


def _extract_payload(raw: str) -> Optional[Dict[str, Any]]:
    contents: List[str] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
            content = event.get("choices", [{}])[0].get("message", {}).get("content")
            if content:
                contents.append(content)
        except (ValueError, TypeError, IndexError):
            continue
    if not contents:
        return None
    match = re.search(r'<chart-view content="([^"]+)"', contents[-1])
    if not match:
        return None
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def run_case(base_url: str, model: str, case: Case) -> Dict[str, Any]:
    body = {
        "user_input": case.question,
        "chat_mode": "chat_with_db_execute",
        "select_param": "Walmart_Sales",
        "model_name": model,
        "incremental": False,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        raw = urllib.request.urlopen(request, timeout=180).read().decode(
            "utf-8", "replace"
        )
        payload = _extract_payload(raw)
        sql = payload.get("sql") if payload else None
        data = payload.get("data", []) if payload else []
        return {
            "id": case.case_id,
            "question": case.question,
            "seconds": round(time.perf_counter() - started, 2),
            "sql": sql,
            "data": data,
            "sql_generated": bool(sql and re.match(r"\s*(SELECT|WITH)\b", sql, re.I)),
            "execution_success": bool(payload and "data" in payload),
            "result_correct": bool(payload and case.checker(data)),
            "error": None,
        }
    except Exception as error:  # noqa: BLE001 - benchmark records failures
        return {
            "id": case.case_id,
            "question": case.question,
            "seconds": round(time.perf_counter() - started, 2),
            "sql": None,
            "data": [],
            "sql_generated": False,
            "execution_success": False,
            "result_correct": False,
            "error": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5670")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--json-out", default=None, help="Write complete results to a JSON file")
    parser.add_argument(
        "--case-ids",
        default=None,
        help="Optional comma-separated case IDs, for example B02",
    )
    args = parser.parse_args()

    selected_ids = (
        {item.strip().upper() for item in args.case_ids.split(",") if item.strip()}
        if args.case_ids
        else None
    )
    selected_cases = [case for case in CASES if selected_ids is None or case.case_id in selected_ids]
    if not selected_cases:
        raise SystemExit("No matching case IDs")
    results = [run_case(args.url, args.model, case) for case in selected_cases]
    total = len(results)
    avg_seconds = sum(item["seconds"] for item in results) / total
    print("id | sql | execute | correct | seconds | sql")
    for item in results:
        print(
            f"{item['id']} | {int(item['sql_generated'])} | "
            f"{int(item['execution_success'])} | {int(item['result_correct'])} | "
            f"{item['seconds']:.2f} | {item['sql'] or item['error']}"
        )
    print()
    print(f"SQL conversion rate: {sum(x['sql_generated'] for x in results)}/{total}")
    print(f"Execution success rate: {sum(x['execution_success'] for x in results)}/{total}")
    print(f"Result correctness: {sum(x['result_correct'] for x in results)}/{total}")
    print(f"Average latency: {avg_seconds:.2f}s")
    payload = {"model": args.model, "results": results}
    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {output_path}")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
