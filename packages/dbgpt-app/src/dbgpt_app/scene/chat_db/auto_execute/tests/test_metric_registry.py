from dbgpt_app.scene.chat_db.auto_execute.metric_registry import MetricRegistry


def test_metric_registry_matches_sales_aliases():
    registry = MetricRegistry.default()
    matches = registry.search("What is the total sales by store?")
    assert matches
    assert matches[0].expression == "SUM(Weekly_Sales)"


def test_metric_registry_renders_governed_context():
    context = MetricRegistry.default().render_context("平均销售额是多少？")
    assert "AVG(Weekly_Sales)" in context
    assert "Average Weekly Sales" in context


def test_metric_registry_loads_datasource_specific_json():
    registry = MetricRegistry.for_datasource("orders")
    matches = registry.search("What is the total revenue?")
    assert matches
    assert matches[0].expression == "SUM(revenue)"
    assert matches[0].table == "orders"


def test_metric_registry_falls_back_for_unknown_datasource():
    registry = MetricRegistry.for_datasource("unknown_demo_source")
    assert not registry.search("What is the total sales?")


def test_semantic_decision_requires_explicit_value_mapping():
    registry = MetricRegistry.from_data(
        {
            "fields": [
                {
                    "table": "schools",
                    "column": "Virtual",
                    "description": "Whether the school is virtual",
                    "aliases": ["virtual school"],
                    "value_mapping": {"exclusively virtual": "F"},
                }
            ]
        }
    )
    decision = registry.semantic_decision("Which schools are virtual schools?")
    assert decision["status"] == "clarification_required"
    assert "schools.Virtual" in registry.render_context("Which schools are virtual schools?")


def test_semantic_decision_resolves_governed_concept():
    registry = MetricRegistry.from_data(
        {
            "fields": [
                {
                    "table": "schools",
                    "column": "Virtual",
                    "description": "Whether the school is virtual",
                    "value_mapping": {"exclusively virtual": "F"},
                }
            ]
        }
    )
    decision = registry.semantic_decision("Which schools are exclusively virtual?")
    assert decision["status"] == "resolved"
    assert decision["candidates"][0]["stored_value"] == "F"


def test_field_value_mapping_terms_resolve_semantic_decision():
    registry = MetricRegistry.from_data(
        {
            "fields": [
                {
                    "table": "district",
                    "column": "A3",
                    "description": "Region name",
                    "value_mapping": {"North Bohemia": "north Bohemia"},
                }
            ]
        }
    )
    decision = registry.semantic_decision("customers in North Bohemia")
    assert decision["status"] == "resolved"
    assert decision["candidates"][0]["stored_value"] == "north Bohemia"


def test_canonicalize_sql_applies_governed_value_casing():
    sql = "SELECT * FROM district WHERE A3 = 'North Bohemia'"
    decision = {
        "status": "resolved",
        "candidates": [
            {
                "field": "district.A3",
                "concept": "North Bohemia",
                "stored_value": "north Bohemia",
            }
        ],
    }
    assert "A3 = 'north Bohemia'" in MetricRegistry.canonicalize_sql(sql, decision)


def test_dimension_context_does_not_block_grouping_query():
    registry = MetricRegistry.from_data(
        {
            "fields": [
                {
                    "table": "client",
                    "column": "gender",
                    "description": "Client gender",
                    "aliases": ["gender"],
                    "value_mapping": {"female": "F", "male": "M"},
                }
            ]
        }
    )
    decision = registry.semantic_decision("Compare customer count by gender")
    assert decision["status"] == "contextual"
