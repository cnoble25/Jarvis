"""
Installed apps and spoken-name matching.

Which apps exist, how to start them and how to close them comes from the OS interface (.desktop
entries on Linux, .app bundles on macOS). Matching what the user said to one of them ("my camera",
"VS Code", "discrod") is the same everywhere and lives here.
"""

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from daemon.os_interface import get_os
from daemon.os_interface.base import AppEntry, OSInterface


# Words that come before an app's name in speech, not part of it ("open up the camera").
_LEAD_WORDS = {"up", "the", "my", "a", "an", "me", "to", "on", "open", "launch", "start", "run", "this", "that", "app"}


# Spoken names that don't match the desktop entry ("VS Code" is "Visual Studio Code", binary "code").
_ALIASES = {"vs code": "code", "vscode": "code", "visual studio": "code", "file manager": "files",
            "web browser": "firefox", "browser": "firefox"}


class AppScanner:
    def __init__(self, system: Optional[OSInterface] = None):
        self._system = system
        self.apps: Dict[str, AppEntry] = {}
        self.scan_installed_apps()

    @property
    def system(self) -> OSInterface:
        return getattr(self, "_system", None) or get_os()

    def scan_installed_apps(self):
        """Index this OS's installed apps by lowercase name and id (the first app with a name wins)."""
        self.apps.clear()
        for entry in self.system.installed_apps():
            self.apps.setdefault(entry.name.lower(), entry)
            if entry.app_id:
                self.apps[entry.app_id.lower()] = entry

    def get_installed_apps_manifest(self) -> List[Dict[str, Any]]:
        """
        Returns list of unique installed desktop applications.
        """
        unique = {id(app): app.to_dict() for app in self.apps.values()}
        return list(unique.values())

    def get_prompt_app_summary(self, limit: int = 60) -> str:
        """
        Installed apps for the LLM system prompt: names only (app_launcher matches them exactly),
        since this is sent with every request.
        """
        # Filter out background system entries
        ignore_keywords = ("helper", "portal", "mime", "driver", "qt5", "qt6", "setup", "im-config", "ibus", "xdg")
        names = sorted({a["name"] for a in self.get_installed_apps_manifest()
                        if not any(k in a["name"].lower() or k in a["app_id"].lower() for k in ignore_keywords)},
                       key=str.lower)
        shown = ", ".join(names[:limit])
        more = f" (and {len(names) - limit} more)" if len(names) > limit else ""
        return f'Open one with app_launcher, args {{"app_name": "<name as written>"}}: {shown}{more}'

    def launch_command_for(self, name: str) -> str:
        """Start something by name that isn't an installed app entry (a macro step like "firefox")."""
        return self.system.launch_command(AppEntry("", name, name, [], name))

    @staticmethod
    def clean_app_query(query: str) -> str:
        """
        Reduce a spoken app request to the app's name: "up Figma, the design website?" -> "figma",
        "my camera app" -> "camera", "DoomTheDarkAges" -> "doom the dark ages".
        """
        q = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(query or "").strip())
        q = re.split(r"[,;:(]|\s+-\s+", q, maxsplit=1)[0]  # drop a trailing description
        q = re.sub(r"[^\w\s.+-]", " ", q).lower()
        q = re.sub(r"\s+(?:for\s+me|please|now|on\s+my\s+(?:computer|pc|desktop)|real\s+quick)\s*$", "", q.strip())
        words = q.split()
        while words and words[0] in _LEAD_WORDS:
            words.pop(0)
        while len(words) > 1 and words[-1] in ("app", "application", "program", "please"):
            words.pop()
        return " ".join(words).strip(" .")

    def find_app(self, query: str) -> Optional[AppEntry]:
        """
        The installed app the query names, or None. Only confident matches: a near-miss like
        "figma" -> "Firmware" is worse than saying the app isn't installed.
        """
        q = self.clean_app_query(query)
        q = _ALIASES.get(q, q)
        if not q:
            return None
        apps = list(dict.fromkeys(self.apps.values()))  # unique entries, scan order

        # 1. Exact name, desktop id, or the id's last part (org.gnome.Snapshot -> snapshot)
        if q in self.apps:
            return self.apps[q]
        for app in apps:
            if (app.app_id and q == app.app_id.lower().rsplit(".", 1)[-1]) or q.replace(" ", "") == app.name.lower().replace(" ", ""):
                return app

        # 2. Binary name
        for app in apps:
            binary = app.binary.lower()
            if binary and binary in (q, q.replace(" ", ""), q.replace(" ", "-")):
                return app

        # 3. Whole words: "code" in "Visual Studio Code", or the app's full name inside the query
        q_pat = re.compile(r"\b" + re.escape(q) + r"\b")
        for app in apps:
            name = re.sub(r"[^\w\s]", " ", app.name.lower())
            if q_pat.search(name) or re.search(r"\b" + re.escape(" ".join(name.split())) + r"\b", q):
                return app

        # 4. A keyword the app declares, as a whole word ("camera" -> Snapshot, "webcam")
        for app in apps:
            if any(q == kw or q_pat.search(kw) for kw in app.keywords):
                return app

        # 5. Token overlap: two or more meaningful words in common ("doom dark ages")
        q_tokens = {t for t in q.split() if len(t) >= 3 and t not in _LEAD_WORDS}
        best, best_overlap = None, 1
        for app in apps:
            app_tokens = {t for t in re.sub(r"[^\w\s]", " ", app.name.lower()).split() if len(t) >= 3}
            overlap = len(q_tokens & app_tokens)
            if overlap > best_overlap:
                best, best_overlap = app, overlap
        if best:
            print(f"[AppScanner] Token match: {sorted(q_tokens)} -> '{best.name}'", flush=True)
            return best

        # 6. Close spelling only ("discrod" -> Discord); strict cutoff keeps "figma" off "Firmware"
        names = {app.name.lower(): app for app in apps}
        close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.8)
        if close:
            return names[close[0]]
        return None

    def resolve_app_launcher_command(self, query: str) -> Tuple[str, str]:
        """
        The launch command and display name for an installed app, or ("", "") when none matches.
        """
        app = self.find_app(query)
        if not app:
            return "", ""
        return self.system.launch_command(app), app.name

    def match_app_launch_intent(self, user_query: str) -> Optional[Tuple[str, str, str]]:
        """
        Checks if user_query is a plain "open X" request for an installed app.
        :return: (launch_command, app_display_name, matched_query) or None
        """
        q = user_query.lower().strip()

        # Skip app launcher fast-path if user query is a mutation/configuration request
        mutation_verbs = ["change", "create", "edit", "modify", "update", "remove", "add", "make", "set up", "how to", "delete"]
        if any(re.search(r"\b" + re.escape(v) + r"\b", q) for v in mutation_verbs):
            return None

        match = re.search(r"^(?:.*?\b)?(?:can\s+you\s+|could\s+you\s+|would\s+you\s+|please\s+)?(?:open|launch|start|run|pull\s+up|bring\s+up)\s+(.+?)[.!?]*$", q)
        if not match:
            return None
        target_q = self.clean_app_query(match.group(1))
        if not target_q or re.search(r"\b(?:mode|timer|playlist|song|music|album)\b", target_q):
            return None  # "start movie mode", "start a timer": not apps

        app = self.find_app(target_q)
        if not app:
            return None
        return self.system.launch_command(app), app.name, target_q

    def close_plan(self, query: str) -> Tuple[Optional[AppEntry], Dict[str, str]]:
        """The app the query names and how the OS should close only it; (None, {}) if none matches."""
        app = self.find_app(query)
        if not app:
            return None, {}
        return app, self.system.close_plan(app)


# Global singleton instance for fast reuse
_global_scanner: Optional[AppScanner] = None

def get_app_scanner() -> AppScanner:
    global _global_scanner
    if _global_scanner is None:
        _global_scanner = AppScanner()
    return _global_scanner


if __name__ == "__main__":
    scanner = AppScanner()
    manifest = scanner.get_installed_apps_manifest()
    print(f"Scanned {len(manifest)} installed applications:")
    for app in manifest[:10]:
        print(" ", app)

    print("\n--- Test Fuzzy App Matcher ---")
    for test in ["chrome", "vs code", "code", "firefox", "terminal", "spotify"]:
        cmd, name = scanner.resolve_app_launcher_command(test)
        print(f" Query '{test}' -> Name: '{name}' | Command: '{cmd}'")
