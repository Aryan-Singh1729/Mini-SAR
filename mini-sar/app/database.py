"""SQLite connection and schema initialization for the Mini SAR Investigator.

This module creates empty tables only. CSV parsing and data insertion belong to
Phase 2C so the schema remains separate from the import pipeline.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "aml.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    nationality TEXT NOT NULL,
    country_of_residence TEXT NOT NULL,
    customer_type TEXT NOT NULL,
    occupation TEXT NOT NULL,
    employer_name TEXT NOT NULL,
    annual_income_declared_gbp NUMERIC NOT NULL CHECK (annual_income_declared_gbp >= 0),
    source_of_funds_declared TEXT NOT NULL,
    onboarding_date TEXT NOT NULL,
    kyc_status TEXT NOT NULL,
    kyc_last_reviewed TEXT NOT NULL,
    kyc_document_type TEXT NOT NULL,
    kyc_document_expiry TEXT NOT NULL,
    pep_flag INTEGER NOT NULL CHECK (pep_flag IN (0, 1)),
    sanctions_flag INTEGER NOT NULL CHECK (sanctions_flag IN (0, 1)),
    risk_rating TEXT NOT NULL,
    address TEXT NOT NULL,
    address_country TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    account_type TEXT NOT NULL,
    currency TEXT NOT NULL,
    account_status TEXT NOT NULL,
    opening_date TEXT NOT NULL,
    last_activity_date TEXT NOT NULL,
    average_monthly_balance_gbp NUMERIC NOT NULL
        CHECK (average_monthly_balance_gbp >= 0),
    iban TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    transaction_datetime TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('CREDIT', 'DEBIT')),
    amount_gbp NUMERIC NOT NULL CHECK (amount_gbp >= 0),
    original_amount NUMERIC NOT NULL CHECK (original_amount >= 0),
    original_currency TEXT NOT NULL,
    counterparty_name TEXT NOT NULL,
    counterparty_account_id TEXT NOT NULL,
    counterparty_bank_bic TEXT NOT NULL,
    counterparty_country TEXT NOT NULL,
    counterparty_is_high_risk_jurisdiction INTEGER NOT NULL
        CHECK (counterparty_is_high_risk_jurisdiction IN (0, 1)),
    payment_reference TEXT,
    channel TEXT NOT NULL,
    is_international INTEGER NOT NULL CHECK (is_international IN (0, 1)),
    transaction_status TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS aml_alerts_history (
    alert_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    alert_date TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    rules_triggered TEXT NOT NULL,
    disposition TEXT NOT NULL,
    sar_filed INTEGER NOT NULL CHECK (sar_filed IN (0, 1)),
    sar_reference TEXT,
    analyst_notes TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS watchlists (
    watchlist_id TEXT PRIMARY KEY,
    entity_name TEXT NOT NULL,
    aliases TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    watchlist_type TEXT NOT NULL,
    source TEXT NOT NULL,
    listed_date TEXT NOT NULL,
    country_of_incorporation TEXT NOT NULL,
    country_of_operation TEXT NOT NULL,
    risk_score INTEGER NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    is_absolute_prohibition INTEGER NOT NULL
        CHECK (is_absolute_prohibition IN (0, 1)),
    status TEXT NOT NULL,
    last_reviewed_date TEXT NOT NULL,
    review_due_date TEXT NOT NULL,
    related_entity_id TEXT,
    notes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_runs (
    investigation_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    final_verdict TEXT CHECK (
        final_verdict IS NULL OR final_verdict IN ('TRUE_POSITIVE', 'FALSE_POSITIVE')
    ),
    confidence NUMERIC CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    llm_provider TEXT,
    model_name TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (investigation_id, sequence_number),
    FOREIGN KEY (investigation_id) REFERENCES audit_runs(investigation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS human_reviews (
    review_id TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    notes TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (investigation_id) REFERENCES audit_runs(investigation_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_accounts_customer_id
    ON accounts(customer_id);
CREATE INDEX IF NOT EXISTS idx_transactions_account_datetime
    ON transactions(account_id, transaction_datetime);
CREATE INDEX IF NOT EXISTS idx_alerts_customer_date
    ON aml_alerts_history(customer_id, alert_date);
CREATE INDEX IF NOT EXISTS idx_audit_runs_started_at
    ON audit_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_investigation_sequence
    ON audit_events(investigation_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_human_reviews_investigation
    ON human_reviews(investigation_id);
"""


def get_database_path(database_path: str | Path | None = None) -> Path:
    """Return an absolute database path, respecting an optional configuration value."""

    configured_path = database_path or os.getenv("DATABASE_PATH")
    if configured_path is None:
        return DEFAULT_DATABASE_PATH

    path = Path(configured_path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def get_connection(database_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with row access by column name and FK enforcement."""

    path = get_database_path(database_path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path | None = None) -> Path:
    """Create the empty schema and return the database path.

    `CREATE TABLE IF NOT EXISTS` makes this safe to run repeatedly. It never
    inserts, replaces, or deletes investigation data.
    """

    path = get_database_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with get_connection(path) as connection:
        connection.executescript(SCHEMA_SQL)

    return path


if __name__ == "__main__":
    created_path = initialize_database()
    print(f"SQLite schema initialized at: {created_path}")
