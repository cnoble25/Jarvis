"""
Fast-Path Pattern Miner & Dynamic Shortcut Extractor (Sub-Task 3.3)
Mines conversation transcripts for recurring user command patterns, tool invocations, and static responses.
Registers discovered dynamic shortcuts into FastPathManager.
"""

import json
from typing import Dict, Any, List, Optional
from collections import defaultdict


class FastPathMiner:
    def __init__(self, fast_path_manager: Optional[Any] = None):
        if fast_path_manager is None:
            from daemon.agent.fast_path_manager import FastPathManager
            self.fast_path_mgr = FastPathManager()
        else:
            self.fast_path_mgr = fast_path_manager

    def mine_transcripts(self, transcripts: List[Dict[str, Any]], llm_provider: Optional[Any] = None) -> List[Dict[str, Any]]:
        """
        Scans transcripts for recurring query patterns (queries repeated 2+ times with matching outputs).
        """
        if not transcripts:
            return []

        new_rules = []

        # 1. Frequency Heuristic Mining: Group queries by normalized text
        query_groups = defaultdict(list)
        for t in transcripts:
            q = t.get("user_query", "").strip()
            tool = t.get("tool_executed", "none")
            tool_args = t.get("tool_args", {})
            spoken = t.get("spoken_response", "")

            if not q or tool == "error" or len(q) < 3:
                continue

            q_norm = q.lower().strip()
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

        # Process queries repeated 2+ times with consistent execution
        rules_to_save = False
        for q_norm, occurrences in query_groups.items():
            if len(occurrences) < 2:
                continue

            # Check consistency of tool execution
            tools = [o["tool"] for o in occurrences]
            most_common_tool = max(set(tools), key=tools.count)
            tool_count = tools.count(most_common_tool)

            # If tool or spoken output is 80%+ consistent across turns
            if tool_count / len(occurrences) >= 0.8:
                sample = next(o for o in occurrences if o["tool"] == most_common_tool)
                raw_triggers = list(set(o["raw_query"] for o in occurrences))

                action_type = "tool" if most_common_tool != "none" else "static_response"

                # Add rule without triggering individual file saves
                rule = self.fast_path_mgr.add_learned_rule(
                    triggers=raw_triggers,
                    action_type=action_type,
                    tool=most_common_tool,
                    args=sample.get("tool_args", {}),
                    spoken_summary=sample.get("spoken", f"Executing {most_common_tool}."),
                    name=f"Learned Shortcut: {raw_triggers[0]}",
                    auto_save=False
                )
                new_rules.append(rule)
                rules_to_save = True

        if rules_to_save:
            self.fast_path_mgr.save_learned_rules()

        return new_rules
