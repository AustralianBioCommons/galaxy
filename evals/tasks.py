"""Task callables that wrap Galaxy agents for use with pydantic-evals.

Each task takes a string query and returns the field of an AgentResponse we
care about scoring. Today: routing target. Future: full AgentResponse for
quality scorers.
"""

from collections.abc import (
    Awaitable,
    Callable,
)
from typing import (
    Optional,
)
from unittest.mock import MagicMock

from galaxy.agents.base import GalaxyAgentDependencies
from galaxy.agents.registry import build_default_registry
from galaxy.agents.router import QueryRouterAgent

DEFAULT_PROXY_URL = "http://localhost:4000/v1/"
DEFAULT_PROXY_KEY = "sk-local-test-master-key"

_registry = build_default_registry()


def make_deps(
    model: str,
    api_key: str = DEFAULT_PROXY_KEY,
    base_url: str = DEFAULT_PROXY_URL,
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
    return GalaxyAgentDependencies(
        trans=MagicMock(),
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
