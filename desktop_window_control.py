"""Fast, narrow Windows window-management primitives for the local MCP server."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass


if ctypes.sizeof(ctypes.c_void_p) == 0:  # Defensive import guard for non-Windows hosts.
    raise RuntimeError("desktop_window_control requires Windows")


user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

SW_RESTORE = 9
SW_MINIMIZE = 6
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
WM_CLOSE = 0x0010
SMTO_ABORTIFHUNG = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class Display:
    id: str
    name: str
    bounds: Rect
    work_area: Rect
    is_primary: bool


@dataclass(frozen=True)
class Window:
    handle: int
    title: str
    process_id: int
    bounds: Rect
    is_minimized: bool
    is_maximized: bool


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _rect(native: _RECT) -> Rect:
    return Rect(native.left, native.top, native.right, native.bottom)


def fit_rect_to_work_area(current: Rect, work_area: Rect) -> Rect:
    """Resize only when needed and position the window at the display's top-left."""
    width = min(current.width, work_area.width)
    height = min(current.height, work_area.height)
    return Rect(work_area.left, work_area.top, work_area.left + width, work_area.top + height)


def vertical_stack_bounds(work_area: Rect, top_fraction: float) -> tuple[Rect, Rect]:
    """Return adjoining top and bottom rectangles for one display work area."""
    if not 0.1 <= top_fraction <= 0.9:
        raise ValueError("top_fraction must be between 0.1 and 0.9")
    split = work_area.top + round(work_area.height * top_fraction)
    return (
        Rect(work_area.left, work_area.top, work_area.right, split),
        Rect(work_area.left, split, work_area.right, work_area.bottom),
    )


def region_bounds(
    work_area: Rect,
    *,
    left_fraction: float,
    top_fraction: float,
    width_fraction: float,
    height_fraction: float,
) -> Rect:
    """Map a fractional display region to an integer outer-window rectangle."""
    values = (left_fraction, top_fraction, width_fraction, height_fraction)
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("All region fractions must be between 0 and 1")
    if width_fraction <= 0 or height_fraction <= 0:
        raise ValueError("Region width and height must be greater than zero")
    if left_fraction + width_fraction > 1 or top_fraction + height_fraction > 1:
        raise ValueError("The requested region extends outside the display work area")
    left = work_area.left + round(work_area.width * left_fraction)
    top = work_area.top + round(work_area.height * top_fraction)
    right = work_area.left + round(work_area.width * (left_fraction + width_fraction))
    bottom = work_area.top + round(work_area.height * (top_fraction + height_fraction))
    return Rect(left, top, right, bottom)


def fancyzones_drag_points(window_bounds: Rect, target: Rect) -> tuple[tuple[int, int], tuple[int, int]]:
    """Choose a title-bar point and the center of one FancyZones target region."""
    title_bar_y = min(window_bounds.bottom - 1, window_bounds.top + 16)
    return (
        ((window_bounds.left + window_bounds.right) // 2, title_bar_y),
        ((target.left + target.right) // 2, (target.top + target.bottom) // 2),
    )


def list_displays() -> list[Display]:
    displays: list[Display] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(_RECT), wintypes.LPARAM
    )

    @callback_type
    def callback(monitor, _hdc, _bounds, _data):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        displays.append(
            Display(
                id=info.szDevice,
                name=info.szDevice,
                bounds=_rect(info.rcMonitor),
                work_area=_rect(info.rcWork),
                is_primary=bool(info.dwFlags & 1),
            )
        )
        return True

    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return displays


def _ensure_window(handle: int) -> wintypes.HWND:
    hwnd = wintypes.HWND(handle)
    if not user32.IsWindow(hwnd):
        raise ValueError(f"Window handle {handle} no longer exists")
    return hwnd


def _window_bounds(hwnd: wintypes.HWND) -> Rect:
    rect = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _rect(rect)


def list_windows() -> list[Window]:
    windows: list[Window] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _data):
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length == 0:
            return True
        title = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        windows.append(
            Window(
                handle=ctypes.cast(hwnd, ctypes.c_void_p).value,
                title=title.value,
                process_id=process_id.value,
                bounds=_window_bounds(hwnd),
                is_minimized=bool(user32.IsIconic(hwnd)),
                is_maximized=bool(user32.IsZoomed(hwnd)),
            )
        )
        return True

    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return windows


def _set_foreground(hwnd: wintypes.HWND) -> None:
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    if not user32.SetForegroundWindow(hwnd):
        raise RuntimeError("Windows prevented this window from receiving foreground focus")


def focus_window(handle: int) -> None:
    _set_foreground(_ensure_window(handle))


def move_window_to_display(handle: int, display_id: str) -> Rect:
    hwnd = _ensure_window(handle)
    display = next((item for item in list_displays() if item.id == display_id), None)
    if display is None:
        raise ValueError(f"Display {display_id!r} was not found")
    target = fit_rect_to_work_area(_window_bounds(hwnd), display.work_area)
    return _place_window(hwnd, target)


def _place_window(hwnd: wintypes.HWND, target: Rect) -> Rect:
    preference = ctypes.c_int(DWMWCP_DONOTROUND)
    result = dwmapi.DwmSetWindowAttribute(
        hwnd,
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(preference),
        ctypes.sizeof(preference),
    )
    if result != 0:
        raise OSError(result, "DwmSetWindowAttribute could not set square corners")
    user32.ShowWindow(hwnd, SW_RESTORE)
    def set_position(rect: Rect) -> Rect:
        if not user32.SetWindowPos(
            hwnd,
            None,
            rect.left,
            rect.top,
            rect.width,
            rect.height,
            SWP_SHOWWINDOW | SWP_NOACTIVATE,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return _window_bounds(hwnd)

    actual = set_position(target)
    if actual == target:
        return actual
    corrected = Rect(
        target.left + (target.left - actual.left),
        target.top + (target.top - actual.top),
        target.left + (target.left - actual.left) + max(1, target.width + (target.width - actual.width)),
        target.top + (target.top - actual.top) + max(1, target.height + (target.height - actual.height)),
    )
    return set_position(corrected)


def arrange_vertical_stack(
    top_handle: int, bottom_handle: int, display_id: str, top_fraction: float = 0.72
) -> tuple[Rect, Rect]:
    """Place two distinct windows in adjoining full-width regions on one display."""
    if top_handle == bottom_handle:
        raise ValueError("The top and bottom windows must be different")
    display = next((item for item in list_displays() if item.id == display_id), None)
    if display is None:
        raise ValueError(f"Display {display_id!r} was not found")
    top_bounds, bottom_bounds = vertical_stack_bounds(display.work_area, top_fraction)
    return _place_window(_ensure_window(top_handle), top_bounds), _place_window(
        _ensure_window(bottom_handle), bottom_bounds
    )


def place_window_in_region(
    handle: int,
    display_id: str,
    *,
    left_fraction: float,
    top_fraction: float,
    width_fraction: float,
    height_fraction: float,
) -> Rect:
    display = next((item for item in list_displays() if item.id == display_id), None)
    if display is None:
        raise ValueError(f"Display {display_id!r} was not found")
    target = region_bounds(
        display.work_area,
        left_fraction=left_fraction,
        top_fraction=top_fraction,
        width_fraction=width_fraction,
        height_fraction=height_fraction,
    )
    return _place_window(_ensure_window(handle), target)


def snap_window_to_fancyzones_region(
    handle: int,
    display_id: str,
    *,
    left_fraction: float,
    top_fraction: float,
    width_fraction: float,
    height_fraction: float,
) -> Rect:
    """Drag a title bar into an already-configured FancyZones region."""
    hwnd = _ensure_window(handle)
    display = next((item for item in list_displays() if item.id == display_id), None)
    if display is None:
        raise ValueError(f"Display {display_id!r} was not found")
    target = region_bounds(
        display.work_area,
        left_fraction=left_fraction,
        top_fraction=top_fraction,
        width_fraction=width_fraction,
        height_fraction=height_fraction,
    )
    # A real title-bar press below activates the window. Avoid SetForegroundWindow here:
    # Windows may deny programmatic foreground changes across processes.
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    start, end = fancyzones_drag_points(_window_bounds(hwnd), target)
    if not user32.SetCursorPos(*start):
        raise ctypes.WinError(ctypes.get_last_error())
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    try:
        time.sleep(0.1)
        if not user32.SetCursorPos(*end):
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.5)
    finally:
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return _window_bounds(hwnd)


def minimize_window(handle: int) -> None:
    user32.ShowWindow(_ensure_window(handle), SW_MINIMIZE)


def restore_window(handle: int) -> None:
    user32.ShowWindow(_ensure_window(handle), SW_RESTORE)


def close_window(handle: int) -> None:
    result = wintypes.DWORD_PTR()
    if not user32.SendMessageTimeoutW(
        _ensure_window(handle), WM_CLOSE, 0, 0, SMTO_ABORTIFHUNG, 2000, ctypes.byref(result)
    ):
        raise RuntimeError("The window did not accept a close request")


def record_to_dict(record: Rect | Display | Window) -> dict:
    value = asdict(record)
    if isinstance(record, Display):
        value["bounds"] = asdict(record.bounds)
        value["work_area"] = asdict(record.work_area)
    elif isinstance(record, Window):
        value["bounds"] = asdict(record.bounds)
    return value
