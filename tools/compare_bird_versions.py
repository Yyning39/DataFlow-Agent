"""Compare completed BIRD evaluator outputs under one experimental contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


METRICS = (
    "sql_conversion_rate",
    "execution_success_rate",
    "result_correctness",
    "average_latency",
    "p50_latency",
    "p95_latency",
    "average_model_generation_seconds",
    "p95_model_generation_seconds",
    "model_timeout_rate",
    "runtime_configuration_mismatch_rate",
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("summary"):
        raise ValueError(f"Missing summary in {path}")
    return payload


def compare(files: dict[str, Path]) -> tuple[dict[str, Any], str]:
    payloads = {version: _load(path) for version, path in files.items()}
    models = {payload.get("model") for payload in payloads.values()}
    manifests = {payload.get("manifest") for payload in payloads.values()}
    contracts = {version: payload.get("experiment_contract") for version, payload in payloads.items()}
    # A strict A/B comparison needs the same benchmark content, model endpoint,
    # provider and timeout. Older result files without a contract are
    # intentionally considered incompatible rather than silently compared.
    contract_keys = (
        "model",
        "manifest_sha256",
        "case_timeout",
        "temperature",
        "provider",
        "api_base",
    )
    normalized = {
        version: tuple((contract or {}).get(key) for key in contract_keys)
        for version, contract in contracts.items()
    }
    complete_contracts = all(
        isinstance(contract, dict)
        and all(key in contract for key in contract_keys)
        and all(contract.get(key) not in (None, "") for key in ("model", "manifest_sha256", "provider", "api_base"))
        and contract.get("case_timeout") is not None
        for contract in contracts.values()
    )
    runtime_mismatch = {
        version: payload["summary"].get("runtime_configuration_mismatch_rate")
        for version, payload in payloads.items()
    }
    compatible = (
        complete_contracts
        and len(set(normalized.values())) == 1
        and all(value == 0 for value in runtime_mismatch.values())
    )
    contract_differences = {}
    if not compatible:
        for key in contract_keys:
            values = {version: (contracts[version] or {}).get(key) for version in payloads}
            if len(set(str(value) for value in values.values())) > 1 or any(value is None for value in values.values()):
                contract_differences[key] = values
    rows = []
    for version, payload in payloads.items():
        summary = payload["summary"]
        rows.append({"version": version, **{metric: summary.get(metric) for metric in METRICS}})
    report = {
        "compatible": compatible,
        "models": sorted(str(value) for value in models),
        "manifests": sorted(str(value) for value in manifests),
        "experiment_contracts": contracts,
        "contract_differences": contract_differences,
        "versions": rows,
        "warning": None
        if compatible
        else "实验契约不一致/缺失，或服务实际运行能力与目标版本不匹配；结果只能作为工程参考，不能称为严格 A/B。",
    }
    header = ["版本", "SQL 转化率", "执行成功率", "结果正确率", "平均延迟", "P50", "P95", "模型生成均值", "模型生成 P95", "超时率", "配置不匹配率"]
    lines = ["# BIRD v2/v3/v4 对比", "", "| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        values = [
            row["version"],
            f"{row['sql_conversion_rate']:.1%}" if row["sql_conversion_rate"] is not None else "-",
            f"{row['execution_success_rate']:.1%}" if row["execution_success_rate"] is not None else "-",
            f"{row['result_correctness']:.1%}" if row["result_correctness"] is not None else "-",
            f"{row['average_latency']:.2f}s" if row["average_latency"] is not None else "-",
            f"{row['p50_latency']:.2f}s" if row["p50_latency"] is not None else "-",
            f"{row['p95_latency']:.2f}s" if row["p95_latency"] is not None else "-",
            f"{row['average_model_generation_seconds']:.2f}s" if row["average_model_generation_seconds"] is not None else "-",
            f"{row['p95_model_generation_seconds']:.2f}s" if row["p95_model_generation_seconds"] is not None else "-",
            f"{row['model_timeout_rate']:.1%}" if row["model_timeout_rate"] is not None else "-",
            f"{row['runtime_configuration_mismatch_rate']:.1%}" if row["runtime_configuration_mismatch_rate"] is not None else "-",
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(["", f"严格条件：{'通过' if compatible else '不通过'}。"])
    if report["warning"]:
        lines.extend(["", f"> {report['warning']}"])
    return report, "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--v3", type=Path, required=True)
    parser.add_argument("--v4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, markdown = compare({"v2": args.v2, "v3": args.v3, "v4": args.v4})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    args.output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(markdown)


if __name__ == "__main__":
    main()
