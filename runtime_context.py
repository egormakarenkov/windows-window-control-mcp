"""Own-session runtime identity and cross-process request serialization."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import math
import os
from pathlib import Path

KERNEL = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
KERNEL.ProcessIdToSessionId.restype = wintypes.BOOL
KERNEL.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
KERNEL.CreateMutexW.restype = wintypes.HANDLE
KERNEL.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
KERNEL.WaitForSingleObject.restype = wintypes.DWORD
KERNEL.ReleaseMutex.argtypes = [wintypes.HANDLE]
KERNEL.ReleaseMutex.restype = wintypes.BOOL
KERNEL.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL.CloseHandle.restype = wintypes.BOOL


def current_session_id() -> int:
    """Identify this process's session; never select another desktop/session."""
    value = wintypes.DWORD()
    if not KERNEL.ProcessIdToSessionId(os.getpid(), ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return value.value


def session_runtime(root: Path, session_id: int) -> Path:
    if not isinstance(session_id, int) or session_id < 0:
        raise ValueError("A nonnegative Windows session ID is required")
    return root / "runtime" / f"session-{session_id}"


SESSION_ID = current_session_id()
RUNTIME = session_runtime(Path(__file__).resolve().parent, SESSION_ID)


def request_mutex_name(runtime: Path) -> str:
    digest = hashlib.sha256(str(runtime.resolve()).casefold().encode("utf-8")).hexdigest()[:24]
    return "Local\\CodexWindowControlRequest-" + digest


def open_named_mutex(name: str) -> int:
    handle = KERNEL.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def close_mutex(handle: int) -> None:
    if not KERNEL.CloseHandle(handle):
        raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def request_lock(runtime: Path, timeout_seconds: float):
    """Serialize a whole request/response cycle, including abandoned-owner recovery."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("A finite positive request timeout is required")
    handle = open_named_mutex(request_mutex_name(runtime))
    owned = False
    try:
        milliseconds = min(0xFFFFFFFE, max(1, math.ceil(timeout_seconds * 1000)))
        result = KERNEL.WaitForSingleObject(handle, milliseconds)
        if result == 0x102:  # WAIT_TIMEOUT
            raise TimeoutError("Timed out waiting for another window-control request to finish")
        if result not in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            raise ctypes.WinError(ctypes.get_last_error())
        owned = True
        yield result == 0x80
    finally:
        try:
            if owned and not KERNEL.ReleaseMutex(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close_mutex(handle)
