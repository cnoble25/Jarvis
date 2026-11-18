"""
Which actions need the user's OK before they run.

Commands the model writes are sorted into three groups:
  safe     read-only or harmless (ls, grep, opening a web page, volume): runs straight away
  confirm  anything that installs, deletes, writes files or can't be analysed: waits for "go ahead"
  block    destructive patterns (rm -rf ~, mkfs): never runs
The allowlist is deliberately small: an unknown command asks first.
"""

import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

BLOCK_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]*\s+)*(/|~|\$HOME)/?(\s|$|\*)",
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\b[^|;&]*\bof=/dev/",
    r">\s*/dev/(sd|nvme|hd|vd)",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}",
    r"\bchmod\s+-R\s+\S+\s+/(\s|$)",
    r"\bchown\s+-R\s+\S+\s+/(\s|$)",
]

SAFE_PROGRAMS = {
    "ls", "cat", "head", "tail", "wc", "grep", "rg", "echo", "printf", "pwd", "date", "whoami", "id",
    "uname", "hostname", "uptime", "df", "du", "free", "ps", "pgrep", "which", "type", "file", "stat",
    "realpath", "basename", "dirname", "sort", "uniq", "cut", "tr", "true", "false", "sleep", "exit",
    "test", "[", "lsblk", "lscpu", "lspci", "lsusb", "nvidia-smi", "sensors", "playerctl", "pactl",
    "notify-send", "spogo", "jq", "diff", "cmp", "md5sum", "sha256sum", "tree", "printenv", "journalctl",
    # Checked further below: only some of their sub-commands are read-only.
    "find", "git", "flatpak", "wpctl", "systemctl", "rpm", "ollama", "xdg-open", "sed",
}
READ_ONLY_SUBCOMMANDS = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse"},
    "flatpak": {"list", "info", "search", "ps", "remote-ls"},
    "wpctl": {"get-volume", "set-volume", "set-mute", "status", "inspect"},
    "systemctl": {"status", "is-active", "is-enabled", "list-units", "--user"},
    "ollama": {"list", "ps", "show"},
}
CONTROL_OPERATORS = {"&&", "||", ";", "|", "&", "\n", ";;", "|&"}
# Approving or refusing a pending action by voice: the whole utterance must be one of these.
_APPROVE_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go", "ahead", "do", "it", "run",
                  "approve", "approved", "confirm", "confirmed", "please", "for", "jarvis", "fine", "alright", "that"}
_APPROVE_KEYS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go", "approve", "approved", "confirm",
                 "confirmed", "do", "run", "alright"}
_DENY_WORDS = {"no", "nope", "don't", "dont", "do", "not", "cancel", "stop", "never", "mind", "deny", "denied",
               "jarvis", "please", "it", "that", "run", "thanks"}
_DENY_KEYS = {"no", "nope", "don't", "dont", "not", "cancel", "stop", "deny", "denied", "never"}


def _segments(command: str) -> Optional[List[List[str]]]:
    """Split a shell command into simple commands; None if it can't be parsed safely."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    segments, current = [], []
    for tok in tokens:
        if tok in CONTROL_OPERATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _segment_is_safe(words: List[str]) -> bool:
    # Drop leading VAR=value assignments.
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if not words:
        return True
    # Redirections: writing anywhere but /dev/null changes files.
    for i, w in enumerate(words):
        if re.fullmatch(r"\d*>>?|&>>?|>\|", w):
            target = words[i + 1] if i + 1 < len(words) else ""
            if target not in ("/dev/null", "&1", "&2") and not re.fullmatch(r"&\d", target):
                return False
        elif re.match(r"\d*>>?(?!&)", w) and not re.fullmatch(r"\d*>>?/dev/null", w) and not re.fullmatch(r"\d*>&\d", w):
            return False
    prog = words[0].rsplit("/", 1)[-1]
    args = words[1:]
    if prog not in SAFE_PROGRAMS:
        return False
    if prog in READ_ONLY_SUBCOMMANDS:
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub not in READ_ONLY_SUBCOMMANDS[prog] and not (prog == "systemctl" and sub == ""):
            return False
        if prog == "git" and sub == "branch" and any(a in ("-d", "-D", "-m", "-M") for a in args):
            return False
    if prog == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fls") for a in args):
        return False
    if prog == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
        return False
    if prog == "rpm" and not any(a.startswith("-q") for a in args):
        return False
    if prog == "xdg-open" and not all(re.match(r"https?://", a) for a in args):
        return False
    return True


def command_risk(command: str) -> Tuple[str, str]:
    """("safe" | "confirm" | "block", reason)."""
    cmd = str(command or "").strip()
    if not cmd:
        return "safe", ""
    for pat in BLOCK_PATTERNS:
        if re.search(pat, cmd):
            return "block", "That command could wipe data, so I won't run it."
    if "$(" in cmd or "`" in cmd or "<(" in cmd or "sudo " in f" {cmd} " or "pkexec" in cmd:
        return "confirm", "runs commands I can't check in advance"
    segments = _segments(cmd)
    if segments is None:
        return "confirm", "I couldn't read the command"
    if all(_segment_is_safe(list(s)) for s in segments):
        return "safe", ""
    return "confirm", "changes files or installs software"


def approval_needed(tool: str, args: Any) -> Optional[Dict[str, str]]:
    """
    None when the action can run straight away, else {"label", "detail", "risk"} describing what
    needs the user's OK. risk "block" means it must not run at all.
    """
    a = args if isinstance(args, dict) else (args[0] if isinstance(args, list) and args and isinstance(args[0], dict) else {})
    if tool in ("execute_terminal_command", "Bash"):
        command = str(a.get("command", ""))
        risk, reason = command_risk(command)
        if risk == "safe":
            return None
        label = str(a.get("explanation", "")).strip() or f"Run a command that {reason}"
        return {"label": label if risk == "confirm" else reason, "detail": command, "risk": risk}
    if tool == "Edit":
        return {"label": f"Write to {a.get('path', 'a file')}", "detail": str(a.get("path", "")), "risk": "confirm"}
    if tool == "system_power_control":
        action = str(a.get("action", "")).lower()
        raw = str(a.get("_raw_user_query", "")).lower()
        if action in ("shutdown", "poweroff", "power_off", "turn_off") or re.search(r"shut\s*down|power off|turn off", raw):
            return {"label": "Shut down the computer", "detail": "", "risk": "confirm"}
        if action in ("reboot", "restart") or re.search(r"restart|reboot", raw):
            return {"label": "Restart the computer", "detail": "", "risk": "confirm"}
    return None


def _words(text: str) -> List[str]:
    return re.sub(r"[^\w\s']", " ", str(text or "").lower()).split()


def is_approval(text: str) -> bool:
    w = _words(text)
    return bool(w) and set(w) <= _APPROVE_WORDS and bool(set(w) & _APPROVE_KEYS) and not is_refusal(text)


def is_refusal(text: str) -> bool:
    w = _words(text)
    return bool(w) and set(w) <= _DENY_WORDS and bool(set(w) & _DENY_KEYS)
