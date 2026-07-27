"""Controlled customer/KYC evidence retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database import get_connection
from app.tools.common import missing_customer_result, optional_database_path


def get_customer_profile(
    customer_id: str, *, database_path: str | Path | None = None
) -> dict[str, Any]:
    """Fetch the bounded KYC and risk profile for one customer.

    The function selects named fields and parameterizes the customer ID. It
    never exposes a general SQL interface to an LLM.
    """

    with get_connection(optional_database_path(database_path)) as connection:
        row = connection.execute(
            """
            SELECT
                customer_id, full_name, occupation, employer_name,
                annual_income_declared_gbp, source_of_funds_declared,
                kyc_status, kyc_last_reviewed, kyc_document_expiry,
                pep_flag, sanctions_flag, risk_rating,
                country_of_residence, address_country
            FROM customers
            WHERE customer_id = ?
            """,
            (customer_id,),
        ).fetchone()

    if row is None:
        return missing_customer_result(customer_id)

    profile = dict(row)
    profile["annual_income_declared_gbp"] = float(profile["annual_income_declared_gbp"])
    profile["pep_flag"] = bool(profile["pep_flag"])
    profile["sanctions_flag"] = bool(profile["sanctions_flag"])

    return {
        "customer_id": customer_id,
        "found": True,
        "source_table": "customers",
        "profile": profile,
    }
