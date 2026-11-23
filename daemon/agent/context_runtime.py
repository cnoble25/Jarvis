"""
Context for learned rules: a rule for a request like "close that" or "skip this song" carries a small
Python resolver that works out the tool's arguments from context, every time the request is heard.

    rule["needs"]     the context it reads: ["front_app", {"helper": "recent_files", "args": {"limit": 3}}]
    rule["resolver"]  def resolve(slots, ctx): ... -> {"args": {...}} (optionally "tool") or None
                      slots: the values heard ({"app": "slack"}); ctx: each need by name, plus
                      "request" (the words) and "base_args" (the rule's args with slots filled in)

Resolvers only compute. Jarvis gathers the context they asked for through read-only helpers and passes
it in, so a resolver never needs system access, and doesn't get it: the code is checked before it
runs (only a few stdlib imports, no file, eval or dunder access), runs in a separate Python process
with a restricted set of builtins, and is stopped after RESOLVER_TIMEOUT seconds. Returning None means
"not sure": Jarvis asks the model instead.

Helpers come in two kinds:
  built in   BUILTIN_HELPERS below (front app, now playing, volume, last action, clipboard, ...)
  proposed   Claude Code can write a new read-only helper when a rule needs context nobody provides.
             Like skills, it is code, so it can't run until the user approves it in the dashboard;
             rules that need it wait until then.
"""

import ast
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from daemon.tools.skills import SkillError, SkillStore

HELPERS_DIR = Path.home() / ".config" / "jarvis" / "helpers"
RESOLVER_TIMEOUT = 3
HELPER_TIMEOUT = 5
MAX_CONTEXT_CHARS = 4000
ALLOWED_IMPORTS = {"json", "re", "math", "datetime", "difflib", "statistics", "string", "itertools", "collections"}
SAFE_BUILTINS = ["abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "frozenset", "int",
                 "isinstance", "len", "list", "map", "max", "min", "range", "repr", "reversed", "round", "set",
                 "slice", "sorted", "str", "sum", "tuple", "zip", "Exception", "ValueError", "KeyError",
                 "IndexError", "TypeError"]
BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                "delattr", "hasattr", "input", "breakpoint", "exit", "quit", "help", "memoryview", "object", "type",
                "super", "dir", "id", "print", "classmethod", "staticmethod", "property"}
BANNED_ATTRIBUTES = {"format", "format_map", "mro", "gi_frame", "f_globals", "f_locals", "f_back"}


# ---- Built-in helpers ----------------------------------------------------------------------------

def _recent_files(folder: str = "~/Downloads", limit: int = 5) -> List[Dict[str, Any]]:
    root = Path(os.path.expanduser(str(folder)))
    if not root.is_dir():
        return []
    entries = []
    for entry in os.scandir(root):
        if entry.name.startswith("."):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        entries.append({"name": entry.name, "path": entry.path, "is_folder": entry.is_dir(),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        "_mtime": stat.st_mtime})
    entries.sort(key=lambda e: -e["_mtime"])
    return [{k: v for k, v in e.items() if k != "_mtime"} for e in entries[:max(1, min(int(limit), 20))]]


def _now() -> Dict[str, Any]:
    now = datetime.now().astimezone()
    return {"iso": now.isoformat(timespec="seconds"), "weekday": now.strftime("%A"), "hour": now.hour,
            "minute": now.minute, "date": now.date().isoformat()}


BUILTIN_HELPERS: Dict[str, Dict[str, Any]] = {
    "front_app": {"description": "Name of the app in front, e.g. \"Slack\" (None if it can't be told).",
                  "get": lambda rt, **_: rt.os().front_app()},
    "running_apps": {"description": "Names of running apps, e.g. [\"Finder\", \"Slack\", \"Spotify\"].",
                     "get": lambda rt, **_: rt.os().running_apps()},
    "now_playing": {"description": "{\"player\", \"state\", \"title\", \"artist\"} for what's playing, or None.",
                    "get": lambda rt, **_: rt.os().now_playing()},
    "volume": {"description": "{\"level\": 0-100 or None, \"muted\": bool} for the sound output.",
               "get": lambda rt, **_: (lambda v: {"level": v.level, "muted": v.muted} if v else None)(rt.os().get_volume())},
    "last_action": {"description": "What Jarvis did on the previous request: {\"request\", \"tool\", \"args\", "
                                   "\"seconds_ago\"} (None if nothing in the last 10 minutes).",
                    "get": lambda rt, **_: rt.last_action()},
    "clipboard": {"description": "The clipboard's text (up to 2000 characters), or None.",
                  "get": lambda rt, **_: (lambda c: c[:2000] if c else c)(rt.os().clipboard())},
    "recent_files": {"description": "Newest files in a folder: args {\"folder\": \"~/Downloads\", \"limit\": 5} -> "
                                    "[{\"name\", \"path\", \"is_folder\", \"modified\"}].",
                     "get": lambda rt, **kw: _recent_files(**kw)},
    "now": {"description": "{\"iso\", \"weekday\", \"hour\", \"minute\", \"date\"} for the current local time.",
            "get": lambda rt, **_: _now()},
}


# ---- Proposed helpers (need approval) ------------------------------------------------------------

PROPOSE_HELPER_TOOL = {
    "name": "propose_helper",
    "description": ("Propose a new read-only context helper when a rule needs context no helper provides. It is a "
                    "Python script that only LOOKS things up (runs read-only commands, reads files) and prints its "
                    "answer as JSON on the last line; its arguments arrive as JSON on stdin. It never changes "
                    "anything. The user must approve it before it runs; rules that need it wait until then."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "snake_case name, e.g. 'frontmost_finder_folder'."},
            "name": {"type": "string"},
            "description": {"type": "string", "description": "What it returns, with an example value."},
            "parameters": {"type": "object", "description": "JSON Schema (type: object) of its arguments."},
            "code": {"type": "string", "description": "The complete Python script."},
        },
        "required": ["id", "name", "description", "code"],
    },
}


class HelperStore(SkillStore):
    """Proposed context helpers: stored and approved like skills, but they return data, not speech."""

    def __init__(self, root: Optional[Path] = None):
        super().__init__(root or HELPERS_DIR)

    def save(self, spec: Dict[str, Any], taken=(), source_request: str = "") -> Dict[str, Any]:
        if str(spec.get("id", "")) in BUILTIN_HELPERS:
            raise SkillError(f"'{spec.get('id')}' is a built-in helper already.")
        return super().save({**spec, "language": "python", "risk_level": "SAFE"}, taken, source_request)

    def approved_manifests(self) -> List[Dict[str, Any]]:
        return []  # helpers are never tools

    def call(self, helper_id: str, args: Dict[str, Any], timeout: int = HELPER_TIMEOUT) -> Any:
        result = self.run(helper_id, args, timeout=timeout)
        if not result.get("success"):
            raise RuntimeError(result.get("stderr") or f"helper '{helper_id}' failed")
        lines = [line for line in result.get("stdout", "").splitlines() if line.strip()]
        try:
            return json.loads(lines[-1]) if lines else None
        except json.JSONDecodeError:
            raise RuntimeError(f"helper '{helper_id}' didn't print JSON on its last line")


# ---- Resolvers ------------------------------------------------------------------------------------

def resolver_problems(code: str) -> List[str]:
    """Why this resolver can't run (empty when it can): it must only compute."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError as err:
        return [f"syntax error: {err}"]
    problems = []
    resolve = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "resolve"]
    if not resolve or len(resolve[0].args.args) != 2:
        problems.append("define a top-level function resolve(slots, ctx).")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import of '{name}' isn't allowed (only {sorted(ALLOWED_IMPORTS)}).")
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            problems.append(f"'{node.id}' isn't allowed in a resolver.")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BANNED_ATTRIBUTES):
            problems.append(f"'.{node.attr}' isn't allowed in a resolver.")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
            problems.append(f"{type(node).__name__} isn't allowed in a resolver.")
    return list(dict.fromkeys(problems))


_RUNNER = r"""
import builtins, json, sys
data = json.loads(sys.stdin.read())
allowed = set(data["allowed_imports"])
real_import = builtins.__import__
def limited_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in allowed:
        raise ImportError(f"import of {name!r} isn't allowed")
    return real_import(name, globals, locals, fromlist, level)
safe = {k: getattr(builtins, k) for k in data["builtins"]}
safe["__import__"] = limited_import
scope = {"__builtins__": safe, "__name__": "resolver"}
exec(compile(data["code"], "<resolver>", "exec"), scope)
out = scope["resolve"](data["slots"], data["ctx"])
sys.stdout.write(json.dumps({"result": out}, default=str))
"""


def run_resolver(code: str, slots: Dict[str, Any], ctx: Dict[str, Any], timeout: float = RESOLVER_TIMEOUT) -> Dict[str, Any]:
    """Run a checked resolver: {"result": ...} or {"error": ...}."""
    problems = resolver_problems(code)
    if problems:
        return {"error": "; ".join(problems)}
    payload = json.dumps({"code": code, "slots": slots, "ctx": ctx, "builtins": SAFE_BUILTINS,
                          "allowed_imports": sorted(ALLOWED_IMPORTS)}, default=str)
    try:
        proc = subprocess.run([sys.executable, "-I", "-S", "-c", _RUNNER], input=payload, capture_output=True,
                              text=True, timeout=timeout, env={"PATH": os.environ.get("PATH", "")})
    except subprocess.TimeoutExpired:
        return {"error": f"the resolver took over {timeout} seconds"}
    if proc.returncode != 0:
        last = [line for line in (proc.stderr or "").strip().splitlines() if line.strip()]
        return {"error": last[-1][:300] if last else f"exit code {proc.returncode}"}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "the resolver's result wasn't JSON-serializable"}


# ---- Runtime --------------------------------------------------------------------------------------

class ContextRuntime:
    def __init__(self, helpers: Optional[HelperStore] = None, os_interface: Optional[Callable[[], Any]] = None,
                 last_turn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None):
        self.helpers = helpers or HelperStore()
        self._os = os_interface
        self._last_turn = last_turn or (lambda: None)

    def os(self):
        if self._os is not None:
            return self._os()
        from daemon.os_interface import get_os
        return get_os()

    def last_action(self) -> Optional[Dict[str, Any]]:
        record = self._last_turn()
        if not record or record.get("tool_executed") in (None, "", "none", "ignored"):
            return None
        try:
            ago = time.time() - datetime.fromisoformat(record["timestamp"]).timestamp()
        except (KeyError, ValueError):
            ago = None
        if ago is not None and ago > 600:
            return None
        args = {k: v for k, v in (record.get("tool_args") or {}).items() if not str(k).startswith("_")}
        return {"request": record.get("user_query", ""), "tool": record.get("tool_executed"), "args": args,
                "seconds_ago": round(ago) if ago is not None else None}

    # ---- Catalog --------------------------------------------------------------------------------

    def catalog(self) -> List[Dict[str, Any]]:
        """Every helper a rule can name, with whether it's usable yet (for Claude Code and the dashboard)."""
        out = [{"name": n, "description": h["description"], "status": "built in"} for n, h in BUILTIN_HELPERS.items()]
        for helper in self.helpers.list():
            out.append({"name": helper["id"], "description": helper["description"],
                        "status": "approved" if helper["status"] == "approved" else "waiting for the user's approval"})
        return out

    def helper_status(self, name: str) -> str:
        """built_in | approved | pending | unknown."""
        if name in BUILTIN_HELPERS:
            return "built_in"
        helper = self.helpers.get(name)
        if not helper:
            return "unknown"
        return "approved" if helper["status"] == "approved" else "pending"

    @staticmethod
    def need_name(need: Any) -> str:
        return need if isinstance(need, str) else str((need or {}).get("helper", ""))

    # ---- Gathering and resolving ----------------------------------------------------------------

    def gather(self, needs: List[Any]) -> Dict[str, Any]:
        """Look up the context a rule asked for. A helper that fails gives None (the resolver decides)."""
        ctx: Dict[str, Any] = {}
        for need in needs or []:
            name = self.need_name(need)
            args = (need.get("args") or {}) if isinstance(need, dict) else {}
            key = need.get("as", name) if isinstance(need, dict) else name
            try:
                if name in BUILTIN_HELPERS:
                    value = BUILTIN_HELPERS[name]["get"](self, **args)
                elif self.helper_status(name) == "approved":
                    value = self.helpers.call(name, args)
                else:
                    value = None
            except Exception as err:
                print(f"[ContextRuntime] Helper '{name}' failed: {err}", flush=True)
                value = None
            ctx[key] = value
        text = json.dumps(ctx, default=str)
        if len(text) > MAX_CONTEXT_CHARS:
            print(f"[ContextRuntime] Context is {len(text)} characters; trimming long values.", flush=True)
            ctx = {k: (v[:MAX_CONTEXT_CHARS // 4] if isinstance(v, (str, list)) else v) for k, v in ctx.items()}
        return ctx

    def resolve(self, rule: Dict[str, Any], slots: Dict[str, Any], args: Dict[str, Any], request: str,
                ctx: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        The tool call for a context rule: {"tool", "args", "context"}, or None to let the model answer.
        ctx overrides gathering (tests and Claude Code's dry runs pass sample context).
        """
        if any(self.helper_status(self.need_name(n)) not in ("built_in", "approved") for n in rule.get("needs") or []):
            return None
        if ctx is None:
            ctx = self.gather(rule.get("needs") or [])
        out = run_resolver(rule["resolver"], dict(slots), {**ctx, "request": request, "base_args": args})
        if "error" in out:
            print(f"[ContextRuntime] Resolver for {rule.get('id')} failed: {out['error']}", flush=True)
            return None
        result = out.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("args", {}), dict):
            return None
        tool = result.get("tool") or rule["tool"]
        return {"tool": tool, "args": {**args, **(result.get("args") or {})}, "context": ctx}
