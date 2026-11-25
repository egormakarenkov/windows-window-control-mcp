"""Runs in the logged-in user's interactive Windows session and performs narrow window actions."""

from __future__ import annotations

import json
import os
import ctypes
from ctypes import wintypes
import hashlib
import time
import importlib
from pathlib import Path
from typing import Any

import desktop_window_control as windows
from bridge import RUNTIME
from runtime_context import SESSION_ID


def previous_agent_pid(status_path: Path) -> int | None:
    try:
        pid = json.loads(status_path.read_text(encoding="utf-8")).get("pid")
    except (OSError, json.JSONDecodeError):
        return None
    return pid if isinstance(pid, int) and pid > 0 else None


def acquire_agent_mutex(runtime: Path) -> int | None:
    """Hold a session-local singleton handle; never act on a status-file PID."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateMutexW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    identity = hashlib.sha256(str(runtime.resolve()).casefold().encode("utf-8")).hexdigest()[:24]
    ctypes.set_last_error(0)
    handle = create(None, False, "Local\\CodexWindowControl-" + identity)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:  # ERROR_ALREADY_EXISTS: another helper holds the handle.
        release_agent_mutex(handle)
        return None
    return handle


def release_agent_mutex(handle: int) -> None:
    close = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    close(handle)


def existing_command_id(command_path: Path) -> str:
    """Skip any request left on disk before this helper became ready."""
    try:
        command_id = json.loads(command_path.read_text(encoding="utf-8")).get("id", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return command_id if isinstance(command_id, str) else ""


def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    global windows
    windows = importlib.reload(windows)
    if name == "list_displays":
        return {"displays": [windows.record_to_dict(item) for item in windows.list_displays()]}
    if name == "list_windows":
        return {"windows": [windows.record_to_dict(item) for item in windows.list_windows()]}
    if name == "arrange_vertical_stack":
        top_bounds, bottom_bounds = windows.arrange_vertical_stack(
            arguments["top_handle"],
            arguments["bottom_handle"],
            arguments["display_id"],
            arguments.get("top_fraction", 0.72),
        )
        return {
            "action": "arranged_vertical_stack",
            "top_bounds": windows.record_to_dict(top_bounds),
            "bottom_bounds": windows.record_to_dict(bottom_bounds),
        }
    if name == "place_window_in_region":
        bounds = windows.place_window_in_region(
            arguments["handle"],
            arguments["display_id"],
            left_fraction=arguments["left_fraction"],
            top_fraction=arguments["top_fraction"],
            width_fraction=arguments["width_fraction"],
            height_fraction=arguments["height_fraction"],
        )
        return {"handle": arguments["handle"], "action": "placed", "bounds": windows.record_to_dict(bounds)}
    if name == "snap_window_to_fancyzones_region":
        bounds = windows.snap_window_to_fancyzones_region(
            arguments["handle"],
            arguments["display_id"],
            left_fraction=arguments["left_fraction"],
            top_fraction=arguments["top_fraction"],
            width_fraction=arguments["width_fraction"],
            height_fraction=arguments["height_fraction"],
        )
        return {"handle": arguments["handle"], "action": "fancyzones_snapped", "bounds": windows.record_to_dict(bounds)}
    handle = arguments["handle"]
    if name == "focus_window":
        windows.focus_window(handle)
        return {"handle": handle, "action": "focused"}
    if name == "move_window_to_display":
        bounds = windows.move_window_to_display(handle, arguments["display_id"])
        return {"handle": handle, "action": "moved", "bounds": windows.record_to_dict(bounds)}
    if name == "minimize_window":
        windows.minimize_window(handle)
        return {"handle": handle, "action": "minimized"}
    if name == "restore_window":
        windows.restore_window(handle)
        return {"handle": handle, "action": "restored"}
    if name == "close_window":
        windows.close_window(handle)
        return {"handle": handle, "action": "close_requested"}
    raise ValueError(f"Unknown action {name!r}")


def serve() -> None:
    command_path = RUNTIME / "command.json"
    response_path = RUNTIME / "response.json"
    status_path = RUNTIME / "status.json"
    last_command_id = existing_command_id(command_path)
    while True:
        status_temporary = RUNTIME / "status.tmp"
        status_temporary.write_text(json.dumps({
            "pid": os.getpid(), "updated": time.time(),
            "service_root": str(Path(__file__).resolve().parent),
            "session_id": SESSION_ID,
        }), encoding="utf-8")
        os.replace(status_temporary, status_path)
        if command_path.exists():
            try:
                command = json.loads(command_path.read_text(encoding="utf-8"))
                if command["id"] != last_command_id:
                    try:
                        result: dict[str, Any] = dispatch(command["name"], command.get("arguments", {}))
                        response = {"id": command["id"], "ok": True, "result": result}
                    except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
                        response = {"id": command["id"], "ok": False, "error": str(error)}
                    temporary = RUNTIME / f"response-{command['id']}.tmp"
                    temporary.write_text(json.dumps(response), encoding="utf-8")
                    os.replace(temporary, response_path)
                    last_command_id = command["id"]
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.05)


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    handle = acquire_agent_mutex(RUNTIME)
    if handle is None:
        return
    try:
        serve()
    finally:
        release_agent_mutex(handle)


if __name__ == "__main__":
    main()
