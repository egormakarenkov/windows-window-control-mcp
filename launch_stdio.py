"""Start/reuse the hidden helper, then serve MCP on this process's stdio."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from runtime_context import RUNTIME, SESSION_ID

ROOT = Path(__file__).resolve().parent


def helper_ready() -> bool:
    try:
        status = json.loads((RUNTIME / "status.json").read_text(encoding="utf-8"))
        age = time.time() - float(status["updated"])
        return status.get("service_root") == str(ROOT) and status.get("session_id") == SESSION_ID and 0 <= age < 2
    except (OSError, ValueError, KeyError, TypeError):
        return False


def ensure_helper(timeout_seconds: float = 8) -> None:
    if helper_ready():
        return
    RUNTIME.mkdir(parents=True, exist_ok=True)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        raise RuntimeError(f"The helper requires the installed pythonw.exe beside {sys.executable}")
    subprocess.Popen(
        [str(pythonw), "-B", str(ROOT / "interactive_agent.py")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if helper_ready():
            return
        time.sleep(0.05)
    raise RuntimeError("The hidden window helper did not become ready. No process was terminated; retry the stable launcher in the logged-in interactive session.")


def main() -> None:
    ensure_helper()
    if sys.argv[1:] == ["--helper-only"]:
        return
    from mcp_server import main as serve_stdio
    serve_stdio()


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
