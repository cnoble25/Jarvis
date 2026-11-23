"""
Skills: abilities Jarvis writes for itself.

Claude Code saves a skill (through the `save_skill` Jarvis tool) as a folder:

    ~/.config/jarvis/skills/<id>/skill.json   what it does, its arguments (JSON Schema), its risk
    ~/.config/jarvis/skills/<id>/run.py       or run.sh: the code

A new skill can't run until the user approves it in the dashboard. Approving records a fingerprint
of the manifest and the code; if either changes afterwards (Claude Code rewrites it, someone edits
the file), the fingerprint no longer matches and the skill waits for approval again. Approved
skills load into the tool registry like any other command, so the model, Claude Code and learned
shortcuts can all use them. HIGH-risk skills still ask before every run (approval.py).

How a skill runs: its arguments arrive as JSON on stdin (and in $JARVIS_ARGS), it runs from the home
folder, and the last line it prints is what Jarvis says. A non-zero exit is a failure, and stderr
says why.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SKILLS_DIR = Path.home() / ".config" / "jarvis" / "skills"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
LANGUAGES = {"python": "run.py", "bash": "run.sh"}
RISK_LEVELS = ("SAFE", "MEDIUM", "HIGH")
MAX_CODE_BYTES = 64 * 1024
RUN_TIMEOUT_SECONDS = 60
MAX_SPOKEN_CHARS = 220
# Manifest fields that are about the skill itself; approval and bookkeeping fields are left out of
# the fingerprint so recording an approval doesn't change it.
FINGERPRINTED = ("id", "name", "description", "parameters", "language", "risk_level", "spoken_confirmation_template")

# Offered to Claude Code sessions as a Jarvis tool (see AgentOrchestrator._run_claude_code).
SAVE_SKILL_TOOL = {
    "name": "save_skill",
    "description": (
        "Save a reusable ability for Jarvis: a small, self-contained script Jarvis can run by voice from now on. "
        "Use it when the user asks Jarvis to learn or be able to do something again, or for a task they will "
        "clearly repeat. The script gets its arguments as a JSON object on stdin, prints one short sentence to be "
        "spoken as its last line of output, and exits non-zero (with the reason on stderr) when it fails. Test the "
        "script before saving it. The user must approve a new or changed skill in the Jarvis dashboard before it "
        "can run."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "snake_case identifier, 3-41 characters, e.g. 'convert_heic_to_jpg'."},
            "name": {"type": "string", "description": "Short human name, e.g. 'Convert HEIC photos to JPG'."},
            "description": {"type": "string", "description": "What it does and when to use it, for Jarvis's model to pick it."},
            "parameters": {"type": "object", "description": "JSON Schema (type: object) of the arguments the script reads."},
            "language": {"type": "string", "enum": list(LANGUAGES)},
            "code": {"type": "string", "description": "The complete script."},
            "risk_level": {"type": "string", "enum": list(RISK_LEVELS),
                           "description": "SAFE: only reads or shows things. MEDIUM: changes the user's own files or apps. HIGH: deletes, sends, buys, or changes system settings (asks before every run)."},
            "example_requests": {"type": "array", "items": {"type": "string"}, "description": "Things the user might say to use it."},
        },
        "required": ["id", "name", "description", "language", "code", "risk_level"],
    },
}


class SkillError(ValueError):
    pass


class SkillStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else SKILLS_DIR
        self._lock = threading.Lock()

    # ---- Reading ------------------------------------------------------------------------------

    def _manifest_path(self, skill_id: str) -> Path:
        return self.root / skill_id / "skill.json"

    def _read_manifest(self, skill_id: str) -> Optional[Dict[str, Any]]:
        if not ID_PATTERN.match(skill_id or ""):
            return None
        try:
            return json.loads(self._manifest_path(skill_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _code_path(self, manifest: Dict[str, Any]) -> Path:
        return self.root / manifest["id"] / LANGUAGES.get(manifest.get("language", ""), "run.py")

    def fingerprint(self, manifest: Dict[str, Any]) -> str:
        """sha256 of what the skill is and does: its manifest fields and its code."""
        core = json.dumps({k: manifest.get(k) for k in FINGERPRINTED}, sort_keys=True, default=str)
        try:
            code = self._code_path(manifest).read_bytes()
        except OSError:
            code = b""
        return hashlib.sha256(core.encode() + b"\0" + code).hexdigest()

    def get(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """The skill with its code and status: approved | pending (never approved) | changed (edited since)."""
        manifest = self._read_manifest(skill_id)
        if not manifest:
            return None
        try:
            code = self._code_path(manifest).read_text(encoding="utf-8", errors="replace")
        except OSError:
            code = ""
        approved = manifest.get("approved_hash")
        status = "approved" if approved and approved == self.fingerprint(manifest) else ("changed" if approved else "pending")
        return {**manifest, "code": code, "status": status}

    def list(self) -> List[Dict[str, Any]]:
        if not self.root.is_dir():
            return []
        skills = [self.get(p.name) for p in sorted(self.root.iterdir()) if p.is_dir()]
        return [s for s in skills if s]

    def approved_manifests(self) -> List[Dict[str, Any]]:
        """Approved skills as tool manifests for the ToolRegistry."""
        out = []
        for s in self.list():
            if s["status"] != "approved":
                continue
            out.append({
                "id": s["id"], "name": s["name"], "version": "1.0.0", "description": s["description"],
                "category": "skill", "parameters": s.get("parameters") or {"type": "object", "properties": {}},
                "execution": {"type": "skill", "template": "builtin_skill"},
                "examples": [{"user_prompt": e, "expected_args": {}} for e in s.get("example_requests", [])[:3]],
                "risk_level": s.get("risk_level", "MEDIUM"),
                "spoken_confirmation_template": s.get("spoken_confirmation_template"),
            })
        return out

    def risk(self, skill_id: str) -> Optional[str]:
        manifest = self._read_manifest(skill_id)
        return manifest.get("risk_level") if manifest else None

    # ---- Writing ------------------------------------------------------------------------------

    def save(self, spec: Dict[str, Any], taken: Iterable[str] = (), source_request: str = "") -> Dict[str, Any]:
        """
        Create or replace a skill from Claude Code's save_skill call. It always starts unapproved.
        taken: tool ids that already belong to something else (a skill can't shadow a built-in).
        """
        skill_id = str(spec.get("id", "")).strip()
        if not ID_PATTERN.match(skill_id):
            raise SkillError("id must be snake_case: a lowercase letter, then 2-40 lowercase letters, digits or underscores.")
        if skill_id in set(taken):
            raise SkillError(f"'{skill_id}' is already a Jarvis command; pick another id.")
        language = str(spec.get("language", "")).strip().lower()
        if language not in LANGUAGES:
            raise SkillError(f"language must be one of: {', '.join(LANGUAGES)}.")
        risk = str(spec.get("risk_level", "")).strip().upper()
        if risk not in RISK_LEVELS:
            raise SkillError(f"risk_level must be one of: {', '.join(RISK_LEVELS)}.")
        code = str(spec.get("code", ""))
        if not code.strip():
            raise SkillError("code is empty.")
        if len(code.encode()) > MAX_CODE_BYTES:
            raise SkillError(f"code is over {MAX_CODE_BYTES // 1024} KB; keep skills small.")
        name, description = str(spec.get("name", "")).strip(), str(spec.get("description", "")).strip()
        if not name or not description:
            raise SkillError("name and description are required.")
        parameters = spec.get("parameters") or {"type": "object", "properties": {}}
        if not isinstance(parameters, dict) or parameters.get("type", "object") != "object":
            raise SkillError("parameters must be a JSON Schema object (type: object).")
        examples = [str(e) for e in (spec.get("example_requests") or []) if str(e).strip()][:5]

        manifest = {
            "id": skill_id, "name": name, "description": description, "parameters": parameters,
            "language": language, "risk_level": risk, "example_requests": examples,
            "spoken_confirmation_template": spec.get("spoken_confirmation_template") or None,
            "created_by": "claude_code", "source_request": source_request[:500],
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        folder = self.root / skill_id
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            for other in LANGUAGES.values():  # switching language leaves no stale script behind
                (folder / other).unlink(missing_ok=True)
            code_path = folder / LANGUAGES[language]
            code_path.write_text(code, encoding="utf-8")
            os.chmod(code_path, 0o700)
            tmp = folder / "skill.json.tmp"
            tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            os.replace(tmp, folder / "skill.json")
        return self.get(skill_id)

    def approve(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """Approve exactly what is on disk now."""
        with self._lock:
            manifest = self._read_manifest(skill_id)
            if not manifest:
                return None
            manifest["approved_hash"] = self.fingerprint(manifest)
            manifest["approved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._manifest_path(skill_id).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return self.get(skill_id)

    def delete(self, skill_id: str) -> bool:
        if not ID_PATTERN.match(skill_id or "") or not (self.root / skill_id).is_dir():
            return False
        shutil.rmtree(self.root / skill_id)
        return True

    # ---- Running ------------------------------------------------------------------------------

    def run(self, skill_id: str, args: Dict[str, Any], cancel: Optional[threading.Event] = None,
            timeout: int = RUN_TIMEOUT_SECONDS) -> Dict[str, Any]:
        """Run an approved skill; the result has the ExecutionEngine's usual keys."""
        skill = self.get(skill_id)
        if not skill:
            return {"success": False, "stdout": "", "stderr": f"No skill named '{skill_id}'.",
                    "spoken_confirmation": "I don't have that skill."}
        if skill["status"] != "approved":
            why = "it changed since you approved it" if skill["status"] == "changed" else "you haven't approved it yet"
            return {"success": False, "stdout": "", "stderr": f"Skill '{skill_id}' can't run: {why}.",
                    "spoken_confirmation": f"The {skill['name']} skill needs your approval in the dashboard first, because {why}."}
        clean = {k: v for k, v in (args or {}).items() if not str(k).startswith("_")}
        payload = json.dumps(clean)
        code_path = str(self._code_path(skill))
        cmd = [sys.executable, "-I", code_path] if skill["language"] == "python" else ["/bin/bash", code_path]
        env = {**os.environ, "JARVIS_ARGS": payload, "JARVIS_SKILL_DIR": str(self.root / skill_id)}
        print(f"[Skills] Running '{skill_id}' with {payload}", flush=True)
        try:
            proc = subprocess.Popen(cmd, cwd=str(Path.home()), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, start_new_session=True)
        except OSError as err:
            return {"success": False, "stdout": "", "stderr": str(err), "spoken_confirmation": "That skill couldn't start."}
        deadline = time.monotonic() + timeout
        to_send: Optional[str] = payload
        while True:
            try:
                out, err = proc.communicate(input=to_send, timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                to_send = None  # communicate() already sent it
                stopped = cancel is not None and cancel.is_set()
                if stopped or time.monotonic() > deadline:
                    proc.kill()
                    out, err = proc.communicate()
                    reason = "Stopped." if stopped else f"Timed out after {timeout} seconds."
                    return {"success": False, "cancelled": stopped, "stdout": out, "stderr": reason,
                            "spoken_confirmation": f"The {skill['name']} skill {'was stopped' if stopped else 'took too long'}."}
        lines = [line.strip() for line in (out or "").splitlines() if line.strip()]
        ok = proc.returncode == 0
        if ok:
            spoken = lines[-1][:MAX_SPOKEN_CHARS] if lines else f"Done: {skill['name']}."
        else:
            first_err = next((line.strip() for line in (err or "").splitlines() if line.strip()), "")
            spoken = f"The {skill['name']} skill failed" + (f": {first_err[:120]}" if first_err else ".")
        return {"success": ok, "exit_code": proc.returncode, "stdout": out or "", "stderr": err or "",
                "spoken_confirmation": spoken}
