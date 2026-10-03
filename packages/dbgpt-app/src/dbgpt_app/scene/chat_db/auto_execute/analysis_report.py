"""Deterministic analysis report generation for database chat results.

The report is deliberately model-free: the SQL and result frame are the
source of truth, so the generated summary cannot invent a number that is not
present in the query result.  An LLM can later add narrative on top of this
structured artifact without changing the data contract.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def _format_value(value: Any) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def build_analysis_report(
    question: str,
    sql: str,
    dataframe: pd.DataFrame,
    execution_trace: Optional[Any] = None,
    max_preview_rows: int = 10,
) -> str:
    """Build a compact Markdown report from an executed SQL result.

    The function only derives descriptive statistics from ``dataframe`` and
    includes the exact SQL for auditability.  It is safe to call for empty
    results and for non-numeric result sets.
    """

    frame = dataframe if isinstance(dataframe, pd.DataFrame) else pd.DataFrame(dataframe)
    lines = ["# 自动分析报告", "", f"**问题**：{question or '-'}", "", "## 查询口径", "", "```sql", sql.strip(), "```", ""]
    lines.extend(["## 结果概览", "", f"- 返回行数：{len(frame)}", f"- 返回列数：{len(frame.columns)}"])

    numeric = frame.select_dtypes(include="number")
    if not numeric.empty:
        lines.extend(["", "### 数值摘要", "", "| 字段 | 最小值 | 平均值 | 最大值 |", "|---|---:|---:|---:|"])
        for column in numeric.columns:
            series = numeric[column].dropna()
            if series.empty:
                continue
            lines.append(
                f"| {column} | {_format_value(series.min())} | "
                f"{_format_value(series.mean())} | {_format_value(series.max())} |"
            )

    lines.extend(["", "## 数据预览", ""])
    if frame.empty:
        lines.append("查询未返回数据。")
    else:
        preview = frame.head(max_preview_rows)
        lines.append("| " + " | ".join(str(column) for column in preview.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in preview.columns) + " |")
        for _, row in preview.iterrows():
            lines.append("| " + " | ".join(_format_value(value) for value in row.tolist()) + " |")
        if len(frame) > max_preview_rows:
            lines.extend(["", f"> 仅展示前 {max_preview_rows} 行，完整结果仍由查询结果集提供。"])

    if execution_trace is not None:
        lines.extend(["", "## 执行追踪", ""])
        for field in (
            "attempts",
            "repaired",
            "executed_sql",
            "structure",
            "error",
            "error_type",
            "validation_warnings",
            "result_row_count",
            "result_column_count",
        ):
            if hasattr(execution_trace, field):
                value = getattr(execution_trace, field)
                if value is not None:
                    lines.append(f"- {field}：{value}")

    lines.extend(["", "## 说明", "", "本报告由 SQL 执行结果自动生成；业务结论应结合指标定义和数据时间范围复核。"])
    return "\n".join(lines)
