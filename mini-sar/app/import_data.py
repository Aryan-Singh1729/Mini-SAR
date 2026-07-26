"""Import the approved CSV dataset into the empty Mini SAR SQLite schema."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from app.database import get_connection, get_database_path, initialize_database
from app.schema_mapper import (
    TABLE_MAPPINGS,
    DatasetMappingError,
    TableMapping,
    assert_unique_primary_keys,
    resolve_dataset_path,
    transformed_rows,
)


class ImportSafetyError(RuntimeError):
    """Raised when import could duplicate or overwrite existing source data."""


def import_dataset(
    dataset_path: str | Path | None = None,
    database_path: str | Path | None = None,
) -> dict[str, int]:
    """Validate, then atomically import all source CSV rows into SQLite.

    The importer refuses to run if a source-derived table already has data.
    This makes accidental duplicate imports impossible; it never deletes rows.
    """

    source_directory = resolve_dataset_path(dataset_path)
    database_file = initialize_database(database_path)

    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for mapping in TABLE_MAPPINGS:
        rows = transformed_rows(mapping, source_directory)
        assert_unique_primary_keys(mapping, rows)
        rows_by_table[mapping.table_name] = rows

    with get_connection(database_file) as connection:
        ensure_source_tables_are_empty(connection)
        try:
            for mapping in TABLE_MAPPINGS:
                insert_rows(connection, mapping, rows_by_table[mapping.table_name])
        except sqlite3.Error as error:
            raise ImportSafetyError(f"Database import failed and was rolled back: {error}") from error

    return {table_name: len(rows) for table_name, rows in rows_by_table.items()}


def ensure_source_tables_are_empty(connection: sqlite3.Connection) -> None:
    """Stop before writing when a prior source-data import already exists."""

    populated_tables = []
    for mapping in TABLE_MAPPINGS:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {mapping.table_name}"
        ).fetchone()[0]
        if count:
            populated_tables.append(f"{mapping.table_name}={count}")

    if populated_tables:
        raise ImportSafetyError(
            "Refusing to import into a populated database: " + ", ".join(populated_tables)
        )


def insert_rows(
    connection: sqlite3.Connection,
    mapping: TableMapping,
    rows: list[dict[str, Any]],
) -> None:
    """Insert one mapped table with bound parameters, never string-built values."""

    placeholders = ", ".join("?" for _ in mapping.columns)
    columns = ", ".join(mapping.columns)
    statement = f"INSERT INTO {mapping.table_name} ({columns}) VALUES ({placeholders})"
    parameters = [tuple(row[column] for column in mapping.columns) for row in rows]
    connection.executemany(statement, parameters)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import AML CSV files into SQLite.")
    parser.add_argument(
        "--dataset-path",
        help="Folder containing customers.csv, accounts.csv, transactions.csv, aml_alerts_history.csv, and watchlists.csv.",
    )
    parser.add_argument(
        "--database-path",
        help="Optional SQLite database path. Defaults to DATABASE_PATH or data/aml.db.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        counts = import_dataset(args.dataset_path, args.database_path)
    except (DatasetMappingError, ImportSafetyError) as error:
        print(f"IMPORT FAILED: {error}")
        return 1

    print(f"Imported dataset into: {get_database_path(args.database_path)}")
    for table_name, count in counts.items():
        print(f"  {table_name}: {count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
