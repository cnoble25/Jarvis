"""
Jarvis Macro Engine & Custom Workspaces Manager
Handles creation, compilation of standalone bash scripts (~/.config/jarvis/macros/*.sh),
FastPath rule synchronization (<1ms execution), supporting arbitrary bash commands & app steps.
"""

import os
import json
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from daemon.agent.fast_path_manager import FastPathManager, get_fast_path_manager

MACRO_DIR = Path(os.path.expanduser("~/.config/jarvis/macros"))


class MacroManager:
    def __init__(self, macro_dir: Optional[Path] = None, fast_path_mgr: Optional[FastPathManager] = None):
        self.macro_dir = macro_dir or MACRO_DIR
        os.makedirs(self.macro_dir, exist_ok=True)
        self.fast_path_mgr = fast_path_mgr or get_fast_path_manager()
        self.reload_and_sync()

    def _normalize_id(self, name: str) -> str:
        """
        Converts human macro name into a clean ID slug (e.g. 'Gaming Mode' -> 'gaming_mode').
        """
        clean = re.sub(r'[^a-zA-Z0-9_\s-]', '', name.strip().lower())
        return clean.replace(' ', '_').replace('-', '_')

    def _compile_sh_script(self, macro_id: str, steps: List[str], directory: Optional[str] = None) -> Path:
        """
        Compiles a list of steps (apps, bash commands, shell actions) into an executable bash script under ~/.config/jarvis/macros/<id>.sh.
        """
        sh_path = self.macro_dir / f"{macro_id}.sh"
        from daemon.tools.app_scanner import get_app_scanner
        scanner = get_app_scanner()

        lines = [
            "#!/bin/bash",
            f"# Jarvis Auto-Generated Macro Script: '{macro_id}'",
            "# Created automatically by Jarvis Macro Engine",
            ""
        ]

        # Working directory change if provided
        if directory:
            clean_dir = os.path.expanduser(directory)
            lines.append("# Set Working Directory")
            lines.append(f"cd '{clean_dir}' || exit 1")
            lines.append("")

        lines.append("# Execute Macro Steps & Commands")
        for step in steps:
            step_clean = step.strip()
            if not step_clean:
                continue

            # Check if step contains shell operators (redirects, flags, pipes, arguments, locked-in commands)
            has_shell_syntax = any(char in step_clean for char in [" ", ">", "<", "|", "&", ";", "-"])

            if "terminal" in step_clean.lower() and directory:
                clean_dir = os.path.expanduser(directory)
                lines.append(f"# Launch Terminal in {clean_dir}")
                lines.append(f"alacritty --working-directory '{clean_dir}' &")
            elif has_shell_syntax:
                # Raw bash command (e.g. 'locked-in start -d 2h', 'wpctl set-volume @DEFAULT_AUDIO_SINK@ 80%')
                lines.append(f"# Shell Command: {step_clean}")
                if step_clean.endswith("&") or ";" in step_clean or "locked-in" in step_clean or "wpctl" in step_clean:
                    lines.append(f"{step_clean}")
                else:
                    lines.append(f"{step_clean} &")
            else:
                # Simple app binary name (e.g. 'firefox', 'spotify', 'steam', 'discord')
                cmd, display_name = scanner.resolve_app_launcher_command(step_clean)
                lines.append(f"# Launch App: {display_name}")
                lines.append(f"{cmd}")

        lines.append("")
        lines.append("# End of Macro Execution")

        with open(sh_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        # Make script executable (chmod +x)
        try:
            os.chmod(sh_path, 0o755)
        except Exception:
            pass
        print(f"[MacroManager] Compiled executable script -> {sh_path}", flush=True)
        return sh_path

    def save_macro(self, name: str, steps: List[str], directory: Optional[str] = None, spoken_summary: Optional[str] = None) -> Dict[str, Any]:
        """
        Saves a macro specification to JSON, compiles its bash script, and syncs FastPath rules.
        """
        macro_id = self._normalize_id(name)
        json_path = self.macro_dir / f"{macro_id}.json"

        # Deduplicate steps list preserving order
        unique_steps = []
        for s in steps:
            s_clean = s.strip()
            if s_clean and s_clean not in unique_steps:
                unique_steps.append(s_clean)

        sh_path = self._compile_sh_script(macro_id, unique_steps, directory)

        spec = {
            "id": macro_id,
            "name": name.strip(),
            "steps": unique_steps,
            "apps": unique_steps,  # Backward compatibility field
            "directory": directory or "",
            "script_path": str(sh_path),
            "spoken_summary": spoken_summary or f"Activated {name.strip()}."
        }

        # Clean up alternate ID file naming variants (e.g. gaming-mode vs gaming_mode)
        for f in self.macro_dir.glob("*.json"):
            if f.name != f"{macro_id}.json" and self._normalize_id(f.stem) == macro_id:
                try:
                    os.remove(f)
                    sh_alt = self.macro_dir / f"{f.stem}.sh"
                    if sh_alt.exists():
                        os.remove(sh_alt)
                except Exception:
                    pass

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)

        # Register Fast-Path triggers (<1ms voice execution)
        display_name = name.strip().replace("_", " ").lower()
        triggers = [
            f"start {display_name}",
            f"{display_name}",
            f"launch {display_name}",
            f"activate {display_name}",
            f"start up {display_name}"
        ]

        self.fast_path_mgr.add_learned_rule(
            triggers=triggers,
            action_type="tool",
            tool="execute_terminal_command",
            args={
                "command": str(sh_path),
                "explanation": f"Activated {name.strip()} macro."
            },
            spoken_summary=f"Activated {name.strip()}."
        )
        print(f"[MacroManager] Saved macro '{macro_id}' with {len(unique_steps)} steps and registered 5 fast-path rules.", flush=True)
        return spec

    def get_macro(self, name: str) -> Optional[Dict[str, Any]]:
        macro_id = self._normalize_id(name)
        json_path = self.macro_dir / f"{macro_id}.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "steps" not in data and "apps" in data:
                        data["steps"] = data["apps"]
                    return data
            except Exception as e:
                print(f"[MacroManager Error] Failed reading macro {json_path}: {e}", flush=True)
        return None

    def list_macros(self) -> Dict[str, Dict[str, Any]]:
        """
        Lists all installed user macros. Automatically resolves and purges duplicate/stale files.
        """
        macros = {}
        file_map = {}

        for f in self.macro_dir.glob("*.json"):
            try:
                mtime = f.stat().st_mtime
                with open(f, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    if "steps" not in data and "apps" in data:
                        data["steps"] = data["apps"]
                    
                    norm_id = self._normalize_id(data.get("name", data.get("id", f.stem)))
                    data["id"] = norm_id

                    if norm_id in file_map:
                        old_file, old_mtime = file_map[norm_id]
                        if mtime > old_mtime:
                            # Current file is newer; delete old stale file
                            try:
                                os.remove(old_file)
                                old_sh = self.macro_dir / f"{old_file.stem}.sh"
                                if old_sh.exists():
                                    os.remove(old_sh)
                            except Exception:
                                pass
                            file_map[norm_id] = (f, mtime)
                            macros[norm_id] = data
                        else:
                            # Current file is older duplicate; delete it
                            try:
                                os.remove(f)
                                sh_f = self.macro_dir / f"{f.stem}.sh"
                                if sh_f.exists():
                                    os.remove(sh_f)
                            except Exception:
                                pass
                    else:
                        file_map[norm_id] = (f, mtime)
                        macros[norm_id] = data
            except Exception:
                pass
        return macros

    def add_step(self, name: str, step: str) -> Optional[Dict[str, Any]]:
        macro = self.get_macro(name)
        if not macro:
            return self.save_macro(name, [step])

        steps = macro.get("steps", macro.get("apps", []))
        if step.strip() not in steps:
            steps.append(step.strip())
        return self.save_macro(macro["name"], steps, macro.get("directory"))

    def remove_step(self, name: str, step: str) -> Optional[Dict[str, Any]]:
        macro = self.get_macro(name)
        if not macro:
            return None

        steps = [s for s in macro.get("steps", macro.get("apps", [])) if s.lower() != step.strip().lower()]
        return self.save_macro(macro["name"], steps, macro.get("directory"))

    def delete_macro(self, name: str) -> bool:
        macro_id = self._normalize_id(name)
        json_path = self.macro_dir / f"{macro_id}.json"
        sh_path = self.macro_dir / f"{macro_id}.sh"

        deleted = False
        if json_path.exists():
            os.remove(json_path)
            deleted = True
        if sh_path.exists():
            os.remove(sh_path)
            deleted = True

        print(f"[MacroManager] Deleted macro '{macro_id}'", flush=True)
        return deleted

    def run_macro(self, name: str) -> Dict[str, Any]:
        macro = self.get_macro(name)
        if not macro:
            return {"success": False, "stderr": f"Macro '{name}' not found."}

        sh_path = macro.get("script_path") or str(self.macro_dir / f"{macro['id']}.sh")
        if not os.path.exists(sh_path):
            self._compile_sh_script(macro["id"], macro.get("steps", macro.get("apps", [])), macro.get("directory"))

        print(f"[MacroManager] Running macro '{macro['id']}' script -> {sh_path}", flush=True)
        try:
            p = subprocess.Popen(
                ["bash", sh_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            spoken = macro.get("spoken_summary") or f"Activated {macro['name']}."
            return {
                "success": True,
                "exit_code": 0,
                "stdout": f"Spawned macro process PID {p.pid}",
                "stderr": "",
                "spoken_confirmation": spoken
            }
        except Exception as e:
            return {"success": False, "stderr": f"Failed running macro script: {e}"}

    def reload_and_sync(self):
        """
        Recompiles scripts and registers fast-path rules for all saved macros.
        """
        for macro_id, spec in self.list_macros().items():
            sh_path = self.macro_dir / f"{macro_id}.sh"
            steps = spec.get("steps", spec.get("apps", []))
            if not sh_path.exists():
                self._compile_sh_script(macro_id, steps, spec.get("directory"))


# Global singleton instance
_macro_manager_instance: Optional[MacroManager] = None

def get_macro_manager() -> MacroManager:
    global _macro_manager_instance
    if _macro_manager_instance is None:
        _macro_manager_instance = MacroManager()
    return _macro_manager_instance
