"""LangGraph agent/tool loop for controlled AML investigation."""

from __future__ import annotations

import json
from functools import partial
from typing import Any, Literal, Mapping

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, START, StateGraph

from app.agent.llm import build_bound_model, load_graph_limits
from app.agent.prompts import PROMPT_VERSION
from app.agent.state import FinalVerdict, InvestigationState
from app.audit.audit_logger import append_audit_event
from app.tools.account_tools import get_account_summary as fetch_account_summary
from app.tools.alert_tools import get_prior_alert_history as fetch_prior_alert_history
from app.tools.customer_tools import get_customer_profile as fetch_customer_profile
from app.tools.transaction_tools import get_transaction_history as fetch_transaction_history
from app.tools.watchlist_tools import screen_watchlist as fetch_watchlist_screening


class VerdictValidationError(ValueError):
    """Raised when a terminal model response is not a valid verdict."""


@tool
def get_customer_profile(customer_id: str) -> dict[str, Any]:
    """Fetch bounded customer KYC/risk evidence for the alert customer."""

    return fetch_customer_profile(customer_id)


@tool
def get_account_summary(customer_id: str) -> dict[str, Any]:
    """Fetch the alert customer's accounts and days since last activity."""

    return fetch_account_summary(customer_id)


@tool
def get_transaction_history(
    customer_id: str, observation_start: str, observation_end: str
) -> dict[str, Any]:
    """Fetch bounded transaction evidence and deterministic AML signals for an exact date window."""

    return fetch_transaction_history(customer_id, observation_start, observation_end)


@tool
def get_prior_alert_history(customer_id: str) -> dict[str, Any]:
    """Fetch bounded prior alerts, SAR status, analyst notes, and false-positive context."""

    return fetch_prior_alert_history(customer_id)


@tool
def screen_watchlist(customer_id: str) -> dict[str, Any]:
    """Screen the alert customer and counterparties by exact, alias, and fuzzy token matching."""

    return fetch_watchlist_screening(customer_id)


INVESTIGATION_TOOLS: tuple[BaseTool, ...] = (
    get_customer_profile,
    get_account_summary,
    get_transaction_history,
    get_prior_alert_history,
    screen_watchlist,
)
TOOL_BY_NAME = {tool_item.name: tool_item for tool_item in INVESTIGATION_TOOLS}


def build_investigation_graph(model: Any | None = None, *, persist_audit: bool = True):
    """Compile the two-node investigation graph.

    A model can be injected for deterministic/offline tests. Production callers
    omit it and receive the configured Groq model bound to the five tools.
    """

    bound_model = model or build_bound_model(INVESTIGATION_TOOLS)
    limits = load_graph_limits()

    builder = StateGraph(InvestigationState)
    builder.add_node(
        "agent_node",
        partial(
            agent_node,
            model=bound_model,
            max_iterations=limits.max_iterations,
            persist_audit=persist_audit,
        ),
    )
    builder.add_node(
        "tools_node", partial(tools_node, persist_audit=persist_audit)
    )
    builder.add_edge(START, "agent_node")
    builder.add_conditional_edges(
        "agent_node",
        route_after_agent,
        {"tools_node": "tools_node", "end": END},
    )
    builder.add_edge("tools_node", "agent_node")
    return builder.compile()


def agent_node(
    state: InvestigationState,
    *,
    model: Any,
    max_iterations: int,
    persist_audit: bool,
) -> dict[str, Any]:
    """Call the model and return either one tool request or a validated verdict."""

    iteration = state.get("agent_iterations", 0) + 1
    if iteration > max_iterations:
        raise RuntimeError(
            f"Agent exceeded the configured maximum of {max_iterations} model iterations."
        )

    queued_events: list[dict[str, Any]] = []
    if not state.get("system_prompt_logged", False):
        queued_events.append(
            _record_event(
                state,
                "SYSTEM_PROMPT_BUILT",
                {"prompt_version": PROMPT_VERSION},
                stream_type="system_prompt_built",
                persist_audit=persist_audit,
            )
        )

    response = model.invoke(state["messages"])
    if not isinstance(response, AIMessage):
        raise TypeError("The bound model must return an AIMessage.")

    if response.tool_calls:
        summary_text = _message_text(response)
        expected_labels = (
            ("INITIAL HYPOTHESIS", "NEXT STEP")
            if not state.get("tool_results")
            else ("ANALYSIS SUMMARY", "UPDATED HYPOTHESIS", "NEXT STEP")
        )
        missing_labels = [label for label in expected_labels if label not in summary_text.upper()]
        if missing_labels:
            raise ValueError(
                "Tool-request response omitted required visible checkpoint label(s): "
                + ", ".join(missing_labels)
            )

        queued_events.append(
            _record_event(
                state,
                "ANALYSIS_SUMMARY",
                {"stage": "tool_planning", "summary": summary_text},
                stream_type="analysis_summary",
                persist_audit=persist_audit,
            )
        )
        return {
            "messages": [response],
            "system_prompt_logged": True,
            "agent_iterations": iteration,
            "audit_event_queue": queued_events,
        }

    verdict = _extract_final_verdict(response)
    if state.get("tool_results"):
        queued_events.append(
            _record_event(
                state,
                "ANALYSIS_SUMMARY",
                {
                    "stage": "final_assessment",
                    "analysis_summary": verdict.final_reasoning,
                    "updated_hypothesis": verdict.verdict,
                    "next_step": "Finalize the validated structured verdict.",
                },
                stream_type="analysis_summary",
                persist_audit=persist_audit,
            )
        )
    queued_events.append(
        _record_event(
            state,
            "VERDICT_PRODUCED",
            {
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "rules_triggered": verdict.rules_triggered,
                "key_evidence_count": len(verdict.key_evidence),
                "false_positive_factor_count": len(
                    verdict.false_positive_factors_considered
                ),
            },
            stream_type="verdict",
            persist_audit=persist_audit,
        )
    )
    return {
        "messages": [response],
        "final_verdict": verdict.model_dump(mode="json"),
        "system_prompt_logged": True,
        "agent_iterations": iteration,
        "audit_event_queue": queued_events,
    }


def tools_node(
    state: InvestigationState, *, persist_audit: bool
) -> dict[str, Any]:
    """Validate and execute requested tools, then append ToolMessages and audit events."""

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        raise ValueError("tools_node requires an AIMessage containing a tool call.")
    if len(last_message.tool_calls) != 1:
        raise ValueError("The investigation graph permits exactly one tool call per turn.")

    tool_call = last_message.tool_calls[0]
    tool_name = tool_call["name"]
    arguments = dict(tool_call.get("args", {}))
    call_id = tool_call.get("id") or f"missing-id-{tool_name}"
    tool_item = TOOL_BY_NAME.get(tool_name)
    if tool_item is None:
        raise ValueError(f"Tool is not allow-listed: {tool_name}")

    scope_error = _validate_tool_scope(state, tool_name, arguments)
    call_key = json.dumps(
        {"tool": tool_name, "arguments": arguments}, sort_keys=True, separators=(",", ":")
    )
    if call_key in state.get("tool_results", {}):
        scope_error = "Duplicate tool call blocked; use the result already in state."

    queued_events = [
        _record_event(
            state,
            "TOOL_CALLED",
            {"tool": tool_name, "arguments": arguments},
            stream_type="tool_call",
            persist_audit=persist_audit,
        )
    ]

    if scope_error:
        result: dict[str, Any] = {
            "found": False,
            "error": scope_error,
            "tool": tool_name,
        }
    else:
        try:
            raw_result = tool_item.invoke(arguments)
            result = dict(raw_result) if isinstance(raw_result, Mapping) else {"result": raw_result}
        except Exception as error:
            result = {
                "found": False,
                "error": f"Controlled tool execution failed: {type(error).__name__}",
                "tool": tool_name,
            }

    queued_events.append(
        _record_event(
            state,
            "TOOL_RESULT",
            {"tool": tool_name, "result": result},
            stream_type="tool_result",
            persist_audit=persist_audit,
        )
    )

    updated_tool_results = dict(state.get("tool_results", {}))
    updated_tool_results[call_key] = {
        "tool": tool_name,
        "arguments": arguments,
        "result": result,
    }
    tool_message = ToolMessage(
        content=json.dumps(result, default=str, ensure_ascii=False, sort_keys=True),
        tool_call_id=call_id,
        name=tool_name,
    )
    return {
        "messages": [tool_message],
        "tool_results": updated_tool_results,
        "audit_event_queue": queued_events,
    }


def route_after_agent(state: InvestigationState) -> Literal["tools_node", "end"]:
    """Route tool calls to execution and validated verdicts to graph termination."""

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools_node"
    if state.get("final_verdict") is not None:
        return "end"
    raise VerdictValidationError("Agent produced neither a tool call nor a final verdict.")


def _validate_tool_scope(
    state: InvestigationState, tool_name: str, arguments: dict[str, Any]
) -> str | None:
    if arguments.get("customer_id") != state["customer_id"]:
        return "Tool customer_id must exactly match the alert customer_id."

    if tool_name == "get_transaction_history":
        alert = state["alert"]
        if not alert.get("observation_start") or not alert.get("observation_end"):
            return "The alert must provide observation_start and observation_end."
        if arguments.get("observation_start") != alert["observation_start"]:
            return "Tool observation_start must exactly match the alert window."
        if arguments.get("observation_end") != alert["observation_end"]:
            return "Tool observation_end must exactly match the alert window."
    return None


def _extract_final_verdict(message: AIMessage) -> FinalVerdict:
    parsed = message.additional_kwargs.get("parsed")
    if isinstance(parsed, FinalVerdict):
        return parsed
    if parsed is not None:
        try:
            return FinalVerdict.model_validate(parsed)
        except Exception as error:
            raise VerdictValidationError("Provider-parsed verdict failed validation.") from error

    content = _message_text(message).strip()
    try:
        return FinalVerdict.model_validate_json(content)
    except Exception as error:
        raise VerdictValidationError(
            "Terminal model response did not contain a valid structured verdict."
        ) from error


def _message_text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    text_parts = []
    for block in message.content:
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
            text_parts.append(str(block.get("text", "")))
    return "\n".join(part for part in text_parts if part)


def _record_event(
    state: InvestigationState,
    event_type: str,
    payload: dict[str, Any],
    *,
    stream_type: str,
    persist_audit: bool,
) -> dict[str, Any]:
    durable_event = None
    if persist_audit:
        durable_event = append_audit_event(
            state["investigation_id"], event_type, payload
        )
    return {
        "stream_type": stream_type,
        "event_type": event_type,
        "investigation_id": state["investigation_id"],
        "payload": payload,
        "audit_event": durable_event,
    }
