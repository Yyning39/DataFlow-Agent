"""Small, extensible metric semantic layer for database chat.

The registry is intentionally local and deterministic. It gives the model an
explicit metric definition instead of asking it to infer business semantics
from a column name alone. A later version can load the same dataclass records
from a governed service or a knowledge base without changing the prompt
contract.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
from typing import Iterable, List


def _normalize_text(value: str) -> str:
    value = value.casefold().replace("_", " ")
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", value).strip()


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    description: str
    expression: str
    table: str
    dimensions: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    notes: str = ""

    def match_score(self, question: str) -> int:
        text = _normalize_text(question)
        terms = (_normalize_text(self.name), *(_normalize_text(alias) for alias in self.aliases))
        return max((len(term) for term in terms if term and term in text), default=0)

    def matches(self, question: str) -> bool:
        return self.match_score(question) > 0

    def to_prompt(self) -> str:
        dimensions = ", ".join(self.dimensions) or "none specified"
        aliases = ", ".join(self.aliases) or "none"
        notes = f" Notes: {self.notes}" if self.notes else ""
        return (
            f"- {self.name}: {self.description}; expression={self.expression}; "
            f"table={self.table}; dimensions={dimensions}; aliases={aliases}."
            f"{notes}"
        )


@dataclass(frozen=True)
class FieldDefinition:
    """Business meaning and value mapping for a physical database field.

    ``value_mapping`` maps user-facing concepts to stored values. The mapping
    is data-source configuration, not a code-level special case, so the same
    registry can describe status flags in any database.
    """

    table: str
    column: str
    description: str
    aliases: tuple[str, ...] = ()
    value_mapping: Mapping[str, str] = None
    source: str = ""
    confidence: float = 1.0
    notes: str = ""

    def match_score(self, question: str) -> int:
        text = _normalize_text(question)
        terms = (
            _normalize_text(self.column),
            _normalize_text(self.description),
            *(_normalize_text(alias) for alias in self.aliases),
            *(_normalize_text(concept) for concept in (self.value_mapping or {})),
        )
        return max((len(term) for term in terms if term and term in text), default=0)

    def matches(self, question: str) -> bool:
        return self.match_score(question) > 0

    def to_prompt(self) -> str:
        aliases = ", ".join(self.aliases) or "none"
        mappings = self.value_mapping or {}
        mapping_text = ", ".join(
            f"{concept} => {value}" for concept, value in mappings.items()
        ) or "none documented"
        provenance = f" source={self.source}" if self.source else ""
        return (
            f"- {self.table}.{self.column}: {self.description}; aliases={aliases}; "
            f"value_mapping={mapping_text}; confidence={self.confidence:.2f}."
            f"{provenance} {self.notes}".rstrip()
        )


class MetricRegistry:
    def __init__(
        self,
        definitions: Iterable[MetricDefinition] = (),
        fields: Iterable[FieldDefinition] = (),
    ):
        self._definitions = list(definitions)
        self._fields = list(fields)

    @classmethod
    def from_data(cls, data: Any) -> "MetricRegistry":
        """Build a registry from a JSON-compatible list or mapping.

        The mapping form is intentionally small and stable so a later config
        service can provide the same contract::

            {"metrics": [{"name": "Revenue", "expression": "SUM(revenue)", ...}]}
        """

        metrics = data.get("metrics", []) if isinstance(data, Mapping) else data
        fields = data.get("fields", []) if isinstance(data, Mapping) else []
        if not isinstance(metrics, list) or not isinstance(fields, list):
            raise ValueError("Metric configuration must contain a metrics list")

        definitions = []
        for record in metrics:
            if not isinstance(record, Mapping):
                raise ValueError("Each metric definition must be an object")
            required = ("name", "description", "expression", "table")
            missing = [field for field in required if not record.get(field)]
            if missing:
                raise ValueError(f"Metric definition missing fields: {', '.join(missing)}")
            definitions.append(
                MetricDefinition(
                    name=str(record["name"]),
                    description=str(record["description"]),
                    expression=str(record["expression"]),
                    table=str(record["table"]),
                    dimensions=tuple(str(value) for value in record.get("dimensions", ())),
                    aliases=tuple(str(value) for value in record.get("aliases", ())),
                    notes=str(record.get("notes", "")),
                )
            )
        field_definitions = []
        for record in fields:
            if not isinstance(record, Mapping):
                raise ValueError("Each field definition must be an object")
            required = ("table", "column", "description")
            missing = [field for field in required if not record.get(field)]
            if missing:
                raise ValueError(
                    f"Field definition missing fields: {', '.join(missing)}"
                )
            raw_mapping = record.get("value_mapping", {})
            if not isinstance(raw_mapping, Mapping):
                raise ValueError("Field value_mapping must be an object")
            field_definitions.append(
                FieldDefinition(
                    table=str(record["table"]),
                    column=str(record["column"]),
                    description=str(record["description"]),
                    aliases=tuple(str(value) for value in record.get("aliases", ())),
                    value_mapping={
                        str(concept): str(value)
                        for concept, value in raw_mapping.items()
                    },
                    source=str(record.get("source", "")),
                    confidence=float(record.get("confidence", 1.0)),
                    notes=str(record.get("notes", "")),
                )
            )
        return cls(definitions, field_definitions)

    @classmethod
    def from_file(cls, path: str | Path) -> "MetricRegistry":
        """Load a registry from a UTF-8 JSON file."""

        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as handle:
            return cls.from_data(json.load(handle))

    @classmethod
    def for_datasource(
        cls, datasource: str, directory: Optional[str | Path] = None
    ) -> "MetricRegistry":
        """Load datasource-specific metrics, falling back to built-in defaults.

        ``DBGPT_METRICS_DIR`` can point to a deployment-owned directory. File
        names are sanitized to prevent a datasource name from escaping that
        directory. Missing Walmart files preserve the existing behavior. Other
        unknown datasources receive an empty registry rather than accidental
        Walmart definitions.
        """

        configured_dir = directory or os.getenv("DBGPT_METRICS_DIR")
        disable_fields = os.getenv("DBGPT_DISABLE_FIELD_SEMANTICS", "false").casefold() == "true"
        semantic_dir = os.getenv("DBGPT_SEMANTICS_DIR")
        if configured_dir is None:
            candidate_dirs = [Path.cwd() / "configs" / "metrics"]
            candidate_dirs.extend(
                parent / "configs" / "metrics" for parent in Path(__file__).resolve().parents
            )
        else:
            candidate_dirs = [Path(configured_dir)]
        semantic_dirs = (
            [Path(semantic_dir)]
            if semantic_dir
            else [Path.cwd() / "configs" / "semantics"]
            + [parent / "configs" / "semantics" for parent in Path(__file__).resolve().parents]
        )
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(datasource))
        names = [safe_name]
        # Benchmark/deployment wrappers may add a run suffix. Resolving the
        # stable datasource portion keeps semantic files reusable without
        # embedding a particular test run id in the configuration.
        base_match = re.match(r"^(?:BIRD|TEST)_([^_]+(?:_[^_]+)*)_[0-9]+$", safe_name)
        if base_match:
            names.append(base_match.group(1))
        for candidate_dir in (*candidate_dirs, *semantic_dirs):
            for name in names:
                config_path = candidate_dir / f"{name}.json"
                if config_path.is_file():
                    registry = cls.from_file(config_path)
                    if disable_fields and candidate_dir in semantic_dirs:
                        return cls(registry._definitions)
                    return registry
        # Semantic files may use the stable datasource id while the runtime
        # name carries a benchmark/deployment suffix (for example,
        # ``BIRD_california_schools_<run-id>``). Match only semantic folders so
        # an unrelated metric file cannot be selected accidentally.
        for candidate_dir in semantic_dirs:
            if not candidate_dir.is_dir():
                continue
            prefixed = sorted(
                candidate_dir.glob("*.json"),
                key=lambda path: len(path.stem),
                reverse=True,
            )
            for config_path in prefixed:
                stem = config_path.stem
                safe_lower = safe_name.casefold()
                if safe_lower in {stem.casefold(), f"bird_{stem}".casefold()} or safe_lower.startswith(
                    f"bird_{stem}_".casefold()
                ):
                    registry = cls.from_file(config_path)
                    return cls(registry._definitions) if disable_fields else registry
        if str(datasource).casefold() in {"walmart_sales", "walmart"}:
            return cls.default()
        return cls()

    @classmethod
    def default(cls) -> "MetricRegistry":
        return cls(
            [
                MetricDefinition(
                    name="Total Weekly Sales",
                    description="Total sales across the selected records",
                    expression="SUM(Weekly_Sales)",
                    table="walmart_sales",
                    dimensions=("Store", "Date", "Holiday_Flag"),
                    aliases=("Weekly_Sales total", "total sales", "sales total", "销售额", "总销售额"),
                    notes="Do not use AVG when the question asks for total sales.",
                ),
                MetricDefinition(
                    name="Average Weekly Sales",
                    description="Mean Weekly_Sales value per record",
                    expression="AVG(Weekly_Sales)",
                    table="walmart_sales",
                    dimensions=("Store", "Date", "Holiday_Flag"),
                    aliases=("average sales", "平均销售额", "平均销售"),
                ),
                MetricDefinition(
                    name="Store Count",
                    description="Number of distinct stores",
                    expression="COUNT(DISTINCT Store)",
                    table="walmart_sales",
                    dimensions=("Store",),
                    aliases=("number of stores", "门店数", "门店数量"),
                ),
            ]
        )

    def search(self, question: str) -> List[MetricDefinition]:
        matches = [definition for definition in self._definitions if definition.matches(question)]
        return sorted(matches, key=lambda definition: definition.match_score(question), reverse=True)

    def field_search(self, question: str) -> List[FieldDefinition]:
        """Return governed field meanings ordered by lexical evidence."""

        matches = [field for field in self._fields if field.matches(question)]
        return sorted(matches, key=lambda field: field.match_score(question), reverse=True)

    def semantic_decision(self, question: str) -> dict:
        """Describe whether a field meaning is resolved or needs clarification.

        The decision is intentionally explainable and data-driven.  It does
        not hard-code a particular column; mappings and aliases come from the
        datasource semantic file.
        """

        matches = self.field_search(question)
        if not matches:
            return {"status": "unmatched", "candidates": []}
        top_score = matches[0].match_score(question)
        top = [field for field in matches if field.match_score(question) == top_score]
        text = _normalize_text(question)
        mapped = []
        for field in top:
            for concept, value in (field.value_mapping or {}).items():
                if _normalize_text(concept) and _normalize_text(concept) in text:
                    mapped.append(
                        {
                            "field": f"{field.table}.{field.column}",
                            "concept": concept,
                            "stored_value": value,
                        }
                    )
        dimension_context = any(
            marker in f" {text} "
            for marker in (" by ", " group by ", " per ", " each ", "按", "分组", "各")
        )
        if mapped and len(mapped) == 1:
            return {"status": "resolved", "candidates": mapped}
        if dimension_context and not mapped:
            return {
                "status": "contextual",
                "candidates": [],
                "reason": "field is used as a grouping dimension, not a value filter",
            }
        candidates = [f"{field.table}.{field.column}" for field in top]
        return {
            "status": "clarification_required",
            "candidates": candidates,
            "reason": "multiple field meanings" if len(candidates) > 1 else "value mapping not explicit",
        }

    def semantic_intent(self, question: str) -> dict:
        """Return a structured, explainable semantic intermediate representation.

        The representation is deliberately datasource-neutral: metrics and
        physical fields are references, while resolved value mappings become
        explicit filters. SQL generation can consume this contract without
        embedding benchmark- or table-specific rules.
        """

        decision = self.semantic_decision(question)
        metrics = [
            {
                "name": metric.name,
                "expression": metric.expression,
                "table": metric.table,
                "dimensions": list(metric.dimensions),
            }
            for metric in self.search(question)
        ]
        fields = [
            {
                "table": field.table,
                "column": field.column,
                "description": field.description,
                "confidence": field.confidence,
            }
            for field in self.field_search(question)
        ]
        return {
            "question": str(question or ""),
            "status": decision.get("status", "unmatched"),
            "metrics": metrics,
            "fields": fields,
            "filters": list(decision.get("candidates", []))
            if decision.get("status") == "resolved"
            else [],
            "ambiguities": list(decision.get("candidates", []))
            if decision.get("status") == "clarification_required"
            else [],
        }

    @staticmethod
    def canonicalize_sql(sql: str, decision: Mapping[str, Any]) -> str:
        """Apply governed stored-value casing to quoted SQL literals.

        Models commonly preserve a user's title case (``North Bohemia``) while
        SQLite stores ``north Bohemia``. Only literals explicitly resolved by
        the semantic registry are changed; table names and arbitrary values
        remain untouched.
        """

        canonical = str(sql or "")
        for candidate in decision.get("candidates", []) if isinstance(decision, Mapping) else []:
            concept = candidate.get("concept")
            stored = candidate.get("stored_value")
            if not concept or not stored or str(concept) == str(stored):
                continue
            concept_text = str(concept)
            stored_text = str(stored)
            def replace_literal(match):
                return (
                    f"{match.group(1)}{stored_text}{match.group(1)}"
                    if match.group(2).casefold() == concept_text.casefold()
                    else match.group(0)
                )
            canonical = re.sub(r"(['\"])(.*?)\1", replace_literal, canonical)
        return canonical

    def render_context(self, question: str) -> str:
        matches = self.search(question)
        field_matches = self.field_search(question)
        context = [metric.to_prompt() for metric in matches]
        context.extend(field.to_prompt() for field in field_matches)
        if not context:
            return "No governed metric or field semantic definition matched this question."
        decision = self.semantic_decision(question)
        if decision["status"] == "clarification_required":
            candidates = ", ".join(decision["candidates"])
            context.append(
                "Semantic decision: clarification required before filtering. "
                f"Candidate field(s): {candidates}. Ask the user which business value they mean; "
                "do not guess a stored flag value."
            )
        return "\n".join(context)
