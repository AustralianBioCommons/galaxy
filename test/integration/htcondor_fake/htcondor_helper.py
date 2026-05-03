import json
import sys
import threading

import htcondor2

from galaxy.jobs.runners.htcondor_helper import _locate_schedd


def main():
    schedd_cache: dict[tuple[str | None, str | None], object] = {}
    schedd_lock = threading.Lock()
    response: dict[str, object]

    for line in sys.stdin:
        if not line:
            break
        try:
            request = json.loads(line)
            command = request["command"]
            if command == "shutdown":
                response = dict(ok=True)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                return 0

            collector = request.get("collector")
            schedd_name = request.get("schedd_name")
            schedd = _locate_schedd(htcondor2, schedd_cache, schedd_lock, collector, schedd_name)
            if command == "submit":
                submit_result = schedd.submit(htcondor2.Submit(request["submit_description"]))
                response = dict(ok=True, cluster=str(submit_result.cluster()))
            elif command == "remove":
                schedd.act(
                    htcondor2.JobAction.Remove,
                    request["job_spec"],
                    reason="Galaxy job stop request",
                )
                response = dict(ok=True)
            else:
                raise RuntimeError(f"Unknown HTCondor helper command: {command}")
        except Exception as exc:
            response = dict(ok=False, error=str(exc))

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
