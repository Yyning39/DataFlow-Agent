import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

import sqlparse
from sqlparse import tokens as T


_FORBIDDEN_KEYWORDS = {
    "ALTER",
    "ATTACH",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "GRANT",
    "INSERT",
    "PRAGMA",
    "REINDEX",
    "REPLACE",
    "REVOKE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}


def classify_sql_error(error: Exception | str) -> str:
    """Map connector errors to a small, stable set of retry policies."""

    message = str(error).casefold()
    if any(token in message for token in ("too many", "result set", "max rows", "返回结果过大")):
        return "result_too_large"
    if "no such table" in message or re.search(r"table .+doesn't exist", message):
        return "missing_table"
    if "no such column" in message or "unknown column" in message:
        return "missing_column"
    if "syntax error" in message or "parse error" in message:
        return "syntax_error"
    if "permission" in message or "not authorized" in message:
        return "permission_denied"
    return "unknown"


def remove_sql_comments(sql: str) -> str:
    """Remove SQL comments from the given SQL string."""

    # Remove single-line comments (--) and multi-line comments (/* ... */)
    sql = re.sub(r"--.*?(\n|$)", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def normalize_sql(sql: str) -> str:
    """Normalize model-produced SQL without changing its semantics.

    Models often wrap SQL in a Markdown code fence or append a semicolon. The
    normalized form is used for validation and execution, while the original
    model response remains available for tracing.
    """

    if not isinstance(sql, str):
        return ""
    normalized = sql.strip()
    normalized = re.sub(r"^```(?:sql)?\s*", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s*```$", "", normalized)
    normalized = remove_sql_comments(normalized).strip()
    return normalized.rstrip(";").strip()


def _schema_table_names(schema: Sequence[str]) -> set[str]:
    """Extract table names from connector schema summaries such as t(a,b)."""

    names: set[str] = set()
    for item in schema or ():
        text = str(item[0] if isinstance(item, (tuple, list)) and item else item)
        match = re.match(r"\s*[`\"\[]?([\w.-]+)[`\"\]]?\s*\(", text)
        if match:
            names.add(match.group(1).casefold())
    return names


def _value_catalog_warnings(sql: str, value_catalog: dict) -> list[str]:
    """Return advisory warnings for literals not seen in bounded samples.

    The catalog is intentionally advisory: samples are not exhaustive, so an
    unseen value must never cause a valid query to be rejected. The warning is
    useful for telemetry and for a future interactive clarification step.
    """

    if not value_catalog:
        return []
    aliases = {}
    for table, alias in re.findall(
        r"\b(?:FROM|JOIN)\s+[`\"\[]?([\w.-]+)[`\"\]]?(?:\s+(?:AS\s+)?([\w-]+))?",
        sql,
        flags=re.IGNORECASE,
    ):
        aliases[(alias or table).casefold()] = table
    warnings = []
    # Handle the common equality/IN forms without attempting full SQL parsing.
    pattern = re.compile(
        r"(?:(?P<table>[\w.-]+)\.)?(?P<column>[\w.-]+)\s*(?P<op>=|IN)\s*"
        r"(?P<values>\([^)]*\)|'[^']*'|\"[^\"]*\")",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(sql):
        table = match.group("table")
        if table:
            table = aliases.get(table.casefold(), table)
        if not table:
            continue
        key = f"{table}.{match.group('column')}".casefold()
        known = value_catalog.get(key)
        if not known:
            continue
        raw_values = match.group("values").strip("()")
        literals = re.findall(r"'([^']*)'|\"([^\"]*)\"", raw_values)
        for left, right in literals:
            literal = left or right
            if literal not in known and literal.casefold() not in {
                str(value).casefold() for value in known
            }:
                warnings.append(
                    f"Value {literal!r} for {table}.{match.group('column')} "
                    "was not present in the sampled rows; verify the filter semantics."
                )
    return warnings


def _canonicalize_catalog_values(sql: str, value_catalog: dict) -> str:
    """Normalize case-insensitive literals to values observed in the database."""

    if not value_catalog:
        return sql
    aliases = {}
    for table, alias in re.findall(
        r"\b(?:FROM|JOIN)\s+[`\"\[]?([\w.-]+)[`\"\]]?(?:\s+(?:AS\s+)?([\w-]+))?",
        sql,
        flags=re.IGNORECASE,
    ):
        aliases[(alias or table).casefold()] = table
    pattern = re.compile(
        r"(?:(?P<table>[\w.-]+)\.)?(?P<column>[\w.-]+)\s*(?P<op>=|IN)\s*"
        r"(?P<values>\([^)]*\)|'[^']*'|\"[^\"]*\")",
        flags=re.IGNORECASE,
    )

    def replace_expression(match):
        table = match.group("table")
        if not table:
            return match.group(0)
        table = aliases.get(table.casefold(), table)
        key = f"{table}.{match.group('column')}".casefold()
        known = value_catalog.get(key)
        if not known:
            return match.group(0)
        by_casefold = {str(value).casefold(): str(value) for value in known}
        raw_values = match.group("values")

        def replace_literal(literal_match):
            original = literal_match.group(2)
            canonical = by_casefold.get(original.casefold())
            if canonical is None:
                return literal_match.group(0)
            return f"{literal_match.group(1)}{canonical}{literal_match.group(1)}"

        return re.sub(r"(['\"])(.*?)\1", replace_literal, match.group(0))

    return pattern.sub(replace_expression, str(sql or ""))


def _structure_warnings(sql: str) -> list[str]:
    """Inspect the sqlparse token tree for unsafe or incomplete structures.

    This is deliberately dialect-neutral.  It does not try to prove business
    correctness, but catches common model failures that table-name checks
    cannot see (for example ``SELECT ... INTO`` or a malformed CTE).  When a
    deployment has sqlglot available it can add a dialect-specific validator
    around this stable hook without changing the guard contract.
    """

    warnings: list[str] = []
    if sql.count("(") != sql.count(")"):
        warnings.append("Unbalanced parentheses in SQL structure")
    parsed = sqlparse.parse(sql)
    keyword_values = {
        token.normalized.upper()
        for token in (parsed[0].flatten() if parsed else ())
        if token.ttype in (T.Keyword, T.DDL, T.DML)
    }
    if "INTO" in keyword_values:
        warnings.append("SELECT INTO is not read-only on all supported dialects")
    if keyword_values.intersection({"COPY", "CALL", "EXEC", "EXECUTE"}):
        warnings.append("Execution or export command detected in SQL structure")
    if re.match(r"\s*WITH\b", sql, flags=re.IGNORECASE) and not re.search(
        r"\bSELECT\b", sql, flags=re.IGNORECASE
    ):
        warnings.append("WITH query has no SELECT body")
    return warnings


def _structure_snapshot(sql: str) -> dict[str, Any]:
    """Return a compact, serializable AST-like summary for observability.

    ``sqlparse`` provides a dialect-neutral token tree rather than a semantic
    AST.  This snapshot deliberately exposes only stable structural facts so
    the UI and evaluator can explain what was checked without pretending to
    prove dialect-specific business semantics.
    """

    parsed = sqlparse.parse(sql)
    if not parsed:
        return {}
    statement = parsed[0]
    upper = sql.upper()
    statement_type = "WITH" if re.match(r"\s*WITH\b", sql, re.IGNORECASE) else "SELECT"
    tables = []
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+[`\"\[]?([\w.-]+)[`\"\]]?",
        sql,
        flags=re.IGNORECASE,
    ):
        name = match.group(1)
        if name.casefold() not in {item.casefold() for item in tables}:
            tables.append(name)
    ctes = re.findall(
        r"\bWITH\s+([\w.-]+)\s+AS\s*\(", sql, flags=re.IGNORECASE
    )
    token_count = sum(1 for token in statement.flatten() if not token.is_whitespace)
    return {
        "statement_type": statement_type,
        "tables": tables,
        "cte_names": ctes,
        "has_join": bool(re.search(r"\bJOIN\b", upper)),
        "has_where": bool(re.search(r"\bWHERE\b", upper)),
        "has_group_by": bool(re.search(r"\bGROUP\s+BY\b", upper)),
        "has_order_by": bool(re.search(r"\bORDER\s+BY\b", upper)),
        "has_limit": bool(re.search(r"\bLIMIT\s+\d+\b", upper)),
        "has_subquery": bool(re.search(r"\(\s*(?:SELECT|WITH)\b", sql, re.IGNORECASE)),
        "token_count": token_count,
    }


def _result_warnings(result: Any, max_rows: int) -> tuple[list[str], Optional[int]]:
    """Return non-blocking data-quality warnings for connector results."""

    warnings: list[str] = []
    rows = result
    if hasattr(result, "to_dict"):
        try:
            rows = result.to_dict(orient="records")
        except Exception:
            rows = result
    try:
        row_count = len(rows)
    except (TypeError, AttributeError):
        return warnings, None
    if row_count == 0:
        warnings.append(
            "Result set is empty; verify filter values and join conditions"
        )
    if row_count > max_rows:
        warnings.append(f"Result contains {row_count} rows, above configured max {max_rows}")
    try:
        iterable = rows.values() if isinstance(rows, Mapping) else rows
        for row in iterable:
            values = row.values() if isinstance(row, Mapping) else row
            for value in values:
                if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                    warnings.append("Result contains NaN or infinity")
                    return warnings, row_count
    except (TypeError, AttributeError):
        pass
    return warnings, row_count


def _intent_warnings(sql: str, question: Optional[str]) -> list[str]:
    """Detect common mismatches between a natural-language request and SQL.

    These are advisory diagnostics rather than blocking rules: dialects and
    business definitions vary, so a model-produced query should not be
    rejected solely because a keyword heuristic did not match.
    """

    if not question:
        return []
    query = str(question).casefold()
    normalized = normalize_sql(sql).casefold()
    warnings: list[str] = []
    count_intent = any(token in query for token in ("how many", "number of", "count of", "数量", "多少"))
    average_intent = any(token in query for token in ("average", "avg", "mean", "平均"))
    ratio_intent = any(token in query for token in ("ratio", "rate", "percentage", "比例", "占比"))
    list_intent = any(token in query for token in ("list", "which", "what are", "列出", "哪些"))
    if count_intent and not re.search(r"\bcount\s*\(", normalized):
        warnings.append("Question asks for a count but SQL has no COUNT aggregate")
    if average_intent and not re.search(r"\bavg\s*\(", normalized):
        warnings.append("Question asks for an average but SQL has no AVG aggregate")
    if ratio_intent and not re.search(r"\b(count|sum|avg)\s*\(", normalized):
        warnings.append("Question asks for a ratio/rate but SQL has no aggregate expression")
    if list_intent and re.search(r"\bcount\s*\(", normalized) and not re.search(r"\bgroup\s+by\b", normalized):
        warnings.append("Question asks to list items but SQL returns a single count")
    if list_intent and not re.search(r"\bcount\s*\(", normalized):
        projection = re.search(
            r"^\s*(?:SELECT)\s+(.*?)\s+FROM\b",
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if projection and projection.group(1).strip() != "*":
            # This is advisory rather than an auto-repair: a user may want a
            # detail table, but a broad projection can also hide an intent
            # mismatch (for example asking for an ID and receiving 8 columns).
            expression_count = projection.group(1).count(",") + 1
            if expression_count > 3:
                warnings.append(
                    "List question projects many columns; verify the requested detail level"
                )
    return warnings


@dataclass(frozen=True)
class SqlValidationResult:
    """Result of a read-only SQL validation pass."""

    ok: bool
    sql: str
    error: Optional[str] = None
    warnings: Sequence[str] = ()


@dataclass(frozen=True)
class SqlExecutionTrace:
    """Small, serializable trace for SQL execution and repair attempts."""

    original_sql: str
    executed_sql: Optional[str]
    attempts: int
    repaired: bool
    error: Optional[str] = None
    error_type: Optional[str] = None
    validation_warnings: Sequence[str] = ()
    structure: Optional[Mapping[str, Any]] = None
    result_row_count: Optional[int] = None
    result_column_count: Optional[int] = None


class SqlGuard:
    """Validate and execute model-produced SQL with a bounded repair loop.

    This is deliberately dialect-light: it enforces the safety boundary that
    applies to every DB-GPT datasource (single read-only statement) and leaves
    dialect-specific parsing to the selected database connector.
    """

    def __init__(
        self,
        max_rows: int = 50,
        enable_structure_checks: bool = True,
        enable_result_checks: bool = True,
    ):
        self.max_rows = max_rows
        self.enable_structure_checks = enable_structure_checks
        self.enable_result_checks = enable_result_checks

    def validate(self, sql: str) -> SqlValidationResult:
        normalized = normalize_sql(sql)
        if not normalized:
            return SqlValidationResult(False, normalized, "SQL is empty")

        statements = sqlparse.split(normalized)
        if len(statements) != 1:
            return SqlValidationResult(
                False, normalized, "Only one SQL statement is allowed"
            )

        parsed = sqlparse.parse(normalized)
        if not parsed:
            return SqlValidationResult(False, normalized, "SQL could not be parsed")

        first_keyword = re.match(r"^(WITH|SELECT)\b", normalized, re.IGNORECASE)
        if not first_keyword:
            return SqlValidationResult(
                False, normalized, "Only SELECT or WITH queries are allowed"
            )

        for token in parsed[0].flatten():
            if token.ttype in (T.Keyword, T.DDL, T.DML):
                keyword = token.value.upper().strip()
                if keyword in _FORBIDDEN_KEYWORDS:
                    return SqlValidationResult(
                        False,
                        normalized,
                        f"Forbidden SQL keyword: {keyword}",
                    )

        structural_warnings = (
            _structure_warnings(normalized) if self.enable_structure_checks else []
        )
        blocking_structure = next(
            (
                warning
                for warning in structural_warnings
                if warning.startswith((
                    "Unbalanced parentheses",
                    "SELECT INTO",
                    "Execution or export command",
                    "WITH query has no SELECT",
                ))
            ),
            None,
        )
        if blocking_structure:
            return SqlValidationResult(
                False, normalized, blocking_structure, tuple(structural_warnings)
            )

        warnings = list(structural_warnings)
        if not re.search(r"\bLIMIT\s+\d+\b", normalized, re.IGNORECASE):
            if not re.search(
                r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(|\bGROUP\s+BY\b",
                normalized,
                re.IGNORECASE,
            ):
                warnings.append(f"Query has no explicit LIMIT {self.max_rows}")
        return SqlValidationResult(True, normalized, warnings=tuple(warnings))

    def validate_schema(
        self, sql: str, schema: Sequence[str], strict: bool = False
    ) -> SqlValidationResult:
        """Optionally verify referenced tables against a connector schema.

        Schema retrieval can be intentionally partial, so non-strict mode
        emits a warning instead of rejecting a query. Strict mode is suitable
        for controlled production data sources with a complete schema snapshot.
        """

        base = self.validate(sql)
        if not base.ok:
            return base
        known = _schema_table_names(schema)
        if not known:
            return base
        referenced = {
            name.casefold()
            for name in re.findall(
                r"\b(?:FROM|JOIN)\s+[`\"\[]?([\w.-]+)[`\"\]]?",
                base.sql,
                flags=re.IGNORECASE,
            )
        }
        unknown = sorted(name for name in referenced if name not in known)
        if not unknown:
            return base
        message = "Unknown table(s): " + ", ".join(unknown)
        if strict:
            return SqlValidationResult(False, base.sql, message, base.warnings)
        return SqlValidationResult(True, base.sql, warnings=(*base.warnings, message))

    def validate_values(
        self, sql: str, value_catalog: Optional[dict] = None
    ) -> SqlValidationResult:
        """Add non-blocking warnings when filters use unseen sample values."""

        base = self.validate(sql)
        if not base.ok or not value_catalog:
            return base
        warnings = (*base.warnings, *_value_catalog_warnings(base.sql, value_catalog))
        return SqlValidationResult(True, base.sql, warnings=warnings)

    def review(
        self,
        sql: str,
        schema: Optional[Sequence[str]] = None,
        strict_schema: bool = False,
        value_catalog: Optional[dict] = None,
        question: Optional[str] = None,
    ) -> SqlValidationResult:
        """Run the complete second-stage SQL review in a stable order.

        Stage one validates syntax/read-only structure and optional table
        references. Stage two adds sampled-value and natural-language intent
        diagnostics. Both remain advisory unless the safety boundary fails.
        """

        result = (
            self.validate_schema(sql, schema, strict=strict_schema)
            if schema is not None
            else self.validate(sql)
        )
        if result.ok and value_catalog:
            result = SqlValidationResult(
                True,
                result.sql,
                result.error,
                (*result.warnings, *_value_catalog_warnings(result.sql, value_catalog)),
            )
        if result.ok and question:
            result = SqlValidationResult(
                True,
                result.sql,
                result.error,
                (*result.warnings, *_intent_warnings(result.sql, question)),
            )
        return result

    def repair(self, sql: str, error: Exception) -> Optional[str]:
        """Apply deterministic, low-risk repairs after a connector error."""

        normalized = normalize_sql(sql)
        if not normalized:
            return None
        # A missing LIMIT is safe to repair for detail queries. Do not add it
        # to aggregates, where it is unnecessary and can hide a model mistake.
        if not re.search(r"\bLIMIT\s+\d+\b", normalized, re.IGNORECASE) and not re.search(
            r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(|\bGROUP\s+BY\b",
            normalized,
            re.IGNORECASE,
        ):
            return f"{normalized} LIMIT {self.max_rows}"
        return None

    def execute(
        self,
        sql: str,
        executor: Callable[[str], object],
        max_retries: int = 1,
        schema: Optional[Sequence[str]] = None,
        strict_schema: bool = False,
        value_catalog: Optional[dict] = None,
        question: Optional[str] = None,
    ):
        validation = self.review(
            sql,
            schema=schema,
            strict_schema=strict_schema,
            value_catalog=value_catalog,
            question=question,
        )
        if not validation.ok:
            raise ValueError(validation.error)

        candidate = validation.sql
        retry_warnings: list[str] = []
        attempts = 0
        last_error = None
        while attempts <= max_retries:
            attempts += 1
            try:
                result = executor(candidate)
                result_warnings, result_row_count = (
                    _result_warnings(result, self.max_rows)
                    if self.enable_result_checks
                    else ([], None)
                )
                if (
                    result_row_count == 0
                    and value_catalog
                    and question
                    and not re.search(
                        r"\b(count|sum|avg|min|max)\s*\(", candidate, re.IGNORECASE
                    )
                    and attempts <= max_retries
                ):
                    canonical = _canonicalize_catalog_values(candidate, value_catalog)
                    if canonical != candidate:
                        retry_warnings.append(
                            "Empty result triggered a case-insensitive value canonicalization retry"
                        )
                        candidate = canonical
                        continue
                result_column_count = None
                try:
                    records = (
                        result.to_dict(orient="records")
                        if hasattr(result, "to_dict")
                        else result
                    )
                    first_record = records[0] if records else None
                    if isinstance(first_record, Mapping):
                        result_column_count = len(first_record)
                    elif first_record is not None:
                        result_column_count = len(first_record)
                except (TypeError, AttributeError, IndexError):
                    result_column_count = None
                trace = SqlExecutionTrace(
                    original_sql=sql,
                    executed_sql=candidate,
                    attempts=attempts,
                    repaired=candidate != validation.sql,
                    validation_warnings=(
                        *validation.warnings,
                        *retry_warnings,
                        *result_warnings,
                    ),
                    structure=(
                        _structure_snapshot(candidate)
                        if self.enable_structure_checks
                        else None
                    ),
                    result_row_count=result_row_count,
                    result_column_count=result_column_count,
                )
                return result, trace
            except Exception as error:
                last_error = error
                repaired = self.repair(candidate, error)
                if not repaired or attempts > max_retries:
                    break
                candidate = repaired

        trace = SqlExecutionTrace(
            original_sql=sql,
            executed_sql=candidate,
            attempts=attempts,
            repaired=candidate != validation.sql,
            error=str(last_error),
            error_type=classify_sql_error(last_error) if last_error else None,
            validation_warnings=validation.warnings,
            structure=(
                _structure_snapshot(candidate)
                if self.enable_structure_checks
                else None
            ),
        )
        raise RuntimeError(f"SQL execution failed: {trace}") from last_error
