"""Cross-model evaluation runner for Galaxy agents.

Run from Galaxy root with the venv active:

    python -m evals.run_evals --models gpt-oss-120b,Llama-4-Maverick-17B-128E-Instruct

By default all models go through one proxy (`--proxy-url`/`--api-key` or env
GALAXY_AGENT_EVALS_PROXY_URL / GALAXY_AGENT_EVALS_API_KEY -- defaults are
LiteLLM at http://localhost:4000/v1/). For models that live on a different
backend, pass `--model-config <yaml>` mapping model -> {proxy_url,
api_key_env}. See evals/models.yaml.sample.

Writes a markdown comparison table to stdout and to evals/results/.
"""

import argparse
import asyncio
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Optional,
)

import yaml
from pydantic_evals.reporting import EvaluationReport

from .datasets import routing_dataset
from .evaluators import HandoffMatch
from .tasks import (
    DEFAULT_PROXY_KEY,
    DEFAULT_PROXY_URL,
    make_deps,
    make_router_task,
)


@dataclass
class ModelResult:
    model: str
    report: EvaluationReport[str, str, dict[str, Any]]


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


async def _run_model(
    model: str,
    api_key: str,
    proxy_url: str,
    include_galaxy_required: bool,
    only: Optional[list[str]],
    max_concurrency: Optional[int],
) -> ModelResult:
    deps = make_deps(model=model, api_key=api_key, base_url=proxy_url)
    task = make_router_task(deps)
    dataset = routing_dataset(include_galaxy_required=include_galaxy_required, only=only)
    dataset.add_evaluator(HandoffMatch())
    report = await dataset.evaluate(task, name=model, max_concurrency=max_concurrency)
    return ModelResult(model=model, report=report)


def _accuracy(report: EvaluationReport[str, str, dict[str, Any]]) -> tuple[int, int]:
    """Count cases that scored a perfect HandoffMatch. Failures count as wrong."""
    passed = 0
    total = len(report.cases) + len(report.failures)
    for case in report.cases:
        scores = case.scores or {}
        match = scores.get("HandoffMatch")
        if match is not None and float(match.value) >= 1.0:
            passed += 1
    return passed, total


def _median_duration_s(
    report: EvaluationReport[str, str, dict[str, Any]],
) -> Optional[float]:
    durations = [c.task_duration for c in report.cases if c.task_duration is not None]
    return statistics.median(durations) if durations else None


def render_markdown(results: list[ModelResult], dataset_name: str) -> str:
    """Build a model-comparison markdown table from per-model reports."""
    lines: list[str] = []
    lines.append(f"# Galaxy agent evals -- {dataset_name}")
    lines.append("")
    lines.append(f"_Generated {datetime.now().isoformat(timespec='seconds')} from `{_git_sha()}`._")
    lines.append("")

    header = "| metric | " + " | ".join(r.model for r in results) + " |"
    sep = "| --- | " + " | ".join("---" for _ in results) + " |"
    lines.append(header)
    lines.append(sep)

    accuracy_row = ["routing accuracy"]
    latency_row = ["median latency (s)"]
    for r in results:
        passed, total = _accuracy(r.report)
        accuracy_row.append(f"{passed}/{total}" if total else "-")
        med = _median_duration_s(r.report)
        latency_row.append(f"{med:.2f}" if med is not None else "-")
    lines.append("| " + " | ".join(accuracy_row) + " |")
    lines.append("| " + " | ".join(latency_row) + " |")

    lines.append("")
    lines.append("## Per-case detail")
    lines.append("")
    case_header = "| case | expected | " + " | ".join(r.model for r in results) + " |"
    case_sep = "| --- | --- | " + " | ".join("---" for _ in results) + " |"
    lines.append(case_header)
    lines.append(case_sep)

    case_names: list[str] = []
    expected_by_name: dict[str, str] = {}
    for r in results:
        for c in r.report.cases:
            if c.name and c.name not in expected_by_name:
                case_names.append(c.name)
                expected_by_name[c.name] = str(c.expected_output) if c.expected_output is not None else "-"
        for f in r.report.failures:
            if f.name and f.name not in expected_by_name:
                case_names.append(f.name)
                expected_by_name[f.name] = str(f.expected_output) if f.expected_output is not None else "-"

    for case_name in case_names:
        row = [case_name, expected_by_name[case_name]]
        for r in results:
            case = next((c for c in r.report.cases if c.name == case_name), None)
            failure = next((f for f in r.report.failures if f.name == case_name), None)
            if case is not None:
                scores = case.scores or {}
                match = scores.get("HandoffMatch")
                actual = case.output if case.output is not None else "?"
                ok = match is not None and float(match.value) >= 1.0
                row.append("OK" if ok else f"WRONG ({actual})")
            elif failure is not None:
                row.append("ERROR")
            else:
                row.append("-")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated model names to evaluate against the LiteLLM proxy.",
    )
    parser.add_argument(
        "--proxy-url",
        default=os.environ.get("GALAXY_AGENT_EVALS_PROXY_URL", DEFAULT_PROXY_URL),
        help=f"LiteLLM proxy URL (default {DEFAULT_PROXY_URL}).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GALAXY_AGENT_EVALS_API_KEY", DEFAULT_PROXY_KEY),
        help="API key for the proxy.",
    )
    parser.add_argument(
        "--model-config",
        help="Path to YAML mapping model -> {proxy_url, api_key_env}. Per-model "
        "overrides for models that live on a backend other than --proxy-url.",
    )
    parser.add_argument(
        "--include-galaxy-required",
        action="store_true",
        help="Include cases that need a running Galaxy session (history_analyzer cases).",
    )
    parser.add_argument(
        "--only",
        help="Comma-separated case names to restrict the run to.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=4,
        help="Per-model max concurrent agent calls (default 4).",
    )
    parser.add_argument(
        "--results-dir",
        default="evals/results",
        help="Directory to write the markdown report (default evals/results).",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Skip writing the report file; print to stdout only.",
    )
    return parser.parse_args()


def _resolve_model_endpoint(
    model: str,
    model_config: dict[str, Any],
    default_url: str,
    default_key: str,
) -> tuple[str, str]:
    """Return (proxy_url, api_key) for a model, falling back to defaults."""
    entry = model_config.get(model)
    if not entry:
        return default_url, default_key
    proxy_url = entry.get("proxy_url", default_url)
    api_key_env = entry.get("api_key_env")
    api_key = os.environ.get(api_key_env) if api_key_env else None
    if api_key_env and not api_key:
        raise SystemExit(f"Model '{model}' requires env var {api_key_env} (not set).")
    return proxy_url, api_key or default_key


async def amain() -> int:
    args = parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    only = [n.strip() for n in args.only.split(",")] if args.only else None

    model_config: dict[str, Any] = {}
    if args.model_config:
        with open(args.model_config) as f:
            model_config = yaml.safe_load(f) or {}

    results: list[ModelResult] = []
    for model in models:
        proxy_url, api_key = _resolve_model_endpoint(model, model_config, args.proxy_url, args.api_key)
        print(f"\n=== Evaluating {model} (via {proxy_url}) ===", file=sys.stderr)
        result = await _run_model(
            model=model,
            api_key=api_key,
            proxy_url=proxy_url,
            include_galaxy_required=args.include_galaxy_required,
            only=only,
            max_concurrency=args.max_concurrency,
        )
        results.append(result)
        result.report.print(include_input=False, include_output=False)

    md = render_markdown(results, dataset_name="routing")
    print(md)

    if not args.no_write:
        results_dir = Path(args.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out = results_dir / f"{stamp}-routing-{_git_sha()}.md"
        out.write_text(md)
        print(f"\nWrote {out}", file=sys.stderr)

    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
