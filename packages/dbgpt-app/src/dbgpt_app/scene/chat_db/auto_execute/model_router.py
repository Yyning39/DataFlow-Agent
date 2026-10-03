"""Opt-in model routing for database chat.

Routing is disabled by default. Deployments must register both models and set
``DBGPT_MODEL_ROUTING=true`` before a request can be moved to the fast or
accurate tier.
"""

from __future__ import annotations

import os
from typing import Optional


def choose_model(question: str, requested_model: Optional[str]) -> tuple[str, str]:
    """Return ``(model, reason)`` using conservative query complexity rules."""

    requested = requested_model or os.getenv("LLM_MODEL_NAME") or ""
    enabled = os.getenv("DBGPT_MODEL_ROUTING", "false").casefold() == "true"
    fast_model = os.getenv("DBGPT_FAST_MODEL", "deepseek-chat")
    accurate_model = os.getenv("DBGPT_ACCURATE_MODEL", requested or "deepseek-v4-flash")
    if not enabled:
        return requested, "routing_disabled"
    text = str(question or "").casefold()
    complex_markers = (
        " join ", "group by", "having", "subquery", "nested", "compare",
        "trend", "同比", "环比", "分组", "连接", "嵌套", "比较",
    )
    if len(text) <= 120 and not any(marker in f" {text} " for marker in complex_markers):
        return fast_model, "simple_query_fast_tier"
    return accurate_model, "complex_query_accurate_tier"
