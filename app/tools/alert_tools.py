"""Controlled retrieval of bounded prior AML alert history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database import get_connection
from app.tools.common import customer_exists, missing_customer_result, optional_database_path


MAX_PRIOR_ALERTS = 10


def get_prior_alert_history(
    customer_id: str, *, database_path: str | Path | None = None
) -> dict[str, Any]:
    """Return bounded prior alerts, SAR status, and false-positive context."""

    with get_connection(optional_database_path(database_path)) as connection:
        if not customer_exists(connection, customer_id):
            return missing_customer_result(customer_id)

        rows = connection.execute(
            """
            SELECT
                alert_id, alert_date, alert_type, rules_triggered,
                disposition, sar_filed, sar_reference, analyst_notes
            FROM aml_alerts_history
            WHERE customer_id = ?
            ORDER BY alert_date DESC, alert_id DESC
            LIMIT ?
            """,
            (customer_id, MAX_PRIOR_ALERTS),
        ).fetchall()

    history = []
    for row in rows:
        item = dict(row)
        item["sar_filed"] = bool(item["sar_filed"])
        history.append(item)

    false_positive_context = [
        {
            "alert_id": item["alert_id"],
            "alert_date": item["alert_date"],
            "analyst_note": item["analyst_notes"],
        }
        for item in history
        if item["disposition"] == "FALSE_POSITIVE"
    ]

    return {
        "customer_id": customer_id,
        "found": True,
        "source_table": "aml_alerts_history",
        "returned_alert_count": len(history),
        "history_limit": MAX_PRIOR_ALERTS,
        "sar_previously_filed": any(item["sar_filed"] for item in history),
        "prior_alerts": history,
        "false_positive_context": false_positive_context,
    }
