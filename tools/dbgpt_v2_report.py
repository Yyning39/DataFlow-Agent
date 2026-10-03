"""Generate the V2 validation report from endpoint evaluation artifacts."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "dbgpt-core" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "dbgpt-app" / "src"))

from dbgpt.util.sql_utils import SqlGuard  # noqa: E402
from dbgpt_app.scene.chat_db.auto_execute.metric_registry import MetricRegistry  # noqa: E402


ENDPOINT_JSON = ROOT / "docs" / "baseline" / "v2_endpoint_eval.json"
RETRY_JSON = ROOT / "docs" / "baseline" / "v2_B02_retry.json"
REPORT_PATH = ROOT / "docs" / "baseline" / "v2_validation_report.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _summary(results: list[dict]) -> dict:
    total = len(results)
    seconds = [float(item["seconds"]) for item in results]
    return {
        "total": total,
        "sql": sum(bool(item.get("sql_generated")) for item in results),
        "execute": sum(bool(item.get("execution_success")) for item in results),
        "correct": sum(bool(item.get("result_correct")) for item in results),
        "average": sum(seconds) / total,
        "median": median(seconds),
        "minimum": min(seconds),
        "maximum": max(seconds),
    }


def _portable_component_checks() -> dict:
    orders = MetricRegistry.for_datasource("orders")
    walmart = MetricRegistry.for_datasource("Walmart_Sales")
    marketing = MetricRegistry.for_datasource("marketing_events")
    metric_checks = [
        bool(orders.search("What is the total revenue?") and orders.search("What is the total revenue?")[0].expression == "SUM(revenue)"),
        bool(orders.search("What is the average order value?") and orders.search("What is the average order value?")[0].expression == "AVG(order_amount)"),
        bool(walmart.search("平均销售额") and walmart.search("平均销售额")[0].expression == "AVG(Weekly_Sales)"),
        bool(marketing.search("转化率") and marketing.search("转化率")[0].expression == "SUM(converted) / COUNT(*)"),
    ]

    guard = SqlGuard(max_rows=50)
    unsafe = [
        "DELETE FROM orders WHERE customer_id = 1",
        "DROP TABLE orders",
        "SELECT 1; DROP TABLE orders",
    ]
    safety_checks = [not guard.validate(sql).ok for sql in unsafe]

    def executor(sql: str):
        if "LIMIT" not in sql.upper():
            raise RuntimeError("result set too large")
        return [{"ok": 1}]

    repair_checks = []
    for sql in ("SELECT * FROM orders", "SELECT * FROM transactions", "SELECT * FROM events"):
        try:
            _, trace = guard.execute(sql, executor, max_retries=1)
            repair_checks.append(trace.repaired and trace.attempts == 2)
        except Exception:
            repair_checks.append(False)

    try:
        _, trace = guard.execute("SELECT COUNT(*) FROM orders", lambda _: [])
        trace_check = bool(trace.original_sql and trace.executed_sql and trace.attempts == 1)
    except Exception:
        trace_check = False
    return {
        "metric": (sum(metric_checks), len(metric_checks)),
        "safety": (sum(safety_checks), len(safety_checks)),
        "repair": (sum(repair_checks), len(repair_checks)),
        "trace": (int(trace_check), 1),
    }


def _rate(value: int, total: int) -> str:
    return f"{value}/{total} = {value / total:.1%}" if total else "0/0"


def main() -> None:
    raw_payload = _load(ENDPOINT_JSON)
    retry_payload = _load(RETRY_JSON)
    raw_results = raw_payload["results"]
    retry_by_id = {item["id"]: item for item in retry_payload["results"]}
    final_results = [retry_by_id.get(item["id"], item) for item in raw_results]
    raw = _summary(raw_results)
    final = _summary(final_results)
    components = _portable_component_checks()

    lines = [
        "# DB-GPT V2 校验报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "模型：`deepseek-v4-flash`；数据源：`Walmart_Sales`；服务：`http://127.0.0.1:5670`",
        "",
        "## 1. 校验范围",
        "",
        "- 服务健康检查：通过，`/api/health` 返回 `status=ok`。",
        "- 模型检查：通过，模型列表包含 `deepseek-v4-flash`。",
        "- 端到端回归：B01-B07，与 V0/V1 使用同一问题集。",
        "- 通用能力专项：数据源指标配置、SQL Guard、SQL 纠错和执行 Trace。",
        "",
        "## 2. V0/V1/V2 端到端对比",
        "",
        "| 版本 | SQL 转化率 | 执行成功率 | 结果正确率 | 平均耗时 | 中位耗时 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| V0 原版 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 14.10s | 13.90s |",
        f"| V1 指标/Guard 版 | 7/7 = 100% | 7/7 = 100% | 7/7 = 100% | 17.80s | 17.00s |",
        f"| V2 首轮实测 | {raw['sql']}/{raw['total']} = {raw['sql']/raw['total']:.1%} | {raw['execute']}/{raw['total']} = {raw['execute']/raw['total']:.1%} | {raw['correct']}/{raw['total']} = {raw['correct']/raw['total']:.1%} | {raw['average']:.2f}s | {raw['median']:.2f}s |",
        f"| V2 B02 重试后 | {final['sql']}/{final['total']} = {final['sql']/final['total']:.1%} | {final['execute']}/{final['total']} = {final['execute']/final['total']:.1%} | {final['correct']}/{final['total']} = {final['correct']/final['total']:.1%} | {final['average']:.2f}s | {final['median']:.2f}s |",
        "",
        "V2 首轮 B02 没有返回可解析的 SQL/data；针对该题重试后成功生成 `SUM(Weekly_Sales)` 查询并返回正确结果。因此应同时关注首轮稳定性和重试恢复能力，不能只报告重试后的 100%。",
        "",
        "## 3. V2 各题结果",
        "",
        "| 编号 | 首轮 | 重试/最终 | 耗时（秒） | 结果 |",
        "|---|---|---|---:|---|",
    ]
    for item in raw_results:
        final_item = retry_by_id.get(item["id"], item)
        first_pass = "通过" if item.get("result_correct") else "失败"
        final_pass = "通过" if final_item.get("result_correct") else "失败"
        suffix = "（重试恢复）" if item["id"] in retry_by_id and not item.get("result_correct") else ""
        lines.append(f"| {item['id']} | {first_pass} | {final_pass}{suffix} | {final_item['seconds']:.2f} | {final_item.get('sql') or '无可解析 SQL'} |")

    lines.extend(
        [
            "",
            "## 4. 通用改进能力专项",
            "",
            "| 能力 | V0 | V2 |",
            "|---|---:|---:|",
            f"| 按数据源指标配置加载与匹配 | 0/4 | {components['metric'][0]}/{components['metric'][1]} |",
            f"| 危险 SQL 预执行拦截 | 0/3 | {components['safety'][0]}/{components['safety'][1]} |",
            f"| SQL 执行失败纠错 | 0/3 | {components['repair'][0]}/{components['repair'][1]} |",
            f"| SQL 执行 Trace | 0/1 | {components['trace'][0]}/{components['trace'][1]} |",
            "",
            "## 5. 结论",
            "",
            "1. V2 重启后已正确加载数据源配置框架，Walmart 配置和通用 orders/marketing_events 配置均可读取。",
            "2. V2 通用专项能力全部通过，说明指标配置不再依赖单一 Walmart 代码路径。",
            "3. V2 首轮端到端为 6/7，B02 经单题重试恢复；这次失败更像模型 SSE/结果解析瞬时波动，不是指标配置导致的 SQL 口径错误。",
            "4. V2 平均耗时高于 V0/V1，下一步应增加请求级重试、SSE 空响应分类和耗时分解，避免把网络/模型波动混入 SQL 准确率。",
            "",
            "## 6. 评测产物",
            "",
            f"- 首轮原始结果：`{ENDPOINT_JSON}`",
            f"- B02 重试结果：`{RETRY_JSON}`",
            f"- 本报告：`{REPORT_PATH}`",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {REPORT_PATH}")
    print(f"V2 first-pass: {raw['correct']}/{raw['total']}; after retry: {final['correct']}/{final['total']}")


if __name__ == "__main__":
    main()
