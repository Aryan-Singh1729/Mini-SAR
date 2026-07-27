"""Durable audit-run and audit-event logging for AML investigations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.database import get_connection


def utc_now() -> str:
    """Return a timezone-aware timestamp suitable for audit ordering."""

    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _audit_connection(database_path: str | Path | None):
    """Commit/roll back and always close an audit database connection."""

    connection = get_connection(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_investigation_run(
    alert_id: str,
    customer_id: str,
    *,
    llm_provider: str | None = None,
    model_name: str | None = None,
    investigation_id: str | None = None,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create one running investigation and its first audit event."""

    run_id = investigation_id or f"INV-{uuid.uuid4()}"
    started_at = utc_now()

    try:
        with _audit_connection(database_path) as connection:
            connection.execute(
                """
                INSERT INTO audit_runs (
                    investigation_id, alert_id, customer_id, started_at,
                    completed_at, status, final_verdict, confidence,
                    llm_provider, model_name
                )
                VALUES (?, ?, ?, ?, NULL, 'RUNNING', NULL, NULL, ?, ?)
                """,
                (run_id, alert_id, customer_id, started_at, llm_provider, model_name),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError(
            "Unable to create an investigation run. Confirm that customer_id exists "
            "and that investigation_id is unique."
        ) from error

    start_event = append_audit_event(
        run_id,
        "INVESTIGATION_STARTED",
        {
            "alert_id": alert_id,
            "customer_id": customer_id,
            "llm_provider": llm_provider,
            "model_name": model_name,
        },
        database_path=database_path,
    )

    return {
        "investigation_id": run_id,
        "alert_id": alert_id,
        "customer_id": customer_id,
        "started_at": started_at,
        "status": "RUNNING",
        "start_event": start_event,
    }


def append_audit_event(
    investigation_id: str,
    event_type: str,
    payload: Mapping[str, Any],
    *,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Append one ordered, JSON-safe event to an existing investigation run."""

    event_id = f"EVT-{uuid.uuid4()}"
    timestamp = utc_now()
    payload_json = json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)

    with _audit_connection(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        run_exists = connection.execute(
            "SELECT 1 FROM audit_runs WHERE investigation_id = ?", (investigation_id,)
        ).fetchone()
        if run_exists is None:
            raise ValueError(f"Unknown investigation_id: {investigation_id}")

        sequence_number = connection.execute(
            """
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM audit_events
            WHERE investigation_id = ?
            """,
            (investigation_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO audit_events (
                event_id, investigation_id, sequence_number,
                event_type, timestamp, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, investigation_id, sequence_number, event_type, timestamp, payload_json),
        )

    return {
        "event_id": event_id,
        "investigation_id": investigation_id,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "timestamp": timestamp,
        "payload": json.loads(payload_json),
    }


def complete_investigation_run(
    investigation_id: str,
    final_verdict: Mapping[str, Any],
    *,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a completed verdict and append a safe final-verdict event."""

    verdict = str(final_verdict.get("verdict", ""))
    confidence = final_verdict.get("confidence")
    if verdict not in {"TRUE_POSITIVE", "FALSE_POSITIVE"}:
        raise ValueError("final_verdict.verdict must be TRUE_POSITIVE or FALSE_POSITIVE.")
    if not isinstance(confidence, (float, int)) or not 0 <= float(confidence) <= 1:
        raise ValueError("final_verdict.confidence must be a number from 0 to 1.")

    completed_at = utc_now()
    with _audit_connection(database_path) as connection:
        updated_rows = connection.execute(
            """
            UPDATE audit_runs
            SET completed_at = ?, status = 'COMPLETED',
                final_verdict = ?, confidence = ?
            WHERE investigation_id = ? AND status = 'RUNNING'
            """,
            (completed_at, verdict, float(confidence), investigation_id),
        ).rowcount
    if updated_rows != 1:
        raise ValueError(
            "Unable to complete investigation. It must exist and currently be RUNNING."
        )

    verdict_event = append_audit_event(
        investigation_id,
        "VERDICT_FINALIZED",
        {
            "verdict": verdict,
            "confidence": float(confidence),
            "rules_triggered": final_verdict.get("rules_triggered", []),
            "key_evidence_count": len(final_verdict.get("key_evidence", [])),
            "false_positive_factor_count": len(
                final_verdict.get("false_positive_factors_considered", [])
            ),
        },
        database_path=database_path,
    )

    return {
        "investigation_id": investigation_id,
        "completed_at": completed_at,
        "status": "COMPLETED",
        "final_verdict": verdict,
        "confidence": float(confidence),
        "verdict_event": verdict_event,
    }


def fail_investigation_run(
    investigation_id: str,
    safe_error_summary: str,
    *,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Mark a run failed without writing an exception traceback to the audit log."""

    completed_at = utc_now()
    with _audit_connection(database_path) as connection:
        updated_rows = connection.execute(
            """
            UPDATE audit_runs
            SET completed_at = ?, status = 'FAILED'
            WHERE investigation_id = ? AND status = 'RUNNING'
            """,
            (completed_at, investigation_id),
        ).rowcount
    if updated_rows != 1:
        raise ValueError("Unable to fail investigation. It must exist and be RUNNING.")

    failure_event = append_audit_event(
        investigation_id,
        "INVESTIGATION_FAILED",
        {"safe_error_summary": safe_error_summary},
        database_path=database_path,
    )
    return {
        "investigation_id": investigation_id,
        "completed_at": completed_at,
        "status": "FAILED",
        "failure_event": failure_event,
    }


def get_audit_run(
    investigation_id: str, *, database_path: str | Path | None = None
) -> dict[str, Any] | None:
    """Return one audit-run row as JSON-ready metadata."""

    with _audit_connection(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM audit_runs WHERE investigation_id = ?", (investigation_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def get_audit_events(
    investigation_id: str, *, database_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Return parsed audit events in durable sequence-number order."""

    with _audit_connection(database_path) as connection:
        rows = connection.execute(
            """
            SELECT event_id, investigation_id, sequence_number,
                   event_type, timestamp, payload_json
            FROM audit_events
            WHERE investigation_id = ?
            ORDER BY sequence_number
            """,
            (investigation_id,),
        ).fetchall()

    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(event.pop("payload_json"))
        events.append(event)
    return events
