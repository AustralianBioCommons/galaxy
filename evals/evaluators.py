"""Custom pydantic-evals evaluators for Galaxy agents."""

from dataclasses import dataclass
from typing import Any

from pydantic_evals.evaluators import (
    Evaluator,
    EvaluatorContext,
)


def _output_text(output: Any) -> str:
    """Pull a string out of a task output that may be a str or {"content": str, ...} dict."""
    if isinstance(output, dict):
        return str(output.get("content") or "")
    return str(output or "")


@dataclass
class HandoffMatch(Evaluator[str, str, dict]):
    """Score 1.0 if router's chosen agent_type matches expected, 0.0 otherwise."""

    def evaluate(self, ctx: EvaluatorContext[str, str, dict]) -> float:
        return 1.0 if ctx.output == ctx.expected_output else 0.0


@dataclass
class MustMention(Evaluator[str, str, dict]):
    """Score 1.0 if every keyword in metadata['must_mention'] appears in the output (case-insensitive)."""

    def evaluate(self, ctx: EvaluatorContext[str, str, dict]) -> float:
        keywords = (ctx.metadata or {}).get("must_mention") or []
        if not keywords:
            return 1.0
        text = (ctx.output or "").lower()
        return 1.0 if all(kw.lower() in text for kw in keywords) else 0.0


@dataclass
class MustMentionAny(Evaluator[Any, Any, dict]):
    """Score 1.0 if any keyword in metadata['must_mention_any'] appears (case-insensitive).

    Use this when several alternatives are equally acceptable -- e.g. naming
    HISAT2 *or* STAR *or* Salmon for an RNA-seq alignment recommendation.
    """

    def evaluate(self, ctx: EvaluatorContext[Any, Any, dict]) -> float:
        keywords = (ctx.metadata or {}).get("must_mention_any") or []
        if not keywords:
            return 1.0
        text = _output_text(ctx.output).lower()
        return 1.0 if any(kw.lower() in text for kw in keywords) else 0.0
