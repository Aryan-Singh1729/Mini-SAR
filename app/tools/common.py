"""Shared helpers for controlled AML evidence tools."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any


def missing_customer_result(customer_id: str) -> dict[str, Any]:
    """Return a safe, JSON-ready result when a requested customer is absent."""

    return {
        "customer_id": customer_id,
        "found": False,
        "message": "No customer exists for the supplied customer_id.",
    }


def customer_exists(connection: sqlite3.Connection, customer_id: str) -> bool:
    """Check customer existence without exposing any customer fields."""

    return connection.execute(
        "SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone() is not None


def parse_iso_date(value: str | date) -> date:
    """Accept an ISO date string or date object for tool boundaries."""

    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def optional_database_path(database_path: str | Path | None) -> str | Path | None:
    """Keep tool signatures readable while allowing isolated database tests."""

    return database_path
