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

Assumes a LiteLLM proxy at `http://localhost:4000/v1/` with both target
models routed through it (see `~/work/tacc-inference/` for the TACC
SambaNova path; gpt-oss-120b is reachable via Jetstream).

```bash
. .venv/bin/activate
python -m evals.run_evals \
    --models gpt-oss-120b,Llama-4-Maverick-17B-128E-Instruct
```

Output goes to stdout and to `evals/results/<date>-<dataset>-<sha>.md`.

### Models on different backends

Maverick (TACC SambaNova) doesn't sit on the LiteLLM proxy. For that case
copy `evals/models.yaml.sample` to `evals/models.yaml` (gitignored), fill in
the per-model proxy URL and the env var name your API key lives in, and
pass `--model-config evals/models.yaml`. Models not listed in the file fall
back to `--proxy-url`/`--api-key`.

### Useful flags

- `--datasets routing,error_analysis` -- pick which datasets to run (default
  is all registered).
- `--repeat 3` -- run each case N times to expose stochasticity. Per-case
  detail shows e.g. `2/3 [+1 ERR]` when one of three runs errored.
- `--judge-model gpt-oss-120b` -- model for fuzzy LLM-as-judge scoring
  (default gpt-oss-120b). Looked up in `--model-config` for proxy/key.
- `--only oom_137,exit_127` -- restrict to specific case names (across all
  datasets that contain them).
- `--include-galaxy-required` -- include cases that need a live Galaxy
  session (the `history_analyzer` ones). Off by default.
- `--max-concurrency 8` -- raise the per-model concurrency limit (default 4).
- `--proxy-url`, `--api-key` -- override defaults; also picked up from
  `GALAXY_AGENT_EVALS_PROXY_URL` / `GALAXY_AGENT_EVALS_API_KEY`.
- `--model-config <yaml>` -- per-model proxy/key overrides (see above).
- `--no-write` -- skip writing the results file.

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
