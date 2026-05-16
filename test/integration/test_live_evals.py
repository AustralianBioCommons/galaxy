"""Live-Galaxy runner for the ``evals/`` agent eval suite.

Wraps the standalone ``evals.run_evals`` machinery inside a Galaxy
integration-test fixture so the ``requires_galaxy=True`` cases (live26
history sanity check, summarize-to-page, report takeaway, social media
post, history_analyzer routing cases) actually run against a real history.

The mock-trans CLI under ``evals/run_evals.py`` stays the fast loop for
prompt iteration on the cases that don't need live data. This test is the
"real flight check" before stage rehearsals -- it shares dataset
definitions, evaluators, and the report renderer with the CLI, only the
deps construction differs.

## Running

    export GALAXY_TEST_ENABLE_LIVE_LLM=1
    export GALAXY_TEST_LIVE_EVALS=1
    # Either inline AI config:
    export GALAXY_TEST_AI_API_KEY="..."
    export GALAXY_TEST_AI_API_BASE_URL="http://localhost:4000/v1/"
    export GALAXY_TEST_AI_MODEL="gpt-oss-120b"
    # Or point at a models.yaml that's structured for the eval CLI:
    export EVALS_MODEL_CONFIG=/path/to/models.yaml
    export EVALS_MODELS="gpt-oss-120b"      # optional comma-separated subset
    export EVALS_JUDGE_MODEL="gpt-oss-120b" # optional override
    export EVALS_DATASETS="live26_demo"     # optional comma-separated subset

    pytest test/integration/test_live_evals.py -v

Reports land in ``evals/results/<stamp>-<datasets>-<sha>.{md,json}``, the
same place and naming as the CLI so ``--baseline`` diffing keeps working
across both runners.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import pytest

from galaxy.util.unittest_utils import pytestmark_live_llm
from galaxy.work.context import WorkRequestContext
from galaxy_test.base.populators import (
    DatasetPopulator,
    WorkflowPopulator,
)
from galaxy_test.driver.integration_util import IntegrationTestCase

# evals/ lives at the repo root, not under lib/ -- add it to sys.path so the
# test can import the standalone harness modules without requiring an install.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.run_evals import (  # noqa: E402
    _load_model_config,
    run_eval_suite,
    write_eval_report,
)
from evals.tasks import make_live_deps  # noqa: E402
from scripts.seed_live26_demo_history import seed_demo_history  # noqa: E402

log = logging.getLogger(__name__)

pytestmark_live_evals = pytest.mark.skipif(
    not os.environ.get("GALAXY_TEST_LIVE_EVALS"),
    reason="Set GALAXY_TEST_LIVE_EVALS=1 to run the live-Galaxy eval suite.",
)


@pytestmark_live_llm
@pytestmark_live_evals
class TestLiveEvals(IntegrationTestCase):
    """Run evals/datasets/* against a real Galaxy with a seeded demo history."""

    dataset_populator: DatasetPopulator
    workflow_populator: WorkflowPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.workflow_populator = WorkflowPopulator(self.galaxy_interactor)

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        # Same env-var wiring as test_agents.py so this test can reuse a
        # configured LLM if one's already set up.
        if ai_api_key := os.environ.get("GALAXY_TEST_AI_API_KEY"):
            config["ai_api_key"] = ai_api_key
        if ai_api_base_url := os.environ.get("GALAXY_TEST_AI_API_BASE_URL"):
            config["ai_api_base_url"] = ai_api_base_url
        if ai_model := os.environ.get("GALAXY_TEST_AI_MODEL"):
            config["ai_model"] = ai_model

    def test_run_live_eval_suite(self):
        """Seed the demo history, run the eval suite, write reports.

        Default scope: ``live26_demo`` dataset with ``--include-galaxy-required``
        so the cases that need a real history actually run. Override via the
        ``EVALS_*`` env vars documented at the top of the file.
        """
        history_id = seed_demo_history(self.dataset_populator)
        log.info("Seeded Live26 demo history: %s", history_id)

        datasets = [d.strip() for d in os.environ.get("EVALS_DATASETS", "live26_demo").split(",") if d.strip()]

        config_path = os.environ.get("EVALS_MODEL_CONFIG")
        _path, model_config = _load_model_config(config_path)

        if env_models := os.environ.get("EVALS_MODELS"):
            models = [m.strip() for m in env_models.split(",") if m.strip()]
        else:
            models = list(model_config.keys())

        judge_model_name = os.environ.get("EVALS_JUDGE_MODEL", "gpt-oss-120b")

        # Build a real trans bound to the test user, then close over it in
        # the deps factory so every (dataset, model) pair sees the same
        # seeded history.
        user = self._user_for_api_key(self.galaxy_interactor.api_key)
        history = self._history_for_id(history_id)
        trans = WorkRequestContext(app=self._app, user=user, history=history)

        def _live_deps_factory(model: str, api_key: str, base_url: str):
            return make_live_deps(trans=trans, model=model, api_key=api_key, base_url=base_url)

        results = asyncio.run(
            run_eval_suite(
                datasets=datasets,
                models=models,
                model_config=model_config,
                judge_model_name=judge_model_name,
                deps_factory=_live_deps_factory,
                include_galaxy_required=True,
            )
        )

        results_dir = _REPO_ROOT / "evals" / "results"
        md_path, json_path = write_eval_report(results, datasets, results_dir)
        log.info("Wrote live eval report: %s", md_path)
        log.info("Wrote live eval JSON sidecar: %s", json_path)

        # Don't assert per-case scores here -- the harness is a measurement
        # tool, not a pass/fail gate. The report file is the artifact.
        assert results, "Expected at least one (dataset, model) result"

    def _user_for_api_key(self, api_key: str):
        user_id = self._user_id_for_api_key(api_key)
        return self._app.model.session.get(self._app.model.User, user_id)

    def _history_for_id(self, history_id: str):
        decoded = self._decode_id(history_id)
        return self._app.model.session.get(self._app.model.History, decoded)
