"""Intermediate Phase 5 checkpoint API for testing the Groq agent loop."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict

from app.agent.graph import build_investigation_graph
from app.agent.llm import (
    LLMConfigurationError,
    build_chat_model,
    load_graph_limits,
    load_llm_settings,
)
from app.agent.state import create_initial_state
from app.tools.customer_tools import get_customer_profile
from app.tools.transaction_tools import get_transaction_history


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = PROJECT_ROOT / "app" / "static" / "index.html"

app = FastAPI(
    title="Mini AML SAR Investigator — Agent Test",
    description="Intermediate Phase 5 checkpoint; not the full Phase 6 API.",
)

REQUIRED_TOOL_NAMES = {
    "get_customer_profile",
    "get_account_summary",
    "get_transaction_history",
    "get_prior_alert_history",
    "screen_watchlist",
}


class CheckpointValidationError(RuntimeError):
    """Raised when a run cannot prove the checkpoint objective."""


class TestInvestigationRequest(BaseModel):
    """Select one server-owned test fixture without accepting an expected label."""

    model_config = ConfigDict(extra="forbid")

    fixture_id: Literal["true_positive", "false_positive"]


TEST_ALERT_FIXTURES: dict[str, dict[str, Any]] = {
    "true_positive": {
        "label": "TRUE_POSITIVE test alert",
        "expected_verdict": "TRUE_POSITIVE",
        "dataset_basis": (
            "Existing customer and November 2024 transactions with deterministic "
            "structuring, rapid-outflow, income-mismatch, and watchlist signals."
        ),
        "alert": {
            "alert_id": "TEST-FIXTURE-A",
            "customer_id": "CUST-UK-004821",
            "alert_date": "2024-11-14",
            "alert_type": "MULTI_SIGNAL_ACTIVITY",
            "triggered_rules": ["RULE-01", "RULE-02", "RULE-03", "RULE-04"],
            "observation_start": "2024-11-07",
            "observation_end": "2024-11-14",
            "test_fixture": True,
        },
    },
    "false_positive": {
        "label": "FALSE_POSITIVE test alert",
        "expected_verdict": "FALSE_POSITIVE",
        "dataset_basis": (
            "Existing high-income customer with ordinary October 2024 activity, "
            "no deterministic transaction signal, no watchlist match, and prior "
            "false-positive context."
        ),
        "alert": {
            "alert_id": "TEST-FIXTURE-B",
            "customer_id": "CUST-UK-050012",
            "alert_date": "2024-10-31",
            "alert_type": "INCOME_MISMATCH_REVIEW",
            "triggered_rules": ["RULE-03"],
            "observation_start": "2024-10-01",
            "observation_end": "2024-10-31",
            "test_fixture": True,
        },
    },
}


@app.get("/", response_class=FileResponse)
def frontend() -> FileResponse:
    """Serve the small checkpoint UI from the same FastAPI origin."""

    return FileResponse(INDEX_FILE, media_type="text/html")


@app.get("/test-model")
def test_model_connection():
    """Make one tiny Groq call without binding or executing investigation tools."""

    events = [
        _public_event(
            "model_connection_started",
            "Testing the configured Groq model connection.",
        )
    ]
    try:
        override = getattr(app.state, "connection_model_override", None)
        if override is None:
            settings = load_llm_settings()
            model = build_chat_model(settings)
            provider = settings.provider
            model_name = settings.model_name
        else:
            model = override
            provider = "groq"
            model_name = "offline-test-model"

        response = model.invoke(
            [HumanMessage(content="Reply with only: MODEL_CONNECTED")]
        )
        response_text = _message_text(response).strip()
        if response_text != "MODEL_CONNECTED":
            events.append(
                _public_event(
                    "investigation_failed",
                    "The model replied, but not with the required probe text.",
                    {"received": response_text},
                )
            )
            return JSONResponse(
                status_code=502,
                content={
                    "status": "error",
                    "provider": provider,
                    "model": model_name,
                    "response": response_text,
                    "error": "Unexpected model probe response.",
                    "events": _number_events(events),
                },
            )

        events.append(
            _public_event(
                "model_connection_success",
                "Groq returned the required MODEL_CONNECTED response.",
                {"provider": provider, "model": model_name},
            )
        )
        return {
            "status": "success",
            "model": model_name,
            "provider": provider,
            "response": response_text,
            "events": _number_events(events),
        }
    except Exception as error:
        _log_checkpoint_error("Model connection checkpoint failed.", error)
        events.append(
            _public_event(
                "investigation_failed",
                _safe_model_error(error),
            )
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "provider": "groq",
                "model": None,
                "response": None,
                "error": _safe_model_error(error),
                "events": _number_events(events),
            },
        )


@app.get("/test-alerts")
def test_alerts():
    """Return two test fixtures that reference existing imported dataset rows."""

    unavailable = []
    fixtures = []
    for fixture_id, fixture in TEST_ALERT_FIXTURES.items():
        alert = fixture["alert"]
        availability_error = _fixture_availability_error(alert)
        if availability_error:
            unavailable.append(
                {"fixture_id": fixture_id, "error": availability_error}
            )
            continue
        fixtures.append(
            {
                "fixture_id": fixture_id,
                "label": fixture["label"],
                "expected_verdict": fixture["expected_verdict"],
                "dataset_basis": fixture["dataset_basis"],
                "alert": deepcopy(alert),
            }
        )

    if unavailable:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error": "One or more checkpoint fixtures are unavailable.",
                "unavailable": unavailable,
                "fixtures": fixtures,
            },
        )
    return {"status": "success", "fixtures": fixtures}


@app.post("/test-investigate")
def test_investigate(request: TestInvestigationRequest):
    """Run one selected fixture through the real controlled LangGraph workflow."""

    fixture = TEST_ALERT_FIXTURES[request.fixture_id]
    alert = deepcopy(fixture["alert"])
    expected_verdict = fixture["expected_verdict"]
    investigation_id = f"TEST-INV-{uuid.uuid4()}"
    events = [
        _public_event(
            "investigation_started",
            "The checkpoint investigation started.",
            {"investigation_id": investigation_id},
        ),
        _public_event(
            "alert_loaded",
            f"Loaded {fixture['label']} from the server-owned fixture registry.",
            {
                "fixture_id": request.fixture_id,
                "alert": alert,
                "expected_verdict": expected_verdict,
            },
        ),
    ]

    try:
        availability_error = _fixture_availability_error(alert)
        if availability_error:
            raise CheckpointValidationError(availability_error)

        override = getattr(app.state, "agent_model_override", None)
        if override is None:
            settings = load_llm_settings()
            provider = settings.provider
            model_name = settings.model_name
            graph = build_investigation_graph(persist_audit=False)
        else:
            provider = "groq"
            model_name = "offline-scripted-model"
            graph = build_investigation_graph(
                model=override,
                persist_audit=False,
            )

        limits = load_graph_limits()
        initial_state = create_initial_state(alert, investigation_id)
        result = graph.invoke(
            initial_state,
            config={"recursion_limit": limits.recursion_limit},
        )
        events.extend(_translate_graph_events(result.get("audit_event_queue", [])))

        final_verdict = result.get("final_verdict")
        if not final_verdict:
            raise CheckpointValidationError(
                "The graph ended without a validated final verdict."
            )

        tool_validation_error = _tool_validation_error(
            result.get("tool_results", {})
        )
        if tool_validation_error:
            raise CheckpointValidationError(tool_validation_error)

        actual_verdict = final_verdict["verdict"]
        matched_expected = actual_verdict == expected_verdict
        mismatch_reason = None
        if not matched_expected:
            mismatch_reason = _mismatch_reason(
                expected_verdict,
                actual_verdict,
                result.get("tool_results", {}),
            )

        events.append(
            _public_event(
                "verdict",
                f"FINAL VERDICT: {actual_verdict}",
                {"final_verdict": final_verdict},
            )
        )
        events.append(
            _public_event(
                "verdict_match_check",
                (
                    "Actual verdict matched the expected checkpoint label."
                    if matched_expected
                    else "Actual verdict did not match the expected checkpoint label."
                ),
                {
                    "expected_verdict": expected_verdict,
                    "actual_verdict": actual_verdict,
                    "matched_expected": matched_expected,
                    "possible_reason": mismatch_reason,
                },
            )
        )
        events.append(
            _public_event(
                "investigation_completed",
                "The checkpoint investigation completed.",
                {
                    "tool_call_count": len(result.get("tool_results", {})),
                    "agent_iterations": result.get("agent_iterations"),
                },
            )
        )
        return {
            "investigation_id": investigation_id,
            "fixture_id": request.fixture_id,
            "provider": provider,
            "model": model_name,
            "expected_verdict": expected_verdict,
            "actual_verdict": actual_verdict,
            "matched_expected": matched_expected,
            "possible_reason_for_mismatch": mismatch_reason,
            "events": _number_events(events),
            "final_verdict": final_verdict,
        }
    except Exception as error:
        _log_checkpoint_error("Checkpoint investigation failed.", error)
        safe_error = _safe_model_error(error)
        events.append(
            _public_event("investigation_failed", safe_error)
        )
        return JSONResponse(
            status_code=500,
            content={
                "investigation_id": investigation_id,
                "fixture_id": request.fixture_id,
                "expected_verdict": expected_verdict,
                "actual_verdict": None,
                "matched_expected": False,
                "possible_reason_for_mismatch": safe_error,
                "events": _number_events(events),
                "final_verdict": None,
            },
        )


def _fixture_availability_error(alert: dict[str, Any]) -> str | None:
    customer = get_customer_profile(alert["customer_id"])
    if not customer.get("found"):
        return f"Dataset customer is missing: {alert['customer_id']}"

    transactions = get_transaction_history(
        alert["customer_id"],
        alert["observation_start"],
        alert["observation_end"],
    )
    if not transactions.get("found"):
        return f"Transaction fixture is unavailable for {alert['customer_id']}."
    if transactions.get("summary", {}).get("transaction_count", 0) == 0:
        return f"No transactions exist in the fixture window for {alert['customer_id']}."
    return None


def _translate_graph_events(
    graph_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    public_events = []
    for event in graph_events:
        stream_type = event.get("stream_type")
        payload = event.get("payload", {})

        if stream_type == "system_prompt_built":
            public_events.append(
                _public_event(
                    "agent_started",
                    "The evidence-constrained agent policy was loaded.",
                    {"prompt_version": payload.get("prompt_version")},
                )
            )
        elif stream_type == "analysis_summary":
            message = _analysis_message(payload)
            event_type = (
                "initial_hypothesis"
                if "INITIAL HYPOTHESIS:" in message.upper()
                else "analysis_summary"
            )
            public_events.append(_public_event(event_type, message, payload))
        elif stream_type == "tool_call":
            public_events.append(
                _public_event(
                    "tool_call",
                    f"TOOL_CALLED: {payload.get('tool')}",
                    {
                        "tool": payload.get("tool"),
                        "args": payload.get("arguments", {}),
                    },
                )
            )
        elif stream_type == "tool_result":
            public_events.append(
                _public_event(
                    "tool_result",
                    f"TOOL_RESULT: {payload.get('tool')}",
                    {
                        "tool": payload.get("tool"),
                        "result": payload.get("result"),
                    },
                )
            )
        # The graph's compact verdict audit event is replaced by the full,
        # validated verdict event appended by the endpoint.
    return public_events


def _analysis_message(payload: dict[str, Any]) -> str:
    if payload.get("summary"):
        return str(payload["summary"])
    if payload.get("analysis_summary"):
        return (
            f"ANALYSIS SUMMARY: {payload['analysis_summary']}\n"
            f"UPDATED HYPOTHESIS: {payload.get('updated_hypothesis', 'Not stated')}\n"
            f"NEXT STEP: {payload.get('next_step', 'Finalize')}"
        )
    return "ANALYSIS SUMMARY: A safe checkpoint was recorded."


def _mismatch_reason(
    expected: str,
    actual: str,
    tool_results: dict[str, dict[str, Any]],
) -> str:
    failed_tools = [
        item["tool"]
        for item in tool_results.values()
        if item.get("result", {}).get("error")
    ]
    if failed_tools:
        return (
            "One or more controlled tools returned errors: "
            + ", ".join(failed_tools)
            + "."
        )

    called_tools = {item["tool"] for item in tool_results.values()}
    missing_tools = sorted(REQUIRED_TOOL_NAMES - called_tools)
    if missing_tools:
        return (
            "The model finalized without the complete checkpoint evidence set. "
            f"Missing tools: {', '.join(missing_tools)}."
        )
    return (
        f"All controlled tools completed, but the model interpreted the visible "
        f"evidence as {actual} instead of {expected}. Review the analysis summaries, "
        "tool results, and final_reasoning; no unobserved cause is asserted."
    )


def _missing_required_tools(
    tool_results: dict[str, dict[str, Any]],
) -> list[str]:
    called_tools = {item["tool"] for item in tool_results.values()}
    return sorted(REQUIRED_TOOL_NAMES - called_tools)


def _tool_validation_error(
    tool_results: dict[str, dict[str, Any]],
) -> str | None:
    missing_tools = _missing_required_tools(tool_results)
    if missing_tools:
        return (
            "The model finalized before completing the five-tool evidence "
            f"checklist. Missing tools: {', '.join(missing_tools)}."
        )

    tool_counts = Counter(item["tool"] for item in tool_results.values())
    repeated_tools = sorted(
        tool_name for tool_name, count in tool_counts.items() if count != 1
    )
    if len(tool_results) != len(REQUIRED_TOOL_NAMES) or repeated_tools:
        return (
            "The checkpoint requires each controlled tool exactly once. "
            f"Observed {len(tool_results)} stored calls; repeated tools: "
            f"{', '.join(repeated_tools) if repeated_tools else 'none'}."
        )

    failed_tools = sorted(
        item["tool"]
        for item in tool_results.values()
        if item.get("result", {}).get("error")
    )
    if failed_tools:
        return (
            "The evidence checklist contains controlled tool errors: "
            f"{', '.join(failed_tools)}."
        )
    return None


def _message_text(message: Any) -> str:
    if not isinstance(message, AIMessage):
        raise TypeError("The Groq connection probe did not return an AIMessage.")
    if isinstance(message.content, str):
        return message.content
    parts = []
    for block in message.content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _safe_model_error(error: Exception) -> str:
    if isinstance(error, LLMConfigurationError):
        return str(error)
    if isinstance(error, CheckpointValidationError):
        return str(error)

    error_name = type(error).__name__
    if error_name in {"AuthenticationError", "PermissionDeniedError"}:
        return "Groq authentication failed. Check GROQ_API_KEY and account access."
    if error_name == "RateLimitError":
        return "Groq rate limit reached. Wait briefly or check the account limits."
    if error_name in {"BadRequestError", "NotFoundError"}:
        return (
            "Groq rejected the request. Confirm that GROQ_MODEL exists in the account "
            "and supports tool calling."
        )
    return (
        f"{error_name}: the checkpoint failed. Check the server log for technical "
        "details; no API key is returned to the browser."
    )


def _log_checkpoint_error(message: str, error: Exception) -> None:
    if isinstance(error, (LLMConfigurationError, CheckpointValidationError)):
        LOGGER.warning("%s %s", message, error)
    else:
        LOGGER.exception(message)


def _public_event(
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "message": message,
        "payload": payload or {},
    }


def _number_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"sequence_number": index, **event}
        for index, event in enumerate(events, start=1)
    ]
