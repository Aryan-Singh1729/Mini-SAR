"""Typed LangGraph state and validated final-verdict models."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from app.agent.prompts import build_alert_message, build_system_prompt


RuleId = Literal["RULE-01", "RULE-02", "RULE-03", "RULE-04"]


class SupportingData(BaseModel):
    """Concrete source values supporting one rule-mapped finding."""

    model_config = ConfigDict(extra="forbid")

    amounts: list[float]
    transaction_ids: list[str]
    counterparties: list[str]
    source_table: str


class KeyEvidence(BaseModel):
    """One explainable finding linked to a named AML rule."""

    model_config = ConfigDict(extra="forbid")

    rule_mapped: RuleId
    finding: str = Field(min_length=1)
    supporting_data: SupportingData
    statistical_context: str = Field(min_length=1)


class FinalVerdict(BaseModel):
    """The only accepted terminal output from the investigation agent."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE"]
    confidence: float = Field(ge=0.0, le=1.0)
    rules_triggered: list[RuleId]
    key_evidence: list[KeyEvidence]
    false_positive_factors_considered: list[str]
    final_reasoning: str = Field(min_length=1)


class InvestigationState(TypedDict, total=False):
    """Shared state passed between the agent and tools nodes."""

    messages: Annotated[list[AnyMessage], add_messages]
    alert: dict[str, Any]
    customer_id: str
    investigation_id: str
    tool_results: dict[str, dict[str, Any]]
    audit_event_queue: Annotated[list[dict[str, Any]], operator.add]
    final_verdict: dict[str, Any] | None
    system_prompt_logged: bool
    agent_iterations: int


def create_initial_state(
    alert: dict[str, Any], investigation_id: str
) -> InvestigationState:
    """Build the complete, explicit starting state for one graph invocation."""

    customer_id = str(alert.get("customer_id", "")).strip()
    if not customer_id:
        raise ValueError("alert.customer_id is required.")
    if not str(alert.get("alert_id", "")).strip():
        raise ValueError("alert.alert_id is required.")

    return {
        "messages": [
            SystemMessage(content=build_system_prompt()),
            HumanMessage(content=build_alert_message(alert, investigation_id)),
        ],
        "alert": dict(alert),
        "customer_id": customer_id,
        "investigation_id": investigation_id,
        "tool_results": {},
        "audit_event_queue": [],
        "final_verdict": None,
        "system_prompt_logged": False,
        "agent_iterations": 0,
    }
