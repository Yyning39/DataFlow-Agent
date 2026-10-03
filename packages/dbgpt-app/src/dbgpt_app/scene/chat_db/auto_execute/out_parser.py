import json
import logging
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, NamedTuple

import numpy as np
import pandas as pd
import sqlparse

from dbgpt._private.config import Config
from dbgpt.core.interface.output_parser import BaseOutputParser
from dbgpt.util.json_utils import serialize

from ...exceptions import AppActionException
from .analysis_report import build_analysis_report

CFG = Config()


class SqlAction(NamedTuple):
    sql: str
    thoughts: Dict
    display: str
    direct_response: str

    def to_dict(self) -> Dict[str, Dict]:
        return {
            "sql": self.sql,
            "thoughts": self.thoughts,
            "display": self.display,
            "direct_response": self.direct_response,
        }


logger = logging.getLogger(__name__)


def _requires_sql(question: str) -> bool:
    """Return whether a chat-with-db question must be grounded in SQL."""

    text = str(question or "").casefold()
    return any(
        token in text
        for token in (
            "how many",
            "number of",
            "count",
            "average",
            "ratio",
            "percentage",
            "list",
            "which",
            "what are",
            "数量",
            "多少",
            "平均",
            "比例",
            "列出",
            "哪些",
        )
    )


def _normalize_display_type(value: str) -> str:
    """Normalize common human-readable chart labels to backend chart types."""

    raw = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "table": "response_table",
        "bar": "response_bar_chart",
        "bar_chart": "response_bar_chart",
        "bar chart": "response_bar_chart",
        "line": "response_line_chart",
        "line_chart": "response_line_chart",
        "line chart": "response_line_chart",
        "pie": "response_pie_chart",
        "pie_chart": "response_pie_chart",
        "pie chart": "response_pie_chart",
    }
    return aliases.get(raw, str(value or "response_table"))


def _infer_display_type(question: str, display_type: str, row_count: int) -> str:
    """Choose a stable chart fallback from the user's intent.

    Models sometimes omit ``display_type`` even when the user explicitly asks
    for a comparison, trend, or share.  Only replace the default table choice;
    an explicit model chart type remains authoritative.
    """

    normalized = _normalize_display_type(display_type)
    if normalized != "response_table" or row_count < 2:
        return normalized
    text = str(question or "").casefold()
    if any(token in text for token in ("trend", "over time", "随时间", "趋势")):
        return "response_line_chart"
    if any(token in text for token in ("share", "proportion", "percentage", "占比", "比例")):
        return "response_pie_chart"
    if any(token in text for token in ("compare", "comparison", "by ", "对比", "比较", "各类别", "按类别")):
        return "response_bar_chart"
    return normalized


class DbChatOutputParser(BaseOutputParser):
    def __init__(self, is_stream_out: bool = False, **kwargs):
        super().__init__(is_stream_out=is_stream_out, **kwargs)

    def is_sql_statement(self, statement):
        parsed = sqlparse.parse(statement)
        if not parsed:
            return False
        for stmt in parsed:
            if stmt.get_type() != "UNKNOWN":
                return True
        return False

    def parse_prompt_response(self, model_out_text):
        clean_str = super().parse_prompt_response(model_out_text)
        logger.info(f"clean prompt response: {clean_str}")
        # Compatible with community pure sql output model
        if self.is_sql_statement(clean_str):
            return SqlAction(clean_str, "", "", "")
        else:
            try:
                response = json.loads(clean_str, strict=False)
                sql = ""
                thoughts = dict
                display = ""
                resp = ""
                for key in sorted(response):
                    if key.strip() == "sql":
                        sql = response[key]
                    if key.strip() == "thoughts":
                        thoughts = response[key]
                    if key.strip() == "display_type":
                        display = response[key]
                    if key.strip() == "direct_response":
                        resp = response[key]
                return SqlAction(
                    sql=sql, thoughts=thoughts, display=display, direct_response=resp
                )
            except Exception:
                logger.error(f"json load failed:{clean_str}")
                return SqlAction("", clean_str, "", "")

    def parse_vector_data_with_pca(self, df):
        try:
            from sklearn.decomposition import PCA
        except ImportError:
            raise ImportError(
                "Could not import scikit-learn package. "
                "Please install it with `pip install scikit-learn`."
            )

        nrow, ncol = df.shape
        if nrow == 0 or ncol == 0:
            return df, False

        vec_col = -1
        for i_col in range(ncol):
            if isinstance(df.iloc[:, i_col][0], list):
                vec_col = i_col
                break
            elif isinstance(df.iloc[:, i_col][0], bytes):
                sample = df.iloc[:, i_col][0]
                if isinstance(json.loads(sample.decode()), list):
                    vec_col = i_col
                    break
        if vec_col == -1:
            return df, False
        vec_dim = len(json.loads(df.iloc[:, vec_col][0].decode()))
        if min(nrow, vec_dim) < 2:
            return df, False
        df.iloc[:, vec_col] = df.iloc[:, vec_col].apply(
            lambda x: json.loads(x.decode())
        )
        X = np.array(df.iloc[:, vec_col].tolist())

        pca = PCA(n_components=2)
        X_pca = pca.fit_transform(X)

        new_df = pd.DataFrame()
        for i_col in range(ncol):
            if i_col == vec_col:
                continue
            col_name = df.columns[i_col]
            new_df[col_name] = df[col_name]
        new_df["__x"] = [pos[0] for pos in X_pca]
        new_df["__y"] = [pos[1] for pos in X_pca]
        return new_df, True

    def parse_view_response(self, speak, data, prompt_response) -> str:
        param = {}
        api_call_element = ET.Element("chart-view")
        err_msg = None
        success = False
        try:
            semantic_decision = getattr(data, "__dbgpt_semantic_decision__", {}) or {}
            if semantic_decision.get("status") == "clarification_required":
                candidates = ", ".join(semantic_decision.get("candidates") or [])
                speak = (
                    "为了避免误解字段含义，暂不执行 SQL。请确认你要筛选的业务含义"
                    + (f"（候选字段：{candidates}）" if candidates else "")
                    + "。"
                )
                view_json_str = ""
                success = True
            elif (
                not prompt_response.direct_response
                or len(prompt_response.direct_response) <= 0
            ) and (not prompt_response.sql or len(prompt_response.sql) <= 0):
                raise AppActionException("Can not find sql in response", speak)

            elif prompt_response.sql:
                df = data(prompt_response.sql)
                param["type"] = _infer_display_type(
                    speak, prompt_response.display, len(df.index)
                )

                if param["type"] == "response_vector_chart":
                    df, visualizable = self.parse_vector_data_with_pca(df)
                    param["type"] = (
                        "response_scatter_chart" if visualizable else "response_table"
                    )

                param["sql"] = prompt_response.sql
                param["data"] = json.loads(
                    df.to_json(orient="records", date_format="iso", date_unit="s")
                )
                param["analysis_report"] = build_analysis_report(
                    question=speak,
                    sql=prompt_response.sql,
                    dataframe=df,
                    execution_trace=getattr(data, "__dbgpt_trace__", None),
                )
                execution_trace = getattr(data, "__dbgpt_trace__", None)
                runtime_features = getattr(data, "__dbgpt_runtime_features__", None)
                if runtime_features:
                    param["runtime_features"] = dict(runtime_features)
                if execution_trace is not None:
                    warnings = list(getattr(execution_trace, "validation_warnings", ()) or ())
                    if warnings:
                        param["validation_warnings"] = warnings
                    structure = getattr(execution_trace, "structure", None)
                    if structure:
                        param["sql_structure"] = dict(structure)
                    result_row_count = getattr(execution_trace, "result_row_count", None)
                    if result_row_count is not None:
                        param["result_row_count"] = int(result_row_count)
                    result_column_count = getattr(
                        execution_trace, "result_column_count", None
                    )
                    if result_column_count is not None:
                        param["result_column_count"] = int(result_column_count)
                timings = getattr(data, "__dbgpt_timings__", None)
                if timings:
                    param["timings"] = dict(timings)
                if semantic_decision.get("status") not in (None, "unmatched"):
                    param["semantic_decision"] = semantic_decision
                semantic_intent = getattr(data, "__dbgpt_semantic_intent__", {}) or {}
                if semantic_intent:
                    param["semantic_intent"] = semantic_intent
                comparison_path = os.getenv("DBGPT_VERSION_COMPARISON_FILE")
                if comparison_path:
                    try:
                        comparison = json.loads(
                            Path(comparison_path).read_text(encoding="utf-8")
                        )
                        rows = comparison.get("versions") if isinstance(comparison, dict) else comparison
                        if isinstance(rows, list):
                            param["version_comparison"] = rows
                    except (OSError, ValueError, TypeError) as error:
                        logger.warning("Could not load version comparison file: %s", error)
                view_json_str = json.dumps(param, default=serialize, ensure_ascii=False)
                success = True
            elif prompt_response.direct_response:
                if _requires_sql(speak):
                    raise AppActionException(
                        "Data question requires SQL grounding",
                        "该问题需要查询数据库后回答，但模型未生成 SQL；请重试。",
                    )
                speak = prompt_response.direct_response
                view_json_str = ""
                success = True
        except Exception as e:
            logger.error("parse_view_response error!" + str(e))
            err_param = {
                "sql": f"{prompt_response.sql}",
                "type": "response_table",
                "data": [],
            }
            # err_param["err_msg"] = str(e)
            err_msg = str(e)
            view_json_str = json.dumps(err_param, default=serialize, ensure_ascii=False)

        # api_call_element.text = view_json_str
        if len(view_json_str) != 0:
            api_call_element.set("content", view_json_str)
            result = ET.tostring(api_call_element, encoding="utf-8")
        else:
            result = b""
        if not success:
            view_content = (
                f'{speak} \\n <span style="color:red">ERROR!</span>'
                f"{err_msg} \n {result.decode('utf-8')}"
            )
            raise AppActionException("Generate view content failed", view_content)
        else:
            return speak + "\n" + result.decode("utf-8")
