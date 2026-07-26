"""One explicit mapping between the supplied CSV files and SQLite tables.

This module is deliberately small: it does not guess source columns or create
data. It validates the known CSV shape and normalizes values before insertion.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class DatasetMappingError(ValueError):
    """Raised when a source file cannot be safely mapped to the schema."""

    def __init__(self, message: str, column: str | None = None) -> None:
        super().__init__(message)
        self.column = column


@dataclass(frozen=True)
class TableMapping:
    """Describes one CSV file, its destination table, and value conversions."""

    source_file: str
    table_name: str
    columns: tuple[str, ...]
    primary_key: str
    nullable_columns: frozenset[str] = frozenset()
    numeric_columns: frozenset[str] = frozenset()
    boolean_columns: frozenset[str] = frozenset()
    date_columns: frozenset[str] = frozenset()
    datetime_columns: frozenset[str] = frozenset()
    source_date_formats: tuple[tuple[str, str], ...] = ()

    @property
    def date_format_by_column(self) -> dict[str, str]:
        return dict(self.source_date_formats)


TABLE_MAPPINGS: tuple[TableMapping, ...] = (
    TableMapping(
        source_file="customers.csv",
        table_name="customers",
        primary_key="customer_id",
        columns=(
            "customer_id", "full_name", "date_of_birth", "nationality",
            "country_of_residence", "customer_type", "occupation", "employer_name",
            "annual_income_declared_gbp", "source_of_funds_declared", "onboarding_date",
            "kyc_status", "kyc_last_reviewed", "kyc_document_type",
            "kyc_document_expiry", "pep_flag", "sanctions_flag", "risk_rating",
            "address", "address_country",
        ),
        numeric_columns=frozenset({"annual_income_declared_gbp"}),
        boolean_columns=frozenset({"pep_flag", "sanctions_flag"}),
        date_columns=frozenset({
            "date_of_birth", "onboarding_date", "kyc_last_reviewed", "kyc_document_expiry",
        }),
    ),
    TableMapping(
        source_file="accounts.csv",
        table_name="accounts",
        primary_key="account_id",
        columns=(
            "account_id", "customer_id", "account_type", "currency", "account_status",
            "opening_date", "last_activity_date", "average_monthly_balance_gbp", "iban",
        ),
        numeric_columns=frozenset({"average_monthly_balance_gbp"}),
        date_columns=frozenset({"opening_date", "last_activity_date"}),
        source_date_formats=(
            ("opening_date", "%d-%m-%Y"),
            ("last_activity_date", "%d-%m-%Y"),
        ),
    ),
    TableMapping(
        source_file="transactions.csv",
        table_name="transactions",
        primary_key="transaction_id",
        columns=(
            "transaction_id", "account_id", "transaction_datetime", "transaction_type",
            "direction", "amount_gbp", "original_amount", "original_currency",
            "counterparty_name", "counterparty_account_id", "counterparty_bank_bic",
            "counterparty_country", "counterparty_is_high_risk_jurisdiction",
            "payment_reference", "channel", "is_international", "transaction_status",
        ),
        nullable_columns=frozenset({"payment_reference"}),
        numeric_columns=frozenset({"amount_gbp", "original_amount"}),
        boolean_columns=frozenset({
            "counterparty_is_high_risk_jurisdiction", "is_international",
        }),
        datetime_columns=frozenset({"transaction_datetime"}),
    ),
    TableMapping(
        source_file="aml_alerts_history.csv",
        table_name="aml_alerts_history",
        primary_key="alert_id",
        columns=(
            "alert_id", "customer_id", "alert_date", "alert_type", "rules_triggered",
            "disposition", "sar_filed", "sar_reference", "analyst_notes",
        ),
        nullable_columns=frozenset({"sar_reference"}),
        boolean_columns=frozenset({"sar_filed"}),
        date_columns=frozenset({"alert_date"}),
    ),
    TableMapping(
        source_file="watchlists.csv",
        table_name="watchlists",
        primary_key="watchlist_id",
        columns=(
            "watchlist_id", "entity_name", "aliases", "entity_type", "watchlist_type",
            "source", "listed_date", "country_of_incorporation", "country_of_operation",
            "risk_score", "is_absolute_prohibition", "status", "last_reviewed_date",
            "review_due_date", "related_entity_id", "notes",
        ),
        nullable_columns=frozenset({"related_entity_id"}),
        numeric_columns=frozenset({"risk_score"}),
        boolean_columns=frozenset({"is_absolute_prohibition"}),
        date_columns=frozenset({"listed_date", "last_reviewed_date", "review_due_date"}),
    ),
)


def resolve_dataset_path(dataset_path: str | Path | None = None) -> Path:
    """Resolve a supplied path or the DATASET_PATH environment variable."""

    candidate = dataset_path or os.getenv("DATASET_PATH")
    if not candidate:
        raise DatasetMappingError(
            "Dataset path is required. Pass --dataset-path or set DATASET_PATH."
        )

    path = Path(candidate).expanduser()
    if not path.is_dir():
        raise DatasetMappingError(f"Dataset directory does not exist: {path}")
    return path


def read_source_rows(mapping: TableMapping, dataset_path: Path) -> list[dict[str, str]]:
    """Read one CSV and require the exact source columns documented in Phase 2A."""

    source_path = dataset_path / mapping.source_file
    if not source_path.is_file():
        raise DatasetMappingError(f"Required source file is missing: {source_path}")

    with source_path.open("r", encoding="utf-8-sig", newline="") as source_file:
        reader = csv.DictReader(source_file)
        actual_columns = tuple(reader.fieldnames or ())
        expected_columns = mapping.columns

        missing = [column for column in expected_columns if column not in actual_columns]
        unexpected = [column for column in actual_columns if column not in expected_columns]
        if missing or unexpected:
            message_parts = []
            if missing:
                message_parts.append(f"missing columns: {', '.join(missing)}")
            if unexpected:
                message_parts.append(f"unexpected columns: {', '.join(unexpected)}")
            raise DatasetMappingError(
                f"{mapping.source_file} does not match the approved mapping ({'; '.join(message_parts)})."
            )

        return list(reader)


def normalize_row(mapping: TableMapping, source_row: dict[str, str], row_number: int) -> dict[str, Any]:
    """Convert one CSV row into SQLite-ready values with row-level error context."""

    normalized: dict[str, Any] = {}
    for column in mapping.columns:
        raw_value = (source_row.get(column) or "").strip()
        if not raw_value:
            if column in mapping.nullable_columns:
                normalized[column] = None
                continue
            raise DatasetMappingError(
                f"{mapping.source_file}, row {row_number}: required value is blank for '{column}'.",
                column,
            )

        try:
            normalized[column] = normalize_value(mapping, column, raw_value)
        except DatasetMappingError as error:
            raise DatasetMappingError(
                f"{mapping.source_file}, row {row_number}: {error}", error.column or column
            ) from error

    return normalized


def normalize_value(mapping: TableMapping, column: str, raw_value: str) -> Any:
    """Normalize one value while preserving the actual source meaning."""

    if column in mapping.boolean_columns:
        return parse_boolean(raw_value, column)
    if column in mapping.numeric_columns:
        return parse_decimal(raw_value, column)
    if column in mapping.date_columns:
        return parse_date(raw_value, mapping.date_format_by_column.get(column), column)
    if column in mapping.datetime_columns:
        return parse_datetime(raw_value, column)
    return raw_value


def parse_boolean(value: str, column: str) -> int:
    """Convert source True/False-style values to SQLite's 1/0 representation."""

    normalized = value.casefold()
    if normalized in {"true", "1", "yes"}:
        return 1
    if normalized in {"false", "0", "no"}:
        return 0
    raise DatasetMappingError(f"invalid Boolean value '{value}' for '{column}'.", column)


def parse_decimal(value: str, column: str) -> str:
    """Validate a finite number and return canonical text for SQLite NUMERIC affinity."""

    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise DatasetMappingError(f"invalid number '{value}' for '{column}'.", column) from error

    if not number.is_finite():
        raise DatasetMappingError(f"non-finite number '{value}' for '{column}'.", column)
    return format(number, "f")


def parse_date(value: str, source_format: str | None, column: str) -> str:
    """Parse a known source date and return normalized ISO date text."""

    try:
        parsed = datetime.strptime(value, source_format).date() if source_format else date.fromisoformat(value)
    except ValueError as error:
        expected = source_format or "YYYY-MM-DD"
        raise DatasetMappingError(
            f"invalid date '{value}' for '{column}'; expected {expected}.", column
        ) from error
    return parsed.isoformat()


def parse_datetime(value: str, column: str) -> str:
    """Parse an ISO timestamp and return a seconds-precision ISO timestamp."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DatasetMappingError(
            f"invalid ISO timestamp '{value}' for '{column}'.", column
        ) from error
    return parsed.isoformat(sep=" ", timespec="seconds")


def transformed_rows(mapping: TableMapping, dataset_path: Path) -> list[dict[str, Any]]:
    """Read and normalize all rows for a source file."""

    return [
        normalize_row(mapping, row, row_number)
        for row_number, row in enumerate(read_source_rows(mapping, dataset_path), start=2)
    ]


def assert_unique_primary_keys(mapping: TableMapping, rows: list[dict[str, Any]]) -> None:
    """Reject duplicate source IDs before any database write occurs."""

    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for row in rows:
        value = row[mapping.primary_key]
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    if duplicates:
        examples = ", ".join(str(value) for value in sorted(duplicates)[:5])
        raise DatasetMappingError(
            f"{mapping.source_file} has duplicate {mapping.primary_key} value(s): {examples}."
        )
