"""
Fast paths: requests answered without asking the model.
Built-in phrase rules live here; learned rules are mined from the transcript log by
daemon/agent/pattern_miner.py. Both persist to ~/.config/jarvis/fast_path_rules.json.
"""

import os
import re
import json
import threading
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional

from daemon.agent.pattern_miner import NEVER_LEARN, match_rules, normalize

RULES_FILE = Path(os.path.expanduser("~/.config/jarvis/fast_path_rules.json"))

DEFAULT_SYSTEM_RULES: List[Dict[str, Any]] = [
    {
        "id": "sys_identity",
        "name": "Assistant Identity & Model Information",
        "triggers": [
            "what model", "which model", "what ai model", "which ai model", "current model",
            "what agent", "which agent", "what ai agent", "which ai agent", "current agent",
            "what engine", "which engine", "what ai engine", "which ai engine", "current engine",
            "ai engine", "ai model", "ai agent", "who are you"
        ],
        "action_type": "dynamic_identity",
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_time",
        "name": "Current Time & Date Query",
        "triggers": [
            "what time", "what's the time", "whats the time", "what is the time",
            "tell me the time", "current time", "what date", "what's the date",
            "whats the date", "what is today's date", "what day is it"
        ],
        "action_type": "tool",
        "tool": "get_current_time",
        "args": {},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_media_play",
        "name": "Media Play / Resume",
        "triggers": [
            "unpause", "un-pause", "un pause", "resume music", "resume song",
            "resume playback", "play music", "play song", "play the music",
            "play some music", "start music", "play youtube", "resume youtube",
            "start playing youtube", "start youtube", "playing youtube",
            "resume video", "play video", "resume media", "play media"
        ],
        "action_type": "tool",
        "tool": "media_play_pause",
        "args": {"action": "play"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_media_pause",
        "name": "Media Pause / Stop",
        "triggers": [
            "pause music", "pause song", "pause video", "pause playback",
            "pause the music", "pause the video", "stop music", "stop playback",
            "pause youtube", "pause media", "pause audio", "pause"
        ],
        "action_type": "tool",
        "tool": "media_play_pause",
        "args": {"action": "pause"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_media_next",
        "name": "Media Next Track",
        "triggers": ["next song", "next track", "skip song", "skip track", "next video"],
        "action_type": "tool",
        "tool": "media_play_pause",
        "args": {"action": "next"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_media_prev",
        "name": "Media Previous Track",
        "triggers": ["previous song", "previous track", "last song", "last track"],
        "action_type": "tool",
        "tool": "media_play_pause",
        "args": {"action": "previous"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_volume_toggle",
        "name": "Volume Mute Toggle",
        "triggers": [
            "mute audio", "mute sound", "mute volume", "unmute audio",
            "unmute sound", "mute the audio", "mute the sound", "mute"
        ],
        "action_type": "tool",
        "tool": "volume_control",
        "args": {"action": "toggle"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_volume_up",
        "name": "Volume Increase",
        "triggers": ["volume up", "turn up volume", "turn up the volume", "increase volume", "louder"],
        "action_type": "tool",
        "tool": "volume_control",
        "args": {"action": "5%+"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_volume_down",
        "name": "Volume Decrease",
        "triggers": ["volume down", "turn down volume", "turn down the volume", "decrease volume", "softer", "quieter"],
        "action_type": "tool",
        "tool": "volume_control",
        "args": {"action": "5%-"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_power_shutdown",
        "name": "System Power Shutdown",
        "triggers": [
            "shutdown", "power off", "poweroff", "turn off computer",
            "turn off the computer", "turn off pc", "turn off my computer", "shut down"
        ],
        "action_type": "tool",
        "tool": "system_power_control",
        "args": {"action": "shutdown"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_power_reboot",
        "name": "System Power Reboot",
        "triggers": [
            "reboot", "restart computer", "restart my computer",
            "restart pc", "restart the pc", "restart the computer"
        ],
        "action_type": "tool",
        "tool": "system_power_control",
        "args": {"action": "reboot"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_power_suspend",
        "name": "System Power Suspend",
        "triggers": ["suspend", "put to sleep", "put computer to sleep", "sleep computer"],
        "action_type": "tool",
        "tool": "system_power_control",
        "args": {"action": "suspend"},
        "match_type": "contains_any",
        "is_system": True
    },
    {
        "id": "sys_power_lock",
        "name": "System Lock Screen",
        "triggers": ["lock screen", "lock computer", "lock my computer screen", "lock pc", "lock session"],
        "action_type": "tool",
        "tool": "system_power_control",
        "args": {"action": "lock"},
        "match_type": "contains_any",
        "is_system": True
    }
]


class FastPathManager:
    """
    Built-in shortcuts (DEFAULT_SYSTEM_RULES, matched by phrase) plus what Jarvis learned:
      mined    rules re-mined from the transcript log after every turn (daemon/agent/pattern_miner.py):
               active ones skip the model, shadow ones are only checked against it, noise ones ignore
               low-confidence background speech
      legacy   shortcuts from before pattern mining, matched against the whole request
      rejected ids of mined rules the user deleted, so mining never brings them back
    """

    def __init__(self, rules_path: Optional[Path] = None, persist: bool = True):
        self.rules_path = rules_path or RULES_FILE
        self.persist = persist  # False: read the rules file but never write it (reports)
        self.learned_rules: List[Dict[str, Any]] = []  # legacy
        self.mined_rules: List[Dict[str, Any]] = []
        self.rejected: List[str] = []
        self._lock = threading.Lock()
        self.load_learned_rules()

    def load_learned_rules(self) -> List[Dict[str, Any]]:
        data: Any = []
        if self.rules_path.exists():
            try:
                with open(self.rules_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"[FastPathManager Warning] Failed loading rules: {e}", flush=True)
        if isinstance(data, list):  # the file before pattern mining: a list of phrase shortcuts
            data = {"legacy": data}
        legacy = [r for r in data.get("legacy", []) if isinstance(r, dict)]
        unsafe = [r for r in legacy if r.get("tool") in NEVER_LEARN]
        for r in unsafe:
            print(f"[FastPathManager] Dropped learned shortcut {r.get('triggers')} -> {r.get('tool')}: "
                  "that tool is never replayed without the model.", flush=True)
        self.learned_rules = [r for r in legacy if r not in unsafe]
        self.mined_rules = [r for r in data.get("mined", []) if isinstance(r, dict)]
        self.rejected = list(data.get("rejected", []))
        if unsafe:
            self.save_learned_rules()
        return self.learned_rules

    def prune_unlaunchable_app_rules(self) -> List[str]:
        """
        Remove learned "open X" shortcuts whose app doesn't exist: they came from a loose fuzzy match
        ("start us on movie mode" -> Peaks of Yore) and would keep opening the wrong thing.
        """
        from daemon.tools.app_scanner import get_app_scanner
        scanner = get_app_scanner()
        removed = [r for r in self.learned_rules
                   if r.get("tool") == "app_launcher" and not scanner.find_app(str(r.get("args", {}).get("app_name", "")))]
        if removed:
            ids = {r.get("id") for r in removed}
            self.learned_rules = [r for r in self.learned_rules if r.get("id") not in ids]
            for r in removed:
                print(f"[FastPathManager] Removed learned shortcut {r.get('triggers')} -> app '{r.get('args', {}).get('app_name')}' (no such app).", flush=True)
            self.save_learned_rules()
        return [r.get("id") for r in removed]

    def save_learned_rules(self):
        if not self.persist:
            return
        try:
            with self._lock:
                os.makedirs(self.rules_path.parent, exist_ok=True)
                tmp = self.rules_path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"version": 2, "legacy": self.learned_rules, "mined": self.mined_rules,
                               "rejected": self.rejected}, f, indent=2)
                os.replace(tmp, self.rules_path)
        except Exception as e:
            print(f"[FastPathManager Error] Failed saving rules: {e}", flush=True)

    def set_mined_rules(self, rules: List[Dict[str, Any]]) -> bool:
        """Replace the mined rules (the miner recomputes all of them each time). True if anything changed."""
        summary = lambda rs: [(r.get("id"), r.get("status"), r.get("support"), r.get("conflicts")) for r in rs]
        if summary(rules) == summary(self.mined_rules):
            return False
        before = {r["id"]: r.get("status") for r in self.mined_rules}
        for r in rules:
            if before.get(r["id"]) != r.get("status"):
                print(f"[FastPathManager] Learned rule \"{r['triggers'][0]}\" -> {r['tool']} is now {r['status']} "
                      f"(support {r['support']}).", flush=True)
        self.mined_rules = list(rules)
        self.save_learned_rules()
        return True

    def get_all_rules(self) -> List[Dict[str, Any]]:
        """Built-in rules, legacy learned shortcuts, then mined rules (for the dashboard)."""
        return DEFAULT_SYSTEM_RULES + self.learned_rules + self.mined_rules

    def add_learned_rule(
        self,
        triggers: List[str],
        action_type: str,
        tool: str = "none",
        args: Optional[Dict[str, Any]] = None,
        spoken_summary: str = "",
        name: str = "Learned Fast-Path Rule",
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """Add (or extend) a phrase shortcut by hand. It matches only the whole request."""
        import uuid
        clean_triggers = [t.lower().strip() for t in triggers if t.strip()]
        for existing in self.learned_rules:
            if any(t in existing.get("triggers", []) for t in clean_triggers):
                existing["triggers"] = list(dict.fromkeys(existing["triggers"] + clean_triggers))
                existing.update(tool=tool, args=args or {}, spoken_summary=spoken_summary,
                                frequency=existing.get("frequency", 1) + 1)
                if auto_save:
                    self.save_learned_rules()
                return existing
        new_rule = {
            "id": f"learned_{uuid.uuid4().hex[:8]}", "name": name, "triggers": clean_triggers,
            "action_type": action_type, "tool": tool, "args": args or {}, "spoken_summary": spoken_summary,
            "match_type": "exact", "is_system": False, "frequency": 1,
        }
        self.learned_rules.append(new_rule)
        if auto_save:
            self.save_learned_rules()
        return new_rule

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a learned rule. A mined one is remembered as rejected so it isn't learned again."""
        if any(r.get("id") == rule_id for r in self.mined_rules):
            self.mined_rules = [r for r in self.mined_rules if r.get("id") != rule_id]
            self.rejected.append(rule_id)
            self.save_learned_rules()
            return True
        initial_len = len(self.learned_rules)
        self.learned_rules = [r for r in self.learned_rules if r.get("id") != rule_id]
        if len(self.learned_rules) < initial_len:
            self.save_learned_rules()
            return True
        return False

    def match_learned(self, user_query: str, heard_confidence: Optional[float] = None,
                      app_exists: Optional[Callable[[str], bool]] = None) -> Optional[Dict[str, Any]]:
        """
        What Jarvis learned about this exact request: {"rule", "mode", "tool", "args"} with mode
        active (run it, skip the model), shadow (log a prediction, ask the model anyway) or ignore
        (background speech). heard_confidence: speech recognition's top-guess probability, None if typed.
        """
        words = " ".join(normalize(user_query))
        for rule in self.learned_rules:
            if words and words in {" ".join(normalize(t)) for t in rule.get("triggers", [])}:
                return {"rule": rule, "mode": "active", "tool": rule.get("tool", "none"),
                        "args": dict(rule.get("args", {}))}
        if app_exists is None:
            def app_exists(name: str) -> bool:
                from daemon.tools.app_scanner import get_app_scanner
                return get_app_scanner().find_app(name) is not None
        return match_rules(self.mined_rules, user_query, app_exists, heard_confidence)

    def handled_by_builtin(self, user_query: str) -> bool:
        """A built-in shortcut already answers this request (so there's nothing to learn from it)."""
        return self.match(user_query, quiet=True) is not None

    def match(self, user_query: str, active_model_name: str = "Jarvis", quiet: bool = False) -> Optional[Dict[str, Any]]:
        """
        Evaluates query against the built-in phrase rules and installed-app launching.
        Returns execution payload dictionary if matched, or None.
        """
        q_clean = re.sub(r"[^\w\s-]", "", user_query.lower()).strip()
        q_nobrand = re.sub(r"^(hey\s+)?jarvis[\s,]+", "", user_query.lower()).strip()
        all_rules = DEFAULT_SYSTEM_RULES  # learned rules: match_learned()

        # Check for compound query connectors (e.g. 'and', 'then', 'also', 'plus', 'while', 'but', etc.)
        compound_connectors = [" and ", " then ", " also ", " plus ", " as well as ", " while ", " but ", " before ", " after ", " with "]
        has_compound_connectors = any(c in f" {q_clean} " for c in compound_connectors)

        # Check for multiple action verbs in a single query
        action_verbs = [
            "pause", "unpause", "play", "resume", "open", "launch", "close", "stop", "start",
            "mute", "unmute", "turn", "increase", "decrease", "softer", "louder", "set",
            "lock", "reboot", "restart", "shutdown", "suspend", "sleep", "run", "execute", "toggle"
        ]
        verb_count = sum(1 for v in action_verbs if re.search(r"\b" + re.escape(v) + r"\b", q_clean))

        # Check for multi-clause punctuation structure (e.g. "pause, spotify playback, resume YouTube playback.")
        clauses = [c.strip() for c in re.split(r"[,;]", q_nobrand) if c.strip()]
        has_multi_clause_verbs = (
            len(clauses) > 1 and
            sum(1 for clause in clauses if any(re.search(r"\b" + re.escape(v) + r"\b", clause) for v in action_verbs)) > 1
        )

        # If query has compound structure, multi-clause verbs, or multiple action verbs, bypass fast-path for LLM Orchestrator multi-step handling
        if has_compound_connectors or has_multi_clause_verbs or verb_count > 1:
            if not quiet:
                print(f"[FastPathManager] Compound/Multi-verb query detected ('{user_query}'). Bypassing fast-path for LLM orchestration.", flush=True)
            return None

        # 1. Match against registered system & learned rules
        for rule in all_rules:
            triggers = rule.get("triggers", [])
            match_type = rule.get("match_type", "contains_any")

            is_match = False
            if match_type == "exact":
                is_match = any(q_clean == t.lower().strip() for t in triggers)
            else:  # contains_any
                for t in triggers:
                    t_clean = t.lower().strip()
                    if t_clean in q_clean:
                        # For single short word triggers (e.g. 'pause', 'play'), require exact match or standard media word
                        if len(t_clean.split()) == 1 and q_clean != t_clean:
                            valid_suffixes = ("music", "video", "playback", "song", "track", "media", "audio", "youtube", "spotify")
                            if not any(s in q_clean for s in valid_suffixes):
                                continue
                        is_match = True
                        break
                    t_words = t_clean.split()
                    if len(t_words) > 1:
                        pattern = r"\b" + r"\s+(?:\w+\s+){0,2}".join(re.escape(w) for w in t_words) + r"\b"
                        if re.search(pattern, q_clean):
                            is_match = True
                            break

            if is_match:
                # Check for mutation/modification intent (e.g. 'change gaming mode to...', 'create a macro for...')
                mutation_verbs = ["change", "create", "edit", "modify", "update", "remove", "add", "make", "set up", "how to", "delete"]
                has_mutation_intent = any(re.search(r"\b" + re.escape(v) + r"\b", q_clean) for v in mutation_verbs)
                
                # If query contains mutation intent and rule executes a macro/command tool, skip fast-path to allow LLM orchestrator handling
                if has_mutation_intent and rule.get("action_type") == "tool":
                    continue

                action_type = rule.get("action_type")

                if action_type == "dynamic_identity":
                    spoken_text = f"I am Jarvis, currently powered by {active_model_name}."
                    return {
                        "rule_id": rule["id"],
                        "tool": "none",
                        "args": {},
                        "spoken_summary": spoken_text,
                        "action_type": "dynamic_identity"
                    }

                elif action_type == "static_response":
                    return {
                        "rule_id": rule["id"],
                        "tool": "none",
                        "args": {},
                        "spoken_summary": rule.get("spoken_summary", ""),
                        "action_type": "static_response"
                    }

                elif action_type == "tool":
                    return {
                        "rule_id": rule["id"],
                        "tool": rule.get("tool", "none"),
                        "args": dict(rule.get("args", {})),
                        "spoken_summary": rule.get("spoken_summary", ""),
                        "action_type": "tool"
                    }

        # 2. Match App Launcher intent via AppScanner
        try:
            from daemon.tools.app_scanner import get_app_scanner
            app_match = get_app_scanner().match_app_launch_intent(user_query)
            if app_match:
                cmd, app_display_name, matched_q = app_match
                spoken_text = f"Opening {app_display_name}."
                return {
                    "rule_id": "sys_app_launcher",
                    "tool": "app_launcher",
                    "args": {"app_name": matched_q, "_app_display_name": app_display_name},
                    "spoken_summary": spoken_text,
                    "action_type": "app_launch"
                }
        except Exception:
            pass

        return None


# Global singleton instance
_fast_path_manager_instance: Optional[FastPathManager] = None

def get_fast_path_manager() -> FastPathManager:
    global _fast_path_manager_instance
    if _fast_path_manager_instance is None:
        _fast_path_manager_instance = FastPathManager()
    return _fast_path_manager_instance
