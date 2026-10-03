"""Run DB-GPT against a public BIRD Mini-Dev SQLite subset.

The benchmark questions and gold SQL come directly from the downloaded public
manifest. Expected results are computed locally with sqlite3, so evaluation is
execution-based rather than hand-written answer matching.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


def _post_json(url: str, body: dict, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _database_exists(base_url: str, db_name: str) -> bool:
    """Avoid re-registering the same database on repeated benchmark runs."""
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/api/v1/chat/db/list?db_name={urllib.parse.quote(db_name)}",
            timeout=20,
        ) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        rows = payload.get("data") or []
        return any(row.get("db_name") == db_name for row in rows)
    except Exception:
        return False


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
    # A streaming response can emit a complete chart-view and then append a
    # natural-language tail. Search backwards for the last valid chart-view
    # instead of assuming the final event contains the structured payload.
    for content in reversed(contents):
        matches = re.findall(r'<chart-view content="([^"]+)"', content)
        for encoded in reversed(matches):
            try:
                return json.loads(html.unescape(encoded))
            except json.JSONDecodeError:
                continue
    return None


def _stream_stats(raw: str) -> Dict[str, Any]:
    """Extract provider usage and optionally estimate cost.

    DeepSeek-compatible gateways do not always forward ``usage`` on streaming
    responses.  Token estimates are therefore retained for relative latency /
    verbosity comparisons only.  A dollar estimate is emitted only when the
    caller supplies an output price through ``DBGPT_OUTPUT_PRICE_PER_MILLION``;
    this prevents the evaluator from presenting stale vendor prices as a bill.
    """

    last_content = ""
    usage: Dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
        except (ValueError, TypeError):
            continue
        event_usage = event.get("usage")
        if isinstance(event_usage, dict) and event_usage:
            usage = event_usage
        content = event.get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(content, str) and content and len(content) >= len(last_content):
            # The bridge emits cumulative prefixes; retain the final prefix so
            # output tokens are not counted once per streaming chunk.
            last_content = content
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    estimated_output_tokens = (len(last_content) + 3) // 4 if last_content else 0
    output_tokens = int(output_tokens) if isinstance(output_tokens, (int, float)) else estimated_output_tokens
    input_tokens = int(input_tokens) if isinstance(input_tokens, (int, float)) else None
    cost = None
    try:
        output_price = float(os.getenv("DBGPT_OUTPUT_PRICE_PER_MILLION", ""))
        input_price = float(os.getenv("DBGPT_INPUT_PRICE_PER_MILLION", ""))
        cost = output_tokens * output_price / 1_000_000
        if input_tokens is not None:
            cost += input_tokens * input_price / 1_000_000
        elif input_price:
            # Input tokens are not observable, so do not report a partial bill.
            cost = None
    except (TypeError, ValueError):
        cost = None
    return {
        "provider_usage": usage,
        "provider_input_tokens": input_tokens,
        "provider_output_tokens": output_tokens if usage else None,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_cost_usd": round(cost, 8) if cost is not None else None,
        "response_chars": len(raw),
    }


def _normalized_value(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 6)
    return str(value) if value is not None else None


def _rows(db_path: Path, sql: str) -> List[List[Any]]:
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(sql)
        return [list(row) for row in cursor.fetchall()]


def _same_rows(expected: List[List[Any]], actual: List[Dict[str, Any]]) -> bool:
    expected_rows = sorted(
        tuple(_normalized_value(value) for value in row) for row in expected
    )
    actual_rows = sorted(
        tuple(_normalized_value(value) for value in row.values()) for row in actual
    )
    return expected_rows == actual_rows


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    """Compute a small linear-interpolation percentile without numpy."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 4)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 4)


def _expected_runtime_features(variant: str) -> dict[str, bool]:
    """Define the feature ablation expected for each comparison version."""

    return {
        "semantic_enabled": variant != "v2",
        "enhanced_sql_guard": variant in {"v4", "v5", "v6", "v7", "v8", "v9"},
    }


def _add_database(
    base_url: str, db_name: str, db_path: Path, refresh: bool = True
) -> None:
    if _database_exists(base_url, db_name):
        return
    body = {
        "db_type": "sqlite",
        "db_name": db_name,
        "file_path": str(db_path),
        "comment": "BIRD Mini-Dev public benchmark",
    }
    result = _post_json(f"{base_url.rstrip('/')}/api/v1/chat/db/add", body)
    if not result.get("success"):
        raise RuntimeError(f"Cannot add database {db_name}: {result}")
    # Registration triggers summary generation asynchronously on some DB-GPT
    # versions. Refresh explicitly so the first evaluated question never sees
    # an empty schema snapshot.
    if refresh:
        try:
            _post_json(
                f"{base_url.rstrip('/')}/api/v1/chat/db/refresh", body, timeout=180
            )
        except Exception:
            # Older versions may not expose refresh; the chat path can still fall
            # back to direct table introspection.
            pass


def run_case(
    base_url: str,
    model: str,
    db_name: str,
    db_path: Path,
    case: dict,
    case_timeout: int = 180,
    variant: str = "v4",
    temperature: float = 0.0,
) -> dict:
    body = {
        "user_input": case["question"],
        "chat_mode": "chat_with_db_execute",
        "select_param": db_name,
        "model_name": model,
        "temperature": temperature,
        "incremental": False,
    }
    started = time.perf_counter()
    try:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Keep the socket timeout aligned with the per-case wall-clock budget.
        # A hard-coded 30s connect/read timeout can surface as
        # ``OSError: cannot read from timed out object`` before the requested
        # budget and makes a resumable run report a misleading non-timeout.
        with urllib.request.urlopen(request, timeout=max(1, case_timeout)) as response:
            raw_lines = []
            while True:
                if time.perf_counter() - started > case_timeout:
                    raise TimeoutError(
                        f"case exceeded wall-clock timeout ({case_timeout}s)"
                    )
                try:
                    line_bytes = response.readline()
                except (socket.timeout, OSError) as error:
                    if time.perf_counter() - started > case_timeout:
                        raise TimeoutError(
                            f"case exceeded wall-clock timeout ({case_timeout}s)"
                        )
                    # urllib may leave the response object unreadable after a
                    # socket timeout. Retry only while the stream remains
                    # usable; otherwise classify the case as a model timeout
                    # instead of leaking an opaque transport error.
                    if isinstance(error, OSError):
                        raise TimeoutError("model stream became unreadable before case completion")
                    continue
                if not line_bytes:
                    break
                raw_lines.append(line_bytes)
            raw = b"".join(raw_lines).decode("utf-8", "replace")
        payload = _extract_payload(raw)
        stream_stats = _stream_stats(raw)
        sql = payload.get("sql") if payload else None
        data = payload.get("data", []) if payload else []
        timings = payload.get("timings", {}) if payload else {}
        runtime_features = payload.get("runtime_features", {}) if payload else {}
        expected_features = _expected_runtime_features(variant)
        configuration_mismatch = bool(
            payload
            and any(runtime_features.get(key) != value for key, value in expected_features.items())
        )
        expected = _rows(db_path, case["SQL"])
        return {
            "question_id": case["question_id"],
            "db_id": case["db_id"],
            "question": case["question"],
            "gold_sql": case["SQL"],
            "sql": sql,
            "seconds": round(time.perf_counter() - started, 2),
            "schema_seconds": timings.get("schema_seconds"),
            "schema_table_count": timings.get("schema_table_count"),
            "schema_fallback_used": timings.get("schema_fallback_used"),
            "schema_retrieval_empty": timings.get("schema_retrieval_empty"),
            "schema_source_local_complete": timings.get("schema_source_local_complete"),
            "schema_vector_candidate_count": timings.get("schema_vector_candidate_count"),
            "schema_local_hybrid_used": timings.get("schema_local_hybrid_used"),
            "schema_local_hybrid_cache_hit": timings.get("schema_local_hybrid_cache_hit"),
            "schema_local_hybrid_candidate_count": timings.get(
                "schema_local_hybrid_candidate_count"
            ),
            "schema_local_hybrid_top_score": timings.get("schema_local_hybrid_top_score"),
            "schema_local_hybrid_seconds": timings.get("schema_local_hybrid_seconds"),
            "value_hint_seconds": timings.get("value_hint_seconds"),
            "value_hint_table_count": timings.get("value_hint_table_count"),
            "value_hint_column_count": timings.get("value_hint_column_count"),
            "sql_value_warning_count": timings.get("sql_value_warning_count"),
            "model_generation_seconds": timings.get("model_generation_seconds"),
            "model_first_token_seconds": timings.get("model_first_token_seconds"),
            "sql_execution_seconds": timings.get("sql_execution_seconds"),
            "sql_generated": bool(sql and re.match(r"\s*(SELECT|WITH)\b", sql, re.I)),
            "execution_success": bool(payload and "data" in payload),
            "result_correct": bool(payload and _same_rows(expected, data)),
            "result_row_count": payload.get("result_row_count") if payload else None,
            "result_column_count": payload.get("result_column_count") if payload else None,
            "expected_column_count": len(expected[0]) if expected else 0,
            "result_shape_match": bool(
                payload
                and data
                and len(data[0]) == (len(expected[0]) if expected else 0)
            ),
            "error": None,
            "model_timeout": False,
            "runtime_features": runtime_features,
            "configuration_mismatch": configuration_mismatch,
            **stream_stats,
        }
    except Exception as error:  # noqa: BLE001 - benchmark records failures
        return {
            "question_id": case["question_id"],
            "db_id": case["db_id"],
            "question": case["question"],
            "gold_sql": case["SQL"],
            "sql": None,
            "seconds": round(time.perf_counter() - started, 2),
            "schema_seconds": None,
            "schema_table_count": None,
            "schema_fallback_used": None,
            "schema_retrieval_empty": None,
            "schema_source_local_complete": None,
            "schema_vector_candidate_count": None,
            "schema_local_hybrid_used": None,
            "schema_local_hybrid_cache_hit": None,
            "schema_local_hybrid_candidate_count": None,
            "schema_local_hybrid_top_score": None,
            "schema_local_hybrid_seconds": None,
            "value_hint_seconds": None,
            "value_hint_table_count": None,
            "value_hint_column_count": None,
            "sql_value_warning_count": None,
            "model_generation_seconds": None,
            "model_first_token_seconds": None,
            "sql_execution_seconds": None,
            "sql_generated": False,
            "execution_success": False,
            "result_correct": False,
            "result_row_count": None,
            "result_column_count": None,
            "expected_column_count": None,
            "result_shape_match": False,
            "error": f"{type(error).__name__}: {error}",
            "model_timeout": isinstance(error, TimeoutError),
            "runtime_features": {},
            "configuration_mismatch": True,
            "provider_usage": {},
            "provider_input_tokens": None,
            "provider_output_tokens": None,
            "estimated_output_tokens": 0,
            "estimated_cost_usd": None,
            "response_chars": 0,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5670")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature sent to the chat endpoint; keep fixed across versions.",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("LLM_MODEL_PROVIDER") or "proxy/deepseek",
        help="Provider recorded in the experiment contract; pass the same value for every version.",
    )
    parser.add_argument(
        "--api-base",
        dest="api_base",
        default=os.getenv("DEEPSEEK_API_BASE")
        or os.getenv("OPENAI_API_BASE")
        or "https://api.deepseek.com/v1",
        help="Model API base recorded in the experiment contract; pass the same value for every version.",
    )
    parser.add_argument(
        "--variant",
        default="v4",
        choices=("v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9"),
        help="Version label recorded with the run; does not change service configuration.",
    )
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--db-id",
        action="append",
        default=None,
        help="Evaluate only the selected database id(s); repeat for multiple databases.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Unique suffix for database registrations; use a fixed value to repeat a run.",
    )
    parser.add_argument(
        "--reuse-registered",
        action="store_true",
        help="Reuse existing BIRD_<db_id> registrations instead of creating run-suffixed copies.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Skip per-database schema refresh; useful when the chat path can introspect schema directly.",
    )
    parser.add_argument(
        "--case-timeout",
        type=int,
        default=180,
        help="Maximum wall-clock seconds per model case before recording a timeout and continuing.",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="Write results after every case so an interrupted run can resume safely.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from --checkpoint and skip question IDs already recorded.",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest_path = Path(args.manifest)
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    cases = list(manifest["cases"])
    if args.db_id:
        selected = {str(value) for value in args.db_id}
        cases = [case for case in cases if str(case.get("db_id")) in selected]
        if not cases:
            raise ValueError(f"No manifest cases matched --db-id {sorted(selected)}")
    db_paths = {
        db_id: data_root / "dev_databases" / db_id / f"{db_id}.sqlite"
        for db_id in sorted({case["db_id"] for case in cases})
    }
    run_id = args.run_id or f"{int(time.time())}"
    db_names = (
        {db_id: f"BIRD_{db_id}" for db_id in db_paths}
        if args.reuse_registered
        else {db_id: f"BIRD_{db_id}_{run_id}" for db_id in db_paths}
    )
    for db_id, db_path in db_paths.items():
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        _add_database(args.url, db_names[db_id], db_path, refresh=not args.skip_refresh)

    checkpoint_path = Path(args.checkpoint) if args.checkpoint else None
    results = []
    if args.resume and checkpoint_path and checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint.get("manifest") == str(Path(args.manifest))
            and checkpoint.get("model") == args.model
            and checkpoint.get("variant") == args.variant
        ):
            results = list(checkpoint.get("results") or [])
            print(f"resumed={len(results)} cases from {checkpoint_path}")
    completed_ids = {item.get("question_id") for item in results}
    for index, case in enumerate(cases, start=1):
        if case["question_id"] in completed_ids:
            print(f"{index:02d}/{len(cases)} {case['db_id']}#{case['question_id']} skipped (checkpoint)")
            continue
        db_id = case["db_id"]
        item = run_case(
            args.url,
            args.model,
            db_names[db_id],
            db_paths[db_id],
            case,
            case_timeout=args.case_timeout,
            variant=args.variant,
            temperature=args.temperature,
        )
        results.append(item)
        completed_ids.add(case["question_id"])
        print(
            f"{index:02d}/{len(cases)} {item['db_id']}#{item['question_id']} "
            f"sql={int(item['sql_generated'])} execute={int(item['execution_success'])} "
            f"correct={int(item['result_correct'])} {item['seconds']:.2f}s"
        )
        if checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "benchmark": "BIRD Mini-Dev SQLite",
                        "model": args.model,
                        "variant": args.variant,
                        "run_id": run_id,
                        "manifest": str(Path(args.manifest)),
                        "experiment_contract": {
                            "model": args.model,
                            "manifest_sha256": manifest_sha256,
                            "case_timeout": args.case_timeout,
                            "temperature": args.temperature,
                            "provider": args.provider,
                            "api_base": args.api_base,
                        },
                        "expected_runtime_features": _expected_runtime_features(args.variant),
                        "results": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    total = len(results)
    def _avg_timing(name: str):
        values = [item[name] for item in results if item.get(name) is not None]
        return round(sum(values) / len(values), 4) if values else None

    def _timing_percentile(name: str, percentile: float):
        values = [float(item[name]) for item in results if item.get(name) is not None]
        return _percentile(values, percentile)

    payload = {
        "benchmark": "BIRD Mini-Dev SQLite",
        "model": args.model,
        "variant": args.variant,
        "run_id": run_id,
        "manifest": str(Path(args.manifest)),
        "experiment_contract": {
            "model": args.model,
            "manifest_sha256": manifest_sha256,
            "case_timeout": args.case_timeout,
            "temperature": args.temperature,
            "provider": args.provider,
            "api_base": args.api_base,
        },
        "expected_runtime_features": _expected_runtime_features(args.variant),
        "results": results,
        "summary": {
            "total": total,
            "sql_conversion_rate": sum(item["sql_generated"] for item in results) / total,
            "execution_success_rate": sum(item["execution_success"] for item in results) / total,
            "result_correctness": sum(item["result_correct"] for item in results) / total,
            "result_shape_match_rate": sum(
                item.get("result_shape_match", False) for item in results
            ) / total,
            "model_timeout_rate": sum(item.get("model_timeout", False) for item in results) / total,
            "runtime_configuration_mismatch_rate": sum(
                item.get("configuration_mismatch", False) for item in results
            ) / total,
            "average_latency": sum(item["seconds"] for item in results) / total,
            "p50_latency": _timing_percentile("seconds", 0.50),
            "p95_latency": _timing_percentile("seconds", 0.95),
            "average_schema_seconds": _avg_timing("schema_seconds"),
            "schema_fallback_rate": _avg_timing("schema_fallback_used"),
            "schema_retrieval_empty_rate": _avg_timing("schema_retrieval_empty"),
            "schema_local_complete_rate": _avg_timing("schema_source_local_complete"),
            "average_schema_vector_candidate_count": _avg_timing(
                "schema_vector_candidate_count"
            ),
            "schema_local_hybrid_used_rate": _avg_timing("schema_local_hybrid_used"),
            "schema_local_hybrid_cache_hit_rate": _avg_timing(
                "schema_local_hybrid_cache_hit"
            ),
            "average_schema_local_hybrid_candidate_count": _avg_timing(
                "schema_local_hybrid_candidate_count"
            ),
            "average_schema_local_hybrid_top_score": _avg_timing(
                "schema_local_hybrid_top_score"
            ),
            "average_schema_local_hybrid_seconds": _avg_timing(
                "schema_local_hybrid_seconds"
            ),
            "average_value_hint_seconds": _avg_timing("value_hint_seconds"),
            "average_value_hint_table_count": _avg_timing("value_hint_table_count"),
            "average_value_hint_column_count": _avg_timing("value_hint_column_count"),
            "average_sql_value_warning_count": _avg_timing(
                "sql_value_warning_count"
            ),
            "average_model_generation_seconds": _avg_timing(
                "model_generation_seconds"
            ),
            "p50_model_generation_seconds": _timing_percentile(
                "model_generation_seconds", 0.50
            ),
            "p95_model_generation_seconds": _timing_percentile(
                "model_generation_seconds", 0.95
            ),
            "average_model_first_token_seconds": _avg_timing(
                "model_first_token_seconds"
            ),
            "average_sql_execution_seconds": _avg_timing("sql_execution_seconds"),
            "average_estimated_output_tokens": _avg_timing("estimated_output_tokens"),
            "average_provider_output_tokens": _avg_timing("provider_output_tokens"),
            "average_estimated_cost_usd": _avg_timing("estimated_cost_usd"),
            "average_response_chars": _avg_timing("response_chars"),
            "provider_usage_available_rate": round(
                sum(bool(item.get("provider_usage")) for item in results) / total, 4
            ),
            "cost_estimation_available_rate": round(
                sum(item.get("estimated_cost_usd") is not None for item in results) / total,
                4,
            ),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if checkpoint_path and checkpoint_path.resolve() != output.resolve():
        checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    print(f"output={output}")


if __name__ == "__main__":
    main()
