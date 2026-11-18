"""
Run a task through Claude Code as an agent: `claude -p` with its own tools (shell, files, web),
streaming each step into the Jarvis task (dashboard and side panel), with every permission
request routed back to Jarvis through daemon/agent/claude_permission_mcp.py.

Verified against Claude Code 2.1.327 (2026-11-17):
- The permission tool receives {"tool_name", "input", "tool_use_id"} and answers with JSON text:
  {"behavior": "allow", "updatedInput": {...}} or {"behavior": "deny", "message": "..."}.
- --safe-mode also disables MCP servers, so it can't be used; instead the session runs from an
  empty Jarvis folder with --setting-sources local (no project or user hooks/plugins load) and
  --add-dir $HOME, with the user's own Claude Code login (no API key).
- Harmless read-only commands (echo, ls) are pre-approved by Claude Code and never reach the tool.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

WORK_DIR = Path.home() / ".local" / "share" / "jarvis" / "claude-code"
PERMISSION_SERVER = Path(__file__).with_name("claude_permission_mcp.py")
TASK_TIMEOUT_SECONDS = 20 * 60
TASK_RULES = """
You are working on a task handed over by Jarvis, the user's voice assistant on their Linux desktop
(KDE Plasma on Bazzite, an immutable Fedora: prefer Flatpak, Homebrew or user-level installs over
system package changes). The user is not watching a terminal: work through the task on your own,
make reasonable choices instead of asking questions, and keep changes inside their home folder
unless the task says otherwise. Steps that change things wait for the user's OK, so don't retry a
step they turned down. End with one or two plain sentences saying what you did (or what stopped
you), written to be read aloud: no markdown, lists, code or URLs.

The request was spoken and transcribed, so file and folder names may not be spelled the way they
are on disk: "Jarvis CC demo" can be jarvis-cc-demo, JarvisCCDemo or jarvis_cc_demo, and a word may
be misheard. Match names loosely (ignore case, spaces, dashes and underscores) and try likely
mishearings. Look where people keep things: the home folder (Desktop, Documents, Downloads,
Pictures), the recently used folders listed below if any, /tmp, and drives under /run/media and
/mnt. `find / -xdev` skips /tmp and other separate filesystems, so search those explicitly. When
several things match, prefer the most recently modified. If nothing matches, say in one sentence
where you looked and name the closest matches you saw, so the user can tell you which one."""


# Spoken requests that name a file or folder get the recently used folders as hints.
PLACE_WORDS = ("file", "folder", "directory", "note", "notes", "document", "doc", "docs", "photo",
               "picture", "screenshot", "download", "project", "repo", "spreadsheet", "pdf")
RECENT_XBEL = Path.home() / ".local" / "share" / "recently-used.xbel"


def recent_folders(limit: int = 15):
    """Local folders of recently used files (KDE/GTK recently-used.xbel), newest first. No URLs."""
    import re
    from urllib.parse import unquote
    try:
        text = RECENT_XBEL.read_text(errors="ignore")
    except OSError:
        return []
    entries = re.findall(r'<bookmark href="file://([^"]+)"[^>]*?modified="([^"]+)"', text)
    folders, seen = [], set()
    for path, modified in sorted(entries, key=lambda e: e[1], reverse=True):
        folder = os.path.realpath(str(Path(unquote(path)).parent))  # /home links to /var/home on Bazzite
        if folder not in seen and os.path.isdir(folder):
            seen.add(folder)
            folders.append(folder)
        if len(folders) >= limit:
            break
    return folders


def with_place_hints(task: str) -> str:
    words = task.lower()
    if not any(w in words for w in PLACE_WORDS):
        return task
    folders = recent_folders()
    if not folders:
        return task
    return task + "\n\nRecently used folders (newest first), in case the request refers to one:\n" + "\n".join(folders)


def find_claude() -> Optional[str]:
    from daemon.providers.llm.claude_code_llm_provider import find_claude as _find
    return _find()


def describe_tool(name: str, tool_input: Dict[str, Any]) -> Dict[str, str]:
    """A short label for a Claude Code tool call, plus the detail (command, path, query)."""
    i = tool_input if isinstance(tool_input, dict) else {}
    path = str(i.get("file_path") or i.get("path") or i.get("notebook_path") or "")
    base = Path(path).name if path else ""
    if name == "Bash":
        return {"label": str(i.get("description") or "Running a command"), "detail": str(i.get("command", ""))}
    if name == "Read":
        return {"label": f"Reading {base or 'a file'}", "detail": path}
    if name == "Write":
        return {"label": f"Writing {base or 'a file'}", "detail": path}
    if name in ("Edit", "MultiEdit", "NotebookEdit"):
        return {"label": f"Editing {base or 'a file'}", "detail": path}
    if name in ("Glob", "Grep"):
        return {"label": "Searching files", "detail": str(i.get("pattern", ""))}
    if name == "WebSearch":
        q = str(i.get("query", ""))
        return {"label": f"Searching the web for “{q}”" if q else "Searching the web", "detail": ""}
    if name == "WebFetch":
        return {"label": "Reading a web page", "detail": str(i.get("url", ""))}
    if name in ("Task", "Agent"):
        return {"label": f"Starting a helper: {i.get('description', 'subtask')}", "detail": ""}
    if name.startswith("mcp__jarvis__"):
        tool = name.split("__", 2)[2]
        return {"label": tool.replace("_", " ").capitalize(), "detail": json.dumps(i)[:200] if i else ""}
    if name == "TodoWrite":
        return {"label": "Planning the steps", "detail": ""}
    return {"label": name.replace("_", " "), "detail": ""}


class ClaudeCodeSession:
    """
    One Claude Code run for one Jarvis task.
    decide(tool_name, tool_input) -> {"behavior": "allow"|"deny", ...} answers permission requests;
    on_step(event, step) is called as steps start ("step") and finish ("step_done").
    """

    def __init__(self, prompt: str, model: str, decide: Callable[[str, Dict[str, Any]], Dict[str, Any]],
                 on_step: Callable[[str, Dict[str, str]], None], cancel_event: threading.Event,
                 on_note: Optional[Callable[[str], None]] = None,
                 tools: Optional[Callable[[], list]] = None,
                 call_tool: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
                 resume: Optional[str] = None):
        self.prompt = prompt
        self.model = model
        self.decide = decide
        self.on_step = on_step
        self.on_note = on_note
        self.cancel_event = cancel_event
        self.resume = resume  # continue an earlier session (a follow-up remark)
        self.session_id: Optional[str] = None
        self.tools = tools or (lambda: [])
        self.call_tool = call_tool
        self._steps: Dict[str, Dict[str, str]] = {}
        self._proc: Optional[subprocess.Popen] = None

    # ---- permission socket: the MCP server forwards each request here -----------------------

    def _serve_permissions(self, server: socket.socket):
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return  # closed when the run ends
            threading.Thread(target=self._answer, args=(conn,), daemon=True, name="JarvisCCPermission").start()

    def _answer(self, conn: socket.socket):
        with conn:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            try:
                req = json.loads(data.decode() or "{}")
                kind = req.get("kind")
                if kind == "list_tools":
                    decision = self.tools()
                elif kind == "call_tool":
                    decision = (self.call_tool(str(req.get("name", "")), req.get("arguments") or {})
                                if self.call_tool else {"text": "Jarvis tools aren't available.", "is_error": True})
                else:  # a permission request
                    decision = self.decide(str(req.get("tool_name", "")), req.get("input") or {})
            except Exception as err:
                decision = {"behavior": "deny", "message": f"Jarvis couldn't decide: {err}", "text": str(err), "is_error": True}
            try:
                conn.sendall((json.dumps(decision) + "\n").encode())
            except OSError:
                pass

    # ---- the run ---------------------------------------------------------------------------

    def _handle_event(self, e: Dict[str, Any], final: Dict[str, Any]):
        kind = e.get("type")
        if e.get("session_id") and not self.session_id:
            self.session_id = e["session_id"]
        if e.get("parent_tool_use_id"):
            return  # a helper agent's inner steps: the helper itself is shown as one step
        if kind == "assistant":
            for block in (e.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    step = describe_tool(block.get("name", ""), block.get("input") or {})
                    step["state"] = "running"
                    self._steps[block.get("id", "")] = step
                    self.on_step("step", step)
                elif block.get("type") == "text" and self.on_note and block.get("text", "").strip():
                    self.on_note(block["text"].strip())
        elif kind == "user":
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    step = self._steps.get(block.get("tool_use_id", ""))
                    if step:
                        step["state"] = "failed" if block.get("is_error") else "done"
                        self.on_step("step_done", step)
        elif kind == "result":
            final.update(e)

    def run(self) -> Dict[str, Any]:
        binary = find_claude()
        if not binary:
            return {"ok": False, "text": "Claude Code isn't installed on this computer."}
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        tmp = Path(tempfile.mkdtemp(prefix="jarvis-cc-", dir=runtime))
        sock_path = str(tmp / "permission.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        os.chmod(sock_path, 0o600)
        server.listen(4)
        threading.Thread(target=self._serve_permissions, args=(server,), daemon=True, name="JarvisCCPermissions").start()

        mcp_config = tmp / "mcp.json"
        mcp_config.write_text(json.dumps({"mcpServers": {"jarvis": {
            "command": sys.executable, "args": [str(PERMISSION_SERVER)],
            "env": {"JARVIS_PERMISSION_SOCKET": sock_path}}}}))
        cmd = [binary, "-p", with_place_hints(self.prompt), "--model", self.model,
               "--setting-sources", "local", "--add-dir", str(Path.home()),
               "--output-format", "stream-json", "--verbose",
               "--mcp-config", str(mcp_config), "--strict-mcp-config",
               "--permission-prompt-tool", "mcp__jarvis__approve",
               "--append-system-prompt", TASK_RULES]
        if self.resume:
            cmd += ["--resume", self.resume]
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        final: Dict[str, Any] = {}
        stderr_tail: list = []
        started = time.monotonic()
        try:
            self._proc = subprocess.Popen(cmd, cwd=WORK_DIR, env=env, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                          bufsize=1, start_new_session=True)
            threading.Thread(target=lambda: stderr_tail.extend(self._proc.stderr.readlines()[-5:]),
                             daemon=True, name="JarvisCCStderr").start()
            threading.Thread(target=self._watch, args=(started,), daemon=True, name="JarvisCCWatch").start()
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._handle_event(json.loads(line), final)
                except ValueError:
                    continue
            self._proc.wait()
        finally:
            server.close()
            shutil.rmtree(tmp, ignore_errors=True)

        self.session_id = self.session_id or final.get("session_id")
        if self.cancel_event.is_set():
            return {"ok": False, "cancelled": True, "text": "Stopped."}
        if final.get("subtype") == "success" and not final.get("is_error"):
            return {"ok": True, "text": str(final.get("result", "")).strip(), "turns": final.get("num_turns"),
                    "session_id": self.session_id,
                    "seconds": round(time.monotonic() - started, 1)}
        reason = final.get("result") or "; ".join(final.get("errors") or []) or "".join(stderr_tail).strip()
        if time.monotonic() - started >= TASK_TIMEOUT_SECONDS:
            reason = f"it ran past {TASK_TIMEOUT_SECONDS // 60} minutes"
        return {"ok": False, "session_id": self.session_id,
                "text": f"Claude Code couldn't finish: {str(reason)[:300] or 'unknown error'}"}

    def _watch(self, started: float):
        """Stop the run when the task is cancelled or takes too long."""
        while self._proc and self._proc.poll() is None:
            if self.cancel_event.is_set() or time.monotonic() - started > TASK_TIMEOUT_SECONDS:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(self._proc.pid, sig)
                    except ProcessLookupError:
                        return
                    time.sleep(3)
                return
            time.sleep(0.3)
