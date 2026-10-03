"""Opt-in datasource and column access policy for database chat.

This is intentionally a small enforcement boundary. It complements DB-GPT's
API-key authentication; enterprise user/role and row-level policies can be
plugged in later without changing SQL generation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SqlAccessPolicy:
    allowed_datasources: frozenset[str] = frozenset()
    denied_columns: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls) -> "SqlAccessPolicy":
        allowed = frozenset(
            item.strip().casefold()
            for item in os.getenv("DBGPT_ALLOWED_DATASOURCES", "").split(",")
            if item.strip()
        )
        denied = frozenset(
            item.strip().casefold()
            for item in os.getenv("DBGPT_DENIED_COLUMNS", "").split(",")
            if item.strip()
        )
        return cls(allowed_datasources=allowed, denied_columns=denied)

    def check(self, datasource: str, sql: str) -> None:
        source = str(datasource).casefold()
        if self.allowed_datasources and source not in self.allowed_datasources:
            raise PermissionError(f"Datasource is not allowed: {datasource}")
        if self.denied_columns:
            identifiers = {
                value.casefold()
                for value in re.findall(r"[`\"\[]?([A-Za-z_][\w]*)[`\"\]]?", sql)
            }
            blocked = sorted(identifiers & self.denied_columns)
            if blocked:
                raise PermissionError("Restricted column(s): " + ", ".join(blocked))
