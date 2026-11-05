"""Tools: read-only SQL is enforced by the SQLite authorizer, not by prose."""
from __future__ import annotations

import pytest

from jevrag.llm import MockLLM
from jevrag.tools import (ToolContext, ToolError, _haversine, execute, run_none,
                          run_search, run_sql)


class SqlScripted:
    """Returns a fixed SQL statement for the sql tool's generation call."""
    model = "sql-scripted"

    def __init__(self, sql):
        self.sql = sql

    def chat(self, *args, **kwargs):
        import json
        return json.dumps({"sql": self.sql})


def _ctx(demo_dataset, sql="SELECT * FROM city_poi LIMIT 10"):
    return ToolContext(dataset=demo_dataset, llm=SqlScripted(sql))


class TestSql:
    def test_select_runs_and_reports_rows(self, demo_dataset):
        result = run_sql("list pois", _ctx(demo_dataset))
        assert result.status == "success"
        assert len(result.rows) == 3
        assert result.evidence and result.evidence[0]["source"] == "sql"

    def test_empty_result_is_status_empty(self, demo_dataset):
        result = run_sql("x", _ctx(demo_dataset,
                                   "SELECT * FROM city_poi WHERE name = 'nope'"))
        assert result.status == "empty"
        assert result.rows == []

    def test_rejects_insert(self, demo_dataset):
        with pytest.raises(ToolError, match="only SELECT/WITH"):
            run_sql("x", _ctx(demo_dataset, "INSERT INTO city_poi VALUES ('x')"))

    def test_rejects_multi_statement(self, demo_dataset):
        with pytest.raises(ToolError, match="multiple statements"):
            run_sql("x", _ctx(demo_dataset, "SELECT 1; DROP TABLE city_poi"))

    def test_authorizer_blocks_ddl_even_past_the_regex(self, demo_dataset):
        # CREATE slips through the SELECT regex check only via WITH... but the
        # authorizer must still deny anything non-read. A bare DELETE-style
        # statement is caught by regex; here we assert the authorizer denies
        # directly through the connection.
        conn = demo_dataset.connect()
        with pytest.raises(Exception):
            conn.execute("DELETE FROM city_poi")

    def test_bad_sql_becomes_error_branch(self, demo_dataset):
        result = run_sql("x", _ctx(demo_dataset, "SELECT nope FROM city_poi"))
        assert result.status == "error"
        assert "SQL failed" in result.summary

    def test_generation_failure_raises_tool_error(self, demo_dataset):
        class Boom:
            model = "boom"
            def chat(self, *a, **k):
                from jevrag.llm import LLMError
                raise LLMError("provider down")

        with pytest.raises(ToolError, match="generation failed"):
            run_sql("x", ToolContext(dataset=demo_dataset, llm=Boom()))


class TestSearchAndNone:
    def test_search_finds_sources(self, demo_dataset):
        result = run_search("park cafe west end", _ctx(demo_dataset))
        assert result.status == "success"
        assert result.evidence and result.evidence[0]["source"] == "search"

    def test_search_empty(self, demo_dataset):
        result = run_search("zzzz qqqq", _ctx(demo_dataset))
        assert result.status == "empty"

    def test_none_is_pure_reasoning(self, demo_dataset):
        result = run_none("compare the two findings", _ctx(demo_dataset))
        assert result.status == "success"
        assert result.evidence == []


class TestExecute:
    def test_unknown_tool(self, demo_dataset):
        with pytest.raises(ToolError, match="unknown tool"):
            execute("shell", "rm -rf /", _ctx(demo_dataset))

    def test_tool_crash_becomes_error_branch(self, demo_dataset):
        class Bad:
            model = "bad"
            def chat(self, *a, **k):
                raise RuntimeError("kaboom")

        result = execute("sql", "x", ToolContext(dataset=demo_dataset, llm=Bad()))
        assert result.status == "error"
        assert "RuntimeError" in result.summary

    def test_mock_llm_end_to_end_sql(self, demo_dataset):
        result = execute("sql", "list everything",
                         ToolContext(dataset=demo_dataset, llm=MockLLM()))
        assert result.status == "success"


class TestHaversine:
    def test_zero_distance(self):
        assert _haversine(41.88, -87.63, 41.88, -87.63) == pytest.approx(0.0)

    def test_known_distance(self):
        # ~1.4 km between two close points in the demo data region.
        metres = _haversine(41.8895, -87.6412, 41.8877, -87.6445)
        assert 300 < metres < 400

    def test_usable_in_sql(self, demo_dataset):
        result = run_sql(
            "near", _ctx(demo_dataset,
                         "SELECT name, haversine(lat, lon, 41.8895, -87.6412) AS d "
                         "FROM city_poi ORDER BY d LIMIT 3"))
        assert result.status == "success"
        assert len(result.rows) == 3
        assert result.rows[0]["d"] == pytest.approx(0.0, abs=1.0)
