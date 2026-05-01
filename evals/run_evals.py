"""Cross-model evaluation runner for Galaxy agents.

Run from Galaxy root with the venv active:

    python -m evals.run_evals --models gpt-oss-120b,Llama-4-Maverick-17B-128E-Instruct

By default all models go through one proxy (`--proxy-url`/`--api-key` or env
GALAXY_AGENT_EVALS_PROXY_URL / GALAXY_AGENT_EVALS_API_KEY -- defaults are
LiteLLM at http://localhost:4000/v1/). For models that live on a different
backend, pass `--model-config <yaml>` mapping model -> {proxy_url,
api_key_env}. See evals/models.yaml.sample.

Datasets default to all registered (routing, error_analysis). Restrict with
`--datasets routing` or similar. Fuzzy quality scoring (LLM judge) uses
`--judge-model` (default gpt-oss-120b on the local LiteLLM proxy).

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

from .judge import build_judge_model
from .specs import SPECS
from .tasks import (
    DEFAULT_PROXY_KEY,
    DEFAULT_PROXY_URL,
    make_deps,
)


@dataclass
class DatasetResult:
    dataset: str
    model: str
    primary_score: str
    report: EvaluationReport[str, str, dict[str, Any]]


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


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
    if "api_key" in entry:
        return proxy_url, entry["api_key"]
    api_key_env = entry.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise SystemExit(f"Model '{model}' requires env var {api_key_env} (not set).")
        return proxy_url, api_key
    return proxy_url, default_key


def _score_pass_count(
    report: EvaluationReport[Any, Any, Any], score_name: str, threshold: float = 1.0
) -> tuple[int, int]:
    """Count cases where the named score met or exceeded threshold. Failures count as wrong."""
    passed = 0
    total = len(report.cases) + len(report.failures)
    for case in report.cases:
        scores = case.scores or {}
        match = scores.get(score_name)
        if match is not None:
            try:
                value = float(match.value)
            except (TypeError, ValueError):
                continue
            if value >= threshold:
                passed += 1
    return passed, total


def _median_duration_s(report: EvaluationReport[Any, Any, Any]) -> Optional[float]:
    durations = [c.task_duration for c in report.cases if c.task_duration is not None]
    return statistics.median(durations) if durations else None


def _all_score_names(reports: list[EvaluationReport[Any, Any, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for r in reports:
        for case in r.cases:
            for score_name in (case.scores or {}).keys():
                if score_name not in seen:
                    seen.add(score_name)
                    names.append(score_name)
    return names


def _render_dataset_section(results: list[DatasetResult]) -> str:
    """Render one markdown section per (dataset, models...) tuple."""
    if not results:
        return ""
    dataset_name = results[0].dataset
    primary = results[0].primary_score
    lines = [f"## {dataset_name}", ""]

    header = "| metric | " + " | ".join(r.model for r in results) + " |"
    sep = "| --- | " + " | ".join("---" for _ in results) + " |"
    lines += [header, sep]

    score_names = _all_score_names([r.report for r in results])
    if primary in score_names:
        score_names = [primary] + [n for n in score_names if n != primary]

    for score_name in score_names:
        row = [score_name]
        for r in results:
            passed, total = _score_pass_count(r.report, score_name, threshold=1.0 if score_name != "LLMJudge" else 0.7)
            row.append(f"{passed}/{total}" if total else "-")
        lines.append("| " + " | ".join(row) + " |")

    latency_row = ["median latency (s)"]
    for r in results:
        med = _median_duration_s(r.report)
        latency_row.append(f"{med:.2f}" if med is not None else "-")
    lines.append("| " + " | ".join(latency_row) + " |")
    lines.append("")

    lines += ["### Per-case detail", ""]
    case_header = "| case | " + " | ".join(r.model for r in results) + " |"
    case_sep = "| --- | " + " | ".join("---" for _ in results) + " |"
    lines += [case_header, case_sep]

    case_names: list[str] = []
    expected_by_name: dict[str, str] = {}
    for r in results:
        for c in r.report.cases:
            if c.name and c.name not in expected_by_name:
                case_names.append(c.name)
                expected_by_name[c.name] = str(c.expected_output) if c.expected_output is not None else ""
        for f in r.report.failures:
            if f.name and f.name not in expected_by_name:
                case_names.append(f.name)
                expected_by_name[f.name] = str(f.expected_output) if f.expected_output is not None else ""

    for case_name in case_names:
        row = [case_name]
        for r in results:
            case = next((c for c in r.report.cases if c.name == case_name), None)
            failure = next((f for f in r.report.failures if f.name == case_name), None)
            if case is not None:
                scores = case.scores or {}
                primary_score = scores.get(r.primary_score)
                ok = primary_score is not None and float(primary_score.value) >= 1.0
                if ok:
                    if "LLMJudge" in scores:
                        try:
                            judge_value = float(scores["LLMJudge"].value)
                            row.append(f"OK (judge {judge_value:.2f})")
                            continue
                        except (TypeError, ValueError):
                            pass
                    row.append("OK")
                else:
                    if case.output is None:
                        actual = "?"
                    else:
                        actual = " ".join(str(case.output).split())[:60]
                    row.append(f"WRONG ({actual})")
            elif failure is not None:
                row.append("ERROR")
            else:
                row.append("-")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    return "\n".join(lines)


def render_markdown(all_results: list[DatasetResult]) -> str:
    """Render a single markdown document covering every dataset evaluated."""
    by_dataset: dict[str, list[DatasetResult]] = {}
    for r in all_results:
        by_dataset.setdefault(r.dataset, []).append(r)

    lines = [
        f"# Galaxy agent evals -- {datetime.now().strftime('%Y-%m-%d')}",
        "",
        f"_Generated {datetime.now().isoformat(timespec='seconds')} from `{_git_sha()}`._",
        "",
    ]
    for results in by_dataset.values():
        lines.append(_render_dataset_section(results))
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated model names to evaluate against the LiteLLM proxy.",
    )
    parser.add_argument(
        "--datasets",
        default=",".join(SPECS.keys()),
        help=f"Comma-separated datasets to run (default: {','.join(SPECS.keys())}).",
    )
    parser.add_argument(
        "--judge-model",
        default="gpt-oss-120b",
        help="Model to use as LLM-as-judge for fuzzy quality scoring (default gpt-oss-120b).",
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
        help="Path to YAML mapping model -> {proxy_url, api_key/api_key_env}. "
        "Per-model overrides for models on a different backend than --proxy-url.",
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


async def amain() -> int:
    args = parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    only = [n.strip() for n in args.only.split(",")] if args.only else None

    for ds in datasets:
        if ds not in SPECS:
            raise SystemExit(f"Unknown dataset: {ds}. Known: {', '.join(SPECS)}.")

    model_config: dict[str, Any] = {}
    if args.model_config:
        with open(args.model_config) as f:
            model_config = yaml.safe_load(f) or {}

    judge_proxy_url, judge_api_key = _resolve_model_endpoint(
        args.judge_model, model_config, args.proxy_url, args.api_key
    )
    judge_model = build_judge_model(args.judge_model, judge_proxy_url, judge_api_key)
    print(f"Judge: {args.judge_model} (via {judge_proxy_url})", file=sys.stderr)

    all_results: list[DatasetResult] = []
    for ds_name in datasets:
        spec_fn = SPECS[ds_name]
        for model in models:
            proxy_url, api_key = _resolve_model_endpoint(model, model_config, args.proxy_url, args.api_key)
            print(f"\n=== {ds_name} | {model} (via {proxy_url}) ===", file=sys.stderr)
            deps = make_deps(model=model, api_key=api_key, base_url=proxy_url)
            built = spec_fn(
                deps,
                judge_model=judge_model,
                only=only,
                include_galaxy_required=args.include_galaxy_required,
            )
            report = await built.dataset.evaluate(
                built.task,
                name=f"{ds_name}/{model}",
                max_concurrency=args.max_concurrency,
            )
            report.print(include_input=False, include_output=False)
            all_results.append(
                DatasetResult(
                    dataset=ds_name,
                    model=model,
                    primary_score=built.primary_score,
                    report=report,
                )
            )

    md = render_markdown(all_results)
    print(md)

    if not args.no_write:
        results_dir = Path(args.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        slug = "+".join(datasets)
        out = results_dir / f"{stamp}-{slug}-{_git_sha()}.md"
        out.write_text(md)
        print(f"\nWrote {out}", file=sys.stderr)

    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
