"""File-based request bridge between an isolated MCP stdio process and an interactive agent."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from runtime_context import RUNTIME, request_lock


def read_response(runtime: Path, command_id: str) -> dict[str, Any] | None:
    response_path = runtime / "response.json"
    if not response_path.exists():
        return None
    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if response.get("id") != command_id:
        return None
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "The interactive window agent failed"))
    return response.get("result", {})


def call(name: str, arguments: dict[str, Any], timeout_seconds: float = 5.0) -> dict[str, Any]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    status = RUNTIME / "status.json"
    if not status.exists():
        raise RuntimeError("The interactive window agent is not running. Run the stable launch_stdio.py entry point in the logged-in session.")
    deadline = time.monotonic() + timeout_seconds
    with request_lock(RUNTIME, timeout_seconds):
        if time.monotonic() >= deadline:
            raise TimeoutError("The window-control request expired while waiting for the request lock")
        command_id = str(uuid.uuid4())
        payload = {"id": command_id, "name": name, "arguments": arguments}
        temporary = RUNTIME / f"command-{command_id}.tmp"
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, RUNTIME / "command.json")
        while time.monotonic() < deadline:
            result = read_response(RUNTIME, command_id)
            if result is not None:
                return result
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"The interactive window agent did not respond within {timeout_seconds:g} seconds")
