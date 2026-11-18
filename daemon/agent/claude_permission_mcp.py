"""
A tiny MCP server (stdio) for Claude Code sessions started by Jarvis. It offers:
- `approve`, the permission tool (`--permission-prompt-tool mcp__jarvis__approve`), and
- Jarvis's own desktop tools (media, volume, apps, timers, macros...), listed and run by Jarvis.

Each call is forwarded to the Jarvis task that started the session, over a private Unix socket
given in JARVIS_PERMISSION_SOCKET; Jarvis decides (safe commands pass, risky ones wait for the
user's "go ahead") and replies with the decision. No socket, or no answer: the step is denied.

Standalone on purpose: Claude Code starts it as its own process, with no Jarvis imports.
"""

import json
import os
import socket
import sys

PROTOCOL_FALLBACK = "2025-06-18"
TOOL = {
    "name": "approve",
    "description": "Ask the Jarvis user whether a Claude Code tool call may run.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string"},
            "input": {"type": "object"},
            "tool_use_id": {"type": "string"},
        },
        "required": ["tool_name", "input"],
    },
}


def ask_jarvis(message: dict):
    """One request/reply over the private socket Jarvis opened for this session."""
    path = os.environ.get("JARVIS_PERMISSION_SOCKET")
    if not path:
        return None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(path)
        s.sendall((json.dumps(message) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode() or "null")


def jarvis_tools() -> list:
    try:
        return ask_jarvis({"kind": "list_tools"}) or []
    except (OSError, ValueError):
        return []


def decide(arguments: dict) -> dict:
    """Ask Jarvis; deny when it can't be reached."""
    tool_input = arguments.get("input") if isinstance(arguments.get("input"), dict) else {}
    log_path = os.environ.get("JARVIS_PERMISSION_LOG")
    if log_path:  # probe mode: record what Claude Code sends
        with open(log_path, "a") as f:
            f.write(json.dumps(arguments) + "\n")
    path = os.environ.get("JARVIS_PERMISSION_SOCKET")
    if not path:
        if os.environ.get("JARVIS_PERMISSION_ALLOW_ALL") == "1":
            return {"behavior": "allow", "updatedInput": tool_input}
        return {"behavior": "deny", "message": "Jarvis isn't available to approve this step."}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(path)
            s.sendall((json.dumps(arguments) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        reply = json.loads(data.decode() or "{}")
    except (OSError, ValueError) as err:
        return {"behavior": "deny", "message": f"Couldn't reach Jarvis for approval ({err})."}
    if reply.get("behavior") == "allow":
        return {"behavior": "allow", "updatedInput": reply.get("updatedInput", tool_input)}
    return {"behavior": "deny", "message": reply.get("message") or "The user said no."}


def respond(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:
            continue  # notifications (initialized, cancelled) need no reply
        if method == "initialize":
            version = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_FALLBACK
            respond(msg_id, {"protocolVersion": version, "capabilities": {"tools": {}},
                             "serverInfo": {"name": "jarvis", "version": "1.0.0"}})
        elif method == "tools/list":
            respond(msg_id, {"tools": [TOOL] + jarvis_tools()})
        elif method == "tools/call":
            params = msg.get("params") or {}
            if params.get("name") != "approve":
                try:
                    reply = ask_jarvis({"kind": "call_tool", "name": params.get("name"),
                                        "arguments": params.get("arguments") or {}}) or {}
                except (OSError, ValueError) as err:
                    reply = {"text": f"Couldn't reach Jarvis: {err}", "is_error": True}
                respond(msg_id, {"content": [{"type": "text", "text": str(reply.get("text", ""))}],
                                 "isError": bool(reply.get("is_error"))})
                continue
            decision = decide(params.get("arguments") or {})
            respond(msg_id, {"content": [{"type": "text", "text": json.dumps(decision)}]})
        elif method == "ping":
            respond(msg_id, {})
        else:
            respond(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
