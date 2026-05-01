"""Routing dataset: (query, expected handoff target) for the QueryRouterAgent.

Seeded from ~/.claude/plans/galaxy-agents/test_agents_live.py and the
TEST_QUERIES in test/unit/app/test_agents.py. Cases marked
requires_galaxy=True need a running Galaxy session and are skipped by default.
"""

from typing import (
    Any,
    Optional,
)

from pydantic_evals import (
    Case,
    Dataset,
)


def _case(
    name: str,
    query: str,
    expected: str,
    description: str,
    requires_galaxy: bool = False,
) -> Case[str, str, dict[str, Any]]:
    return Case(
        name=name,
        inputs=query,
        expected_output=expected,
        metadata={"description": description, "requires_galaxy": requires_galaxy},
    )


ROUTING_CASES: list[Case[str, str, dict[str, Any]]] = [
    # Direct router responses
    _case("greeting", "Hi, what can you help me with?", "router", "General greeting"),
    _case(
        "upload_basics",
        "How do I upload a file to Galaxy?",
        "router",
        "Basic Galaxy usage",
    ),
    _case(
        "tool_discovery_rnaseq",
        "What tools are available for RNA-seq analysis?",
        "router",
        "Tool discovery -- router answers directly",
    ),
    _case("citation", "How do I cite Galaxy in my paper?", "router", "Citation request"),
    _case(
        "off_topic_weather",
        "What's the weather like today?",
        "router",
        "Off-topic -- router declines",
    ),
    # Error analysis handoff
    _case(
        "oom_137",
        "My job failed with exit code 137 and stderr shows 'Killed'. What happened?",
        "error_analysis",
        "OOM kill -- exit 137",
    ),
    _case(
        "command_not_found",
        "I got 'command not found: samtools' in my job stderr. How do I fix this?",
        "error_analysis",
        "Missing tool error",
    ),
    _case(
        "bwa_oom",
        "Why did my BWA job fail? The log shows 'out of memory'",
        "error_analysis",
        "Memory error",
    ),
    # Custom tool handoff
    _case(
        "tool_create_fasta_lines",
        "Create a Galaxy tool that counts lines in a FASTA file",
        "custom_tool",
        "Tool creation request",
    ),
    _case(
        "tool_wrap_seqtk",
        "Build a wrapper for the seqtk command line tool",
        "custom_tool",
        "Tool wrapper request",
    ),
    # History analyzer handoff (requires Galaxy)
    _case(
        "history_summary",
        "Summarize my current history",
        "history_analyzer",
        "History summary",
        requires_galaxy=True,
    ),
    _case(
        "history_question",
        "What analysis did I perform in my RNA-seq history?",
        "history_analyzer",
        "History question",
        requires_galaxy=True,
    ),
    _case(
        "methods_section",
        "Generate a methods section for my analysis",
        "history_analyzer",
        "Methods generation",
        requires_galaxy=True,
    ),
    _case(
        "tool_versions_used",
        "What tools and versions did I use?",
        "history_analyzer",
        "Tool usage question",
        requires_galaxy=True,
    ),
]


def routing_dataset(
    include_galaxy_required: bool = False,
    only: Optional[list[str]] = None,
) -> Dataset[str, str, dict[str, Any]]:
    """Build the routing Dataset.

    Args:
        include_galaxy_required: include cases that need a running Galaxy session.
        only: if given, restrict to cases whose name is in this list.
    """
    cases = ROUTING_CASES
    if not include_galaxy_required:
        cases = [c for c in cases if not (c.metadata or {}).get("requires_galaxy")]
    if only:
        wanted = set(only)
        cases = [c for c in cases if c.name in wanted]
    return Dataset(name="routing", cases=cases)
