"""
Fast-Path Creator Agent (Sub-Task 3.3)
Dedicated AI Agent that runs after the Memory Profiling phase.
Analyzes recent interaction logs, user profile facts, and tool usage to create and update dynamic fast-path query rules.
"""

import json
from typing import Dict, Any, List, Optional
from daemon.agent.fast_path_manager import FastPathManager


class FastPathCreatorAgent:
    def __init__(self, fast_path_manager: Optional[FastPathManager] = None):
        self.fast_path_mgr = fast_path_manager or FastPathManager()

    def update_fast_paths(
        self,
        transcripts: List[Dict[str, Any]],
        user_profile: str = "",
        llm_provider: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Step 4 in Execution Chain: Runs LLM Agent + Heuristics to create dynamic fast-path rules.
        """
        if not transcripts:
            return []

        print("[FastPathCreatorAgent] Running Fast-Path Creator Agent to synthesize query rules...", flush=True)
        created_rules = []

        # 1. Deterministic Frequency Mining (Queries repeated 2+ times)
        from collections import defaultdict
        query_groups = defaultdict(list)
        for t in transcripts:
            q = t.get("user_query", "").strip()
            tool = t.get("tool_executed", "none")
            tool_args = t.get("tool_args", {})
            spoken = t.get("spoken_response", "")

            if not q or tool in ["none", "None", "", "error"] or len(q) < 3:
                continue

            q_norm = q.lower().strip().rstrip(".!?")
            
            # Skip transient / test / conversational queries
            transient_kws = ["test", "testing", "status", "check", "hello", "hi", "hey", "what", "time", "date", "mode"]
            if any(kw in q_norm.split() or kw == q_norm for kw in transient_kws):
                continue

            # Skip single-word queries
            if len(q_norm.split()) < 2:
                continue

            # Skip compound queries with connectors or punctuation or multiple verbs
            compound_kw = [" and ", " then ", " also ", " plus ", " as well as ", " while ", " but ", " before ", " after ", " with "]
            if any(c in f" {q_norm} " for c in compound_kw) or "," in q_norm or ";" in q_norm:
                continue

            query_groups[q_norm].append({
                "raw_query": q,
                "tool": tool,
                "tool_args": tool_args,
                "spoken": spoken
            })

        rules_added = False
        for q_norm, occurrences in query_groups.items():
            # Require at least 4 consistent repetitions before auto-saving a fast-path shortcut rule
            if len(occurrences) < 4:
                continue

            tools = [o["tool"] for o in occurrences]
            most_common_tool = max(set(tools), key=tools.count)
            tool_count = tools.count(most_common_tool)

            if tool_count / len(occurrences) >= 0.85:
                sample = next(o for o in occurrences if o["tool"] == most_common_tool)
                raw_triggers = list(set(o["raw_query"] for o in occurrences))

                action_type = "tool"

                rule = self.fast_path_mgr.add_learned_rule(
                    triggers=raw_triggers,
                    action_type=action_type,
                    tool=most_common_tool,
                    args=sample.get("tool_args", {}),
                    spoken_summary=sample.get("spoken", f"Executing {most_common_tool}."),
                    name=f"Learned Shortcut: {raw_triggers[0]}",
                    auto_save=False
                )
                created_rules.append(rule)
                rules_added = True

        if rules_added:
            self.fast_path_mgr.save_learned_rules()
            print(f"[FastPathCreatorAgent] Updated fast-path rules saved ({len(self.fast_path_mgr.learned_rules)} active rules).", flush=True)

        return created_rules
