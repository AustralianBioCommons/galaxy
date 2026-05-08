"""Cross-model evaluation runner for Galaxy agents.

Run from Galaxy root with the venv active:

    python -m evals.run_evals

Reads `evals/models.yaml` (falling back to `evals/models.yaml.sample`) for
the full set of models to evaluate. `--models gpt-oss-120b,...` filters
to a subset of those declared. Every model -- including the LLM judge --
must appear in the YAML.

Datasets default to all registered (routing, error_analysis). Restrict with
`--datasets routing` or similar. Fuzzy quality scoring (LLM judge) uses
`--judge-model` (default gpt-oss-120b -- must also be in the YAML).

Writes a markdown comparison table to stdout and to evals/results/.
"""

import argparse
import asyncio
import os
import statistics
import sys
from dataclasses import (
    dataclass,
    field,
)
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Optional,
)

import yaml
from pydantic_evals.reporting import (
    EvaluationReport,
    EvaluationReportAdapter,
)

from .judge import build_judge_model
from .pricing import model_cost
from .specs import SPECS
from .tasks import make_deps

DEFAULT_MODEL_CONFIG = "evals/models.yaml"
FALLBACK_MODEL_CONFIG = "evals/models.yaml.sample"


@dataclass
class DatasetResult:
    dataset: str
    model: str
    primary_score: str
    report: EvaluationReport[str, str, dict[str, Any]]
    usage: list[dict[str, int]] = field(default_factory=list)


def _usage_totals(usage: list[dict[str, int]]) -> dict[str, int]:
    total_in = sum(u.get("input_tokens", 0) for u in usage)
    total_out = sum(u.get("output_tokens", 0) for u in usage)
    return {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "total_tokens": total_in + total_out,
        "calls": len(usage),
    }


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _resolve_model_endpoint(model: str, model_config: dict[str, Any]) -> tuple[str, str]:
    """Return (proxy_url, api_key) for a model declared in model_config."""
    entry = model_config.get(model)
    if not entry:
        raise SystemExit(
            f"Model '{model}' is not declared in the model-config YAML. "
            f"Known: {', '.join(model_config) or '(none)'}."
        )
    proxy_url = entry.get("proxy_url")
    if not proxy_url:
        raise SystemExit(f"Model '{model}' is missing proxy_url in the YAML.")
    if "api_key" in entry:
        return proxy_url, entry["api_key"]
    api_key_env = entry.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise SystemExit(f"Model '{model}' requires env var {api_key_env} (not set).")
        return proxy_url, api_key
    raise SystemExit(f"Model '{model}' needs either api_key or api_key_env in the YAML.")


def _load_model_config(path: Optional[str]) -> tuple[str, dict[str, Any]]:
    """Resolve the model-config YAML path and load it. Falls back to .sample.

    Returns (path_used, parsed_dict).
    """
    candidate = path or DEFAULT_MODEL_CONFIG
    if not os.path.exists(candidate):
        if path:
            raise SystemExit(f"--model-config '{path}' does not exist.")
        if os.path.exists(FALLBACK_MODEL_CONFIG):
            candidate = FALLBACK_MODEL_CONFIG
        else:
            raise SystemExit(
                f"No model config found at {DEFAULT_MODEL_CONFIG} or {FALLBACK_MODEL_CONFIG}. "
                "Copy the sample and fill in your models."
            )
    with open(candidate) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict) or not data:
        raise SystemExit(f"Model config '{candidate}' is empty or invalid.")
    return candidate, data


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


def _base_case_name(name: Optional[str]) -> Optional[str]:
    """Strip pydantic-evals' " [N/M]" repeat suffix from a case name."""
    if not name:
        return name
    import re

    return re.sub(r"\s+\[\d+/\d+\]$", "", name)


def _case_outcomes(
    result: "DatasetResult",
) -> dict[str, dict[str, Any]]:
    """Reduce a DatasetResult's per-case rows to {case_name: {ok, errored, primary, judge}}."""
    out: dict[str, dict[str, Any]] = {}
    pass_threshold = 0.7 if result.primary_score == "LLMJudge" else 1.0
    for case in result.report.cases:
        base = _base_case_name(case.name)
        if not base:
            continue
        scores = case.scores or {}
        primary = scores.get(result.primary_score)
        ok = primary is not None and float(primary.value) >= pass_threshold
        bucket = out.setdefault(base, {"ok": 0, "wrong": 0, "errored": 0, "judge": []})
        if ok:
            bucket["ok"] += 1
        else:
            bucket["wrong"] += 1
        judge = scores.get("LLMJudge")
        if judge is not None:
            try:
                bucket["judge"].append(float(judge.value))
            except (TypeError, ValueError):
                pass
    for failure in result.report.failures:
        base = _base_case_name(failure.name)
        if not base:
            continue
        bucket = out.setdefault(base, {"ok": 0, "wrong": 0, "errored": 0, "judge": []})
        bucket["errored"] += 1
    return out


def _outcome_label(bucket: dict[str, Any]) -> str:
    """Single-line summary of a case bucket: 'OK', 'WRONG', 'ERROR', or 'OK 2/3'."""
    runs = bucket["ok"] + bucket["wrong"] + bucket["errored"]
    if runs == 0:
        return "?"
    if runs == 1:
        if bucket["errored"]:
            return "ERROR"
        return "OK" if bucket["ok"] else "WRONG"
    parts = [f"OK {bucket['ok']}/{runs}"]
    if bucket["errored"]:
        parts.append(f"ERR {bucket['errored']}/{runs}")
    return " ".join(parts)


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

    if any(r.usage for r in results):
        tokens_row = ["total tokens (in/out)"]
        cost_row = ["est. cost ($)"]
        for r in results:
            totals = _usage_totals(r.usage)
            tokens_row.append(f"{totals['input_tokens']}/{totals['output_tokens']}" if r.usage else "-")
            cost = sum(model_cost(r.model, u.get("input_tokens", 0), u.get("output_tokens", 0)) for u in r.usage)
            cost_row.append(f"{cost:.4f}" if r.usage else "-")
        lines.append("| " + " | ".join(tokens_row) + " |")
        lines.append("| " + " | ".join(cost_row) + " |")
    lines.append("")

    lines += ["### Per-case detail", ""]
    case_header = "| case | " + " | ".join(r.model for r in results) + " |"
    case_sep = "| --- | " + " | ".join("---" for _ in results) + " |"
    lines += [case_header, case_sep]

    case_names: list[str] = []
    expected_by_name: dict[str, str] = {}
    for r in results:
        for c in r.report.cases:
            base = _base_case_name(c.name)
            if base and base not in expected_by_name:
                case_names.append(base)
                expected_by_name[base] = str(c.expected_output) if c.expected_output is not None else ""
        for f in r.report.failures:
            base = _base_case_name(f.name)
            if base and base not in expected_by_name:
                case_names.append(base)
                expected_by_name[base] = str(f.expected_output) if f.expected_output is not None else ""

    for case_name in case_names:
        row = [case_name]
        for r in results:
            cases = [c for c in r.report.cases if _base_case_name(c.name) == case_name]
            failures = [f for f in r.report.failures if _base_case_name(f.name) == case_name]
            runs = len(cases) + len(failures)
            if runs == 0:
                row.append("-")
                continue
            ok_count = 0
            judge_values: list[float] = []
            wrong_sample: Optional[str] = None
            pass_threshold = 0.7 if r.primary_score == "LLMJudge" else 1.0
            for case in cases:
                scores = case.scores or {}
                primary_score = scores.get(r.primary_score)
                ok = primary_score is not None and float(primary_score.value) >= pass_threshold
                if ok:
                    ok_count += 1
                elif wrong_sample is None and case.output is not None:
                    wrong_sample = " ".join(str(case.output).split())[:60]
                judge = scores.get("LLMJudge")
                if judge is not None:
                    try:
                        judge_values.append(float(judge.value))
                    except (TypeError, ValueError):
                        pass
            if runs == 1:
                if ok_count == 1:
                    if judge_values:
                        row.append(f"OK (judge {judge_values[0]:.2f})")
                    else:
                        row.append("OK")
                elif failures:
                    row.append("ERROR")
                else:
                    row.append(f"WRONG ({wrong_sample or '?'})")
            else:
                cell = f"{ok_count}/{runs}"
                if judge_values:
                    avg = sum(judge_values) / len(judge_values)
                    cell += f" (judge {avg:.2f})"
                if failures:
                    cell += f" [+{len(failures)} ERR]"
                row.append(cell)
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    return "\n".join(lines)


def render_markdown(
    all_results: list["DatasetResult"],
    baseline: Optional[list["DatasetResult"]] = None,
) -> str:
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
    if baseline:
        lines.append(_render_diff_section(all_results, baseline))
    for results in by_dataset.values():
        lines.append(_render_dataset_section(results))
    return "\n".join(lines)


def _render_diff_section(
    new_results: list["DatasetResult"],
    baseline: list["DatasetResult"],
) -> str:
    """Render regressions and improvements vs. the baseline run."""
    new_index: dict[tuple[str, str], DatasetResult] = {(r.dataset, r.model): r for r in new_results}
    base_index: dict[tuple[str, str], DatasetResult] = {(r.dataset, r.model): r for r in baseline}

    lines = ["## Changes vs baseline", ""]
    any_change = False

    for key, new_result in new_index.items():
        if key not in base_index:
            continue
        ds_name, model = key
        new_outcomes = _case_outcomes(new_result)
        base_outcomes = _case_outcomes(base_index[key])
        regressions: list[tuple[str, str, str]] = []
        improvements: list[tuple[str, str, str]] = []
        for case_name in sorted(set(new_outcomes) & set(base_outcomes)):
            new_b = new_outcomes[case_name]
            base_b = base_outcomes[case_name]
            new_pass = new_b["ok"] >= max(1, new_b["ok"] + new_b["wrong"] + new_b["errored"])
            base_pass = base_b["ok"] >= max(1, base_b["ok"] + base_b["wrong"] + base_b["errored"])
            if new_pass and not base_pass:
                improvements.append((case_name, _outcome_label(base_b), _outcome_label(new_b)))
            elif base_pass and not new_pass:
                regressions.append((case_name, _outcome_label(base_b), _outcome_label(new_b)))

        if not (regressions or improvements):
            continue
        any_change = True
        lines.append(f"### {ds_name} | {model}")
        if regressions:
            lines.append("")
            lines.append("**Regressions:**")
            lines.append("")
            lines.append("| case | baseline | now |")
            lines.append("| --- | --- | --- |")
            for case_name, base_state, new_state in regressions:
                lines.append(f"| {case_name} | {base_state} | {new_state} |")
        if improvements:
            lines.append("")
            lines.append("**Improvements:**")
            lines.append("")
            lines.append("| case | baseline | now |")
            lines.append("| --- | --- | --- |")
            for case_name, base_state, new_state in improvements:
                lines.append(f"| {case_name} | {base_state} | {new_state} |")
        lines.append("")

    if not any_change:
        lines.append("_No per-case changes vs baseline._")
        lines.append("")
    return "\n".join(lines)


def _serialize_results(all_results: list["DatasetResult"]) -> str:
    """Dump per-(dataset, model) reports as JSON for later diffing."""
    payload = []
    for r in all_results:
        totals = _usage_totals(r.usage)
        cost = sum(model_cost(r.model, u.get("input_tokens", 0), u.get("output_tokens", 0)) for u in r.usage)
        payload.append(
            {
                "dataset": r.dataset,
                "model": r.model,
                "primary_score": r.primary_score,
                "report": EvaluationReportAdapter.dump_python(r.report, mode="json"),
                "usage": {
                    "per_call": r.usage,
                    "totals": totals,
                    "estimated_cost_usd": round(cost, 6),
                },
            }
        )
    import json

    return json.dumps(payload, indent=2)


def _load_baseline(path: str) -> list["DatasetResult"]:
    """Load a previously-written results.json (or the .json sibling of a .md file)."""
    import json

    candidate = Path(path)
    if candidate.suffix == ".md":
        candidate = candidate.with_suffix(".json")
    if not candidate.exists():
        raise SystemExit(f"Baseline file not found: {candidate}")
    payload = json.loads(candidate.read_text())
    out: list[DatasetResult] = []
    for entry in payload:
        report = EvaluationReportAdapter.validate_python(entry["report"])
        out.append(
            DatasetResult(
                dataset=entry["dataset"],
                model=entry["model"],
                primary_score=entry["primary_score"],
                report=report,
            )
        )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        help="Comma-separated subset of model names from --model-config to "
        "evaluate. If omitted, every model in the YAML runs.",
    )
    parser.add_argument(
        "--datasets",
        default=",".join(SPECS.keys()),
        help=f"Comma-separated datasets to run (default: {','.join(SPECS.keys())}).",
    )
    parser.add_argument(
        "--judge-model",
        default="gpt-oss-120b",
        help="Model to use as LLM-as-judge for fuzzy quality scoring (default "
        "gpt-oss-120b). Must also be declared in --model-config.",
    )
    parser.add_argument(
        "--model-config",
        help=(
            f"Path to YAML mapping model -> {{proxy_url, api_key/api_key_env}}. "
            f"Defaults to {DEFAULT_MODEL_CONFIG}, falling back to {FALLBACK_MODEL_CONFIG}."
        ),
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
        "--repeat",
        type=int,
        default=1,
        help="Run each case N times (per model) for noise estimates (default 1).",
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
    parser.add_argument(
        "--baseline",
        help="Path to a previous results .md or .json. The .json sibling is "
        "loaded and used to flag regressions / improvements per case.",
    )
    return parser.parse_args()


async def amain() -> int:
    args = parse_args()
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    only = [n.strip() for n in args.only.split(",")] if args.only else None

    for ds in datasets:
        if ds not in SPECS:
            raise SystemExit(f"Unknown dataset: {ds}. Known: {', '.join(SPECS)}.")

    config_path, model_config = _load_model_config(args.model_config)
    print(f"Using model config: {config_path}", file=sys.stderr)

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        unknown = [m for m in models if m not in model_config]
        if unknown:
            raise SystemExit(
                f"--models entries not in {config_path}: {', '.join(unknown)}. Known: {', '.join(model_config)}."
            )
    else:
        models = list(model_config.keys())

    judge_proxy_url, judge_api_key = _resolve_model_endpoint(args.judge_model, model_config)
    judge_model = build_judge_model(args.judge_model, judge_proxy_url, judge_api_key)
    print(f"Judge: {args.judge_model} (via {judge_proxy_url})", file=sys.stderr)

    all_results: list[DatasetResult] = []
    for ds_name in datasets:
        spec_fn = SPECS[ds_name]
        for model in models:
            proxy_url, api_key = _resolve_model_endpoint(model, model_config)
            print(f"\n=== {ds_name} | {model} (via {proxy_url}) ===", file=sys.stderr)
            deps = make_deps(model=model, api_key=api_key, base_url=proxy_url)
            usage_buffer: list[dict[str, int]] = []
            built = spec_fn(
                deps,
                judge_model=judge_model,
                only=only,
                include_galaxy_required=args.include_galaxy_required,
                usage_buffer=usage_buffer,
            )
            report = await built.dataset.evaluate(
                built.task,
                name=f"{ds_name}/{model}",
                max_concurrency=args.max_concurrency,
                repeat=args.repeat,
            )
            report.print(include_input=False, include_output=False)
            all_results.append(
                DatasetResult(
                    dataset=ds_name,
                    model=model,
                    primary_score=built.primary_score,
                    report=report,
                    usage=usage_buffer,
                )
            )

    baseline = _load_baseline(args.baseline) if args.baseline else None
    md = render_markdown(all_results, baseline=baseline)
    print(md)

    if not args.no_write:
        results_dir = Path(args.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        slug = "+".join(datasets)
        out_md = results_dir / f"{stamp}-{slug}-{_git_sha()}.md"
        out_json = out_md.with_suffix(".json")
        out_md.write_text(md)
        out_json.write_text(_serialize_results(all_results))
        print(f"\nWrote {out_md}", file=sys.stderr)
        print(f"Wrote {out_json}", file=sys.stderr)

    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
