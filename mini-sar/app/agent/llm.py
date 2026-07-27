"""Groq-backed LangChain model configuration for the investigation graph."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_groq import ChatGroq


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LLMConfigurationError(RuntimeError):
    """Raised when the configured model cannot be built safely."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model_name: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class GraphLimits:
    """Safety limits that are also usable by offline graph tests."""

    max_iterations: int
    recursion_limit: int


def load_llm_settings() -> LLMSettings:
    """Load and validate the Groq provider, credential, and model selection."""

    load_dotenv(PROJECT_ROOT / ".env")

    provider = _required_environment_value("LLM_PROVIDER").lower()
    if provider != "groq":
        raise LLMConfigurationError(
            "Only the Groq provider is supported. Set LLM_PROVIDER=groq in .env."
        )

    api_key = _required_environment_value("GROQ_API_KEY")
    if api_key == "your_groq_api_key":
        raise LLMConfigurationError(
            "GROQ_API_KEY still contains the .env.example placeholder. "
            "Replace it with your real Groq API key in .env."
        )

    return LLMSettings(
        provider=provider,
        api_key=api_key,
        model_name=_required_environment_value("GROQ_MODEL"),
    )


def load_graph_limits() -> GraphLimits:
    """Load loop limits without requiring live LLM credentials."""

    load_dotenv(PROJECT_ROOT / ".env")
    return GraphLimits(
        max_iterations=_positive_int("AGENT_MAX_ITERATIONS", 8),
        recursion_limit=_positive_int("LANGGRAPH_RECURSION_LIMIT", 20),
    )


def build_bound_model(tools: Sequence[BaseTool]):
    """Create a ChatGroq model and expose only the allow-listed local tools."""

    settings = load_llm_settings()
    model = ChatGroq(
        model=settings.model_name,
        api_key=settings.api_key,
        temperature=0,
        timeout=60.0,
        max_retries=2,
    )
    return model.bind_tools(
        list(tools),
        parallel_tool_calls=False,
    )


def _required_environment_value(environment_name: str) -> str:
    value = os.getenv(environment_name, "").strip()
    if not value:
        raise LLMConfigurationError(
            f"{environment_name} is not configured. Copy .env.example to .env "
            "and provide the required Groq configuration."
        )
    return value


def _positive_int(environment_name: str, default: int) -> int:
    raw_value = os.getenv(environment_name, str(default))
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise LLMConfigurationError(f"{environment_name} must be an integer.") from error
    if parsed <= 0:
        raise LLMConfigurationError(f"{environment_name} must be positive.")
    return parsed
