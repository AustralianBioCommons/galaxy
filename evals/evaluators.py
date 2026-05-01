"""Custom pydantic-evals evaluators for Galaxy agents."""

from dataclasses import dataclass

from pydantic_evals.evaluators import (
    Evaluator,
    EvaluatorContext,
)


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
