"""
Linux Installed Desktop Applications Scanner & Fuzzy Matcher (Sub-Task 2.2)
Parses system and user .desktop application entry files (/usr/share/applications, Flatpak, snap)
to build a live manifest of installed apps for accurate voice app launching and STT fuzzy matching.
"""

import os
import re
import glob
import difflib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

DESKTOP_DIRS = [
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications"
]


# Words that come before an app's name in speech, not part of it ("open up the camera").
_LEAD_WORDS = {"up", "the", "my", "a", "an", "me", "to", "on", "open", "launch", "start", "run", "this", "that", "app"}


# Spoken names that don't match the desktop entry ("VS Code" is "Visual Studio Code", binary "code").
_ALIASES = {"vs code": "code", "vscode": "code", "visual studio": "code", "file manager": "files",
            "web browser": "firefox", "browser": "firefox"}


class AppEntry:
    def __init__(self, desktop_path: str, name: str, exec_cmd: str, keywords: List[str], desktop_id: str):
        self.desktop_path = desktop_path
        self.name = name
        self.exec_cmd = exec_cmd
        self.keywords = keywords
        self.desktop_id = desktop_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "desktop_id": self.desktop_id,
            "name": self.name,
            "exec": self.exec_cmd,
            "keywords": self.keywords
        }


class AppScanner:
    def __init__(self):
        self.apps: Dict[str, AppEntry] = {}
        self.scan_installed_apps()

    def scan_installed_apps(self):
        """
        Scans all desktop entry locations and parses metadata.
        """
        self.apps.clear()

        for d in DESKTOP_DIRS:
            if not os.path.exists(d):
                continue
            for filepath in glob.glob(os.path.join(d, "*.desktop")):
                entry = self._parse_desktop_file(filepath)
                if entry and entry.name:
                    # Key by normalized lowercase name and desktop_id
                    key = entry.name.lower()
                    if key not in self.apps:
                        self.apps[key] = entry
                    self.apps[entry.desktop_id.lower()] = entry

    def _parse_desktop_file(self, filepath: str) -> Optional[AppEntry]:
        """
        Parses a .desktop file to extract Name, Exec, Keywords, and NoDisplay.
        """
        name = ""
        exec_cmd = ""
        keywords = []
        no_display = False
        desktop_id = Path(filepath).stem

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                in_main_section = False
                for line in f:
                    line = line.strip()
                    if line == "[Desktop Entry]":
                        in_main_section = True
                        continue
                    elif line.startswith("[") and line.endswith("]"):
                        in_main_section = False

                    if not in_main_section:
                        continue

                    if line.startswith("NoDisplay=true") or line.startswith("Hidden=true"):
                        no_display = True
                    elif line.startswith("Name=") and not name:
                        name = line.split("=", 1)[1].strip()
                    elif line.startswith("Exec=") and not exec_cmd:
                        raw_exec = line.split("=", 1)[1].strip()
                        # Clean field codes (%u, %f, %U, etc.)
                        exec_cmd = re.sub(r"%[a-zA-Z]", "", raw_exec).strip()
                    elif line.startswith("Keywords="):
                        raw_kw = line.split("=", 1)[1].strip()
                        keywords = [k.strip().lower() for k in raw_kw.split(";") if k.strip()]

            if no_display or not name or not exec_cmd:
                return None

            return AppEntry(
                desktop_path=filepath,
                name=name,
                exec_cmd=exec_cmd,
                keywords=keywords,
                desktop_id=desktop_id
            )
        except Exception:
            return None

    def get_installed_apps_manifest(self) -> List[Dict[str, Any]]:
        """
        Returns list of unique installed desktop applications.
        """
        unique = {}
        for app in self.apps.values():
            unique[app.desktop_id] = app.to_dict()
        return list(unique.values())

    def get_prompt_app_summary(self) -> str:
        """
        Returns a compact formatted text manifest of installed apps for the LLM system prompt.
        """
        manifest = self.get_installed_apps_manifest()
        lines = []
        # Filter out background system entries
        ignore_keywords = ("helper", "portal", "mime", "driver", "qt5", "qt6", "setup", "im-config", "ibus", "xdg")
        filtered = [
            a for a in manifest
            if not any(k in a["name"].lower() or k in a["desktop_id"].lower() for k in ignore_keywords)
        ]
        # Sort and cap at top 25 user apps
        for a in sorted(filtered, key=lambda x: x["name"])[:25]:
            name = a["name"]
            desktop_id = a["desktop_id"]
            lines.append(f'- **{name}**: Use tool "app_launcher" with args {{"app_name": "{desktop_id}"}}')
        return "\n".join(lines)

    def _build_launch_cmd(self, desktop_id: str, exec_cmd: str) -> str:
        clean_exec = exec_cmd.strip()
        if desktop_id and clean_exec:
            return f"nohup bash -c \"gtk-launch '{desktop_id}' 2>/dev/null || {clean_exec}\" >/dev/null 2>&1 &"
        elif desktop_id:
            return f"nohup gtk-launch '{desktop_id}' >/dev/null 2>&1 &"
        return f"nohup {clean_exec} >/dev/null 2>&1 &"

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
            if q == app.desktop_id.lower().rsplit(".", 1)[-1] or q.replace(" ", "") == app.name.lower().replace(" ", ""):
                return app

        # 2. Binary name
        for app in apps:
            binary = Path(app.exec_cmd.split()[0]).name.lower() if app.exec_cmd else ""
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
        return self._build_launch_cmd(app.desktop_id, app.exec_cmd), app.name

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
        return self._build_launch_cmd(app.desktop_id, app.exec_cmd), app.name, target_q

    def resolve_app_close_command(self, query: str) -> Tuple[str, str]:
        """
        Resolves a user target app query to a process termination command and display name.
        
        :return: (close_command, app_display_name)
        """
        _, display_name = self.resolve_app_launcher_command(query)
        display_name = display_name or query
        clean_name = self.clean_app_query(query) or query.lower().strip()
        clean_name_no_space = clean_name.replace(" ", "")

        # Process name mapping table for common desktop applications
        proc_map = {
            "steam": "steam",
            "spotify": "spotify",
            "discord": "discord",
            "firefox": "firefox",
            "chrome": "chrome",
            "chromium": "chromium",
            "brave": "brave",
            "code": "code",
            "vscode": "code",
            "visualstudiocode": "code",
            "slack": "slack",
            "terminal": "ptyxis",
            "calculator": "gnome-calculator",
            "vlc": "vlc"
        }

        proc_target = proc_map.get(clean_name_no_space, clean_name_no_space)
        close_cmd = f"pkill -i -f '{proc_target}' || killall -i '{proc_target}' || flatpak kill '{proc_target}' 2>/dev/null"
        return close_cmd, display_name



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
