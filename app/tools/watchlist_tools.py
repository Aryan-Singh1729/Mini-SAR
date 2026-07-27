"""Controlled customer/counterparty screening against the imported watchlist."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.tools.common import missing_customer_result, optional_database_path


FUZZY_JACCARD_THRESHOLD = 0.60
MAX_WATCHLIST_MATCHES = 10
METHOD_PRIORITY = {"exact": 3, "alias": 2, "fuzzy_token_jaccard": 1}


def screen_watchlist(
    customer_id: str, *, database_path: str | Path | None = None
) -> dict[str, Any]:
    """Screen one customer and their counterparties using controlled matching rules.

    Exact and alias matches score 1.0. Fuzzy matches use Jaccard similarity of
    normalized name tokens and are explicitly labeled as proximity, not proof.
    """

    with get_connection(optional_database_path(database_path)) as connection:
        customer = connection.execute(
            "SELECT full_name FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        if customer is None:
            return missing_customer_result(customer_id)

        counterparties = connection.execute(
            """
            SELECT DISTINCT t.counterparty_name
            FROM transactions AS t
            INNER JOIN accounts AS a ON a.account_id = t.account_id
            WHERE a.customer_id = ?
              AND t.counterparty_name <> ''
            ORDER BY t.counterparty_name
            """,
            (customer_id,),
        ).fetchall()
        watchlist_rows = connection.execute(
            """
            SELECT
                watchlist_id, entity_name, aliases, entity_type, watchlist_type,
                source, country_of_operation, risk_score,
                is_absolute_prohibition, status
            FROM watchlists
            WHERE status IN ('ACTIVE', 'UNDER_REVIEW')
            """
        ).fetchall()

    candidates = [("customer", customer["full_name"])] + [
        ("counterparty", row["counterparty_name"]) for row in counterparties
    ]
    matches = []
    for candidate_type, candidate_name in candidates:
        for watchlist_row in watchlist_rows:
            match = _match_name(candidate_name, dict(watchlist_row))
            if match is None:
                continue
            matches.append(
                {
                    "screened_entity_type": candidate_type,
                    "screened_name": candidate_name,
                    "watchlist_id": watchlist_row["watchlist_id"],
                    "watchlist_entity_name": watchlist_row["entity_name"],
                    "match_method": match["method"],
                    "match_score": match["score"],
                    "watchlist_type": watchlist_row["watchlist_type"],
                    "risk_score": int(watchlist_row["risk_score"]),
                    "is_absolute_prohibition": bool(
                        watchlist_row["is_absolute_prohibition"]
                    ),
                    "status": watchlist_row["status"],
                    "country_of_operation": watchlist_row["country_of_operation"],
                    "source": watchlist_row["source"],
                }
            )

    matches.sort(
        key=lambda item: (
            METHOD_PRIORITY[item["match_method"]],
            item["match_score"],
            item["risk_score"],
        ),
        reverse=True,
    )
    matches = matches[:MAX_WATCHLIST_MATCHES]

    return {
        "customer_id": customer_id,
        "found": True,
        "source_tables": ["customers", "transactions", "watchlists"],
        "screening_summary": {
            "customer_name_screened": True,
            "counterparty_count_screened": len(counterparties),
            "watchlist_records_screened": len(watchlist_rows),
            "match_count_returned": len(matches),
            "fuzzy_jaccard_threshold": FUZZY_JACCARD_THRESHOLD,
        },
        "matches": matches,
    }


def _match_name(candidate_name: str, watchlist_row: dict[str, Any]) -> dict[str, Any] | None:
    candidate_normalized = _normalize_name(candidate_name)
    entity_normalized = _normalize_name(watchlist_row["entity_name"])
    aliases = [_normalize_name(alias) for alias in _split_aliases(watchlist_row["aliases"])]

    if candidate_normalized == entity_normalized:
        return {"method": "exact", "score": 1.0}
    if candidate_normalized in aliases:
        return {"method": "alias", "score": 1.0}

    comparison_names = [entity_normalized, *aliases]
    best_score = max(
        (_jaccard_similarity(candidate_normalized, comparison) for comparison in comparison_names),
        default=0.0,
    )
    if best_score >= FUZZY_JACCARD_THRESHOLD:
        return {"method": "fuzzy_token_jaccard", "score": round(best_score, 4)}
    return None


def _split_aliases(aliases: str) -> list[str]:
    """Support the pipe/semicolon alias separators used by structured lists."""

    return [alias.strip() for alias in re.split(r"[|;]", aliases or "") if alias.strip()]


def _normalize_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _jaccard_similarity(first: str, second: str) -> float:
    first_tokens = set(first.split())
    second_tokens = set(second.split())
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)
