"""Unit tests for the resubmit state handler.

Focuses on the deferred-evaluation behaviour and prior-attempt
``destination_params`` carry-forward introduced for chained dynamic
destinations.
"""

from types import SimpleNamespace
from unittest import mock

from galaxy.jobs.job_destination import JobDestination
from galaxy.jobs.runners import JobState
from galaxy.jobs.runners.state_handlers.resubmit import _handle_resubmit_definitions


def _make_job(*, destination_id, destination_params, runner_name):
    """Create a stand-in Job model with only the fields the handler reads."""
    return SimpleNamespace(
        id=42,
        destination_id=destination_id,
        destination_params=destination_params,
        job_runner_name=runner_name,
        job_runner_external_id="ext-123",
        state_history=[],
        set_handler=mock.MagicMock(),
    )


def _make_job_state(*, prior_destination, prior_destination_params, runner_state):
    """Build a JobState with mocked job_wrapper/job_runner sufficient for the handler."""
    job = _make_job(
        destination_id=prior_destination.id,
        destination_params=prior_destination_params,
        runner_name=prior_destination.runner,
    )
    job_wrapper = mock.MagicMock()
    job_wrapper.job_id = job.id
    job_wrapper.get_job.return_value = job
    job_wrapper.job_destination = prior_destination
    persisted = {}

    def _set_job_destination(destination, external_id=None, flush=True, job=None):
        persisted["destination"] = destination
        persisted["external_id"] = external_id
        # Mirror the real method: persist params/id/runner onto job.
        target_job = job or job_wrapper.get_job.return_value
        target_job.destination_id = destination.id
        target_job.destination_params = destination.params
        target_job.job_runner_name = destination.runner
        target_job.job_runner_external_id = external_id

    job_wrapper.set_job_destination.side_effect = _set_job_destination
    job_wrapper.set_cached_job_destination.side_effect = AssertionError(
        "Deferred evaluation: resubmit handler must not eagerly cache a destination"
    )

    js = JobState(job_wrapper=job_wrapper, job_destination=prior_destination)
    js.runner_state = runner_state
    js.job_id = "ext-123"
    return js, persisted


def _make_app_with_dispatcher(dispatcher_id, dispatcher_static_params):
    """Build an `app` whose job_config returns a fresh dispatcher destination per call."""
    app = mock.MagicMock()

    def _get_destination(name):
        assert name == dispatcher_id
        # Real get_destination deep-copies; mirror that so callers can mutate freely.
        import copy

        return JobDestination(
            id=dispatcher_id,
            runner="dynamic",
            params=copy.deepcopy(dispatcher_static_params),
        )

    app.job_config.get_destination.side_effect = _get_destination
    return app


def _make_job_runner():
    runner = mock.MagicMock()
    runner.sa_session = mock.MagicMock()
    return runner


def test_handler_does_not_eagerly_evaluate_dynamic_destination():
    """The handler must NOT call set_cached_job_destination — that would defeat
    deferred evaluation and re-introduce the chain-caching bug."""
    prior_destination = JobDestination(
        id="local",
        runner="local",
        params={"SCALING_FACTOR": 4},
        resubmit=[{"condition": "any_failure", "environment": "tpv_dispatcher"}],
    )
    js, _ = _make_job_state(
        prior_destination=prior_destination,
        prior_destination_params={"SCALING_FACTOR": 4},
        runner_state=JobState.runner_states.MEMORY_LIMIT_REACHED,
    )
    app = _make_app_with_dispatcher(
        "tpv_dispatcher",
        {"function": "map_tool_to_destination", "rules_module": "tpv.rules"},
    )

    _handle_resubmit_definitions(prior_destination.resubmit, app, _make_job_runner(), js)

    # set_cached_job_destination must not have been called (the side_effect would
    # have raised AssertionError before reaching here).
    js.job_wrapper.set_cached_job_destination.assert_not_called()


def test_handler_persists_dynamic_intent_not_resolved_destination():
    """After the handler runs, job.destination_id and job.job_runner_name must
    reflect the dynamic dispatcher (the intent), so recovery can re-walk the
    chain on pickup."""
    prior_destination = JobDestination(
        id="local",
        runner="local",
        params={"SCALING_FACTOR": 4},
        resubmit=[{"condition": "any_failure", "environment": "tpv_dispatcher"}],
    )
    js, persisted = _make_job_state(
        prior_destination=prior_destination,
        prior_destination_params={"SCALING_FACTOR": 4},
        runner_state=JobState.runner_states.MEMORY_LIMIT_REACHED,
    )
    app = _make_app_with_dispatcher(
        "tpv_dispatcher",
        {"function": "map_tool_to_destination"},
    )

    _handle_resubmit_definitions(prior_destination.resubmit, app, _make_job_runner(), js)

    assert persisted["destination"].id == "tpv_dispatcher"
    assert persisted["destination"].runner == "dynamic"


def test_handler_carries_prior_destination_params_forward():
    """Prior attempt's destination_params must survive the resubmit handler so
    dynamic rules that branch on prior context (e.g. TPV reading
    job.destination_params['SCALING_FACTOR']) keep working across attempts."""
    prior_destination = JobDestination(
        id="local",
        runner="local",
        params={"SCALING_FACTOR": 4, "user_specified_key": "value-from-prior-attempt"},
        resubmit=[{"condition": "any_failure", "environment": "tpv_dispatcher"}],
    )
    js, persisted = _make_job_state(
        prior_destination=prior_destination,
        prior_destination_params={"SCALING_FACTOR": 4, "user_specified_key": "value-from-prior-attempt"},
        runner_state=JobState.runner_states.MEMORY_LIMIT_REACHED,
    )
    app = _make_app_with_dispatcher(
        "tpv_dispatcher",
        {"function": "map_tool_to_destination"},
    )

    _handle_resubmit_definitions(prior_destination.resubmit, app, _make_job_runner(), js)

    persisted_params = persisted["destination"].params
    # Prior keys preserved.
    assert persisted_params["SCALING_FACTOR"] == 4
    assert persisted_params["user_specified_key"] == "value-from-prior-attempt"
    # Dispatcher static params still present so the chain re-walk on pickup
    # can find the rule function.
    assert persisted_params["function"] == "map_tool_to_destination"


def test_dispatcher_static_params_take_precedence_on_conflict():
    """If a prior attempt's destination_params shares a key with the dispatcher's
    static config (e.g. ``function``), the dispatcher's value must win so the
    chain re-walk picks the right rule."""
    prior_destination = JobDestination(
        id="local",
        runner="local",
        # Prior resolved destination accidentally has a ``function`` key — the
        # dispatcher's value must not be shadowed by it.
        params={"function": "stale_rule_from_prior_walk", "SCALING_FACTOR": 4},
        resubmit=[{"condition": "any_failure", "environment": "tpv_dispatcher"}],
    )
    js, persisted = _make_job_state(
        prior_destination=prior_destination,
        prior_destination_params={"function": "stale_rule_from_prior_walk", "SCALING_FACTOR": 4},
        runner_state=JobState.runner_states.MEMORY_LIMIT_REACHED,
    )
    app = _make_app_with_dispatcher(
        "tpv_dispatcher",
        {"function": "map_tool_to_destination"},
    )

    _handle_resubmit_definitions(prior_destination.resubmit, app, _make_job_runner(), js)

    assert persisted["destination"].params["function"] == "map_tool_to_destination"
    assert persisted["destination"].params["SCALING_FACTOR"] == 4


def test_resubmit_delay_persisted_alongside_prior_params():
    """The ``__resubmit_delay_seconds`` flag (set by the delay handler) must be
    persisted on top of the prior+static merge so is_ready_for_resubmission can
    pick it up from job.destination_params."""
    prior_destination = JobDestination(
        id="local",
        runner="local",
        params={"SCALING_FACTOR": 4},
        resubmit=[
            {
                "condition": "any_failure",
                "environment": "tpv_dispatcher",
                "delay": "30",
            }
        ],
    )
    js, persisted = _make_job_state(
        prior_destination=prior_destination,
        prior_destination_params={"SCALING_FACTOR": 4},
        runner_state=JobState.runner_states.MEMORY_LIMIT_REACHED,
    )
    app = _make_app_with_dispatcher("tpv_dispatcher", {"function": "map_tool_to_destination"})

    _handle_resubmit_definitions(prior_destination.resubmit, app, _make_job_runner(), js)

    persisted_params = persisted["destination"].params
    assert persisted_params["__resubmit_delay_seconds"] == "30"
    assert persisted_params["SCALING_FACTOR"] == 4
    assert persisted_params["function"] == "map_tool_to_destination"
