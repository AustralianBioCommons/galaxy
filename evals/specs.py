"""DatasetSpec registry: each spec wires a dataset to its task and evaluators.

Used by run_evals.py to iterate over datasets without hard-coding any of them.
"""

from collections.abc import (
    Awaitable,
    Callable,
)
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
)

from pydantic_ai.models import Model
from pydantic_evals import Dataset

from galaxy.agents.base import GalaxyAgentDependencies
from .datasets import (
    bioinformatics_workflows_dataset,
    error_analysis_dataset,
    router_tool_use_dataset,
    routing_dataset,
    tool_recommendation_dataset,
)
from .evaluators import (
    HandoffMatch,
    MustMention,
    MustMentionAny,
    ToolCallMatch,
)
from .tasks import (
    make_error_analysis_task,
    make_router_content_task,
    make_router_inspect_task,
    make_router_task,
    make_tool_recommendation_task,
)


@dataclass
class BuiltDataset:
    """A dataset configured with evaluators and a task ready to evaluate."""

    dataset: Dataset[str, Any, dict[str, Any]]
    task: Callable[[str], Awaitable[Any]]
    primary_score: str  # name of the headline scorer for the summary table


def build_routing(
    deps: GalaxyAgentDependencies,
    judge_model: Optional[Model] = None,
    only: Optional[list[str]] = None,
    include_galaxy_required: bool = False,
) -> BuiltDataset:
    dataset = routing_dataset(include_galaxy_required=include_galaxy_required, only=only)
    dataset.add_evaluator(HandoffMatch())
    return BuiltDataset(dataset=dataset, task=make_router_task(deps), primary_score="HandoffMatch")


def build_error_analysis(
    deps: GalaxyAgentDependencies,
    judge_model: Optional[Model] = None,
    only: Optional[list[str]] = None,
    include_galaxy_required: bool = False,
) -> BuiltDataset:
    dataset = error_analysis_dataset(judge_model=judge_model, only=only)
    dataset.add_evaluator(MustMention())
    return BuiltDataset(
        dataset=dataset,
        task=make_error_analysis_task(deps),
        primary_score="MustMention",
    )


def build_tool_recommendation(
    deps: GalaxyAgentDependencies,
    judge_model: Optional[Model] = None,
    only: Optional[list[str]] = None,
    include_galaxy_required: bool = False,
) -> BuiltDataset:
    dataset = tool_recommendation_dataset(judge_model=judge_model, only=only)
    dataset.add_evaluator(MustMentionAny())
    return BuiltDataset(
        dataset=dataset,
        task=make_tool_recommendation_task(deps),
        primary_score="MustMentionAny",
    )


def build_router_tool_use(
    deps: GalaxyAgentDependencies,
    judge_model: Optional[Model] = None,
    only: Optional[list[str]] = None,
    include_galaxy_required: bool = False,
) -> BuiltDataset:
    dataset = router_tool_use_dataset(only=only)
    dataset.add_evaluator(ToolCallMatch())
    return BuiltDataset(
        dataset=dataset,
        task=make_router_inspect_task(deps),
        primary_score="ToolCallMatch",
    )


def build_bioinformatics_workflows(
    deps: GalaxyAgentDependencies,
    judge_model: Optional[Model] = None,
    only: Optional[list[str]] = None,
    include_galaxy_required: bool = False,
) -> BuiltDataset:
    dataset = bioinformatics_workflows_dataset(judge_model=judge_model, only=only)
    return BuiltDataset(
        dataset=dataset,
        task=make_router_content_task(deps),
        primary_score="LLMJudge",
    )


SPECS: dict[str, Callable[..., BuiltDataset]] = {
    "routing": build_routing,
    "error_analysis": build_error_analysis,
    "tool_recommendation": build_tool_recommendation,
    "router_tool_use": build_router_tool_use,
    "bioinformatics_workflows": build_bioinformatics_workflows,
}
