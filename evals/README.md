# Galaxy agent evals

Real-LLM evaluation harness for the agents in `lib/galaxy/agents/`. Built on
[pydantic-evals](https://ai.pydantic.dev/evals/). Runs on demand, **not in
CI** -- real LLMs cost money, are slow, and are flaky.

## What it does

Runs curated datasets against Galaxy agents, scores each model, and emits a
markdown comparison table. The point is to weigh models against each other
("is gpt-oss-120b on Jetstream good enough as a free default? does
Llama-4-Maverick win on error analysis?") and to iterate on prompts with
real measurement. Not run in CI.

Current datasets:

- **routing**: (query, expected handoff target) pairs against `QueryRouterAgent`.
  Scored by `HandoffMatch` (deterministic).
- **error_analysis**: prose failure descriptions against `ErrorAnalysisAgent`.
  Scored two ways: `MustMention` (deterministic keyword check) and `LLMJudge`
  (fuzzy "is the advice on-topic and actionable for this failure mode").
- **tool_recommendation**: "what tool should I use for X?" queries against
  `ToolRecommendationAgent`. Scored by `MustMentionAny` (any of a set of
  canonical tool names appears) plus optional `LLMJudge` with per-case rubrics.
  Runs without a live toolbox, so it measures the model's prior knowledge of
  Galaxy tools rather than grounded search behavior.
- **router_tool_use**: inventory/availability queries that should trigger
  router fast-path tool calls (`search_tools`, `search_workflows`,
  `list_histories`, `get_server_info`, `get_user_info`). Scored by
  `ToolCallMatch` -- did the model invoke at least one of the expected
  tools? Includes a regression case for the failure observed in
  galaxyproject/galaxy#21661 (comment 4367167981) where the router answered
  "what tools are installed?" with a generic essay instead of calling
  `search_tools`.

## Layout

```
evals/
  datasets/                # One module per dataset
    routing.py
    error_analysis.py
  evaluators.py            # HandoffMatch, MustMention
  judge.py                 # Builds an OpenAIChatModel for use as LLM judge
  specs.py                 # DatasetSpec registry: dataset -> task + evaluators
  tasks.py                 # Wraps agents as pydantic-evals task callables
  run_evals.py             # CLI
  results/                 # Markdown reports, checked in so we can diff over time
```

## Running

Copy `evals/models.yaml.sample` to `evals/models.yaml` (gitignored), list
each model you want to evaluate with its proxy URL and key, then:

```bash
. .venv/bin/activate
python -m evals.run_evals --model-config evals/models.yaml
```

That runs every model in the YAML against every dataset. Output goes to
stdout and to `evals/results/<date>-<datasets>-<sha>.md`.

You can still pass `--models gpt-oss-120b,Llama-4-Maverick-17B-128E-Instruct`
to restrict to a subset.

### Diffing against a previous run

```bash
python -m evals.run_evals \
    --baseline evals/results/2026-05-01-080419-routing+error_analysis-5693106ee00.md
```

`--baseline` looks for the JSON sidecar next to the markdown (each run writes
both) and renders a "Changes vs baseline" section listing per-case
regressions and improvements per (dataset, model). Useful when iterating
on a prompt -- run before, change the prompt, run with `--baseline` pointing
at the before file, see what moved.

### Useful flags

- `--datasets routing,error_analysis` -- pick which datasets to run (default
  is all registered).
- `--repeat 3` -- run each case N times to expose stochasticity. Per-case
  detail shows e.g. `2/3 [+1 ERR]` when one of three runs errored.
- `--judge-model gpt-oss-120b` -- model for fuzzy LLM-as-judge scoring
  (default gpt-oss-120b). Must also be declared in `--model-config`.
- `--only oom_137,exit_127` -- restrict to specific case names.
- `--include-galaxy-required` -- include cases that need a live Galaxy
  session (the `history_analyzer` ones). Off by default.
- `--max-concurrency 8` -- raise the per-model concurrency limit (default 4).
- `--model-config <yaml>` -- override default of `evals/models.yaml`.
- `--baseline <md-or-json>` -- diff results against a previous run.
- `--no-write` -- skip writing the report file.

## Adding cases

Edit the relevant `datasets/<name>.py`. Each case is the input the agent
sees plus whatever metadata the dataset's evaluators need (expected handoff
target for routing, must_mention keywords + failure_mode for error_analysis).

## Adding datasets

1. Drop a new module under `datasets/` exporting a `<name>_dataset(...)`
   function that returns a pydantic-evals `Dataset`.
2. Add a `make_<name>_task` to `tasks.py`.
3. Register a `build_<name>` in `specs.py`'s `SPECS` dict.

The CLI auto-includes anything registered in `SPECS`.

## How this relates to other agent test infrastructure

- `test/unit/app/test_agents.py::TestAgentUnitMocked` -- deterministic mocked
  unit tests, run in CI. Cover plumbing, not LLM behaviour.
- `test/unit/app/test_static_agent_backend.py` -- tests for the
  `StaticAgentRegistry`, which swaps real agents for canned-YAML responses.
  Complementary, not a substitute: static fixture is for orchestrator
  plumbing tests; evals are for measuring the LLM itself.
- `~/.claude/plans/galaxy-agents/test_agents_live.py` -- standalone live
  test script the routing dataset is seeded from. Slated for retirement once
  this harness covers what it covered.
