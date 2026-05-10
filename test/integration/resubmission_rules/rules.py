from galaxy.jobs.job_destination import JobDestination

DEFAULT_INITIAL_ENVIRONMENT = "fail_first_try"


def initial_target_environment(resource_params):
    return resource_params.get("initial_target_environment", None) or DEFAULT_INITIAL_ENVIRONMENT


def dynamic_resubmit_once(resource_params) -> JobDestination:
    """Build environment that always fails first time and always re-routes to passing environment."""
    return JobDestination(
        # Always fail on the first attempt.
        runner="failure_runner",
        # Resubmit to a valid environment.
        resubmit=[
            dict(
                condition="any_failure",
                environment="local",
            )
        ],
    )


def dynamic_resubmit_initial() -> JobDestination:
    """First link of a chained dynamic destination: fail and resubmit to the second link."""
    return JobDestination(
        runner="failure_runner",
        resubmit=[
            dict(
                condition="any_failure",
                environment="secondary_destination",
            )
        ],
    )


def dynamic_resubmit_secondary() -> JobDestination:
    """Second link: fail and resubmit to the third link.

    Reaching this rule on the *second* resubmit-attempt requires that the
    chain re-evaluates from the persisted dynamic intent rather than from
    the cached resolved destination of the previous attempt.
    """
    return JobDestination(
        runner="failure_runner",
        resubmit=[
            dict(
                condition="any_failure",
                environment="tertiary_destination",
            )
        ],
    )


def dynamic_resubmit_tertiary() -> JobDestination:
    """Third link: succeed on the local runner."""
    return JobDestination(runner="local")
