"""Task callables that wrap Galaxy agents for use with pydantic-evals.

Each task takes a string query and returns whatever shape the dataset's
evaluators need. Most return a string; tasks that need to expose the
underlying pydantic-ai run (e.g. for tool-call inspection) return a dict
with ``content`` and ``tool_calls``.
"""

from collections.abc import (
    Awaitable,
    Callable,
)
from typing import (
    Any,
    Optional,
)
from unittest.mock import MagicMock

from galaxy.agents.base import (
    extract_result_content,
    GalaxyAgentDependencies,
)
from galaxy.agents.error_analysis import ErrorAnalysisAgent
from galaxy.agents.registry import build_default_registry
from galaxy.agents.router import QueryRouterAgent
from galaxy.agents.tools import ToolRecommendationAgent

_registry = build_default_registry()


def make_deps(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> GalaxyAgentDependencies:
    """Build minimal GalaxyAgentDependencies pointing at a single model.

    Routes all agents through `inference_services.default`, so the router
    handoff targets resolve via the registry without needing a live Galaxy.
    """
    config = MagicMock()
    config.ai_api_key = None
    config.ai_model = None
    config.ai_api_base_url = None
    config.inference_services = {
        "default": {
            "model": model,
            "api_key": api_key,
            "api_base_url": base_url,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    }
    # MagicMock for trans/user so handoff targets that touch deps.trans.app
    # (history, error_analysis, tools) don't crash before the model returns.
    # Real-Galaxy operations still won't work, but routing-decision measurement
    # survives the handoff chain.
    trans = MagicMock()
    # Router fast-path tools call workflow / history services that unpack a
    # (rows, total_count) tuple. A bare MagicMock returns another MagicMock,
    # which raises ValueError on unpack and aborts the agent run before we
    # can read tool calls. Give those service .index() calls an explicit
    # empty result so the tool succeeds with no data and the model moves on.
    trans.app.__getitem__.return_value.index.return_value = ([], 0)
    return GalaxyAgentDependencies(
        trans=trans,
        user=MagicMock(),
        config=config,
        get_agent=_registry.get_agent,
    )


def make_router_task(
    deps: GalaxyAgentDependencies,
    context: Optional[dict] = None,
) -> Callable[[str], Awaitable[str]]:
    """Build an async callable: query -> router's chosen agent_type."""

    async def router_task(query: str) -> str:
        router = QueryRouterAgent(deps)
        response = await router.process(query, context=context)
        return response.agent_type

    return router_task


def make_error_analysis_task(
    deps: GalaxyAgentDependencies,
    context: Optional[dict] = None,
) -> Callable[[str], Awaitable[str]]:
    """Build an async callable: query -> error-analysis response content."""

    async def error_analysis_task(query: str) -> str:
        agent = ErrorAnalysisAgent(deps)
        response = await agent.process(query, context=context)
        return response.content

    return error_analysis_task


def make_tool_recommendation_task(
    deps: GalaxyAgentDependencies,
    context: Optional[dict] = None,
) -> Callable[[str], Awaitable[str]]:
    """Build an async callable: query -> tool-recommendation response content.

    Note: deps here typically have ``toolbox=None`` (no live Galaxy), so the
    fast-path exact-match branch and the agent's ``search_galaxy_tools``
    in-agent tool both return empty. That means we're scoring the model's
    prior knowledge of canonical Galaxy tools, not its grounded search
    behavior. Useful for prompt + model quality; not a substitute for an
    end-to-end test against a live toolbox.
    """

    async def tool_recommendation_task(query: str) -> str:
        agent = ToolRecommendationAgent(deps)
        response = await agent.process(query, context=context)
        return response.content

    return tool_recommendation_task


def _extract_tool_calls(result: Any) -> list[dict[str, Any]]:
    """Pull every ToolCallPart from a pydantic-ai result into a flat list.

    Each entry is ``{"name": tool_name, "args": args}``. Args may be a dict,
    a JSON string, or None depending on how the model emitted them.
    """
    calls: list[dict[str, Any]] = []
    try:
        messages = result.all_messages()
    except AttributeError:
        return calls
    for msg in messages:
        for part in getattr(msg, "parts", ()) or ():
            tool_name = getattr(part, "tool_name", None)
            if tool_name and getattr(part, "part_kind", None) == "tool-call":
                calls.append({"name": tool_name, "args": getattr(part, "args", None)})
    return calls


def make_router_inspect_task(
    deps: GalaxyAgentDependencies,
    context: Optional[dict] = None,
) -> Callable[[str], Awaitable[dict[str, Any]]]:
    """Build an async callable: query -> {"content": str, "tool_calls": list}.

    Bypasses ``QueryRouterAgent.process`` so we can read tool calls off the
    raw pydantic-ai result. Useful for evaluating router fast-path tool use
    (did it call ``search_tools`` when asked "is FastQC installed?"?).
    """

    async def router_inspect_task(query: str) -> dict[str, Any]:
        router = QueryRouterAgent(deps)
        message_history = router._extract_message_history(context)
        result = await router._run_with_retry(query, message_history=message_history)
        return {
            "content": extract_result_content(result),
            "tool_calls": _extract_tool_calls(result),
        }

    return router_inspect_task
