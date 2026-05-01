# Galaxy agent evals

Real-LLM evaluation harness for the agents in `lib/galaxy/agents/`. Built on
[pydantic-evals](https://ai.pydantic.dev/evals/). Runs on demand, **not in
CI** -- real LLMs cost money, are slow, and are flaky.

## What it does

Runs a curated dataset of (query, expected handoff target) pairs against the
`QueryRouterAgent`, scores each model's routing decisions, and emits a
markdown comparison table. The point is to weigh models against each other
("is gpt-oss-120b on Jetstream good enough as a free default? does
Llama-4-Maverick win on tool generation?"), not to gate PRs.

## Layout

```
evals/
  datasets/routing.py     # Cases: (query, expected_handoff_target)
  evaluators.py           # HandoffMatch -- 1.0 if router picked the expected agent
  tasks.py                # Wraps QueryRouterAgent as a pydantic-evals task callable
  run_evals.py            # CLI
  results/                # Markdown reports, checked in so we can diff over time
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

- `--only greeting,oom_137` -- restrict to specific case names.
- `--include-galaxy-required` -- include cases that need a live Galaxy
  session (the `history_analyzer` ones). Off by default.
- `--max-concurrency 8` -- raise the per-model concurrency limit (default 4).
- `--proxy-url`, `--api-key` -- override defaults; also picked up from
  `GALAXY_AGENT_EVALS_PROXY_URL` / `GALAXY_AGENT_EVALS_API_KEY`.
- `--model-config <yaml>` -- per-model proxy/key overrides (see above).
- `--no-write` -- skip writing the results file.

## Adding cases

Edit `datasets/routing.py`. Each case is one query + the agent_type the
router should hand off to (`router` for direct answers, `error_analysis`,
`custom_tool`, `tool_recommendation`, `history_analyzer`, ...).

## Adding datasets

Mirror `datasets/routing.py` for new task shapes (CustomTool quality,
error-analysis specificity, etc.). The CLI currently hard-codes routing;
extend `run_evals.py` once you have a second dataset.

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
