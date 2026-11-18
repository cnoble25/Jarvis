#!/usr/bin/env python3
"""Stands in for `claude -p --output-format stream-json`: one tool call, routed through the
Jarvis permission socket exactly as the real MCP permission server would forward it."""
import json, socket, sys, time
args = sys.argv[1:]
cfg = json.load(open(args[args.index("--mcp-config") + 1]))
sock_path = cfg["mcpServers"]["jarvis"]["env"]["JARVIS_PERMISSION_SOCKET"]
prompt = args[args.index("-p") + 1]
command = prompt.split("RUN:", 1)[1].strip() if "RUN:" in prompt else "echo hi"
def out(e): print(json.dumps(e), flush=True)
resume = args[args.index("--resume") + 1] if "--resume" in args else None
out({"type": "system", "subtype": "init", "model": "fake", "session_id": resume or "sess-1"})
out({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": command, "description": "Doing the thing"}}]}})
if "SLOW" in prompt:
    time.sleep(30)
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(sock_path)
s.sendall((json.dumps({"tool_name": "Bash", "input": {"command": command, "description": "Doing the thing"}, "tool_use_id": "t1"}) + "\n").encode())
decision = json.loads(s.makefile().readline())
allowed = decision.get("behavior") == "allow"
out({"type": "user", "parent_tool_use_id": None, "message": {"content": [
    {"type": "tool_result", "tool_use_id": "t1", "content": "ok" if allowed else decision.get("message"), "is_error": not allowed}]}})
out({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
     "session_id": resume or "sess-1",
     "result": ("I did the thing." if allowed else f"I couldn't: {decision.get('message')}") + (f" (resumed {resume})" if resume else "")})
