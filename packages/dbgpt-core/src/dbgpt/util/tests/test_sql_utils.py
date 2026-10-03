import pytest

from dbgpt.util.sql_utils import SqlGuard, remove_sql_comments


class TestRemoveSqlComments:
    """Test cases for the remove_sql_comments method."""

    def test_remove_single_line_comments_basic(self):
        """Test removing basic single-line comments."""
        sql = "SELECT * FROM users -- This is a comment"
        expected = "SELECT * FROM users "
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_single_line_comments_with_newline(self):
        """Test removing single-line comments followed by newline."""
        sql = "SELECT * FROM users -- This is a comment\nWHERE id = 1"
        expected = "SELECT * FROM users WHERE id = 1"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_single_line_comments_at_end(self):
        """Test removing single-line comments at the end of string."""
        sql = "SELECT * FROM users\n-- Final comment"
        expected = "SELECT * FROM users\n"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_multiple_single_line_comments(self):
        """Test removing multiple single-line comments."""
        sql = """SELECT * FROM users -- Comment 1
                 WHERE id = 1 -- Comment 2
                 ORDER BY name -- Comment 3"""
        expected = """SELECT * FROM users                  WHERE id = 1                  ORDER BY name """  # noqa: E501
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_multiline_comments_basic(self):
        """Test removing basic multi-line comments."""
        sql = "SELECT * FROM users /* This is a comment */ WHERE id = 1"
        expected = "SELECT * FROM users  WHERE id = 1"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_multiline_comments_with_newlines(self):
        """Test removing multi-line comments spanning multiple lines."""
        sql = """SELECT * FROM users 
                 /* This is a 
                    multi-line comment */ 
                 WHERE id = 1"""
        expected = """SELECT * FROM users 
                  
                 WHERE id = 1"""
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_multiple_multiline_comments(self):
        """Test removing multiple multi-line comments."""
        sql = "SELECT * /* comment 1 */ FROM users /* comment 2 */ WHERE id = 1"
        expected = "SELECT *  FROM users  WHERE id = 1"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_remove_mixed_comments(self):
        """Test removing both single-line and multi-line comments."""
        sql = """SELECT * FROM users /* multi-line comment */
                 WHERE id = 1 -- single line comment
                 /* another multi-line 
                    comment */
                 ORDER BY name -- final comment"""
        expected = """SELECT * FROM users 
                 WHERE id = 1                  
                 ORDER BY name """
        result = remove_sql_comments(sql)
        assert result == expected

    def test_no_comments_to_remove(self):
        """Test SQL with no comments."""
        sql = "SELECT * FROM users WHERE id = 1 ORDER BY name"
        expected = "SELECT * FROM users WHERE id = 1 ORDER BY name"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_empty_string(self):
        """Test with empty string."""
        sql = ""
        expected = ""
        result = remove_sql_comments(sql)
        assert result == expected

    def test_only_comments(self):
        """Test string with only comments."""
        sql = "-- This is only a comment"
        expected = ""
        result = remove_sql_comments(sql)
        assert result == expected

    def test_only_multiline_comments(self):
        """Test string with only multi-line comments."""
        sql = "/* This is only a multi-line comment */"
        expected = ""
        result = remove_sql_comments(sql)
        assert result == expected

    def test_comments_with_special_characters(self):
        """Test comments containing special characters."""
        sql = "SELECT * FROM users -- Comment with special chars: @#$%^&*()"
        expected = "SELECT * FROM users "
        result = remove_sql_comments(sql)
        assert result == expected

    def test_comments_with_sql_keywords(self):
        """Test comments containing SQL keywords."""
        sql = "SELECT * FROM users -- SELECT * FROM another_table"
        expected = "SELECT * FROM users "
        result = remove_sql_comments(sql)
        assert result == expected

    def test_whitespace_handling(self):
        """Test whitespace handling around comments."""
        sql = "SELECT *    -- comment with spaces   \n    FROM users"
        expected = "SELECT *        FROM users"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_multiline_comment_at_start(self):
        """Test multi-line comment at the beginning."""
        sql = "/* Initial comment */ SELECT * FROM users"
        expected = " SELECT * FROM users"
        result = remove_sql_comments(sql)
        assert result == expected

    def test_multiline_comment_at_end(self):
        """Test multi-line comment at the end."""
        sql = "SELECT * FROM users /* Final comment */"
        expected = "SELECT * FROM users "
        result = remove_sql_comments(sql)
        assert result == expected

    def test_complex_sql_with_comments(self):
        """Test complex SQL statement with various comment types."""
        sql = """
        /* Query to get user information */
        SELECT 
            u.id, -- User ID
            u.name, /* User full name */
            u.email -- Contact email
        FROM users u
        /* Join with posts table */
        LEFT JOIN posts p ON u.id = p.user_id
        WHERE u.active = 1 -- Only active users
        /* Order by creation date */
        ORDER BY u.created_at DESC
        -- Limit results
        LIMIT 10;
        """

        result = remove_sql_comments(sql)

        # Verify that all comments are removed
        assert "--" not in result
        assert "/*" not in result
        assert "*/" not in result

        # Verify that SQL keywords are preserved
        assert "SELECT" in result
        assert "FROM" in result
        assert "WHERE" in result
        assert "ORDER BY" in result
        assert "LIMIT" in result


# 如果需要测试实际的类实例，可以使用以下参数化测试
@pytest.mark.parametrize(
    "sql_input,expected_output",
    [
        ("SELECT * FROM users", "SELECT * FROM users"),
        ("SELECT * FROM users -- comment", "SELECT * FROM users "),
        ("SELECT * /* comment */ FROM users", "SELECT *  FROM users"),
        ("", ""),
        ("-- only comment", ""),
        ("/* only comment */", ""),
    ],
)
def test_remove_sql_comments_parametrized(sql_input, expected_output):
    """Parametrized test for common cases."""

    # 创建测试实例
    class MockClass:
        def _remove_sql_comments(self, sql: str) -> str:
            import re

            sql = re.sub(r"--.*?(\n|$)", "", sql)
            sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
            return sql

    instance = MockClass()
    result = instance._remove_sql_comments(sql_input)
    assert result == expected_output


class TestSqlGuard:
    def test_accepts_read_only_select(self):
        result = SqlGuard().validate("```sql\nSELECT COUNT(*) FROM users;\n```")
        assert result.ok
        assert result.sql == "SELECT COUNT(*) FROM users"

    def test_rejects_write_operations(self):
        result = SqlGuard().validate("DELETE FROM users")
        assert not result.ok
        assert "DELETE" in result.error

    def test_rejects_multiple_statements(self):
        result = SqlGuard().validate("SELECT 1; DROP TABLE users")
        assert not result.ok
        assert "one SQL statement" in result.error

    def test_repairs_detail_query_with_limit_after_execution_error(self):
        calls = []

        def executor(sql):
            calls.append(sql)
            if len(calls) == 1:
                raise RuntimeError("result set too large")
            return [{"id": 1}]

        result, trace = SqlGuard(max_rows=50).execute(
            "SELECT * FROM users", executor, max_retries=1
        )
        assert result == [{"id": 1}]
        assert calls == ["SELECT * FROM users", "SELECT * FROM users LIMIT 50"]
        assert trace.repaired
        assert trace.attempts == 2

    def test_value_catalog_emits_advisory_without_rejecting_query(self):
        guard = SqlGuard()
        result = guard.validate_values(
            "SELECT * FROM orders WHERE orders.status = 'unknown'",
            {"orders.status": {"paid", "cancelled"}},
        )
        assert result.ok
        assert any("verify the filter semantics" in warning for warning in result.warnings)

    def test_value_catalog_accepts_case_insensitive_observed_value(self):
        guard = SqlGuard()
        result = guard.validate_values(
            "SELECT * FROM orders WHERE orders.status = 'PAID'",
            {"orders.status": {"paid", "cancelled"}},
        )
        assert result.ok
        assert not result.warnings

    def test_review_combines_structure_values_and_intent_checks(self):
        result = SqlGuard().review(
            "SELECT * FROM orders WHERE orders.status = 'PAID'",
            schema=["orders(id,status)"],
            value_catalog={"orders.status": {"paid"}},
            question="List orders",
        )
        assert result.ok
        assert not any("verify the filter semantics" in warning for warning in result.warnings)

    def test_catalog_case_normalization_is_a_low_risk_repair(self):
        calls = []

        def executor(sql):
            calls.append(sql)
            return [{"id": 1}] if "'paid'" in sql else []

        result, trace = SqlGuard().execute(
            "SELECT * FROM orders WHERE orders.status = 'PAID'",
            executor,
            value_catalog={"orders.status": {"paid"}},
            question="List orders",
        )
        assert result == [{"id": 1}]
        assert calls == [
            "SELECT * FROM orders WHERE orders.status = 'PAID'",
            "SELECT * FROM orders WHERE orders.status = 'paid'",
        ]
        assert trace.executed_sql.endswith("'paid'")

    def test_rejects_unbalanced_structure(self):
        result = SqlGuard().validate("SELECT * FROM users WHERE id IN (1, 2")
        assert not result.ok
        assert "Unbalanced parentheses" in result.error

    def test_rejects_select_into_as_non_read_only(self):
        result = SqlGuard().validate("SELECT * INTO archive_users FROM users")
        assert not result.ok
        assert "SELECT INTO" in result.error

    def test_records_result_quality_warnings(self):
        result, trace = SqlGuard(max_rows=1).execute(
            "SELECT * FROM users LIMIT 2", lambda _sql: [{"value": 1}, {"value": 2}]
        )
        assert len(result) == 2
        assert any("above configured max" in warning for warning in trace.validation_warnings)

    def test_records_ast_like_structure_for_explainability(self):
        _result, trace = SqlGuard().execute(
            "WITH recent AS (SELECT * FROM orders) "
            "SELECT * FROM recent JOIN users ON recent.user_id = users.id "
            "WHERE users.active = 1 ORDER BY recent.created_at DESC LIMIT 5",
            lambda _sql: [{"id": 1}],
        )
        assert trace.structure["statement_type"] == "WITH"
        assert trace.structure["tables"] == ["orders", "recent", "users"]
        assert trace.structure["has_subquery"]
        assert trace.structure["has_join"]
        assert trace.structure["has_order_by"]
