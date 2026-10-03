import unittest
from types import SimpleNamespace

import pandas as pd

from dbgpt_app.scene.chat_db.auto_execute.analysis_report import build_analysis_report
from dbgpt_app.scene.chat_db.auto_execute.chat import ChatWithDbAutoExecute
from dbgpt_app.scene.chat_db.auto_execute.out_parser import (
    DbChatOutputParser,
    SqlAction,
    _normalize_display_type,
    _infer_display_type,
)


class AnalysisReportTest(unittest.TestCase):
    def test_report_contains_query_summary_and_preview(self):
        report = build_analysis_report(
            "What is revenue by region?",
            "SELECT region, SUM(revenue) AS total FROM orders GROUP BY region",
            pd.DataFrame({"region": ["East", "West"], "total": [100.0, 50.0]}),
        )
        self.assertIn("查询口径", report)
        self.assertIn("数值摘要", report)
        self.assertIn("East", report)
        self.assertIn("75", report)

    def test_empty_result_is_explicit(self):
        report = build_analysis_report("No rows", "SELECT 1 WHERE 0", pd.DataFrame())
        self.assertIn("查询未返回数据", report)

    def test_value_hints_are_bounded_and_include_real_samples(self):
        instance = ChatWithDbAutoExecute.__new__(ChatWithDbAutoExecute)
        instance.curr_config = SimpleNamespace(
            value_hint_max_tables=1, value_hint_rows=3, value_hint_max_values=2
        )
        instance.database = SimpleNamespace(
            dialect="sqlite",
            run_to_df=lambda _sql: pd.DataFrame(
                {"status": ["F", "Y", "F"], "name": ["a", "b", "c"]}
            ),
        )
        hints, catalog, table_count, column_count = instance._collect_value_hints(
            [("orders(status,name)",), ("ignored(id)",)]
        )
        self.assertIn("orders.status: 'F', 'Y'", hints)
        self.assertEqual(catalog["orders.status"], {"F", "Y"})
        self.assertEqual(table_count, 1)
        self.assertEqual(column_count, 2)

    def test_ambiguous_semantics_block_sql_execution_and_ask_user(self):
        def should_not_execute(_sql):
            raise AssertionError("ambiguous semantic query must not execute")

        should_not_execute.__dbgpt_semantic_decision__ = {
            "status": "clarification_required",
            "candidates": ["schools.Virtual"],
        }
        result = DbChatOutputParser().parse_view_response(
            "Which schools are virtual?",
            should_not_execute,
            SqlAction("SELECT * FROM schools", {}, "Table", ""),
        )
        self.assertIn("暂不执行 SQL", result)
        self.assertIn("schools.Virtual", result)

    def test_data_question_cannot_return_ungrounded_direct_answer(self):
        with self.assertRaises(Exception):
            DbChatOutputParser().parse_view_response(
                "How many schools are there?",
                lambda _sql: [],
                SqlAction("", {}, "Table", "There are 3 schools."),
            )

    def test_chart_labels_are_normalized(self):
        self.assertEqual(_normalize_display_type("Bar chart"), "response_bar_chart")
        self.assertEqual(_normalize_display_type("line"), "response_line_chart")

    def test_chart_type_fallback_follows_generic_question_intent(self):
        self.assertEqual(
            _infer_display_type("Compare revenue by region", "", 3),
            "response_bar_chart",
        )
        self.assertEqual(
            _infer_display_type("Show the trend over time", "Table", 3),
            "response_line_chart",
        )
        self.assertEqual(_infer_display_type("Compare revenue", "", 1), "response_table")

    def test_grouping_context_allows_chart_payload(self):
        def execute(_sql):
            return pd.DataFrame({"gender": ["F", "M"], "client_count": [10, 8]})

        execute.__dbgpt_semantic_decision__ = {
            "status": "contextual",
            "candidates": [],
        }
        execute.__dbgpt_semantic_intent__ = {
            "status": "contextual",
            "fields": [{"table": "client", "column": "gender"}],
        }
        result = DbChatOutputParser().parse_view_response(
            "Compare the number of clients by gender and show a bar chart.",
            execute,
            SqlAction(
                "SELECT gender, COUNT(*) AS client_count FROM client GROUP BY gender",
                {},
                "",
                "",
            ),
        )
        result_text = result.decode("utf-8") if isinstance(result, bytes) else result
        self.assertIn("response_bar_chart", result_text)
        self.assertIn("analysis_report", result_text)


if __name__ == "__main__":
    unittest.main()
