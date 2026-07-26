"""Validate the supplied CSV dataset and its imported SQLite representation."""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.database import get_connection, get_database_path
from app.schema_mapper import (
    TABLE_MAPPINGS,
    DatasetMappingError,
    TableMapping,
    read_source_rows,
    resolve_dataset_path,
    normalize_row,
)


@dataclass
class FileValidationResult:
    """Compact, printable validation facts for one CSV file."""

    source_file: str
    row_count: int = 0
    duplicate_primary_keys: int = 0
    missing_required_values: int = 0
    invalid_dates: int = 0
    invalid_other_values: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (
            self.duplicate_primary_keys
            or self.missing_required_values
            or self.invalid_dates
            or self.invalid_other_values
            or self.errors
        )


def validate_source_dataset(dataset_path: str | Path | None = None) -> tuple[
    dict[str, FileValidationResult], dict[str, list[dict[str, str]]]
]:
    """Check CSV shape, counts, missing values, IDs, and parseable fields."""

    source_directory = resolve_dataset_path(dataset_path)
    results: dict[str, FileValidationResult] = {}
    raw_rows_by_table: dict[str, list[dict[str, str]]] = {}

    for mapping in TABLE_MAPPINGS:
        result = FileValidationResult(source_file=mapping.source_file)
        results[mapping.table_name] = result
        try:
            rows = read_source_rows(mapping, source_directory)
        except DatasetMappingError as error:
            result.errors.append(str(error))
            continue

        raw_rows_by_table[mapping.table_name] = rows
        result.row_count = len(rows)
        primary_keys: set[str] = set()

        for row_number, row in enumerate(rows, start=2):
            primary_key = (row.get(mapping.primary_key) or "").strip()
            if primary_key in primary_keys:
                result.duplicate_primary_keys += 1
            primary_keys.add(primary_key)

            missing_columns = [
                column
                for column in mapping.columns
                if not (row.get(column) or "").strip()
                and column not in mapping.nullable_columns
            ]
            result.missing_required_values += len(missing_columns)

            try:
                normalize_row(mapping, row, row_number)
            except DatasetMappingError as error:
                if error.column in mapping.date_columns or error.column in mapping.datetime_columns:
                    result.invalid_dates += 1
                elif not missing_columns:
                    result.invalid_other_values += 1

    return results, raw_rows_by_table


def foreign_key_results(raw_rows_by_table: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    """Count broken source relationships using the documented source keys."""

    required_tables = {"customers", "accounts", "transactions", "aml_alerts_history"}
    if not required_tables.issubset(raw_rows_by_table):
        return {"relationship_checks_skipped": 1}

    customer_ids = {row["customer_id"].strip() for row in raw_rows_by_table["customers"]}
    account_ids = {row["account_id"].strip() for row in raw_rows_by_table["accounts"]}

    return {
        "accounts.customer_id -> customers.customer_id": sum(
            row["customer_id"].strip() not in customer_ids
            for row in raw_rows_by_table["accounts"]
        ),
        "transactions.account_id -> accounts.account_id": sum(
            row["account_id"].strip() not in account_ids
            for row in raw_rows_by_table["transactions"]
        ),
        "aml_alerts_history.customer_id -> customers.customer_id": sum(
            row["customer_id"].strip() not in customer_ids
            for row in raw_rows_by_table["aml_alerts_history"]
        ),
    }


def validate_imported_database(
    database_path: str | Path | None,
    expected_counts: dict[str, int],
) -> tuple[dict[str, int], list[tuple[Any, ...]]]:
    """Compare imported row counts and ask SQLite to report FK violations."""

    path = get_database_path(database_path)
    if not path.is_file():
        return {}, [("database_missing", str(path))]

    with get_connection(path) as connection:
        imported_counts = {
            mapping.table_name: connection.execute(
                f"SELECT COUNT(*) FROM {mapping.table_name}"
            ).fetchone()[0]
            for mapping in TABLE_MAPPINGS
        }
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    mismatches = [
        (table_name, expected_counts[table_name], actual_count)
        for table_name, actual_count in imported_counts.items()
        if expected_counts.get(table_name) != actual_count
    ]
    return imported_counts, [tuple(item) for item in foreign_key_violations] + mismatches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate AML CSV source files and SQLite import.")
    parser.add_argument("--dataset-path", help="Folder containing the five source CSV files.")
    parser.add_argument("--database-path", help="Optional SQLite database path to compare after import.")
    parser.add_argument(
        "--skip-database-check",
        action="store_true",
        help="Validate source CSV files only; do not inspect SQLite.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        results, raw_rows = validate_source_dataset(args.dataset_path)
    except DatasetMappingError as error:
        print(f"VALIDATION FAILED: {error}")
        return 1

    print("Source CSV validation")
    for mapping in TABLE_MAPPINGS:
        result = results[mapping.table_name]
        status = "PASS" if result.passed else "FAIL"
        print(
            f"  {status} {result.source_file}: rows={result.row_count}, "
            f"duplicate_ids={result.duplicate_primary_keys}, "
            f"missing_required={result.missing_required_values}, "
            f"invalid_dates={result.invalid_dates}, "
            f"invalid_values={result.invalid_other_values}"
        )
        for error in result.errors:
            print(f"    error: {error}")

    relationships = foreign_key_results(raw_rows)
    print("Source relationship checks")
    for relationship, broken_references in relationships.items():
        print(f"  {relationship}: broken_references={broken_references}")

    source_passed = all(result.passed for result in results.values()) and all(
        broken_references == 0 for broken_references in relationships.values()
    )
    database_passed = True

    if not args.skip_database_check:
        expected_counts = {table_name: result.row_count for table_name, result in results.items()}
        imported_counts, database_issues = validate_imported_database(
            args.database_path, expected_counts
        )
        print("SQLite import checks")
        for table_name, row_count in imported_counts.items():
            print(f"  {table_name}: rows={row_count}")
        if database_issues:
            database_passed = False
            for issue in database_issues:
                print(f"  issue: {issue}")
        else:
            print("  PASS: imported row counts match source and SQLite has no FK violations.")

    if source_passed and database_passed:
        print("VALIDATION PASSED")
        return 0

    print("VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
