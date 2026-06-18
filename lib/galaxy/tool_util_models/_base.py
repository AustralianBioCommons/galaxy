"""Base model classes for tool utilities."""

from typing import Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
)
from typing_extensions import Annotated


class ToolSourceBaseModel(BaseModel):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Liberal-input coercions (accepting the loose shapes LLMs emit -- a string ``help``,
# a ``value`` on a select, a single ``discover_datasets`` object, a meaningless
# ``min`` on a single data input) are gated on this validation-context flag so they
# apply ONLY when ingesting agent output. The canonical API / storage / lift path
# validates without it and stays strict, surfacing those shapes as errors instead of
# silently rewriting them. The agent opts in via ``Agent(validation_context=AGENT_LENIENT_CONTEXT)``.
LENIENT_CONTEXT_KEY = "lenient"
AGENT_LENIENT_CONTEXT = {LENIENT_CONTEXT_KEY: True}


def lenient_coercion_enabled(info) -> bool:
    """True when validation is running in agent-ingest mode (see above)."""
    context = getattr(info, "context", None)
    return bool(isinstance(context, dict) and context.get(LENIENT_CONTEXT_KEY))


def _check_collection_type(v: str) -> str:
    if len(v) == 0:
        raise ValueError("Invalid empty collection_type specified.")
    for level in v.split(":"):
        if level not in ("list", "paired", "paired_or_unpaired", "record", "sample_sheet"):
            raise ValueError(f"Invalid collection_type specified [{v}]")
    return v


CollectionType = Annotated[Optional[str], AfterValidator(_check_collection_type)]
