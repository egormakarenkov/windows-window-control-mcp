"""A dependency-free stdio MCP server for deliberate Windows window management."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from bridge import call


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] = []) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool("list_displays", "List local displays, their bounds, and their usable work areas.", {}),
    _tool("list_windows", "List visible top-level windows. Use the returned numeric handle for any action." , {}),
    _tool(
        "focus_window",
        "Restore and focus one existing window handle returned by list_windows.",
        {"handle": {"type": "integer", "description": "Exact handle returned by list_windows."}},
        ["handle"],
    ),
    _tool(
        "move_window_to_display",
        "Restore one existing window and fit it at the top-left of a selected display's work area.",
        {
            "handle": {"type": "integer", "description": "Exact handle returned by list_windows."},
            "display_id": {"type": "string", "description": "Exact display ID returned by list_displays."},
        },
        ["handle", "display_id"],
    ),
    _tool(
        "arrange_vertical_stack",
        "Place two different windows in an adjoining full-width vertical split on one display.",
        {
            "top_handle": {"type": "integer", "description": "Exact handle for the upper window from list_windows."},
            "bottom_handle": {"type": "integer", "description": "Exact handle for the lower window from list_windows."},
            "display_id": {"type": "string", "description": "Exact display ID from list_displays."},
            "top_fraction": {"type": "number", "description": "Upper window share of display height, from 0.1 to 0.9."},
        },
        ["top_handle", "bottom_handle", "display_id"],
    ),
    _tool(
        "place_window_in_region",
        "Place one returned window in a fractional rectangular region of one display, correcting for its frame edge.",
        {
            "handle": {"type": "integer", "description": "Exact handle from list_windows."},
            "display_id": {"type": "string", "description": "Exact display ID from list_displays."},
            "left_fraction": {"type": "number", "description": "Region left edge from 0 to 1."},
            "top_fraction": {"type": "number", "description": "Region top edge from 0 to 1."},
            "width_fraction": {"type": "number", "description": "Region width from 0 to 1."},
            "height_fraction": {"type": "number", "description": "Region height from 0 to 1."},
        },
        ["handle", "display_id", "left_fraction", "top_fraction", "width_fraction", "height_fraction"],
    ),
    _tool(
        "snap_window_to_fancyzones_region",
        "Drag one selected window into an already-configured FancyZones region.",
        {
            "handle": {"type": "integer", "description": "Exact handle from list_windows."},
            "display_id": {"type": "string", "description": "Exact display ID from list_displays."},
            "left_fraction": {"type": "number", "description": "Zone left edge from 0 to 1."},
            "top_fraction": {"type": "number", "description": "Zone top edge from 0 to 1."},
            "width_fraction": {"type": "number", "description": "Zone width from 0 to 1."},
            "height_fraction": {"type": "number", "description": "Zone height from 0 to 1."},
        },
        ["handle", "display_id", "left_fraction", "top_fraction", "width_fraction", "height_fraction"],
    ),
    _tool(
        "minimize_window",
        "Minimize one existing window handle returned by list_windows.",
        {"handle": {"type": "integer", "description": "Exact handle returned by list_windows."}},
        ["handle"],
    ),
    _tool(
        "restore_window",
        "Restore one existing window handle returned by list_windows.",
        {"handle": {"type": "integer", "description": "Exact handle returned by list_windows."}},
        ["handle"],
    ),
    _tool(
        "close_window",
        "Request a normal close for one existing window. Obtain the user's confirmation immediately before calling this tool.",
        {"handle": {"type": "integer", "description": "Exact handle returned by list_windows."}},
        ["handle"],
    ),
]


def _json_content(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, indent=2)}], "structuredContent": value}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in {tool["name"] for tool in TOOLS}:
        raise ValueError(f"Unknown tool {name!r}")
    return _json_content(call(name, arguments))


def response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": message}}


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return response(
            request_id,
            {
                "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-03-26"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "local-window-control", "version": "1.0.0"},
            },
        )
    if method == "tools/list":
        return response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params", {})
        try:
            return response(request_id, call_tool(params["name"], params.get("arguments", {})))
        except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
            return response(request_id, {"content": [{"type": "text", "text": str(error)}], "isError": True})
    return error_response(request_id, f"Unsupported method {method!r}")


def main() -> None:
    for line in sys.stdin:
        try:
            reply = handle_request(json.loads(line))
            if reply is not None:
                print(json.dumps(reply), flush=True)
        except json.JSONDecodeError as error:
            print(json.dumps(error_response(None, f"Invalid JSON: {error.msg}")), flush=True)


if __name__ == "__main__":
    main()
