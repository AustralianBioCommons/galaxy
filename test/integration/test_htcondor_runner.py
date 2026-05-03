import contextlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from queue import Queue
from typing import ClassVar

import pytest

from galaxy import model
from galaxy.jobs.job_destination import JobDestination
from galaxy.jobs.runners import htcondor
from galaxy.util import bunch
from galaxy_test.base.populators import (
    DatasetPopulator,
    skip_without_tool,
)
from galaxy_test.driver import integration_util

LIVE_FAKE_MODULE_PATH = os.path.join(os.path.dirname(__file__), "htcondor_fake")


def _fake_job_conf() -> str:
    """Job config for the fake end-to-end test: in-process htcondor, no htcondor_config."""
    return """
runners:
  local:
    load: galaxy.jobs.runners.local:LocalJobRunner
    workers: 1
  htcondor:
    load: galaxy.jobs.runners.htcondor:HTCondorJobRunner
    workers: 1
execution:
  default: htcondor_environment
  environments:
    htcondor_environment:
      runner: htcondor
    local_environment:
      runner: local
tools:
  - id: __DATA_FETCH__
    environment: local_environment
"""


# ---------------------------------------------------------------------------
# Docker-based minicondor container tests
# ---------------------------------------------------------------------------

# Override with GALAXY_TEST_HTCONDOR_IMAGE to pin a specific version, e.g.
# "htcondor/mini:23-el9".
HTCONDOR_MINI_IMAGE = os.environ.get("GALAXY_TEST_HTCONDOR_IMAGE", "htcondor/mini:el9")

# Seconds to wait for the schedd to become reachable after container start.
HTCONDOR_STARTUP_TIMEOUT = 120


def _container_condor_config() -> str:
    """Condor config mounted into the minicondor container.

    Makes all daemons listen on every interface so the host htcondor2 library
    can reach the schedd via the Docker bridge IP.  We keep the container's
    default IDTOKENS-based security model intact; the host authenticates with
    a token generated inside the container (see ``start_htcondor_docker``).

    The negotiator interval is reduced so jobs are matched quickly in tests
    (the default 60 s cycle would exceed the test timeout).
    """
    return textwrap.dedent("""
        # Listen on all interfaces — required for the host to reach the container
        # via its Docker bridge IP rather than only 127.0.0.1.
        NETWORK_INTERFACE = *

        # Match jobs quickly so tests finish well within their timeout.
        NEGOTIATOR_INTERVAL = 5
        """).lstrip()


def _host_condor_config(collector_addr: str, token_dir: str) -> str:
    """Minimal condor config for the host-side htcondor2 subprocess client.

    Points the htcondor2 library at the containerised collector and provides
    the path to the IDTOKEN that was generated inside the container.
    """
    return textwrap.dedent(f"""
        COLLECTOR_HOST      = {collector_addr}
        CONDOR_HOST         = {collector_addr.split(":")[0]}
        SEC_TOKEN_DIRECTORY = {token_dir}
        """).lstrip()


def _container_job_conf(collector_addr: str, host_config_path: str) -> str:
    return textwrap.dedent(f"""
        runners:
          local:
            load: galaxy.jobs.runners.local:LocalJobRunner
            workers: 1
          htcondor:
            load: galaxy.jobs.runners.htcondor:HTCondorJobRunner
            workers: 1
        execution:
          default: htcondor_environment
          environments:
            htcondor_environment:
              runner: htcondor
              htcondor_collector: "{collector_addr}"
              htcondor_config: "{host_config_path}"
            local_environment:
              runner: local
        tools:
          - id: __DATA_FETCH__
            environment: local_environment
        """).lstrip()


def _two_cluster_job_conf(
    collector_addr_a: str,
    host_config_path_a: str,
    collector_addr_b: str,
    host_config_path_b: str,
) -> str:
    """Job config routing tools across two independent HTCondor clusters.

    All tools default to cluster A.  ``create_2`` is explicitly routed to
    cluster B so ``test_htcondor_docker_job_cluster_b`` can verify that each
    cluster receives its own jobs independently.
    """
    return textwrap.dedent(f"""
        runners:
          local:
            load: galaxy.jobs.runners.local:LocalJobRunner
            workers: 1
          htcondor:
            load: galaxy.jobs.runners.htcondor:HTCondorJobRunner
            workers: 1
        execution:
          default: htcondor_cluster_a
          environments:
            htcondor_cluster_a:
              runner: htcondor
              htcondor_collector: "{collector_addr_a}"
              htcondor_config: "{host_config_path_a}"
            htcondor_cluster_b:
              runner: htcondor
              htcondor_collector: "{collector_addr_b}"
              htcondor_config: "{host_config_path_b}"
            local_environment:
              runner: local
        tools:
          - id: __DATA_FETCH__
            environment: local_environment
          - id: checksum
            environment: htcondor_cluster_b
        """).lstrip()


def start_htcondor_docker(container_name: str, jobs_directory: str) -> tuple[str, str, str, str]:
    """Start an htcondor/mini container and return (container_config_path, host_config_path, collector_addr, token_dir).

    The container is started without port mapping.  After it is running, its
    Docker bridge IP is obtained via ``docker inspect`` and used as the
    collector address.  This avoids the CEDAR address-embedding problem that
    occurs with port mapping.

    Authentication uses the container's default IDTOKENS model.  Once the
    schedd is ready, the host OS user is added to the container's
    ``/etc/passwd`` (so HTCondor can setuid to the right UID when running
    jobs), and an IDTOKEN is generated inside the container and written to a
    temporary directory on the host.  The host-side htcondor2 subprocess
    client uses this token to authenticate with the container's schedd.

    The Galaxy job-working directory is bind-mounted at the same path inside
    the container so job scripts written by Galaxy are accessible to the startd.
    """
    with tempfile.NamedTemporaryFile(suffix="_container_condor_config.local", mode="w", delete=False) as f:
        f.write(_container_condor_config())
        container_config_path = f.name

    subprocess.check_call(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            container_name,
            "--rm",
            "-v",
            f"{jobs_directory}:{jobs_directory}",
            "-v",
            f"{container_config_path}:/etc/condor/condor_config.local",
            HTCONDOR_MINI_IMAGE,
        ]
    )

    # Obtain the container's Docker bridge IP — reachable from the host.
    container_ip = subprocess.check_output(
        ["docker", "inspect", "-f", "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_name],
        text=True,
    ).strip()
    collector_addr = f"{container_ip}:9618"

    # Wait for the schedd — this also ensures the pool password (used to sign
    # IDTOKENS) has been initialised by condor_master.
    _wait_for_htcondor_schedd(container_name)

    # Determine which username to use for the job identity.  HTCondor's schedd
    # validates that the submitting user exists in the container's /etc/passwd
    # and the startd setuid()s to that UID when running the job.  The job
    # working directories are owned by the host user's UID, so the job process
    # must run as the same numeric UID.
    #
    # Strategy: look up the host UID in the container's passwd database.  If a
    # user already has that UID (e.g. "restd" in htcondor/mini:el9), use that
    # username for the token identity — the numeric UID is the same as the host
    # user, so the job can write to the bind-mounted directories.  If no
    # container user has the host UID, add an entry for the host username.
    host_uid = os.getuid()
    host_gid = os.getgid()
    host_username = subprocess.check_output(["id", "-un"], text=True).strip()
    result = subprocess.run(
        ["docker", "exec", container_name, "getent", "passwd", str(host_uid)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        token_username = result.stdout.split(":")[0]
    else:
        # The host user is not in the container's passwd database.  Append a
        # minimal entry so HTCondor can validate the identity and setuid to the
        # right UID.  Pipe via stdin to tee to avoid any shell-quoting concerns.
        passwd_line = f"{host_username}:x:{host_uid}:{host_gid}:{host_username}:/tmp:/bin/sh\n"
        subprocess.run(
            ["docker", "exec", "-i", container_name, "tee", "-a", "/etc/passwd"],
            input=passwd_line,
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        token_username = host_username

    # Generate an IDTOKEN inside the container for the resolved identity.
    # The container signs the token with its pool password; the host client
    # presents the token and the schedd verifies it — no password exchange needed.
    token_identity = f"{token_username}@galaxy_test"
    token_content = subprocess.check_output(
        ["docker", "exec", container_name, "condor_token_create", "-identity", token_identity],
        text=True,
    ).strip()
    token_dir = tempfile.mkdtemp(prefix="htcondor_tokens_")
    os.chmod(token_dir, 0o700)
    token_path = os.path.join(token_dir, "galaxy_test")
    with open(token_path, "w") as fh:
        fh.write(token_content + "\n")
    os.chmod(token_path, 0o600)

    with tempfile.NamedTemporaryFile(suffix="_host_condor_config", mode="w", delete=False) as f:
        f.write(_host_condor_config(collector_addr, token_dir))
        host_config_path = f.name

    return container_config_path, host_config_path, collector_addr, token_dir


def stop_htcondor_docker(
    container_name: str, container_config_path: str, host_config_path: str, token_dir: str
) -> None:
    """Stop the minicondor container and clean up temporary config files."""
    subprocess.call(["docker", "rm", "-f", container_name])
    with contextlib.suppress(OSError):
        os.remove(container_config_path)
    with contextlib.suppress(OSError):
        os.remove(host_config_path)
    with contextlib.suppress(OSError):
        os.remove(os.path.join(token_dir, "galaxy_test"))
    with contextlib.suppress(OSError):
        os.rmdir(token_dir)


def _condor_history_count(container_name: str) -> int:
    """Return the number of jobs recorded in the container's condor history.

    Uses ``condor_history -format`` so the output contains exactly one line
    per completed job, with no header — making the count unambiguous.
    """
    result = subprocess.run(
        ["docker", "exec", container_name, "condor_history", "-format", "%d\n", "ClusterId"],
        capture_output=True,
        text=True,
    )
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _wait_for_htcondor_schedd(container_name: str, timeout: int = HTCONDOR_STARTUP_TIMEOUT) -> None:
    """Poll until the schedd inside the container reports at least one slot."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container_name, "condor_status", "-schedd"],
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return
        time.sleep(2)
    raise RuntimeError(f"HTCondor schedd in container {container_name!r} did not become ready within {timeout}s")


@integration_util.skip_unless_docker()
class TestHTCondorContainerJob(integration_util.IntegrationTestCase):
    """End-to-end tests using a real HTCondor minicondor Docker container.

    These tests submit actual Galaxy jobs to the htcondor runner, which in turn
    talks to a real HTCondor schedd running inside ``htcondor/mini``.  They
    validate the full submit → monitor → finish cycle and the cancel path
    against the real htcondor2 Python API, complementing the unit-style tests
    that use the fake htcondor2 stub.

    Prerequisites
    -------------
    * Docker must be available (tests are skipped otherwise).

    Environment variables
    ---------------------
    ``GALAXY_TEST_HTCONDOR_IMAGE``
        Override the Docker image (default: ``htcondor/mini:el9``).
    """

    framework_tool_and_types = True
    _container_name: ClassVar[str] = "galaxy_htcondor_integration_test"
    _container_name_b: ClassVar[str] = "galaxy_htcondor_integration_test_b"
    _jobs_directory: ClassVar[str]
    _container_config_path: ClassVar[str]
    _host_config_path: ClassVar[str]
    _collector_addr: ClassVar[str]
    _token_dir: ClassVar[str]
    _container_config_path_b: ClassVar[str]
    _host_config_path_b: ClassVar[str]
    _collector_addr_b: ClassVar[str]
    _token_dir_b: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._jobs_directory = tempfile.mkdtemp(prefix="htcondor_container_jobs_")
        os.chmod(cls._jobs_directory, 0o777)
        for sub in ("files", "new_files"):
            subdir = os.path.join(cls._jobs_directory, sub)
            os.makedirs(subdir, exist_ok=True)
            os.chmod(subdir, 0o777)

        # Start both containers in parallel to reduce wall-clock setup time.
        _results: dict[str, tuple] = {}
        _errors: dict[str, BaseException] = {}

        def _start(label: str, name: str) -> None:
            try:
                _results[label] = start_htcondor_docker(name, cls._jobs_directory)
            except BaseException as exc:
                _errors[label] = exc

        threads = [
            threading.Thread(target=_start, args=("a", cls._container_name), daemon=True),
            threading.Thread(target=_start, args=("b", cls._container_name_b), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if _errors:
            raise RuntimeError(f"HTCondor container startup failed: {_errors}")

        cls._container_config_path, cls._host_config_path, cls._collector_addr, cls._token_dir = _results["a"]
        cls._container_config_path_b, cls._host_config_path_b, cls._collector_addr_b, cls._token_dir_b = _results["b"]

        # Remove any fake htcondor2 stub so the real library is imported.
        sys.modules.pop("htcondor2", None)
        if LIVE_FAKE_MODULE_PATH in sys.path:
            sys.path.remove(LIVE_FAKE_MODULE_PATH)

        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            super().tearDownClass()
        finally:
            stop_htcondor_docker(cls._container_name, cls._container_config_path, cls._host_config_path, cls._token_dir)
            stop_htcondor_docker(
                cls._container_name_b, cls._container_config_path_b, cls._host_config_path_b, cls._token_dir_b
            )
            shutil.rmtree(cls._jobs_directory, ignore_errors=True)

    def setUp(self) -> None:
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        job_conf_str = _two_cluster_job_conf(
            cls._collector_addr,
            cls._host_config_path,
            cls._collector_addr_b,
            cls._host_config_path_b,
        )
        with tempfile.NamedTemporaryFile(suffix="_htcondor_container_job_conf.yml", mode="w", delete=False) as f:
            f.write(job_conf_str)
        config["job_config_file"] = f.name
        config["job_working_directory"] = cls._jobs_directory
        config["file_path"] = os.path.join(cls._jobs_directory, "files")
        config["new_file_path"] = os.path.join(cls._jobs_directory, "new_files")

    @skip_without_tool("simple_constructs")
    def test_htcondor_docker_job(self) -> None:
        """A job submitted to cluster A via htcondor/mini finishes successfully."""
        before_a = _condor_history_count(self._container_name)
        before_b = _condor_history_count(self._container_name_b)
        self._run_tool_test("simple_constructs", maxseconds=300)
        assert _condor_history_count(self._container_name) > before_a, "No new completed job in cluster A"
        assert _condor_history_count(self._container_name_b) == before_b, "Unexpected job appeared in cluster B"

    @skip_without_tool("cat_data_and_sleep")
    def test_htcondor_docker_cancel(self) -> None:
        """Cancelling a running job calls condor_rm and the job reaches DELETED."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1 2 3")
            run_response = self.dataset_populator.run_tool(
                "cat_data_and_sleep",
                {"input1": {"src": "hda", "id": hda["id"]}, "sleep_time": 300},
                history_id,
            )
            job_id = run_response["jobs"][0]["id"]

            app = self._app
            sa_session = app.model.session
            job = sa_session.get(model.Job, app.security.decode_id(job_id))
            assert job

            # Wait for the job to be submitted to the real schedd.
            for _ in range(60):
                sa_session.refresh(job)
                if job.job_runner_external_id:
                    break
                time.sleep(1)
            assert job.job_runner_external_id, "Job was never submitted to the HTCondor schedd"

            # Cancel via the Galaxy API.
            delete_response = self.dataset_populator.cancel_job(job_id)
            assert delete_response.json() is True

            # Wait for the Galaxy job record to reach the terminal DELETED state.
            for _ in range(60):
                sa_session.refresh(job)
                if job.state == model.Job.states.DELETED:
                    break
                time.sleep(1)
            assert job.state == model.Job.states.DELETED, f"Expected DELETED, got {job.state}"

    @skip_without_tool("checksum")
    def test_htcondor_docker_job_cluster_b(self) -> None:
        """A job routed to cluster B finishes successfully and does not appear in cluster A."""
        before_a = _condor_history_count(self._container_name)
        before_b = _condor_history_count(self._container_name_b)
        self._run_tool_test("checksum", maxseconds=300)
        assert _condor_history_count(self._container_name) == before_a, "Unexpected job appeared in cluster A"
        assert _condor_history_count(self._container_name_b) > before_b, "No new completed job in cluster B"


class FakeHTCondorIntegrationInstance(integration_util.IntegrationInstance):
    """Galaxy app instance backed by the fake htcondor2 module.

    Used by unit-style tests that exercise the runner directly without going
    through Galaxy's job routing system.
    """

    framework_tool_and_types = True
    _fake_record_dir: str
    _old_pythonpath: str | None
    _added_fake_sys_path: bool

    @classmethod
    def _prepare_galaxy(cls):
        sys.modules.pop("htcondor2", None)
        cls._fake_record_dir = tempfile.mkdtemp(prefix="fake_htcondor_records_")
        cls._old_pythonpath = os.environ.get("PYTHONPATH")
        cls._added_fake_sys_path = LIVE_FAKE_MODULE_PATH not in sys.path
        if cls._added_fake_sys_path:
            sys.path.insert(0, LIVE_FAKE_MODULE_PATH)
        fake_pythonpath = LIVE_FAKE_MODULE_PATH
        if cls._old_pythonpath:
            os.environ["PYTHONPATH"] = f"{fake_pythonpath}{os.pathsep}{cls._old_pythonpath}"
        else:
            os.environ["PYTHONPATH"] = fake_pythonpath
        os.environ["GALAXY_TEST_FAKE_HTCONDOR_RECORD_DIR"] = cls._fake_record_dir

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            sys.modules.pop("htcondor2", None)
            if cls._added_fake_sys_path and LIVE_FAKE_MODULE_PATH in sys.path:
                sys.path.remove(LIVE_FAKE_MODULE_PATH)
            if cls._old_pythonpath is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = cls._old_pythonpath
            os.environ.pop("GALAXY_TEST_FAKE_HTCONDOR_RECORD_DIR", None)
            shutil.rmtree(cls._fake_record_dir, ignore_errors=True)


fake_instance = integration_util.integration_module_instance(FakeHTCondorIntegrationInstance)


class FakeHTCondorJobIntegrationInstance(FakeHTCondorIntegrationInstance):
    """Like FakeHTCondorIntegrationInstance but configures Galaxy's job routing
    to use the htcondor runner end-to-end, with auto-completion so submitted
    jobs finish without a real HTCondor installation.
    """

    @classmethod
    def _prepare_galaxy(cls):
        super()._prepare_galaxy()
        os.environ["GALAXY_TEST_FAKE_HTCONDOR_AUTO_COMPLETE"] = "1"

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            os.environ.pop("GALAXY_TEST_FAKE_HTCONDOR_AUTO_COMPLETE", None)

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        job_conf_str = _fake_job_conf()
        with tempfile.NamedTemporaryFile(suffix="_fake_htcondor_job_conf.yml", mode="w", delete=False) as job_conf:
            job_conf.write(job_conf_str)
        config["job_config_file"] = job_conf.name


fake_job_instance = integration_util.integration_module_instance(FakeHTCondorJobIntegrationInstance)


def test_fake_end_to_end_job(fake_job_instance):
    """Full Galaxy job lifecycle via the htcondor runner backed by the fake module."""
    fake_job_instance._run_tool_test("simple_constructs")


class FakeHTCondorCancelIntegrationInstance(FakeHTCondorIntegrationInstance):
    """Like FakeHTCondorJobIntegrationInstance but without auto-completion.

    Jobs are submitted to the fake schedd and stay pending indefinitely, which
    allows the test to cancel them via the Galaxy API before they finish.
    AUTO_COMPLETE is explicitly cleared so this instance is not affected by
    other module-scoped fixtures that enable it.
    """

    @classmethod
    def _prepare_galaxy(cls):
        super()._prepare_galaxy()
        # Clear auto-complete so jobs stay pending and can be cancelled.
        os.environ.pop("GALAXY_TEST_FAKE_HTCONDOR_AUTO_COMPLETE", None)

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        job_conf_str = _fake_job_conf()
        with tempfile.NamedTemporaryFile(suffix="_fake_htcondor_cancel_job_conf.yml", mode="w", delete=False) as f:
            f.write(job_conf_str)
        config["job_config_file"] = f.name


fake_cancel_instance = integration_util.integration_module_instance(FakeHTCondorCancelIntegrationInstance)


def test_fake_cancel_job(fake_cancel_instance):
    """Cancel a pending htcondor job via the Galaxy API and verify condor_rm is called."""
    fake_cancel_instance.dataset_populator = DatasetPopulator(fake_cancel_instance.galaxy_interactor)
    with fake_cancel_instance.dataset_populator.test_history() as history_id:
        hda = fake_cancel_instance.dataset_populator.new_dataset(history_id, content="1 2 3")
        run_response = fake_cancel_instance.dataset_populator.run_tool(
            "cat_data_and_sleep",
            {"input1": {"src": "hda", "id": hda["id"]}, "sleep_time": 300},
            history_id,
        )
        job_id = run_response["jobs"][0]["id"]

        app = fake_cancel_instance._app
        sa_session = app.model.session
        job = sa_session.get(model.Job, app.security.decode_id(job_id))
        assert job

        # Wait for the job to be submitted to the fake schedd (external_id set).
        for _ in range(60):
            sa_session.refresh(job)
            if job.job_runner_external_id:
                break
            time.sleep(1)
        assert job.job_runner_external_id, "Job was never submitted to the fake htcondor schedd"
        external_id = job.job_runner_external_id

        # Cancel via Galaxy API.
        delete_response = fake_cancel_instance.dataset_populator.cancel_job(job_id)
        assert delete_response.json() is True

        # Wait for the job to reach the DELETED terminal state.
        for _ in range(30):
            sa_session.refresh(job)
            if job.state == model.Job.states.DELETED:
                break
            time.sleep(1)
        assert job.state == model.Job.states.DELETED, f"Expected DELETED, got {job.state}"

        # Verify the fake schedd received a Remove action for this job.
        remove_records = _records(fake_cancel_instance, kind="remove")
        assert remove_records, "No condor remove record written — stop_job was not called"
        assert int(remove_records[0]["job_spec"]) == int(external_id)


class FastFakeHTCondorJobRunner(htcondor.HTCondorJobRunner):
    def prepare_job(
        self,
        job_wrapper,
        include_metadata=False,
        include_work_dir_outputs=True,
        modify_command_for_container=True,
        stream_stdout_stderr=False,
    ):
        job_state = job_wrapper.get_state()
        if job_state == model.Job.states.DELETED:
            return False
        if job_state != model.Job.states.QUEUED:
            return False
        job_wrapper.prepare()
        job_wrapper.runner_command_line = job_wrapper.command_line
        return True

    def get_job_file(self, job_wrapper, **kwds):
        return "#!/bin/bash\nexit 0\n"

    def write_executable_script(self, path, contents, job_io):
        with open(path, "w") as handle:
            handle.write(contents)
        os.chmod(path, 0o755)


@pytest.fixture
def fake_htcondor(fake_instance):
    record_dir = fake_instance._fake_record_dir
    module = importlib.import_module("htcondor2")
    for entry in os.listdir(record_dir):
        os.unlink(os.path.join(record_dir, entry))
    module.JobEventLog.events_by_log.clear()
    yield module
    module.JobEventLog.events_by_log.clear()
    for entry in os.listdir(record_dir):
        os.unlink(os.path.join(record_dir, entry))


@pytest.fixture
def runner_factory(fake_instance):
    runners = []
    original_helper_module = htcondor.HTCONDOR_HELPER_MODULE

    def create_runner():
        runner = FastFakeHTCondorJobRunner(fake_instance._app, 1)
        runner.work_queue = Queue()
        runners.append(runner)
        return runner

    htcondor.HTCONDOR_HELPER_MODULE = "htcondor_helper"
    yield create_runner
    htcondor.HTCONDOR_HELPER_MODULE = original_helper_module

    for runner in runners:
        work_threads = getattr(runner, "work_threads", None)
        if work_threads is not None and not runner._should_stop:
            runner.shutdown()
        else:
            runner._shutdown_clients()


def _tool(fake_instance):
    tool = fake_instance._app.toolbox.get_tool("create_2")
    assert tool is not None
    return tool


def _job_wrapper(fake_instance, job_id, destination_params=None, *, state=model.Job.states.QUEUED):
    return MockJobWrapper(
        fake_instance._app,
        fake_instance._tempdir,
        _tool(fake_instance),
        destination_params or {},
        job_id,
        state=state,
    )


def _records(fake_instance, kind=None):
    records = []
    for entry in sorted(os.listdir(fake_instance._fake_record_dir)):
        path = os.path.join(fake_instance._fake_record_dir, entry)
        with open(path) as handle:
            record = json.load(handle)
        if kind is None or record["kind"] == kind:
            records.append(record)
    return records


def _watch_job(runner, job_wrapper, external_id="123"):
    cjs = htcondor.HTCondorJobState(
        job_wrapper=job_wrapper,
        job_destination=job_wrapper.job_destination,
        user_log=os.path.join(job_wrapper.working_directory, f"galaxy_{job_wrapper.get_id_tag()}.condor.log"),
        files_dir=job_wrapper.working_directory,
        job_id=external_id,
    )
    cjs.register_cleanup_file_attribute("user_log")
    runner.watched = [cjs]
    return cjs


def _write_user_log(cjs):
    with open(cjs.user_log, "w") as handle:
        handle.write("1")


def _set_job_events(fake_htcondor, cjs, event_names):
    fake_htcondor.JobEventLog.set_events(
        cjs.user_log,
        [
            fake_htcondor.FakeJobEvent(int(cjs.job_id), 0, getattr(fake_htcondor.JobEventType, event_name))
            for event_name in event_names
        ],
    )


@pytest.mark.parametrize(
    (
        "destination_params",
        "event_names",
        "job_state",
        "create_log",
        "expected_method_name",
        "expected_wrapper_state",
        "expected_running",
        "expected_watched_count",
        "expect_entry_points",
    ),
    [
        pytest.param(
            dict(htcondor_config="/tmp/condor-execute"),
            ["EXECUTE"],
            None,
            True,
            None,
            model.Job.states.RUNNING,
            True,
            1,
            True,
            id="execute-sets-running",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-terminated"),
            ["JOB_TERMINATED"],
            None,
            True,
            "finish_job",
            model.Job.states.QUEUED,
            False,
            0,
            False,
            id="terminated-finishes",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-aborted"),
            ["JOB_ABORTED"],
            None,
            True,
            "fail_job",
            model.Job.states.QUEUED,
            False,
            0,
            False,
            id="aborted-fails",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-removed"),
            ["CLUSTER_REMOVE"],
            None,
            True,
            "fail_job",
            model.Job.states.QUEUED,
            False,
            0,
            False,
            id="cluster-remove-fails",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-shadow"),
            ["SHADOW_EXCEPTION"],
            None,
            True,
            "fail_job",
            model.Job.states.QUEUED,
            False,
            0,
            False,
            id="shadow-exception-fails",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-exe-error"),
            ["EXECUTABLE_ERROR"],
            None,
            True,
            "fail_job",
            model.Job.states.QUEUED,
            False,
            0,
            False,
            id="executable-error-fails",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-held-stays"),
            ["JOB_HELD"],
            None,
            True,
            None,
            model.Job.states.QUEUED,
            False,
            1,
            False,
            id="held-stays-watched",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-held-stopped"),
            ["JOB_HELD"],
            model.Job.states.STOPPED,
            True,
            "finish_job",
            model.Job.states.STOPPED,
            False,
            0,
            False,
            id="held-stopped-finishes",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-held-failed"),
            ["JOB_HELD", "JOB_ABORTED"],
            None,
            True,
            "fail_job",
            model.Job.states.QUEUED,
            False,
            0,
            False,
            id="held-terminal-fails",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-released"),
            ["JOB_HELD", "JOB_RELEASED"],
            None,
            True,
            None,
            model.Job.states.QUEUED,
            False,
            1,
            False,
            id="held-released-stays-watched",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-suspended"),
            ["EXECUTE", "JOB_SUSPENDED"],
            None,
            True,
            None,
            model.Job.states.QUEUED,
            False,
            1,
            False,
            id="suspended-stops-running",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-unsuspended"),
            ["EXECUTE", "JOB_SUSPENDED", "JOB_UNSUSPENDED"],
            None,
            True,
            None,
            model.Job.states.RUNNING,
            True,
            1,
            True,
            id="unsuspended-resumes-running",
        ),
        pytest.param(
            dict(htcondor_config="/tmp/condor-missing-log"),
            [],
            None,
            False,
            None,
            model.Job.states.QUEUED,
            False,
            1,
            False,
            id="missing-log-stays-watched",
        ),
    ],
)
def test_watch_lifecycle_transitions(
    fake_instance,
    fake_htcondor,
    runner_factory,
    destination_params,
    event_names,
    job_state,
    create_log,
    expected_method_name,
    expected_wrapper_state,
    expected_running,
    expected_watched_count,
    expect_entry_points,
):
    runner = runner_factory()
    job_wrapper = _job_wrapper(fake_instance, 1, destination_params)
    cjs = _watch_job(runner, job_wrapper)

    if create_log:
        _write_user_log(cjs)
    if event_names:
        _set_job_events(fake_htcondor, cjs, event_names)
    if job_state is not None:
        job_wrapper.state = job_state

    runner.check_watched_items()

    if expected_method_name is None:
        assert runner.work_queue.empty()
    else:
        method, job_state_record = runner.work_queue.get_nowait()
        assert method == getattr(runner, expected_method_name)
        assert job_state_record.job_id == cjs.job_id
        assert runner.work_queue.empty()

    assert len(runner.watched) == expected_watched_count
    if expected_watched_count:
        assert runner.watched[0] is cjs
        assert runner.watched[0].running is expected_running
    assert job_wrapper.state == expected_wrapper_state
    assert job_wrapper.entry_points_checked is expect_entry_points


def test_held_released_then_executes_and_finishes(fake_instance, fake_htcondor, runner_factory):
    """A job that is held, released, then executes and terminates completes normally."""
    runner = runner_factory()
    job_wrapper = _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-held-released-finish"))
    cjs = _watch_job(runner, job_wrapper)
    _write_user_log(cjs)

    # Cycle 1: job is held then released — should stay watched, not running
    _set_job_events(fake_htcondor, cjs, ["JOB_HELD", "JOB_RELEASED"])
    runner.check_watched_items()
    assert runner.work_queue.empty()
    assert len(runner.watched) == 1
    assert not runner.watched[0].running

    # Cycle 2: job re-executes and terminates
    _set_job_events(fake_htcondor, cjs, ["EXECUTE", "JOB_TERMINATED"])
    runner.check_watched_items()
    method, job_state_record = runner.work_queue.get_nowait()
    assert method == runner.finish_job
    assert job_state_record.job_id == cjs.job_id
    assert runner.watched == []


def test_different_configs_use_separate_helpers(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    runner.queue_job(
        _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-A", htcondor_schedd="schedd@alpha"))
    )
    runner.queue_job(
        _job_wrapper(fake_instance, 2, dict(htcondor_config="/tmp/condor-B", htcondor_schedd="schedd@beta"))
    )

    records = _records(fake_instance, "submit")
    assert len(records) == 2
    assert {record["config"] for record in records} == {
        os.path.realpath("/tmp/condor-A"),
        os.path.realpath("/tmp/condor-B"),
    }
    assert {record["schedd_name"] for record in records} == {"schedd@alpha", "schedd@beta"}
    assert len({record["pid"] for record in records}) == 2


def test_same_config_reuses_helper_across_shedds(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    shared_config = "/tmp/condor-shared"
    runner.queue_job(
        _job_wrapper(
            fake_instance,
            1,
            dict(
                htcondor_config=shared_config,
                htcondor_collector="collector:9618",
                htcondor_schedd="schedd@alpha",
            ),
        )
    )
    runner.queue_job(
        _job_wrapper(
            fake_instance,
            2,
            dict(
                htcondor_config=shared_config,
                htcondor_collector="collector:9618",
                htcondor_schedd="schedd@beta",
            ),
        )
    )

    records = _records(fake_instance, "submit")
    assert len(records) == 2
    assert {record["config"] for record in records} == {os.path.realpath(shared_config)}
    assert {record["schedd_name"] for record in records} == {"schedd@alpha", "schedd@beta"}
    assert {record["collector"] for record in records} == {"collector:9618"}
    assert len({record["pid"] for record in records}) == 1
    for record in records:
        assert "htcondor_config" not in record["submit_description"]
        assert "htcondor_collector" not in record["submit_description"]
        assert "htcondor_schedd" not in record["submit_description"]


def test_stop_job_uses_same_config_scoped_helper(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    job_wrapper = _job_wrapper(
        fake_instance, 1, dict(htcondor_config="/tmp/condor-stop", htcondor_schedd="schedd@stop")
    )
    runner.queue_job(job_wrapper)
    runner.stop_job(job_wrapper)

    submit_record = _records(fake_instance, "submit")[0]
    remove_record = _records(fake_instance, "remove")[0]
    assert submit_record["pid"] == remove_record["pid"]
    assert submit_record["config"] == remove_record["config"] == os.path.realpath("/tmp/condor-stop")
    assert remove_record["schedd_name"] == "schedd@stop"
    assert remove_record["job_spec"] == int(job_wrapper.job.job_runner_external_id)


@pytest.mark.parametrize("state", [model.Job.states.STOPPED, model.Job.states.DELETED], ids=["stopped", "deleted"])
def test_stopped_or_deleted_jobs_are_not_submitted(fake_instance, fake_htcondor, runner_factory, state):
    runner = runner_factory()
    job_wrapper = _job_wrapper(
        fake_instance,
        1,
        dict(htcondor_config="/tmp/condor-cancelled"),
        state=state,
    )

    runner.queue_job(job_wrapper)

    assert _records(fake_instance) == []
    assert runner.monitor_queue.empty()
    assert runner._client_cache == {}


@pytest.mark.parametrize(
    "job_state, expected_running",
    [
        pytest.param(model.Job.states.QUEUED, False, id="queued"),
        pytest.param(model.Job.states.RUNNING, True, id="running"),
        pytest.param(model.Job.states.STOPPED, True, id="stopped"),
    ],
)
def test_recover_readds_monitored_jobs(fake_instance, fake_htcondor, runner_factory, job_state, expected_running):
    runner = runner_factory()
    job = model.Job()
    job.id = 7
    job.state = job_state
    job.job_runner_external_id = "123"
    job_wrapper = _job_wrapper(fake_instance, 7, dict(htcondor_config="/tmp/condor-recover"))

    runner.recover(job, job_wrapper)

    cjs = runner.monitor_queue.get_nowait()
    assert cjs.job_id == "123"
    assert cjs.running is expected_running
    assert cjs.job_wrapper is job_wrapper


def test_recover_without_external_id_requeues_job(fake_instance, fake_htcondor, runner_factory, monkeypatch):
    runner = runner_factory()
    job = model.Job()
    job.id = 8
    job.state = model.Job.states.QUEUED
    job_wrapper = _job_wrapper(fake_instance, 8, dict(htcondor_config="/tmp/condor-requeue"))
    put_calls = []
    monkeypatch.setattr(runner, "put", lambda recovered_job_wrapper: put_calls.append(recovered_job_wrapper))

    runner.recover(job, job_wrapper)

    assert put_calls == [job_wrapper]
    assert runner.monitor_queue.empty()


def test_runner_shutdown_terminates_all_helpers(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    runner.work_threads = []
    runner.shutdown_monitor = lambda: None
    runner.queue_job(
        _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-A", htcondor_schedd="schedd@alpha"))
    )
    runner.queue_job(
        _job_wrapper(fake_instance, 2, dict(htcondor_config="/tmp/condor-B", htcondor_schedd="schedd@beta"))
    )

    clients = list(runner._client_cache.values())
    processes = [client._process for client in clients if getattr(client, "_process", None) is not None]
    assert len(processes) == 2
    assert all(process.poll() is None for process in processes)

    runner.shutdown()

    assert all(getattr(client, "_process", None) is None for client in clients)
    assert all(process.poll() is not None for process in processes)


def test_helper_respawns_after_crash(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    destination_params = dict(htcondor_config="/tmp/condor-respawn", htcondor_schedd="schedd@respawn")
    first_job_wrapper = _job_wrapper(fake_instance, 1, destination_params)
    second_job_wrapper = _job_wrapper(fake_instance, 2, destination_params)
    runner.queue_job(first_job_wrapper)

    client = runner._client_for_destination(first_job_wrapper.job_destination)
    process = client._process
    assert process is not None
    first_pid = process.pid
    process.kill()
    process.wait(timeout=5)

    runner.queue_job(second_job_wrapper)

    submit_records = _records(fake_instance, "submit")
    assert len(submit_records) == 2
    assert submit_records[0]["pid"] == first_pid
    assert submit_records[1]["pid"] != first_pid
    assert submit_records[1]["config"] == os.path.realpath(destination_params["htcondor_config"])


def test_finish_handles_external_metadata(fake_instance, fake_htcondor, runner_factory, monkeypatch):
    runner = runner_factory()
    job_wrapper = _job_wrapper(
        fake_instance,
        1,
        dict(htcondor_config="/tmp/condor-external-metadata", embed_metadata_in_job=False),
    )
    cjs = _watch_job(runner, job_wrapper)
    _write_user_log(cjs)
    _set_job_events(fake_htcondor, cjs, ["JOB_TERMINATED"])
    metadata_calls = []

    def handle_metadata_externally(job_wrapper_arg, resolve_requirements=False):
        metadata_calls.append((job_wrapper_arg, resolve_requirements))

    monkeypatch.setattr(runner, "_handle_metadata_externally", handle_metadata_externally)

    runner.check_watched_items()

    method, job_state_record = runner.work_queue.get_nowait()
    assert method == runner.finish_job
    assert job_state_record.job_id == cjs.job_id
    assert metadata_calls == [(job_wrapper, True)]
    assert runner.watched == []


def test_submit_failure_fails_job(fake_instance, fake_htcondor, runner_factory, monkeypatch):
    runner = runner_factory()
    job_wrapper = _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-submit-fail"))

    def failing_submit(*args, **kwargs):
        raise RuntimeError("schedd unavailable")

    client = runner._client_for_destination(job_wrapper.job_destination)
    monkeypatch.setattr(client, "submit", failing_submit)

    runner.queue_job(job_wrapper)

    assert hasattr(job_wrapper, "fail_message")
    assert "htcondor submit failed" in job_wrapper.fail_message
    assert runner.monitor_queue.empty()


def test_condor_remove_failure_is_logged(fake_instance, fake_htcondor, runner_factory, monkeypatch):
    runner = runner_factory()
    job_wrapper = _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-remove-fail"))
    runner.queue_job(job_wrapper)

    client = runner._client_for_destination(job_wrapper.job_destination)

    def failing_remove(*args, **kwargs):
        raise RuntimeError("condor_rm failed")

    monkeypatch.setattr(client, "remove", failing_remove)

    failure_msg = runner._condor_remove(job_wrapper.job.job_runner_external_id, job_wrapper.job_destination)
    assert failure_msg is not None
    assert "condor_rm failed" in failure_msg


def test_event_log_closed_on_job_complete(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    job_wrapper = _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-close-log"))
    cjs = _watch_job(runner, job_wrapper)
    _write_user_log(cjs)
    _set_job_events(fake_htcondor, cjs, ["JOB_TERMINATED"])

    # Access the event log so it is created
    _ = cjs.event_log(runner.htcondor)
    assert cjs._event_log is not None

    runner.check_watched_items()

    assert cjs._event_log is None


def test_event_log_closed_on_job_fail(fake_instance, fake_htcondor, runner_factory):
    runner = runner_factory()
    job_wrapper = _job_wrapper(fake_instance, 1, dict(htcondor_config="/tmp/condor-close-log-fail"))
    cjs = _watch_job(runner, job_wrapper)
    _write_user_log(cjs)
    _set_job_events(fake_htcondor, cjs, ["JOB_ABORTED"])

    _ = cjs.event_log(runner.htcondor)
    assert cjs._event_log is not None

    runner.check_watched_items()

    assert cjs._event_log is None


class MockJobWrapper:
    def __init__(self, app, test_directory, tool, destination_params, job_id, state=model.Job.states.QUEUED):
        working_directory = tempfile.mkdtemp(prefix="htcondor_workdir_", dir=test_directory)
        tool_working_directory = os.path.join(working_directory, "working")
        os.makedirs(tool_working_directory)
        self.app = app
        self.tool = tool
        self.requires_containerization = False
        self.state = state
        self.command_line = "echo HelloWorld"
        self.environment_variables = []
        self.commands_in_new_shell = False
        self.prepare_called = False
        self.dependency_shell_commands = None
        self.working_directory = working_directory
        self.tool_working_directory = tool_working_directory
        self.requires_setting_metadata = True
        self.job_destination = JobDestination(id=f"htcondor_destination_{job_id}", params=destination_params)
        self.galaxy_lib_dir = os.path.abspath("lib")
        self.job = model.Job()
        self.job_id = job_id
        self.job.id = job_id
        self.job.container = None
        self.output_paths = ["/tmp/output1.dat"]
        self.mock_metadata_path = os.path.join(working_directory, f"METADATA_SET_{job_id}")
        self.metadata_command = f"touch {self.mock_metadata_path}"
        self.galaxy_virtual_env = None
        self.shell = "/bin/bash"
        self.cleanup_job = "never"
        self.tmp_dir_creation_statement = ""
        self.use_metadata_binary = False
        self.guest_ports = []
        self.metadata_strategy = "directory"
        self.remote_command_line = False
        self.entry_points_checked = False
        self.cleanup_called = False
        self.user = None

        self.external_output_metadata = bunch.Bunch()
        self.app.datatypes_registry.set_external_metadata_tool = bunch.Bunch(build_dependency_shell_commands=lambda: [])

    def check_tool_output(*args, **kwds):
        return "ok"

    def prepare(self):
        self.prepare_called = True

    def set_external_id(self, external_id, **kwd):
        self.job.job_runner_external_id = external_id

    def get_command_line(self):
        return self.command_line

    def container_monitor_command(self, *args, **kwds):
        return None

    def check_for_entry_points(self):
        self.entry_points_checked = True

    def get_id_tag(self):
        return str(self.job_id)

    def get_state(self):
        return self.state

    def change_state(self, state, job=None):
        self.state = state

    @property
    def job_io(self):
        return bunch.Bunch(
            get_output_fnames=lambda: [],
            check_job_script_integrity=False,
            version_path="/tmp/version_path",
        )

    def get_job(self):
        return self.job

    def setup_external_metadata(self, **kwds):
        return self.metadata_command

    def get_env_setup_clause(self):
        return ""

    def has_limits(self):
        return False

    def fail(
        self, message, exception=False, tool_stdout="", tool_stderr="", exit_code=None, job_stdout=None, job_stderr=None
    ):
        self.fail_message = message
        self.fail_exception = exception

    def finish(self, stdout, stderr, exit_code, **kwds):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code

    def cleanup(self):
        self.cleanup_called = True

    def tmp_directory(self):
        return None

    def home_directory(self):
        return None

    def reclaim_ownership(self):
        pass

    @property
    def is_cwl_job(self):
        return False
