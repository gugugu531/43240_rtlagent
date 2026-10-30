"""Own exactly one tool tree while remaining in the caller's task group.

Invoked by ProcessManager as a short-lived standard-library-only child. This
process never starts unrelated children, so adopted orphans have unambiguous
ownership. It is not a resident service or a resumable workflow worker.
"""

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class Stopped(BaseException):
    pass


def children(pid):
    result = set()
    for path in Path(f"/proc/{pid}/task").glob("*/children"):
        try:
            result.update(int(value) for value in path.read_text().split())
        except (OSError, ValueError):
            pass
    return result


def cleanup(proc):
    # Only this helper's descendants are owned. Never scan the agent's other
    # children or signal the shared task group during a single tool timeout.
    deadline = time.monotonic() + 1
    while True:
        owned = children(os.getpid())
        if not owned:
            return
        pending = list(owned)
        while pending:
            found = children(pending.pop()) - owned
            owned.update(found)
            pending.extend(found)
        for pid in owned:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc is not None:
            proc.poll()
        for pid in children(os.getpid()):
            if proc is not None and pid == proc.pid:
                continue
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        if time.monotonic() >= deadline:
            raise RuntimeError("tool descendants did not exit after SIGKILL")
        time.sleep(0.01)


def main():
    result_path = Path(sys.argv[1])
    if not sys.platform.startswith("linux") or ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
        print("process_worker: Linux child subreaper unavailable", file=sys.stderr)
        result_path.write_text(json.dumps({"rc": -1, "status": "unavailable"}))
        return 125

    def stop(signum, frame):
        raise Stopped()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    proc = None
    result = {"rc": -1, "status": "error"}
    try:
        proc = subprocess.Popen(sys.argv[2:])
        result = {"rc": proc.wait(), "status": "finished"}
    except Stopped:
        result = {"rc": -signal.SIGTERM, "status": "cancelled"}
    except OSError as error:
        print(f"process_worker: {error}", file=sys.stderr)
        result = {"rc": -1, "status": "unavailable", "error": str(error)}
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        try:
            cleanup(proc)
        except Exception as error:
            result = {"rc": -1, "status": "cleanup_failed", "error": str(error)}
        result_path.write_text(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
