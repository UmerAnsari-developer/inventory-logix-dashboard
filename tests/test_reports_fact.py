"""Tests for the reports endpoint focusing on fact-table usage and performance."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import pytest


def test_reports_endpoint_returns_success(auth_client):
    """Ensure reports endpoint returns a successful HTML response when logged in."""
    resp = auth_client.get("/reports")
    assert resp.status_code == 200
    assert b"Analytics & Reports" in resp.data  # Check for title in HTML


def test_reports_endpoint_uses_fact_tables(auth_client):
    """Verify that the reports endpoint queries fact tables when filters are applied."""
    from app.database.connection import etl_database
    from app.utils.cache import reports_cache

    # Ensure fact tables are populated
    with auth_client.application.app_context():
        etl_result = etl_database(force=True)
        assert not etl_result["skipped"], "ETL should have run and populated fact tables"
        reports_cache.invalidate("")

    # We will monkey-patch get_cursor in the ui routes module to capture SQL
    executed_queries = []

    def mock_get_cursor(commit=False):
        # Get a real cursor context manager from the real get_cursor
        from app.database import get_cursor as real_get_cursor
        real_cm = real_get_cursor(commit=commit)

        @contextmanager
        def logging_cm():
            with real_cm as real_cur:
                class LoggingCursor:
                    def __init__(self, cursor):
                        self.cursor = cursor

                    def execute(self, sql, params=()):
                        executed_queries.append((sql.strip(), params))
                        return self.cursor.execute(sql, params)

                    def fetchall(self):
                        return self.cursor.fetchall()

                    def fetchone(self):
                        return self.cursor.fetchone()

                yield LoggingCursor(real_cur)

        return logging_cm()

    # Patch the get_cursor function in the ui routes module
    with patch("app.routes.ui.get_cursor", side_effect=mock_get_cursor):
        # Define filter parameters for the current month
        today = date.today()
        month_json = json.dumps([str(today.month)])
        year_json = json.dumps([str(today.year)])
        warehouse_json = json.dumps([])
        category_json = json.dumps([])

        # Make request to reports endpoint with filters
        resp = auth_client.get(
            f"/reports?month_json={month_json}&year_json={year_json}"
            f"&warehouse_json={warehouse_json}&category_json={category_json}"
        )
        assert resp.status_code == 200

    # Check that at least one executed query references the fact table
    fact_table_used = any(
        "fact_movement_daily" in sql.lower() for sql, _ in executed_queries
    )
    assert fact_table_used, (
        "Expected at least one query to reference fact_movement_daily. "
        f"Executed queries: {[sql for sql, _ in executed_queries]}"
    )


def test_reports_endpoint_uses_dimension_tables(auth_client):
    """Verify that the reports endpoint joins to dimension tables."""
    from app.database.connection import etl_database
    from app.utils.cache import reports_cache

    with auth_client.application.app_context():
        etl_database(force=True)
        reports_cache.invalidate("")

    executed_queries = []

    def mock_get_cursor(commit=False):
        from app.database import get_cursor as real_get_cursor
        real_cm = real_get_cursor(commit=commit)

        @contextmanager
        def logging_cm():
            with real_cm as real_cur:
                class LoggingCursor:
                    def __init__(self, cursor):
                        self.cursor = cursor

                    def execute(self, sql, params=()):
                        executed_queries.append((sql.strip(), params))
                        return self.cursor.execute(sql, params)

                    def fetchall(self):
                        return self.cursor.fetchall()

                    def fetchone(self):
                        return self.cursor.fetchone()

                yield LoggingCursor(real_cur)

        return logging_cm()

    with patch("app.routes.ui.get_cursor", side_effect=mock_get_cursor):
        today = date.today()
        month_json = json.dumps([str(today.month)])
        year_json = json.dumps([str(today.year)])
        warehouse_json = json.dumps([])
        category_json = json.dumps([])

        resp = auth_client.get(
            f"/reports?month_json={month_json}&year_json={year_json}"
            f"&warehouse_json={warehouse_json}&category_json={category_json}"
        )
        assert resp.status_code == 200

    # Check for joins to dimension tables
    dimension_joins = []
    for sql, _ in executed_queries:
        sql_lower = sql.lower()
        if "dim_product" in sql_lower or "dim_warehouse" in sql_lower or "dim_date" in sql_lower:
            dimension_joins.append(sql)

    assert dimension_joins, (
        "Expected at least one query to join with dimension tables. "
        f"Executed queries: {[sql for sql, _ in executed_queries]}"
    )