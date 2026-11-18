"""
Core Meta-Tools Execution Engine (Sub-Task 2.2)
Implements Claude Code Meta-Tools (Bash, View, Edit, Grep, ManageTools)
and executes custom JSON tool templates safely.
"""

import os
import signal
import subprocess
import re
import threading
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional
from .registry import ToolRegistry, ToolManifest


class ExecutionEngine:
    def __init__(self, registry: Optional[ToolRegistry] = None, dry_run: bool = False):
        """
        Initialize ExecutionEngine with a ToolRegistry instance.
        """
        self.registry = registry if registry is not None else ToolRegistry()
        self.dry_run = dry_run
        # Per-thread run context: a background task sets a cancel event and a longer command timeout
        # for its own thread without affecting a voice request running at the same time.
        self._local = threading.local()

    TERMINAL_TIMEOUT = 20  # seconds, for a terminal command run while the user waits

    def set_run_context(self, cancel_event: Optional[threading.Event] = None, command_timeout: Optional[int] = None):
        self._local.cancel = cancel_event
        self._local.command_timeout = command_timeout

    def _run_cancellable(self, command: str, cwd: Optional[str], timeout: int) -> Dict[str, Any]:
        """Run a shell command in its own process group; stop it on timeout or when the task is cancelled."""
        cancel = getattr(self._local, "cancel", None)
        proc = subprocess.Popen(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, start_new_session=True)
        deadline = time.monotonic() + timeout
        while True:
            try:
                out, err = proc.communicate(timeout=0.25)
                return {"success": proc.returncode == 0, "exit_code": proc.returncode,
                        "stdout": out.strip(), "stderr": err.strip(),
                        "spoken_confirmation": f"Executed command: {command[:40]}..."}
            except subprocess.TimeoutExpired:
                cancelled = bool(cancel and cancel.is_set())
                if not cancelled and time.monotonic() < deadline:
                    continue
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(proc.pid, sig)
                    except ProcessLookupError:
                        break
                    try:
                        proc.communicate(timeout=3)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if cancelled:
                    return {"success": False, "exit_code": 130, "stdout": "", "stderr": "Cancelled.", "cancelled": True}
                return {"success": False, "exit_code": 124, "stdout": "", "stderr": f"Command timed out after {timeout} seconds."}

    def execute_bash(self, command: str, cwd: Optional[str] = None, timeout: Optional[int] = None) -> Dict[str, Any]:

        """
        Executes a shell command (Claude Code 'Bash' meta-tool).
        
        :param command: Shell command string to execute.
        :param cwd: Working directory (defaults to current working dir).
        :param timeout: Command timeout in seconds.
        :return: Result dict with success, exit_code, stdout, stderr.
        """
        if not command or not command.strip():
            return {"success": False, "exit_code": 1, "stdout": "", "stderr": "Empty command provided."}
        timeout = timeout or getattr(self._local, "command_timeout", None) or 30

        print(f"[ExecutionEngine.Bash] Executing: {command}", flush=True)
        # For background process launching (commands ending with '&'),
        # spawn detached Popen to prevent EPIPE broken pipe errors in Electron/GUI apps
        if command.strip().endswith("&"):
            try:
                p = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True
                )
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": f"Spawned background process PID {p.pid}",
                    "stderr": "",
                    "spoken_confirmation": f"Launched background application process."
                }
            except Exception as e:
                return {"success": False, "exit_code": 1, "stdout": "", "stderr": str(e)}

        try:
            return self._run_cancellable(command, cwd, timeout)
        except Exception as e:
            return {"success": False, "exit_code": 1, "stdout": "", "stderr": str(e)}

    def execute_view(self, path: str, max_lines: int = 200) -> Dict[str, Any]:
        """
        Reads and inspects file contents (Claude Code 'View' meta-tool).
        """
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return {"success": False, "stdout": "", "stderr": f"File not found: {path}"}

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(max_lines)]
                content = "".join(lines)
            
            return {
                "success": True,
                "stdout": content,
                "stderr": "",
                "spoken_confirmation": f"Inspected file {os.path.basename(path)}."
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e)}

    def execute_edit(self, path: str, content: str) -> Dict[str, Any]:
        """
        Creates or overwrites a file with content (Claude Code 'Edit' meta-tool).
        """
        path = os.path.expanduser(path)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            
            return {
                "success": True,
                "stdout": f"Wrote {len(content)} characters to {path}",
                "stderr": "",
                "spoken_confirmation": f"Updated file {os.path.basename(path)}."
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e)}

    def execute_grep(self, pattern: str, search_path: str = ".") -> Dict[str, Any]:
        """
        Searches for a text pattern in files (Claude Code 'Grep' meta-tool).
        """
        search_path = os.path.expanduser(search_path)
        cmd = f"grep -rnI '{pattern}' '{search_path}' | head -n 50"
        return self.execute_bash(cmd)

    def execute_manage_tools(self, action: str, manifest: Optional[Dict[str, Any]] = None, tool_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Manages custom JSON tool manifests (Claude Code 'ManageTools' meta-tool).
        
        :param action: 'register', 'unregister', 'list', or 'get'.
        :param manifest: Manifest dictionary for 'register'.
        :param tool_id: Tool ID string for 'unregister' or 'get'.
        """
        action = action.lower().strip()
        if action == "register" and manifest:
            try:
                reg_manifest = self.registry.register_tool(manifest)
                return {"success": True, "stdout": f"Registered tool '{reg_manifest.id}'", "stderr": "", "spoken_confirmation": f"Registered new tool {reg_manifest.name}."}
            except Exception as e:
                return {"success": False, "stdout": "", "stderr": f"Failed to register tool: {e}"}
        
        elif action == "unregister" and tool_id:
            success = self.registry.unregister_tool(tool_id)
            return {"success": success, "stdout": f"Unregistered '{tool_id}'" if success else "", "stderr": f"Tool '{tool_id}' not found." if not success else ""}
        
        elif action == "list":
            tools = [t.model_dump() for t in self.registry.list_tools()]
            return {"success": True, "stdout": str(tools), "stderr": "", "spoken_confirmation": f"There are {len(tools)} custom tools installed."}
        
        return {"success": False, "stdout": "", "stderr": "Invalid ManageTools action or parameters."}

    def execute_web_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Performs live web search using DDGS and returns text result snippets for LLM information gathering.
        """
        query = query.strip()
        if not query:
            return {"success": False, "stdout": "", "stderr": "Empty search query provided."}

        print(f"[ExecutionEngine.WebSearch] Searching web for: '{query}'", flush=True)

        try:
            from ddgs import DDGS
            results = list(DDGS().text(query, max_results=max_results))
            snippets = []
            for i, r in enumerate(results):
                title = r.get("title", "")
                snippet = r.get("body", "")
                href = r.get("href", "")
                snippets.append(f"Result {i+1}: {title} - {snippet} (URL: {href})")

            if snippets:
                output_text = f"Web Search Results for '{query}':\n" + "\n".join(snippets)
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": output_text,
                    "stderr": "",
                    "spoken_confirmation": f"Searched web for {query}."
                }
        except Exception as e:
            print(f"[ExecutionEngine.WebSearch Warning] DDGS search failed ({e}), attempting fallback...", flush=True)

        try:
            encoded = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            snippets = []
            results = re.findall(r'<a class="result__snippet[^">]*">(.*?)</a>', html, re.DOTALL)
            titles = re.findall(r'<a class="result__url[^">]*">(.*?)</a>', html, re.DOTALL)

            for i in range(min(len(results), max_results)):
                clean_snippet = re.sub(r'<[^>]+>', '', results[i]).strip()
                clean_url = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else ""
                clean_snippet = clean_snippet.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                snippets.append(f"Result {i+1}: {clean_snippet} (URL: {clean_url})")

            if snippets:
                output_text = f"Web Search Results for '{query}':\n" + "\n".join(snippets)
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": output_text,
                    "stderr": "",
                    "spoken_confirmation": f"Searched web for {query}."
                }
        except Exception:
            pass

        return {"success": False, "exit_code": 1, "stdout": "", "stderr": f"Failed to execute web search for '{query}'"}

    def execute_custom_tool(self, tool_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a custom tool from the JSON ToolRegistry by interpolating arguments.
        Integrates AppScanner fuzzy matching for app_launcher.
        
        :param tool_id: ID of the custom tool (e.g. 'app_launcher', 'set_timer').
        :param args: Dictionary of argument key-values to interpolate into template.
        """
        if tool_id == "macro_control":
            action = args.get("action", "run").lower().strip()
            macro_name = args.get("macro_name", "").strip()
            steps = args.get("steps") or args.get("apps") or []
            single_step = args.get("step", "").strip()
            directory = args.get("directory", "").strip()

            from daemon.macros.macro_manager import get_macro_manager
            mgr = get_macro_manager()

            if action == "run":
                return mgr.run_macro(macro_name)
            elif action in ["create", "save"]:
                if single_step and single_step not in steps:
                    steps.append(single_step)
                spec = mgr.save_macro(macro_name, steps, directory=directory)
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": f"Saved macro '{spec['name']}' with {len(spec['steps'])} steps.",
                    "stderr": "",
                    "spoken_confirmation": f"Created macro mode {spec['name']}."
                }
            elif action in ["add_step", "add", "add_app"]:
                step_to_add = single_step or (steps[0] if steps else "")
                spec = mgr.add_step(macro_name, step_to_add)
                return {
                    "success": True if spec else False,
                    "exit_code": 0 if spec else 1,
                    "stdout": f"Updated macro '{macro_name}' steps: {spec.get('steps')}" if spec else "Macro not found.",
                    "stderr": "",
                    "spoken_confirmation": f"Added {step_to_add} to {macro_name} mode."
                }
            elif action in ["remove_step", "remove", "remove_app"]:
                step_to_rem = single_step or (steps[0] if steps else "")
                spec = mgr.remove_step(macro_name, step_to_rem)
                return {
                    "success": True if spec else False,
                    "exit_code": 0 if spec else 1,
                    "stdout": f"Updated macro '{macro_name}' steps: {spec.get('steps')}" if spec else "Macro not found.",
                    "stderr": "",
                    "spoken_confirmation": f"Removed {step_to_rem} from {macro_name} mode."
                }
            elif action == "delete":
                deleted = mgr.delete_macro(macro_name)
                return {
                    "success": deleted,
                    "exit_code": 0 if deleted else 1,
                    "stdout": f"Deleted macro '{macro_name}'" if deleted else "Macro not found.",
                    "stderr": "",
                    "spoken_confirmation": f"Deleted macro {macro_name}."
                }
            elif action == "list":
                macros = mgr.list_macros()
                summary_list = [f"{m['name']}: {m.get('steps', [])}" for m in macros.values()]
                return {
                    "success": True,
                    "exit_code": 0,
                    "stdout": str(summary_list),
                    "stderr": "",
                    "spoken_confirmation": f"You have {len(macros)} custom macro modes defined."
                }

        if tool_id == "web_search":
            query = args.get("query", "").strip()
            return self.execute_web_search(query)

        if tool_id == "execute_terminal_command":
            cmd = args.get("command", "").strip()
            explanation = args.get("explanation", "").strip()
            if not cmd:
                return {"success": False, "exit_code": 1, "stdout": "", "stderr": "No command provided."}

            # Safety blacklist filter for dangerous commands
            dangerous_patterns = [r"\brm\s+-rf\s+/", r"\bmkfs\b", r"\bdd\s+if=/dev/zero"]
            for pat in dangerous_patterns:
                if re.search(pat, cmd):
                    return {
                        "success": False,
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "Execution blocked for unsafe command.",
                        "spoken_confirmation": "Blocked unsafe command."
                    }

            print(f"[ExecutionEngine.execute_terminal_command] Running: {cmd}", flush=True)
            res = self.execute_bash(cmd, timeout=getattr(self._local, "command_timeout", None) or self.TERMINAL_TIMEOUT)
            
            if res.get("success"):
                if explanation:
                    res["spoken_confirmation"] = explanation
                else:
                    res["spoken_confirmation"] = f"Executed terminal command successfully."
            else:
                err_msg = res.get("stderr") or "Command execution failed."
                res["spoken_confirmation"] = f"Command failed: {err_msg[:60]}"
            return res

        if tool_id == "get_current_time":
            from datetime import datetime
            now = datetime.now()
            formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")
            iso_str = now.isoformat()
            time_data = f"Current Time: {formatted} (ISO: {iso_str}, Timestamp: {int(now.timestamp())})"
            print(f"[ExecutionEngine.get_current_time] {time_data}", flush=True)
            return {
                "success": True,
                "exit_code": 0,
                "stdout": time_data,
                "stderr": "",
                "spoken_confirmation": f"It is currently {now.strftime('%I:%M %p on %A, %B %d')}."
            }

        if tool_id == "locked_in_mode":
            action = args.get("action", "status").lower().strip()
            name = args.get("name") or args.get("profile", "")
            if isinstance(name, str):
                name = name.strip().lower()

            duration = str(args.get("duration", "")).strip()
            app = str(args.get("app", "")).strip()
            domain = str(args.get("domain", "")).strip()

            apps = args.get("apps", [])
            if isinstance(apps, str):
                apps = [apps]

            domains = args.get("domains", [])
            if isinstance(domains, str):
                domains = [domains]

            # Use absolute path to locked-in binary in venv
            cmd_parts = ["/home/carson/Documents/Jarvis/.venv/bin/locked-in", action]

            if action == "create":
                if name:
                    cmd_parts.extend(["--name", name])
                for a in apps:
                    if a:
                        cmd_parts.extend(["--app", str(a)])
                for d in domains:
                    if d:
                        cmd_parts.extend(["--domain", str(d)])
            elif action in ["delete", "remove_profile"]:
                cmd_parts = ["/home/carson/Documents/Jarvis/.venv/bin/locked-in", "delete"]
                if name:
                    cmd_parts.extend(["--name", name])
            elif action == "start":
                if name:
                    cmd_parts.extend(["-n", name])
                if duration:
                    cmd_parts.extend(["-d", duration])
            elif action in ["add", "remove"]:
                if name:
                    cmd_parts.extend(["-n", name])
                if app:
                    cmd_parts.extend(["-a", app])
                if domain:
                    cmd_parts.extend(["-d", domain])

            cmd = " ".join(cmd_parts)
            res = self.execute_bash(cmd)

            if action == "start":
                prof_desc = f"profile '{name}'" if name else "focus mode"
                res["spoken_confirmation"] = f"Locked-in {prof_desc} activated for {duration or 'indefinite duration'}."
            elif action == "create":
                res["spoken_confirmation"] = f"Created locked-in focus profile '{name or 'custom'}'."
            elif action == "delete":
                res["spoken_confirmation"] = f"Deleted locked-in focus profile '{name}'."
            elif action == "list":
                res["spoken_confirmation"] = "Listed all locked-in focus profiles."
            elif action == "stop":
                res["spoken_confirmation"] = "Locked in mode deactivated. Focus restrictions lifted."
            elif action in ["add", "remove"]:
                target = domain or app or "item"
                res["spoken_confirmation"] = f"{action.capitalize()}ed {target} in focus profile '{name or 'active'}'."
            elif action == "status":
                status_output = res.get("stdout", "").strip()
                # Clean CLI emojis for speech synthesis
                clean_speech = status_output.replace("🔒 [Locked-In] ", "").replace("☕ [Locked-In] ", "").replace("⏰ [Locked-In] ", "")
                res["spoken_confirmation"] = clean_speech or "Checked locked-in mode status."
            else:
                res["spoken_confirmation"] = "Checked locked-in mode status."

            return res

        if tool_id == "app_launcher":
            app_query = args.get("app_name", "")
            raw_q = args.get("_raw_user_query", "").lower()
            
            # Safeguard: Prevent app_launcher from over-matching mode queries like "movie mode" to games or apps
            if " mode" in raw_q and ("movie" in raw_q or "work" in raw_q or "focus" in raw_q):
                return {
                    "success": False, 
                    "stdout": "", 
                    "stderr": "Mode query detected; deferring to macro or focus mode provider.",
                    "spoken_confirmation": "Processing mode request."
                }

            from .app_scanner import get_app_scanner
            scanner = get_app_scanner()

            # The model sometimes names a different app than the user did ("Firefox" for "open Discord"):
            # trust the app named in the user's own words when there is one.
            if raw_q and app_query.lower() not in raw_q:
                match = re.search(r'(?:open|launch|start|run|pull\s+up|bring\s+up)\s+(.+)', raw_q)
                if match and scanner.find_app(match.group(1)):
                    print(f"[ExecutionEngine.app_launcher] Using the app from the request ('{match.group(1)}') instead of '{app_query}'", flush=True)
                    app_query = match.group(1)

            cmd, app_display_name = scanner.resolve_app_launcher_command(app_query)
            if not cmd:  # maybe installed since Jarvis started
                scanner.scan_installed_apps()
                cmd, app_display_name = scanner.resolve_app_launcher_command(app_query)
            if not cmd:
                name = scanner.clean_app_query(app_query) or app_query
                print(f"[ExecutionEngine.app_launcher] No installed app matches '{app_query}'.", flush=True)
                return {
                    "success": False,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"No installed app matches '{name}'. If it's a website, open its URL with "
                              f"execute_terminal_command (xdg-open https://...).",
                    "spoken_confirmation": f"I couldn't find an app called {name} on this computer.",
                }
            print(f"[ExecutionEngine.app_launcher] Matched '{app_query}' -> '{app_display_name}' ({cmd})", flush=True)
            res = self.execute_bash(cmd)
            res["spoken_confirmation"] = f"Opened {app_display_name}."
            return res


        if tool_id == "close_app":
            app_query = args.get("app_name") or args.get("app") or args.get("name", "").strip()
            raw_q = args.get("_raw_user_query", "").lower()
            from .app_scanner import get_app_scanner
            scanner = get_app_scanner()

            if not app_query and raw_q:
                match = re.search(r'(?:close|quit|exit|stop|kill)\s+(.+)', raw_q)
                if match:
                    app_query = match.group(1).strip().rstrip('.!')

            close_cmd, app_display_name = scanner.resolve_app_close_command(app_query or "steam")
            print(f"[ExecutionEngine.close_app] Closing app query '{app_query}' -> '{app_display_name}' ({close_cmd})", flush=True)
            res = self.execute_bash(close_cmd)
            res["spoken_confirmation"] = f"Closed {app_display_name}."
            return res


        if tool_id == "system_power_control":
            action = args.get("action", "shutdown").lower().strip()
            raw_q = args.get("_raw_user_query", "").lower()

            if "restart" in raw_q or "reboot" in raw_q:
                action = "reboot"
            elif "shutdown" in raw_q or "power off" in raw_q or "turn off" in raw_q:
                action = "shutdown"
            elif "suspend" in raw_q or "sleep" in raw_q:
                action = "suspend"
            elif "lock" in raw_q:
                action = "lock"

            if action in ["shutdown", "poweroff", "power_off", "turn_off"]:
                cmd = "systemctl poweroff || loginctl poweroff || shutdown -h now"
                spoken = "Shutting down your computer."
            elif action in ["reboot", "restart"]:
                cmd = "systemctl reboot || loginctl reboot || shutdown -r now"
                spoken = "Rebooting your computer."
            elif action in ["suspend", "sleep"]:
                cmd = "systemctl suspend || loginctl suspend"
                spoken = "Putting your computer to sleep."
            else:
                cmd = "loginctl lock-session || kscreenlocker_greet || xdg-screensaver lock"
                spoken = "Locking your computer screen."

            if self.dry_run or args.get("_dry_run"):
                print(f"[ExecutionEngine.system_power_control DRY RUN] Simulated command: {cmd}", flush=True)
                return {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "spoken_confirmation": spoken, "cmd": cmd}

            res = self.execute_bash(cmd)
            res["spoken_confirmation"] = spoken
            return res


        if tool_id == "media_play_pause":
            action = args.get("action", "").lower().strip()
            player = args.get("player", "").lower().strip()

            raw_query = args.get("_raw_user_query", "").lower().strip()
            if not action:
                if any(w in raw_query for w in ["play", "resume", "unpause", "start"]):
                    action = "play"
                elif any(w in raw_query for w in ["pause", "stop"]):
                    action = "pause"
                else:
                    action = "toggle"

            if not player:
                if any(w in raw_query for w in ["music", "song", "track", "spotify"]):
                    player = "spotify"
                elif any(w in raw_query for w in ["video", "youtube", "firefox", "browser"]):
                    player = "youtube"
            
            mpris_players = []
            try:
                out = subprocess.run(["busctl", "--user", "list"], capture_output=True, text=True).stdout
                for line in out.split("\n"):
                    if "org.mpris.MediaPlayer2" in line:
                        parts = line.split()
                        if parts:
                            mpris_players.append(parts[0])
            except Exception:
                pass

            target_players = []
            if player:
                browser_keywords = ["firefox", "chrome", "chromium", "brave", "youtube", "zen", "vivaldi", "opera", "edge"]
                kw_targets = browser_keywords if player in ("youtube", "video", "browser", "firefox", "chrome") else [player]
                for p in mpris_players:
                    p_lower = p.lower()
                    if any(t in p_lower for t in kw_targets):
                        target_players.append(p)
            
            # Prefer specific active player (e.g. Spotify or Firefox) rather than blasting all players simultaneously
            if not target_players and mpris_players:
                spotify_p = [p for p in mpris_players if "spotify" in p.lower()]
                firefox_p = [p for p in mpris_players if "firefox" in p.lower() or "chrome" in p.lower()]
                if spotify_p:
                    target_players = spotify_p
                elif firefox_p:
                    target_players = firefox_p
                else:
                    target_players = [mpris_players[0]]

            method_map = {
                "play": "Play",
                "pause": "Pause",
                "stop": "Pause",
                "toggle": "PlayPause",
                "play-pause": "PlayPause",
                "next": "Next",
                "previous": "Previous"
            }
            method_name = method_map.get(action, "PlayPause")

            executed = []
            for target in target_players:
                cmd = ["busctl", "--user", "call", target, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method_name]
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode == 0:
                    executed.append(target)

            if not executed:
                subprocess.run(["xdotool", "key", "XF86AudioPlay"], capture_output=True)
                if method_name == "Play":
                    spoken = "Resumed media playback."
                elif method_name == "Pause":
                    spoken = "Paused media playback."
                else:
                    spoken = "Toggled media playback."
            else:
                display_p = player.title() if player else "media"
                action_word = "Paused" if method_name == "Pause" else ("Resumed" if method_name == "Play" else "Toggled")
                spoken = f"{action_word} {display_p} playback."

            return {
                "success": True,
                "stdout": f"Executed {method_name} on {executed}",
                "stderr": "",
                "spoken_confirmation": spoken
            }

        if tool_id == "update_memory_profile":
            key = args.get("key", "").strip()
            value = args.get("value", "").strip()
            fact_statement = args.get("fact", "").strip()

            from daemon.memory.profiler_agent import load_user_profile, PROFILE_PATH
            content = load_user_profile(PROFILE_PATH)
            if not content:
                content = (
                    "# User Profile & Personal Preferences\n\n"
                    "## Technical Environment & Tools\n"
                    "- Operating System: Linux Bazzite\n"
                    "- Preferred IDE / Editors: VS Code\n"
                    "- Primary Programming Languages & Stacks: Python, HTML/CSS, JS\n\n"
                    "## Frequent Projects & Paths\n"
                    "- Active Project: Jarvis AI Agent (~/Documents/Jarvis)\n\n"
                    "## Personalization & Spoken Response Preferences\n"
                    "- Response Length: 1 sentence max\n"
                    "- Preferred Voice: af_kore (Kokoro-ONNX)\n"
                )

            updated_lines = []
            updated = False

            if key and value:
                for line in content.split("\n"):
                    if key.lower() in line.lower() and ":" in line and line.strip().startswith("-"):
                        prefix = line.split(":", 1)[0]
                        updated_lines.append(f"{prefix}: {value}")
                        updated = True
                    else:
                        updated_lines.append(line)
                if not updated:
                    updated_lines.append(f"- {key}: {value}")

                new_md = "\n".join(updated_lines)
                spoken = f"Updated your memory profile: {key} set to {value}."
            elif fact_statement:
                new_md = content + f"\n- Fact: {fact_statement}"
                spoken = f"Added to your memory profile: {fact_statement}."
            else:
                return {"success": False, "stdout": "", "stderr": "No key, value, or fact provided to update memory profile."}

            try:
                with open(PROFILE_PATH, "w", encoding="utf-8") as f:
                    f.write(new_md.strip() + "\n")
                print(f"[ExecutionEngine.update_memory_profile] Successfully wrote updated profile to {PROFILE_PATH}", flush=True)
                return {
                    "success": True,
                    "stdout": new_md,
                    "stderr": "",
                    "spoken_confirmation": spoken
                }
            except Exception as e:
                return {"success": False, "stdout": "", "stderr": f"Failed updating memory profile: {e}"}

        tool: Optional[ToolManifest] = self.registry.get_tool(tool_id)
        if not tool:
            return {"success": False, "stdout": "", "stderr": f"Custom tool '{tool_id}' not found in registry."}

        template = tool.execution.template
        
        # Interpolate template string: e.g., "gtk-launch '{app_name}'" -> "gtk-launch 'code'".
        # Values are escaped for the quoting context they land in, so spoken text can never
        # break out of the command ("Don't Stop Me Now", or anything containing ; $ ` " ').
        interpolated_cmd = interpolate_shell_template(template, args)

        # Check for un-interpolated required placeholders
        missing_placeholders = re.findall(r"\{([a-zA-Z0-9_]+)\}", interpolated_cmd)
        if missing_placeholders:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Missing required template parameters: {missing_placeholders}"
            }

        # Execute via Bash
        res = self.execute_bash(interpolated_cmd)

        # Render custom spoken confirmation if template provided
        if tool.spoken_confirmation_template and res["success"]:
            spoken_text = tool.spoken_confirmation_template
            for key, val in args.items():
                spoken_text = spoken_text.replace(f"{{{key}}}", str(val))
            res["spoken_confirmation"] = spoken_text
        elif not res.get("spoken_confirmation"):
            res["spoken_confirmation"] = f"Executed {tool.name}."

        return res

def interpolate_shell_template(template: str, args: Dict[str, Any]) -> str:
    """
    Replace {name} placeholders with argument values, escaped for where each placeholder sits:
    inside '...' (single-quote escape), inside "..." (escape \\ " $ `), or bare (shlex.quote).
    Placeholders without a matching argument are left as-is so the caller can report them.
    """
    import shlex

    out = []
    quote = None  # None, "'" or '"'
    i = 0
    while i < len(template):
        ch = template[i]
        match = re.match(r"\{([a-zA-Z0-9_]+)\}", template[i:])
        if match and match.group(1) in args:
            value = str(args[match.group(1)])
            if quote == "'":
                out.append(value.replace("'", "'\\''"))
            elif quote == '"':
                out.append(re.sub(r'([\\"$`])', r"\\\1", value))
            else:
                out.append(shlex.quote(value))
            i += len(match.group(0))
            continue
        if ch == "\\" and quote != "'" and i + 1 < len(template):
            out.append(template[i:i + 2])
            i += 2
            continue
        if ch in ("'", '"'):
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
        out.append(ch)
        i += 1
    return "".join(out)
