"""Controlled account-summary retrieval and deterministic activity-age calculation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.tools.common import (
    customer_exists,
    missing_customer_result,
    optional_database_path,
    parse_iso_date,
)


def get_account_summary(
    customer_id: str,
    *,
    as_of_date: str | date | None = None,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a customer's accounts with deterministic days-since-activity values."""

    reference_date = parse_iso_date(as_of_date) if as_of_date else date.today()

    with get_connection(optional_database_path(database_path)) as connection:
        if not customer_exists(connection, customer_id):
            return missing_customer_result(customer_id)

        rows = connection.execute(
            """
            SELECT
                account_id, account_type, currency, account_status,
                opening_date, last_activity_date, average_monthly_balance_gbp
            FROM accounts
            WHERE customer_id = ?
            ORDER BY opening_date, account_id
            """,
            (customer_id,),
        ).fetchall()

    accounts = []
    for row in rows:
        account = dict(row)
        last_activity = parse_iso_date(account["last_activity_date"])
        account["average_monthly_balance_gbp"] = float(
            account["average_monthly_balance_gbp"]
        )
        account["days_since_last_activity"] = max(
            (reference_date - last_activity).days, 0
        )
        accounts.append(account)

    return {
        "customer_id": customer_id,
        "found": True,
        "source_table": "accounts",
        "as_of_date": reference_date.isoformat(),
        "account_count": len(accounts),
        "accounts": accounts,
    }
