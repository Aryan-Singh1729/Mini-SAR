"""Build and atomically persist complete, audit-safe investigation evidence packages."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.audit.audit_logger import append_audit_event, get_audit_events, get_audit_run


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_LOG_DIR = PROJECT_ROOT / "audit" / "evidence_logs"


def build_evidence_package(
    investigation_id: str,
    original_alert: Mapping[str, Any],
    tool_results: Mapping[str, Any],
    final_verdict: Mapping[str, Any],
    *,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Assemble the full evidence record from actual run, tool, and audit data."""

    audit_run = get_audit_run(investigation_id, database_path=database_path)
    if audit_run is None:
        raise ValueError(f"Unknown investigation_id: {investigation_id}")

    return {
        "investigation_id": investigation_id,
        "evidence_generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_run": audit_run,
        "original_alert": dict(original_alert),
        "tool_outputs_used": dict(tool_results),
        "final_verdict": dict(final_verdict),
        "key_evidence": list(final_verdict.get("key_evidence", [])),
        "false_positive_factors_considered": list(
            final_verdict.get("false_positive_factors_considered", [])
        ),
        "chronological_audit_events": get_audit_events(
            investigation_id, database_path=database_path
        ),
    }


def save_evidence_package(
    investigation_id: str,
    original_alert: Mapping[str, Any],
    tool_results: Mapping[str, Any],
    final_verdict: Mapping[str, Any],
    *,
    database_path: str | Path | None = None,
    evidence_log_dir: str | Path | None = None,
) -> Path:
    """Write the evidence package, log the save, then include that event in the file.

    The first atomic write proves a file exists before the save event is logged.
    A second atomic write refreshes the package so its chronological event list
    includes the `EVIDENCE_PACKAGE_SAVED` event itself.
    """

    destination_dir = Path(evidence_log_dir or DEFAULT_EVIDENCE_LOG_DIR)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_path = destination_dir / f"{investigation_id}.json"

    package = build_evidence_package(
        investigation_id,
        original_alert,
        tool_results,
        final_verdict,
        database_path=database_path,
    )
    _atomic_json_write(destination_path, package)

    append_audit_event(
        investigation_id,
        "EVIDENCE_PACKAGE_SAVED",
        {"evidence_file": destination_path.name, "format": "json"},
        database_path=database_path,
    )

    refreshed_package = build_evidence_package(
        investigation_id,
        original_alert,
        tool_results,
        final_verdict,
        database_path=database_path,
    )
    _atomic_json_write(destination_path, refreshed_package)
    return destination_path


def _atomic_json_write(destination_path: Path, package: Mapping[str, Any]) -> None:
    """Avoid leaving a partially written evidence JSON file after interruption."""

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json.tmp",
        prefix=f".{destination_path.stem}-",
        dir=destination_path.parent,
        delete=False,
    ) as temporary_file:
        json.dump(package, temporary_file, default=str, ensure_ascii=False, indent=2)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)

    try:
        os.replace(temporary_path, destination_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
