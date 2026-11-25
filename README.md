# Windows Window Control MCP

**Status:** Standalone Prototype (`v0.1.0`)

A dependency-free Python stdio MCP server and interactive Windows session helper for listing displays/windows and applying deliberate window placement actions via Win32 APIs (`ctypes`).

## Architecture

- **`mcp_server.py` / `launch_stdio.py`:** Stdio JSON-RPC MCP server that ensures the interactive helper (`interactive_agent.py`) is running in the current Windows session (`ProcessIdToSessionId`) before serving requests.
- **`bridge.py` / `runtime_context.py`:** File-based IPC under `runtime/session-<SessionId>` protected by a cross-process named request mutex with bounded wait and abandoned-owner recovery. Stale pre-startup requests are skipped on helper restart.
- **`desktop_window_control.py`:** Win32 `user32` / `dwmapi` display enumeration, invisible frame-margin adjustment, window state controls, and optional PowerToys FancyZones drag placement.

## Supported MCP tools

| Tool | Description |
| --- | --- |
| `list_displays` | List local displays, bounds, and usable work areas |
| `list_windows` | List visible top-level windows and handles |
| `focus_window` | Restore and focus a window by handle |
| `move_window_to_display` | Fit a window at the top-left of a target display work area |
| `arrange_vertical_stack` | Tile two windows in a full-width vertical split (`top_fraction`) |
| `place_window_in_region` | Place a window in a fractional display rectangle with frame correction |
| `snap_window_to_fancyzones_region` | Drag a window into a configured PowerToys FancyZones region |
| `minimize_window` | Minimize a window by handle |
| `restore_window` | Restore a window by handle |
| `close_window` | Request a normal `WM_CLOSE` on a window handle |

## Behavior & Windows Snap Groups

- Direct placement tools (`place_window_in_region`, `arrange_vertical_stack`, `move_window_to_display`) position windows via Win32 `SetWindowPos` and DWM frame-inset calculations rather than triggering Windows 11 native Snap Layouts / Snap Groups. Native Snap Group membership and Snap Assist previews remain Windows-managed behaviors.
- `snap_window_to_fancyzones_region` simulates a Shift-drag over a configured zone rather than calling private FancyZones APIs.

## Usage

No external pip packages are required (standard library + Windows `ctypes` only).

1. See `example-mcp-config.json` for a sample MCP stdio client entry pointing to `launch_stdio.py`.
2. Or start just the background helper in your logged-in Windows session:
   ```powershell
   python -B launch_stdio.py --helper-only
   ```
   (Or run `Start Window Control.cmd`.)

## Tests

```powershell
python -B -W error::ResourceWarning -m unittest test_transport test_lifecycle test_desktop_window_control -v
```

## License

MIT - see [LICENSE](LICENSE).
