"""Bounded transaction retrieval and deterministic AML pre-signal calculations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.tools.common import (
    customer_exists,
    missing_customer_result,
    optional_database_path,
    parse_iso_date,
)


STRUCTURING_REPORTING_THRESHOLD_GBP = 10_000.00
STRUCTURING_NEAR_THRESHOLD_FLOOR_GBP = 8_000.00
STRUCTURING_WINDOW_DAYS = 7
STRUCTURING_MINIMUM_CREDITS = 3
RAPID_MOVEMENT_DAYS = 2
RAPID_OUTFLOW_RATIO = 0.80
INCOME_MISMATCH_CREDIT_RATIO = 0.50
MAX_IMPORTANT_TRANSACTIONS = 12
MAX_RAPID_OUTFLOW_PAIRS = 5


def get_transaction_history(
    customer_id: str,
    observation_start: str,
    observation_end: str,
    *,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a bounded transaction summary and deterministic risk pre-signals.

    The LLM receives totals, explicitly defined signals, and at most twelve
    selected material transactions. It never receives unrestricted raw history.
    """

    try:
        start_date = parse_iso_date(observation_start)
        end_date = parse_iso_date(observation_end)
    except ValueError:
        return {
            "customer_id": customer_id,
            "found": False,
            "error": "observation_start and observation_end must use YYYY-MM-DD.",
        }

    if start_date > end_date:
        return {
            "customer_id": customer_id,
            "found": False,
            "error": "observation_start must be on or before observation_end.",
        }

    start_boundary = f"{start_date.isoformat()} 00:00:00"
    end_boundary = f"{(end_date + timedelta(days=1)).isoformat()} 00:00:00"

    with get_connection(optional_database_path(database_path)) as connection:
        customer = connection.execute(
            """
            SELECT annual_income_declared_gbp
            FROM customers
            WHERE customer_id = ?
            """,
            (customer_id,),
        ).fetchone()
        if customer is None:
            return missing_customer_result(customer_id)

        rows = connection.execute(
            """
            SELECT
                t.transaction_id, t.account_id, t.transaction_datetime,
                t.transaction_type, t.direction, t.amount_gbp,
                t.counterparty_name, t.counterparty_country,
                t.counterparty_is_high_risk_jurisdiction, t.channel,
                t.is_international, t.transaction_status
            FROM transactions AS t
            INNER JOIN accounts AS a ON a.account_id = t.account_id
            WHERE a.customer_id = ?
              AND t.transaction_status = 'COMPLETED'
              AND t.transaction_datetime >= ?
              AND t.transaction_datetime < ?
            ORDER BY t.transaction_datetime, t.transaction_id
            """,
            (customer_id, start_boundary, end_boundary),
        ).fetchall()

    transactions = [_transaction_from_row(row) for row in rows]
    total_credits = round(
        sum(item["amount_gbp"] for item in transactions if item["direction"] == "CREDIT"), 2
    )
    total_debits = round(
        sum(item["amount_gbp"] for item in transactions if item["direction"] == "DEBIT"), 2
    )
    net_retained_amount = round(max(total_credits - total_debits, 0), 2)
    retention_ratio = round(net_retained_amount / total_credits, 4) if total_credits else 0.0

    structuring = _structuring_signal(transactions)
    rapid_outflow = _rapid_outflow_signal(transactions)
    declared_income = float(customer["annual_income_declared_gbp"])
    income_ratio = round(total_credits / declared_income, 4) if declared_income else None
    income_mismatch = bool(
        declared_income and total_credits >= declared_income * INCOME_MISMATCH_CREDIT_RATIO
    )

    important_transactions = _select_important_transactions(
        transactions,
        structuring["transaction_ids"],
        rapid_outflow["transaction_ids"],
    )

    return {
        "customer_id": customer_id,
        "found": True,
        "source_table": "transactions",
        "observation_window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "summary": {
            "total_credits": total_credits,
            "total_debits": total_debits,
            "transaction_count": len(transactions),
            "net_retained_amount": net_retained_amount,
            "retention_ratio": retention_ratio,
            "structuring_presignal": structuring["detected"],
            "rapid_outflow_detected": rapid_outflow["detected"],
            "income_mismatch": income_mismatch,
        },
        "signal_details": {
            "structuring": structuring,
            "rapid_outflow": rapid_outflow,
            "income_mismatch": {
                "detected": income_mismatch,
                "declared_annual_income_gbp": declared_income,
                "window_credit_to_income_ratio": income_ratio,
                "policy_credit_ratio_threshold": INCOME_MISMATCH_CREDIT_RATIO,
            },
        },
        "selected_transaction_count": len(important_transactions),
        "selection_policy": (
            "Signal-linked transactions first, then highest-value remaining transactions; "
            f"maximum {MAX_IMPORTANT_TRANSACTIONS} records."
        ),
        "important_transactions": important_transactions,
    }


def _transaction_from_row(row: Any) -> dict[str, Any]:
    transaction = dict(row)
    transaction["amount_gbp"] = float(transaction["amount_gbp"])
    transaction["counterparty_is_high_risk_jurisdiction"] = bool(
        transaction["counterparty_is_high_risk_jurisdiction"]
    )
    transaction["is_international"] = bool(transaction["is_international"])
    transaction["parsed_datetime"] = datetime.fromisoformat(transaction["transaction_datetime"])
    return transaction


def _structuring_signal(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        transaction
        for transaction in transactions
        if transaction["direction"] == "CREDIT"
        and STRUCTURING_NEAR_THRESHOLD_FLOOR_GBP <= transaction["amount_gbp"]
        < STRUCTURING_REPORTING_THRESHOLD_GBP
    ]

    best_window: list[dict[str, Any]] = []
    for candidate in candidates:
        window_end = candidate["parsed_datetime"] + timedelta(days=STRUCTURING_WINDOW_DAYS)
        current_window = [
            item
            for item in candidates
            if candidate["parsed_datetime"] <= item["parsed_datetime"] <= window_end
        ]
        if len(current_window) > len(best_window):
            best_window = current_window

    return {
        "detected": len(best_window) >= STRUCTURING_MINIMUM_CREDITS,
        "reporting_threshold_gbp": STRUCTURING_REPORTING_THRESHOLD_GBP,
        "near_threshold_floor_gbp": STRUCTURING_NEAR_THRESHOLD_FLOOR_GBP,
        "window_days": STRUCTURING_WINDOW_DAYS,
        "minimum_credit_count": STRUCTURING_MINIMUM_CREDITS,
        "candidate_credit_count": len(candidates),
        "largest_window_credit_count": len(best_window),
        "transaction_ids": [item["transaction_id"] for item in best_window],
        "amounts": [item["amount_gbp"] for item in best_window],
    }


def _rapid_outflow_signal(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    credits = [item for item in transactions if item["direction"] == "CREDIT"]
    debits = [item for item in transactions if item["direction"] == "DEBIT"]
    pairs = []

    for credit in credits:
        for debit in debits:
            time_difference = debit["parsed_datetime"] - credit["parsed_datetime"]
            if (
                debit["account_id"] == credit["account_id"]
                and timedelta(0) <= time_difference <= timedelta(days=RAPID_MOVEMENT_DAYS)
                and debit["amount_gbp"] >= credit["amount_gbp"] * RAPID_OUTFLOW_RATIO
            ):
                pairs.append(
                    {
                        "credit_transaction_id": credit["transaction_id"],
                        "credit_amount_gbp": credit["amount_gbp"],
                        "debit_transaction_id": debit["transaction_id"],
                        "debit_amount_gbp": debit["amount_gbp"],
                        "hours_between": round(time_difference.total_seconds() / 3600, 2),
                        "counterparty_name": debit["counterparty_name"],
                    }
                )
                break

    selected_pairs = pairs[:MAX_RAPID_OUTFLOW_PAIRS]
    transaction_ids = []
    for pair in selected_pairs:
        transaction_ids.extend([pair["credit_transaction_id"], pair["debit_transaction_id"]])

    return {
        "detected": bool(pairs),
        "window_days": RAPID_MOVEMENT_DAYS,
        "minimum_debit_to_credit_ratio": RAPID_OUTFLOW_RATIO,
        "pair_count": len(pairs),
        "pairs": selected_pairs,
        "transaction_ids": transaction_ids,
    }


def _select_important_transactions(
    transactions: list[dict[str, Any]],
    structuring_ids: list[str],
    rapid_outflow_ids: list[str],
) -> list[dict[str, Any]]:
    selected_ids: list[str] = []
    for transaction_id in structuring_ids + rapid_outflow_ids:
        if transaction_id not in selected_ids:
            selected_ids.append(transaction_id)

    for transaction in sorted(
        transactions,
        key=lambda item: (item["amount_gbp"], item["transaction_datetime"]),
        reverse=True,
    ):
        if transaction["transaction_id"] not in selected_ids:
            selected_ids.append(transaction["transaction_id"])
        if len(selected_ids) >= MAX_IMPORTANT_TRANSACTIONS:
            break

    by_id = {item["transaction_id"]: item for item in transactions}
    selected = [by_id[transaction_id] for transaction_id in selected_ids[:MAX_IMPORTANT_TRANSACTIONS]]
    selected.sort(key=lambda item: (item["transaction_datetime"], item["transaction_id"]))

    return [
        {
            key: value
            for key, value in transaction.items()
            if key != "parsed_datetime"
        }
        for transaction in selected
    ]
