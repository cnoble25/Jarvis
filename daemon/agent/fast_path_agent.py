"""
Shortcut learner: runs after each turn (in the background) and re-mines the whole transcript log
for requests the model always answers the same way. See daemon/agent/pattern_miner.py for how a
pattern earns the right to skip the model.
"""

import contextlib
import io
from typing import Any, Dict, List, Optional

from daemon.agent.fast_path_manager import FastPathManager
from daemon.agent.pattern_miner import NEVER_LEARN, mine  # noqa: F401  (NEVER_LEARN re-exported)


def _app_exists(app_name: str) -> bool:
    try:
        from daemon.tools.app_scanner import get_app_scanner
        return get_app_scanner().find_app(app_name) is not None
    except Exception:
        return False


def _required_args() -> Dict[str, List[str]]:
    """Tool id -> required arguments, for every registered tool (only these can be learned)."""
    try:
        from daemon.tools.registry import ToolRegistry
        with contextlib.redirect_stdout(io.StringIO()):
            registry = ToolRegistry()
        return {t.id: list(t.parameters.get("required", [])) for t in registry.list_tools()}
    except Exception as err:
        print(f"[FastPathCreatorAgent Warning] Couldn't read the tool registry: {err}", flush=True)
        return {}


class FastPathCreatorAgent:
    def __init__(self, fast_path_manager: Optional[FastPathManager] = None,
                 required_args: Optional[Dict[str, List[str]]] = None):
        self.fast_path_mgr = fast_path_manager or FastPathManager()
        self._required_args = required_args
        try:
            self.fast_path_mgr.prune_unlaunchable_app_rules()
        except Exception as err:
            print(f"[FastPathCreatorAgent Warning] Couldn't check learned app shortcuts: {err}", flush=True)

    @property
    def required_args(self) -> Dict[str, List[str]]:
        if self._required_args is None:
            self._required_args = _required_args()
        return self._required_args

    def update_fast_paths(
        self,
        transcripts: List[Dict[str, Any]],
        user_profile: str = "",
        llm_provider: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """Re-mine every rule from the log; returns the rules (active, shadow and noise)."""
        if not transcripts:
            return []
        rules = mine(
            transcripts,
            self.required_args,
            app_exists=_app_exists,
            handled_elsewhere=self.fast_path_mgr.handled_by_builtin,
            rejected=self.fast_path_mgr.rejected,
        )
        if self.fast_path_mgr.set_mined_rules(rules):
            counts = {s: sum(1 for r in rules if r["status"] == s and r["kind"] == "pattern") for s in ("active", "shadow")}
            noise = sum(1 for r in rules if r["kind"] == "noise")
            print(f"[FastPathCreatorAgent] Learned rules: {counts['active']} active, {counts['shadow']} watching, "
                  f"{noise} ignored phrases.", flush=True)
        return rules
