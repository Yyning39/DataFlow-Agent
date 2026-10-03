import logging
import os
import re
import time
from typing import Dict, Type

from dbgpt import SystemApp
from dbgpt.agent.util.api_call import ApiCall
from dbgpt.util.executor_utils import blocking_func_to_async
from dbgpt.util.sql_utils import SqlGuard
from dbgpt.util.tracer import root_tracer, trace
from dbgpt_app.scene import BaseChat, ChatScene
from dbgpt_app.scene.base_chat import ChatParam
from dbgpt_app.scene.chat_db.auto_execute.config import ChatWithDBExecuteConfig
from dbgpt_serve.core.config import GPTsAppCommonConfig
from dbgpt_serve.datasource.manages import ConnectorManager

from .metric_registry import MetricRegistry
from .access_policy import SqlAccessPolicy
from .result_cache import SqlResultCache
from .schema_hybrid_retriever import SchemaHybridRetriever

logger = logging.getLogger(__name__)


class ChatWithDbAutoExecute(BaseChat):
    chat_scene: str = ChatScene.ChatWithDbExecute.value()

    """Number of results to return from the query"""

    @classmethod
    def param_class(cls) -> Type[GPTsAppCommonConfig]:
        return ChatWithDBExecuteConfig

    def __init__(self, chat_param: ChatParam, system_app: SystemApp):
        """Chat Data Module Initialization
        Args:
           - chat_param: Dict
            - chat_session_id: (str) chat session_id
            - current_user_input: (str) current user input
            - model_name:(str) llm model name
            - select_param:(str) dbname
        """
        self.db_name = chat_param.select_param
        self.curr_config = chat_param.real_app_config(ChatWithDBExecuteConfig)
        super().__init__(chat_param=chat_param, system_app=system_app)
        if not self.db_name:
            raise ValueError(
                f"{ChatScene.ChatWithDbExecute.value} mode should chose db!"
            )
        with root_tracer.start_span(
            "ChatWithDbAutoExecute.get_connect", metadata={"db_name": self.db_name}
        ):
            local_db_manager = ConnectorManager.get_instance(self.system_app)
            self.database = local_db_manager.get_connector(self.db_name)
        self.api_call = ApiCall()
        self.metric_registry = MetricRegistry.for_datasource(self.db_name)
        enhanced_sql_guard = (
            os.getenv("DBGPT_SQL_GUARD_ENHANCED", "true").casefold() != "false"
        )
        self.sql_guard = SqlGuard(
            max_rows=self.curr_config.max_num_results,
            enable_structure_checks=enhanced_sql_guard,
            enable_result_checks=enhanced_sql_guard,
        )
        self._runtime_features = {
            "semantic_enabled": not (
                os.getenv("DBGPT_DISABLE_FIELD_SEMANTICS", "false").casefold()
                == "true"
            ),
            "enhanced_sql_guard": enhanced_sql_guard,
            "model_name": self.llm_model,
        }
        routing_reason = (chat_param.ext_info or {}).get("model_routing_reason")
        if routing_reason:
            self._runtime_features["model_routing_reason"] = routing_reason
        self.access_policy = SqlAccessPolicy.from_env()
        self.result_cache = SqlResultCache.from_env()
        self._cache_scope = str(getattr(chat_param, "user_name", "") or "anonymous")
        self._schema_snapshot = None
        self._value_hints = "-"
        self._value_catalog = {}
        self._semantic_decision = {"status": "unmatched", "candidates": []}
        self._semantic_intent = {}
        self.schema_hybrid_retriever = SchemaHybridRetriever()

    @staticmethod
    def _table_name_and_columns(table_info):
        """Parse connector schema rows such as ``('orders(id,status)',)``."""

        raw = (
            table_info[0]
            if isinstance(table_info, (tuple, list)) and table_info
            else table_info
        )
        text = str(raw)
        match = re.match(
            r"\s*[`\"\[]?([\w.-]+)[`\"\]]?\s*\((.*?)\)\s*;?\s*$", text
        )
        if not match:
            return None, []
        columns = [
            column.strip().strip('`\"[]')
            for column in match.group(2).split(",")
        ]
        return match.group(1), [
            column for column in columns if re.match(r"^[\w.-]+$", column)
        ]

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a trusted schema identifier for the selected SQL dialect."""

        dialect = str(getattr(self.database, "dialect", "")).lower()
        if dialect in {"mysql", "mariadb"}:
            return "`" + identifier.replace("`", "``") + "`"
        if dialect in {"mssql", "sqlserver"}:
            return "[" + identifier.replace("]", "]]" ) + "]"
        return '"' + identifier.replace('"', '""') + '"'

    @classmethod
    def _select_local_schema(cls, table_infos, question: str, top_k: int):
        """Select relevant tables deterministically when vector retrieval is empty."""

        if not table_infos:
            return []
        tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", question or "")
            if len(token) >= 2
        }
        scored = []
        for index, table_info in enumerate(table_infos):
            table_name, columns = cls._table_name_and_columns(table_info)
            haystack = " ".join([str(table_name or ""), *(str(column) for column in columns)]).casefold()
            score = sum(1 for token in tokens if token in haystack)
            scored.append((score, index, table_info))
        matched = [item for item in sorted(scored, key=lambda item: (-item[0], item[1])) if item[0] > 0]
        if not matched:
            return list(table_infos)
        limit = max(1, int(top_k or len(table_infos)))
        return [item[2] for item in matched[:limit]]

    @classmethod
    def _merge_schema_candidates(
        cls, retrieved_infos, all_table_infos, question: str, top_k: int
    ):
        """Merge vector candidates with deterministic lexical table/column hits."""

        retrieved = list(retrieved_infos or [])
        all_infos = list(all_table_infos or [])
        if not all_infos:
            return retrieved
        limit = max(1, int(top_k or len(all_infos)))
        seen = set()
        merged = []
        for item in retrieved:
            name, _ = cls._table_name_and_columns(item)
            key = str(name or item).casefold()
            if key not in seen:
                seen.add(key)
                merged.append(item)
        if len(merged) >= limit:
            return merged[:limit]
        tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", question or "")
            if len(token) >= 2
        }
        scored = []
        for index, item in enumerate(all_infos):
            name, columns = cls._table_name_and_columns(item)
            key = str(name or item).casefold()
            if key in seen:
                continue
            haystack = " ".join(
                [str(name or ""), *(str(column) for column in columns)]
            ).casefold()
            score = sum(1 for token in tokens if token in haystack)
            scored.append((score, index, item))
        scored.sort(key=lambda value: (-value[0], value[1]))
        for _score, _index, item in scored:
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged

    def _collect_value_hints(self, table_infos):
        """Collect bounded row samples and format prompt-safe value hints.

        This performs at most one small read per selected table, works through
        the existing connector APIs, and never changes database state.
        """

        max_tables = max(0, int(getattr(self.curr_config, "value_hint_max_tables", 8)))
        max_rows = max(1, int(getattr(self.curr_config, "value_hint_rows", 5)))
        max_values = max(1, int(getattr(self.curr_config, "value_hint_max_values", 8)))
        max_columns = max(1, int(getattr(self.curr_config, "value_hint_max_columns", 12)))
        lines = []
        catalog = {}
        table_count = 0
        column_count = 0
        for table_info in list(table_infos or [])[:max_tables]:
            table_name, schema_columns = self._table_name_and_columns(table_info)
            if not table_name:
                continue
            try:
                sample = self.database.run_to_df(
                    f"SELECT * FROM {self._quote_identifier(table_name)} LIMIT {max_rows}"
                )
                sample_columns_attr = getattr(sample, "columns", None)
                sample_columns = (
                    list(sample_columns_attr) if sample_columns_attr is not None else []
                )
                columns = sample_columns or schema_columns
                rows = (
                    sample.to_dict(orient="records")
                    if hasattr(sample, "to_dict")
                    else []
                )
            except Exception:
                try:
                    result = self.database.query_table_schema(table_name)
                    columns = list(result[0]) if result else schema_columns
                    rows = [
                        dict(zip(columns, row))
                        for row in (result[1:] if result else [])
                    ]
                except Exception:
                    continue
            table_count += 1
            # Prefer columns that commonly encode business states, then fill
            # remaining slots in schema order. This keeps prompts compact while
            # retaining useful examples for arbitrary schemas.
            preferred = [
                column
                for column in columns
                if re.search(
                    r"(?:status|state|type|category|class|flag|active|enabled|mode|level|code|is[_-])",
                    str(column),
                    flags=re.IGNORECASE,
                )
            ]
            ordered_columns = preferred + [column for column in columns if column not in preferred]
            for column in ordered_columns[:max_columns]:
                values = []
                for row in rows:
                    value = row.get(column) if isinstance(row, dict) else None
                    if value is None or str(value).strip() == "":
                        continue
                    value_text = (
                        str(value).replace("\n", " ").replace("\r", " ").strip()
                    )
                    if value_text not in values:
                        values.append(value_text)
                    if len(values) >= max_values:
                        break
                if not values:
                    continue
                column_count += 1
                key = f"{table_name}.{column}"
                catalog[key.casefold()] = set(values)
                lines.append(
                    f"{key}: " + ", ".join(repr(value[:80]) for value in values)
                )
        return "\n".join(lines) if lines else "-", catalog, table_count, column_count

    @trace()
    async def generate_input_values(self) -> Dict:
        """
        generate input values
        """
        try:
            from dbgpt_serve.datasource.service.db_summary_client import DBSummaryClient
        except ImportError:
            raise ValueError("Could not import DBSummaryClient. ")
        user_input = self.current_user_input.last_text
        client = DBSummaryClient(system_app=self.system_app)
        try:
            with root_tracer.start_span("ChatWithDbAutoExecute.get_db_summary"):
                table_infos = await blocking_func_to_async(
                    self._executor,
                    client.get_db_summary,
                    self.db_name,
                    user_input,
                    self.curr_config.schema_retrieve_top_k,
                )
        except Exception as e:
            logger.error(f"Retrieved table info error: {str(e)}")
            table_infos = []

        # Retrieval indexes can be empty or incomplete after a fresh database
        # registration (or when an embedding service is unavailable). For
        # small databases, prefer a complete schema so relevant tables are not
        # silently omitted; retain top-k retrieval for larger databases.
        all_table_infos = None
        schema_fallback_used = False
        schema_retrieval_empty = not bool(table_infos)
        schema_hybrid_used = False
        schema_local_selection_used = False
        schema_hybrid_added_count = 0
        schema_vector_candidate_count = len(table_infos)
        schema_local_hybrid_used = False
        schema_local_hybrid_diagnostics = {}
        # Build/read the local, versioned index even when the remote embedding
        # service is unavailable. ``table_simple_info`` is read-only metadata
        # and is cheap for SQLite/MySQL connectors; the persisted index itself
        # lives under DBGPT_SCHEMA_INDEX_DIR (D: in the supplied launcher).
        hybrid_enabled = os.getenv("DBGPT_SCHEMA_HYBRID", "true").casefold() != "false"
        try:
            all_table_infos = await blocking_func_to_async(
                self._executor, self.database.table_simple_info
            )
        except Exception as exc:  # pragma: no cover - connector-specific
            logger.warning("Local schema snapshot failed: %s", exc)
            all_table_infos = []
        if hybrid_enabled and all_table_infos:
            try:
                local_infos, schema_local_hybrid_diagnostics = await blocking_func_to_async(
                    self._executor,
                    self.schema_hybrid_retriever.retrieve,
                    self.db_name,
                    user_input,
                    all_table_infos,
                    self.curr_config.schema_retrieve_top_k,
                )
                if local_infos:
                    before = len(table_infos)
                    # Keep vector candidates first when they exist, then fill
                    # missing tables from the local lexical/vector index.
                    table_infos = self._merge_schema_candidates(
                        table_infos or [],
                        local_infos,
                        user_input,
                        self.curr_config.schema_retrieve_top_k,
                    )
                    schema_hybrid_added_count = max(0, len(table_infos) - before)
                    schema_local_hybrid_used = True
            except Exception as exc:  # pragma: no cover - connector-specific
                logger.warning("Local schema hybrid retrieval failed: %s", exc)

        if not table_infos or len(table_infos) < self.curr_config.schema_retrieve_top_k:
            if not table_infos:
                table_infos = self._select_local_schema(
                    all_table_infos,
                    user_input,
                    self.curr_config.schema_retrieve_top_k,
                )
                schema_local_selection_used = bool(table_infos)
            elif len(all_table_infos) <= self.curr_config.schema_retrieve_top_k:
                table_infos = all_table_infos
                # A complete local schema is a valid deterministic source, not
                # an error fallback. Track retrieval availability separately so
                # the benchmark distinguishes an empty vector index from an
                # actually incomplete schema.
                schema_fallback_used = not bool(all_table_infos)
            else:
                before = len(table_infos)
                table_infos = self._merge_schema_candidates(
                    table_infos,
                    all_table_infos,
                    user_input,
                    self.curr_config.schema_retrieve_top_k,
                )
                schema_hybrid_added_count = max(
                    schema_hybrid_added_count, max(0, len(table_infos) - before)
                )
                schema_hybrid_used = schema_hybrid_added_count > 0

        if len(table_infos) > self.curr_config.schema_max_tokens:
            # Load all tables schema, must be less then schema_max_tokens
            # Here we just truncate the table_infos
            # TODO: Count the number of tokens by LLMClient
            table_infos = table_infos[: self.curr_config.schema_max_tokens]

        input_values = {
            "db_name": self.db_name,
            "user_input": user_input,
            "top_k": self.curr_config.max_num_results,
            "dialect": self.database.dialect,
            "table_info": table_infos,
            "display_type": self._generate_numbered_list(),
            "metric_context": self.metric_registry.render_context(user_input),
        }
        self._semantic_decision = self.metric_registry.semantic_decision(user_input)
        self._semantic_intent = self.metric_registry.semantic_intent(user_input)
        value_hints = "-"
        value_catalog = {}
        hint_tables = hint_columns = 0
        hint_started = time.perf_counter()
        if bool(getattr(self.curr_config, "enable_value_hints", True)):
            (
                value_hints,
                value_catalog,
                hint_tables,
                hint_columns,
            ) = await blocking_func_to_async(
                self._executor, self._collect_value_hints, table_infos
            )
        self._value_hints = value_hints
        self._value_catalog = value_catalog
        input_values["value_hints"] = value_hints
        # Keep the same schema snapshot used for prompting so the execution
        # guard can optionally perform a strict table-reference check.
        self._schema_snapshot = table_infos
        self._perf_timings["schema_table_count"] = float(len(table_infos))
        self._perf_timings["schema_fallback_used"] = float(schema_fallback_used)
        self._perf_timings["schema_retrieval_empty"] = float(schema_retrieval_empty)
        self._perf_timings["schema_hybrid_used"] = float(schema_hybrid_used)
        self._perf_timings["schema_local_selection_used"] = float(
            schema_local_selection_used
        )
        self._perf_timings["schema_hybrid_added_count"] = float(
            schema_hybrid_added_count
        )
        self._perf_timings["schema_vector_candidate_count"] = float(
            schema_vector_candidate_count
        )
        self._perf_timings.update(schema_local_hybrid_diagnostics)
        self._perf_timings["schema_local_hybrid_used"] = float(schema_local_hybrid_used)
        self._perf_timings["schema_source_local_complete"] = float(
            bool(all_table_infos) and table_infos == all_table_infos
        )
        self._perf_timings["value_hint_seconds"] = round(
            time.perf_counter() - hint_started, 4
        )
        self._perf_timings["value_hint_table_count"] = float(hint_tables)
        self._perf_timings["value_hint_column_count"] = float(hint_columns)
        return input_values

    def do_action(self, prompt_response):
        def guarded_run(sql):
            canonical_sql = self.metric_registry.canonicalize_sql(
                sql, self._semantic_decision
            )
            self.access_policy.check(self.db_name, canonical_sql)
            started = time.perf_counter()

            cache_hit = False

            def execute_with_cache(query):
                nonlocal cache_hit
                cached = self.result_cache.get(self.db_name, query, self._cache_scope)
                if cached is not None:
                    cache_hit = True
                    return cached
                value = self.database.run_to_df(query)
                self.result_cache.set(self.db_name, query, value, self._cache_scope)
                return value

            result, trace = self.sql_guard.execute(
                canonical_sql,
                execute_with_cache,
                max_retries=1,
                schema=self._schema_snapshot,
                strict_schema=bool(getattr(self.curr_config, "strict_schema", False)),
                value_catalog=self._value_catalog,
                question=self.current_user_input.last_text,
            )
            self._perf_timings["sql_execution_seconds"] = round(
                time.perf_counter() - started, 4
            )
            self._perf_timings["sql_cache_enabled"] = float(self.result_cache.enabled)
            self._perf_timings["sql_cache_hit"] = float(cache_hit)
            logger.info("SQL guard trace: %s", trace)
            self._perf_timings["sql_value_warning_count"] = float(
                len(getattr(trace, "validation_warnings", ()) or ())
            )
            guarded_run.__dbgpt_trace__ = trace
            return result

        # The output parser receives this callable and can include the
        # timings in the chart-view payload consumed by benchmark tooling.
        guarded_run.__dbgpt_timings__ = self._perf_timings
        guarded_run.__dbgpt_semantic_decision__ = self._semantic_decision
        guarded_run.__dbgpt_semantic_intent__ = self._semantic_intent
        guarded_run.__dbgpt_runtime_features__ = self._runtime_features
        return guarded_run
