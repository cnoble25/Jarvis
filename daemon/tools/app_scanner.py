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

    def resolve_app_launcher_command(self, query: str) -> Tuple[str, str]:
        """
        Fuzzy matches a user spoken query (e.g. "VS Code", "Doom The Dark Ages", "DoomTheDarkAges", "Discord")
        against installed apps and returns the exact executable launch command and display name.
        
        :return: (launch_command, app_display_name)
        """
        import re

        # 0. Un-camelCase and clean query string
        normalized_q = re.sub(r'([a-z])([A-Z])', r'\1 \2', query.strip())
        normalized_q = re.sub(r'[^\w\s]', ' ', normalized_q)
        clean_q = normalized_q.lower().strip()

        if not clean_q:
            return f"nohup gtk-launch '{query}' >/dev/null 2>&1 &", query

        # 1. Exact match by desktop_id or lowercase name
        if clean_q in self.apps:
            app = self.apps[clean_q]
            return self._build_launch_cmd(app.desktop_id, app.exec_cmd), app.name

        # 2. Match binary name
        for app in self.apps.values():
            binary = app.exec_cmd.split()[0].lower() if app.exec_cmd else ""
            if binary == clean_q or Path(binary).name == clean_q:
                return self._build_launch_cmd(app.desktop_id, app.exec_cmd), app.name

        # 3. Substring / Keyword match
        for app in self.apps.values():
            if clean_q in app.name.lower() or any(clean_q in kw for kw in app.keywords):
                return self._build_launch_cmd(app.desktop_id, app.exec_cmd), app.name

        # 4. Token Intersection Match (e.g. "doom that arc ages" or "doom dark ages" -> "DOOM: The Dark Ages")
        q_tokens = set(t for t in clean_q.split() if len(t) >= 3 and t not in ("open", "launch", "start", "run", "the", "that", "this"))
        if q_tokens:
            best_token_app = None
            best_overlap_count = 0
            for app in self.apps.values():
                app_name_clean = re.sub(r'[^\w\s]', ' ', app.name.lower())
                app_tokens = set(t for t in app_name_clean.split() if len(t) >= 3)
                overlap = len(q_tokens.intersection(app_tokens))
                if overlap >= 2 and overlap > best_overlap_count:
                    best_overlap_count = overlap
                    best_token_app = app
            if best_token_app:
                print(f"[AppScanner] Token match found: query tokens {q_tokens} -> app '{best_token_app.name}'", flush=True)
                return self._build_launch_cmd(best_token_app.desktop_id, best_token_app.exec_cmd), best_token_app.name

        # 5. Fuzzy string matching fallback
        names = [app.name for app in self.apps.values()]
        ids = [app.desktop_id for app in self.apps.values()]
        all_candidates = names + ids

        matches = difflib.get_close_matches(clean_q, all_candidates, n=1, cutoff=0.4)
        if matches:
            best_match_str = matches[0]
            for app in self.apps.values():
                if app.name == best_match_str or app.desktop_id == best_match_str:
                    return self._build_launch_cmd(app.desktop_id, app.exec_cmd), app.name

        # Fallback to direct gtk-launch / shell launch
        return self._build_launch_cmd(query, query), query

    def match_app_launch_intent(self, user_query: str) -> Optional[Tuple[str, str, str]]:
        """
        Checks if user_query contains an app launching verb (open, launch, start, run)
        and matches an installed system application.
        :return: (launch_command, app_display_name, matched_query) or None
        """
        import re
        q = user_query.lower().strip()

        # Skip app launcher fast-path if user query is a mutation/configuration request
        mutation_verbs = ["change", "create", "edit", "modify", "update", "remove", "add", "make", "set up", "how to", "delete"]
        if any(re.search(r"\b" + re.escape(v) + r"\b", q) for v in mutation_verbs):
            return None

        match = re.search(r'(?:can\s+you\s+|could\s+you\s+|would\s+you\s+|please\s+)?(?:open|launch|start|run)\s+(.+?)(?:\s+for\s+me|\s+please|[.!])?$', q)
        if not match:
            return None

        target_q = match.group(1).strip().rstrip('.!')
        if not target_q:
            return None

        # Resolve via scanner
        cmd, display_name = self.resolve_app_launcher_command(target_q)
        
        # Verify if display_name matched an actual app entry in system
        target_tokens = set(re.sub(r'[^\w\s]', ' ', target_q).split())
        for app in self.apps.values():
            app_name_lower = app.name.lower()
            desktop_id_lower = app.desktop_id.lower()
            binary_lower = app.exec_cmd.split()[0].lower() if app.exec_cmd else ""
            
            if (app.name == display_name or 
                app_name_lower in target_q or 
                target_q in app_name_lower or
                desktop_id_lower in target_q or
                binary_lower == target_q or
                any(t in app_name_lower for t in target_tokens if len(t) >= 3)):
                return cmd, display_name, target_q

        return None

    def resolve_app_close_command(self, query: str) -> Tuple[str, str]:
        """
        Resolves a user target app query to a process termination command and display name.
        
        :return: (close_command, app_display_name)
        """
        _, display_name = self.resolve_app_launcher_command(query)
        clean_name = query.lower().strip()
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
