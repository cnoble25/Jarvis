"""
Learned shortcuts: requests the model always answers the same way, so Jarvis can skip the model.

Mining is a pure function of the transcript log (mine(records) -> rules), re-run after every turn,
so each rule's status always reflects all the evidence so far:

  template   the request with fillers removed and slots for values that vary:
             "open {app_name}", "set volume to {level}", or plain "turn volume to 0%"
  action     the tool call the template stands for; slot values come from the request
  support    past model decisions the rule reproduces exactly
  conflicts  past requests the rule matches where the model did something else

A rule replaces the model ("active") only with MIN_SUPPORT agreeing decisions, no conflict at all, and
a successful most recent run. Below that it is "shadow": it is matched on every request and its
prediction is logged beside what the model actually did, but the model still answers. Any conflict
drops the rule.

Noise rules cover speech that isn't a request, like Whisper hearing "the video." in background noise:
the same words, heard with low confidence every time, that the model never acted on. They only fire
when the current turn was heard with low confidence too, so saying the words clearly still works.

Run `python -m daemon.agent.pattern_miner` for a report on the current log.
"""

import hashlib
import json
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MIN_SUPPORT = 4          # agreeing model decisions before a rule skips the model
SHADOW_SUPPORT = 2       # agreeing decisions before a rule is tracked at all
NOISE_MIN = 3            # times the model ignored the same low-confidence words
NOISE_CONFIDENCE = 0.6   # speech recognition's top-guess probability below which a turn may be noise
MAX_SLOT_WORDS = 4
MAX_EXAMPLES = 6

# Tools whose arguments are free-form or depend on the moment: replaying them blindly is unsafe.
NEVER_LEARN = {"execute_terminal_command", "Bash", "Edit", "View", "Grep", "ManageTools", "web_search",
               "cancel_task", "background_task", "claude_code_task", "update_memory_profile",
               "system_power_control", "macro_control"}
# Slots validated against installed apps; any app that exists can fill them.
APP_SLOTS = {("app_launcher", "app_name"), ("close_app", "app_name")}
NOT_DECISIONS = {"approve_task", "refuse_task", "cancel_task", "ignored"}

_ADDRESS = re.compile(r"^\s*(?:(?:hey|ok|okay|yo)\s+)?jarvis\b[\s,.:;!?-]*", re.I)
_TOKEN = re.compile(r"\d+(?:\.\d+)?%?|[a-z0-9]+(?:'[a-z]+)?")
_NUMBER = re.compile(r"\d+(?:\.\d+)?%?")
_LEADING = [("please",), ("can", "you"), ("could", "you"), ("would", "you"), ("will", "you"),
            ("can", "u"), ("i", "want", "you", "to"), ("go", "ahead", "and")]
_TRAILING = [("please",), ("for", "me"), ("thanks",), ("thank", "you"), ("now", "please")]


# ---- Normalizing requests --------------------------------------------------------------------

def tokenize(text: str) -> List[str]:
    return [t.replace("'", "") for t in _TOKEN.findall(str(text).lower())]


def normalize(query: str) -> List[str]:
    """
    The words that decide what a request means: lowercase, no punctuation, no "hey Jarvis", and no
    politeness around the edges ("can you open chrome for me" -> open chrome).
    """
    tokens = tokenize(_ADDRESS.sub("", query or ""))
    changed = True
    while changed and tokens:
        changed = False
        for filler in _LEADING:
            if tuple(tokens[:len(filler)]) == filler and len(tokens) > len(filler):
                tokens, changed = tokens[len(filler):], True
        for filler in _TRAILING:
            if tuple(tokens[-len(filler):]) == filler and len(tokens) > len(filler):
                tokens, changed = tokens[:-len(filler)], True
    return tokens


# ---- Decisions ---------------------------------------------------------------------------------

def _canon(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        n = value.strip().lower()
        return float(n) if _NUMBER.fullmatch(n) and not n.endswith("%") else n
    if isinstance(value, (list, tuple)):
        return tuple(_canon(v) for v in value)
    if isinstance(value, dict):
        return json.dumps({k: value[k] for k in sorted(value)}, default=str).lower()
    return str(value).lower()


def clean_args(args: Any) -> Any:
    if isinstance(args, dict):
        return {k: v for k, v in args.items() if not str(k).startswith("_")}
    return args


def decision_key(tool: Any, args: Any) -> Tuple:
    tool = "none" if tool in (None, "", "None") else str(tool)
    if tool == "none":
        return ("none",)
    if not isinstance(args, dict):
        return (tool, "__not_a_dict__", _canon(args))
    return (tool,) + tuple(sorted((k, _canon(v)) for k, v in clean_args(args).items()))


def model_decision(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    What the model decided on this turn: {"tool", "args", "key", "multi"}. None when the model didn't
    decide it (a shortcut did, Claude Code was asked directly, or it was an approval / cancel).
    """
    served = record.get("served_by")
    tool_executed = str(record.get("tool_executed") or "none")
    if tool_executed in NOT_DECISIONS:
        return None
    if served is not None:
        if (served or {}).get("kind") != "llm":
            return None
        d = record.get("llm_decision") or {}
        tool, args = d.get("tool", "none"), d.get("args", {})
    else:
        # Logged before served_by existed: routed turns are recognizable, shortcuts aren't (callers
        # skip requests a shortcut already handles, so those can't teach anything either way).
        if record.get("route") or record.get("background_task"):
            return None
        tool, args = tool_executed, record.get("tool_args", {})
    multi = "->" in tool_executed
    return {"tool": "none" if tool in (None, "", "None") else tool, "args": clean_args(args) or {},
            "key": ("__multi__",) if multi else decision_key(tool, args), "multi": multi}


def _succeeded(record: Dict[str, Any]) -> bool:
    outcome = record.get("outcome")
    if outcome is not None:
        return outcome == "ok"
    return not (record.get("execution_stderr") or "").strip()


def _top_probability(record: Dict[str, Any]) -> Optional[float]:
    alts = record.get("heard_alternatives") or []
    if not alts or record.get("source") == "typed":
        return None
    try:
        return max(float(a.get("probability", 0)) for a in alts)
    except (TypeError, ValueError):
        return None


# ---- Templates ---------------------------------------------------------------------------------

def _find_span(tokens: List[str], sub: List[str]) -> Optional[int]:
    for i in range(len(tokens) - len(sub) + 1):
        if tokens[i:i + len(sub)] == sub:
            return i
    return None


def induce(query_tokens: List[str], tool: str, args: Dict[str, Any]) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]:
    """
    Turn one decision into a template: each argument value that appears word for word in the request
    becomes a slot. Returns (template tokens, {slot: kind}, constant args).
    """
    tokens, slots, const = list(query_tokens), {}, {}
    for key, value in args.items():
        value_tokens = tokenize(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else []
        i = _find_span(tokens, value_tokens) if 0 < len(value_tokens) <= MAX_SLOT_WORDS else None
        if i is None:
            const[key] = value
            continue
        tokens[i:i + len(value_tokens)] = ["{%s}" % key]
        joined = " ".join(value_tokens)
        slots[key] = "app" if (tool, key) in APP_SLOTS else ("number" if _NUMBER.fullmatch(joined) else "enum")
    return tokens, slots, const


def _slot_name(token: str) -> Optional[str]:
    return token[1:-1] if token.startswith("{") and token.endswith("}") else None


def match_template(template: List[str], tokens: List[str], slot_ok: Callable[[str, str], bool]) -> Optional[Dict[str, str]]:
    """Whole-request match: every word accounted for. Returns the slot values, or None."""
    def go(ti: int, qi: int, found: Dict[str, str]) -> Optional[Dict[str, str]]:
        if ti == len(template):
            return found if qi == len(tokens) else None
        name = _slot_name(template[ti])
        if name is None:
            return go(ti + 1, qi + 1, found) if qi < len(tokens) and tokens[qi] == template[ti] else None
        for width in range(1, MAX_SLOT_WORDS + 1):
            if qi + width > len(tokens):
                break
            value = " ".join(tokens[qi:qi + width])
            if slot_ok(name, value):
                hit = go(ti + 1, qi + width, {**found, name: value})
                if hit is not None:
                    return hit
        return None
    return go(0, 0, {})


class Rule:
    """A learned pattern rule; to_dict() is what's saved and shown in the dashboard."""

    def __init__(self, template: List[str], tool: str, slots: Dict[str, Dict[str, Any]], const: Dict[str, Any]):
        self.template, self.tool, self.slots, self.const = template, tool, slots, const
        # Fixed at creation: a slot later widening from "seen values" to "any app" keeps the same id,
        # so a rule the user deleted stays deleted.
        key = json.dumps([template, tool, sorted(const.items()), sorted((k, s["kind"]) for k, s in slots.items())],
                         default=str)
        self.id = "pattern_" + hashlib.sha1(key.encode()).hexdigest()[:10]
        self.support = self.conflicts = self.failures = 0
        self.last_ok = True
        self.examples: List[str] = []
        self.conflict_examples: List[str] = []
        self.last_seen = ""

    def slot_checker(self, app_exists: Callable[[str], bool]) -> Callable[[str, str], bool]:
        def ok(name: str, value: str) -> bool:
            slot = self.slots[name]
            if slot["kind"] == "app":
                return app_exists(value)
            if slot["kind"] == "number":
                return bool(_NUMBER.fullmatch(value))
            return value in slot["values"]
        return ok

    def predict(self, tokens: List[str], app_exists: Callable[[str], bool]) -> Optional[Dict[str, Any]]:
        found = match_template(self.template, tokens, self.slot_checker(app_exists))
        if found is None:
            return None
        args = dict(self.const)
        for name, value in found.items():
            slot = self.slots[name]
            if slot["kind"] == "enum":
                args[name] = slot["values"][value]
            elif slot["kind"] == "number" and slot.get("type") == "int" and not value.endswith("%"):
                args[name] = int(float(value))
            elif slot["kind"] == "number" and slot.get("type") == "float" and not value.endswith("%"):
                args[name] = float(value)
            else:
                args[name] = value
        return {"tool": self.tool, "args": args}

    @property
    def status(self) -> Optional[str]:
        if self.conflicts:
            return None
        if self.support >= MIN_SUPPORT and self.last_ok:
            return "active"
        if self.support >= SHADOW_SUPPORT:
            return "shadow"
        return None

    def to_dict(self) -> Dict[str, Any]:
        shown = " ".join(self.template)
        return {
            "id": self.id, "kind": "pattern", "name": f"Learned: {shown}", "template": self.template,
            "triggers": [shown], "examples": self.examples[-MAX_EXAMPLES:], "tool": self.tool,
            "args": {**self.const, **{k: "{%s}" % k for k in self.slots}}, "const_args": self.const,
            "slots": self.slots, "support": self.support, "conflicts": self.conflicts, "failures": self.failures,
            "status": self.status, "last_seen": self.last_seen, "action_type": "tool", "is_system": False,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        rule = cls(list(data["template"]), data["tool"], dict(data.get("slots") or {}), dict(data.get("const_args") or {}))
        rule.support, rule.conflicts = int(data.get("support", 0)), int(data.get("conflicts", 0))
        rule.failures, rule.examples = int(data.get("failures", 0)), list(data.get("examples") or [])
        rule.id = data.get("id", rule.id)
        return rule


# ---- Mining ------------------------------------------------------------------------------------

def _learnable(record: Dict[str, Any], decision: Dict[str, Any], required: Dict[str, List[str]]) -> bool:
    tool, args = decision["tool"], decision["args"]
    if decision["multi"] or tool == "none" or tool in NEVER_LEARN or tool not in required:
        return False
    if not isinstance(args, dict) or not _succeeded(record):
        return False
    return all(args.get(k) not in (None, "") for k in required[tool])


def mine(records: Iterable[Dict[str, Any]], required_args: Dict[str, List[str]],
         app_exists: Callable[[str], bool] = lambda name: False,
         handled_elsewhere: Callable[[str], bool] = lambda query: False,
         rejected: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """
    Every rule the log supports, active and shadow, plus noise rules.
      required_args      tool id -> its required arguments (only these tools can be learned)
      app_exists         whether an app name is installed (fills "{app_name}" slots)
      handled_elsewhere  the request already has a built-in shortcut (learning it would duplicate it)
      rejected           rule ids the user deleted: never brought back
    """
    rejected = set(rejected)
    app_cache: Dict[str, bool] = {}

    def has_app(name: str) -> bool:
        if name not in app_cache:
            try:
                app_cache[name] = bool(app_exists(name))
            except Exception:
                app_cache[name] = False
        return app_cache[name]

    decided: List[Tuple[Dict[str, Any], List[str], Dict[str, Any]]] = []
    for record in records:
        decision = model_decision(record)
        tokens = normalize(record.get("user_query", ""))
        if decision is not None and tokens:
            decided.append((record, tokens, decision))

    # 1. Candidates from successful, learnable decisions.
    candidates: Dict[str, Rule] = {}
    values: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for record, tokens, decision in decided:
        if not _learnable(record, decision, required_args) or handled_elsewhere(record.get("user_query", "")):
            continue
        # Never learn opening an app that isn't installed: it came from a loose match or will fail.
        if any(not has_app(str(decision["args"].get(key, ""))) for tool, key in APP_SLOTS if tool == decision["tool"]):
            continue
        template, kinds, const = induce(tokens, decision["tool"], decision["args"])
        rule = Rule(template, decision["tool"], {k: {"kind": v} for k, v in kinds.items()}, const)
        rule = candidates.setdefault(rule.id, rule)
        seen = values.setdefault(rule.id, {k: {} for k in kinds})
        for key in kinds:
            value = decision["args"][key]
            seen[key][" ".join(tokenize(value))] = value

    # An app or number slot generalizes to values never heard only once two different ones agree;
    # until then it accepts exactly the values seen.
    for rule_id, rule in candidates.items():
        for key, slot in rule.slots.items():
            observed = values[rule_id][key]
            if slot["kind"] == "number":
                originals = list(observed.values())
                slot["type"] = ("int" if all(isinstance(v, int) for v in originals)
                                else "float" if all(isinstance(v, float) for v in originals) else "str")
            if slot["kind"] in ("app", "number") and len(observed) < 2:
                slot["kind"] = "enum"
            if slot["kind"] == "enum":
                slot["values"] = observed

    # 2. Verify each candidate against every model decision it would have made (the shadow check).
    for rule in candidates.values():
        for record, tokens, decision in decided:
            prediction = rule.predict(tokens, has_app)
            if prediction is None:
                continue
            query = record.get("user_query", "")
            if decision["key"] != decision_key(prediction["tool"], prediction["args"]):
                rule.conflicts += 1
                rule.conflict_examples.append(query)
                continue
            if _succeeded(record):
                rule.support += 1
                rule.last_ok = True
                if query not in rule.examples:
                    rule.examples.append(query)
            else:
                rule.failures += 1
                rule.last_ok = False
            rule.last_seen = record.get("timestamp", rule.last_seen)

    rules = [r.to_dict() for r in candidates.values() if r.status and r.id not in rejected]

    # 3. Noise: the same low-confidence words, never acted on.
    by_text: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    for record, tokens, decision in decided:
        by_text.setdefault(" ".join(tokens), []).append((record, decision))
    for text, turns in by_text.items():
        if len(turns) < NOISE_MIN or any(d["key"] != ("none",) for _, d in turns):
            continue
        confidences = [_top_probability(r) for r, _ in turns]
        if any(c is None or c >= NOISE_CONFIDENCE for c in confidences):
            continue
        rule_id = "noise_" + hashlib.sha1(text.encode()).hexdigest()[:10]
        if rule_id in rejected:
            continue
        rules.append({
            "id": rule_id, "kind": "noise", "name": f"Ignored: {text}", "template": text.split(),
            "triggers": [text], "examples": list(dict.fromkeys(r.get("user_query", "") for r, _ in turns))[-MAX_EXAMPLES:],
            "tool": "none", "args": {}, "support": len(turns), "conflicts": 0, "failures": 0,
            "max_confidence": round(max(confidences), 3), "status": "active",
            "last_seen": turns[-1][0].get("timestamp", ""), "action_type": "ignore", "is_system": False,
        })

    order = {"active": 0, "shadow": 1}
    rules.sort(key=lambda r: (order.get(r["status"], 2), -r["support"], r["id"]))
    return rules


def match_rules(rules: List[Dict[str, Any]], query: str, app_exists: Callable[[str], bool],
                heard_confidence: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """
    The rule this request matches, as {"rule", "mode": active|shadow|ignore, "tool", "args"}, or None.
    Plain templates win over ones with slots; a noise rule needs this turn's confidence to be low too.
    heard_confidence is None for typed requests.
    """
    tokens = normalize(query)
    if not tokens:
        return None
    text = " ".join(tokens)
    for data in rules:
        if data.get("kind") == "noise" and data.get("triggers") == [text]:
            if heard_confidence is not None and heard_confidence < NOISE_CONFIDENCE:
                return {"rule": data, "mode": "ignore", "tool": "none", "args": {}}
    patterns = [d for d in rules if d.get("kind") == "pattern" and d.get("status") in ("active", "shadow")]
    patterns.sort(key=lambda d: (len(d.get("slots") or {}), d.get("status") != "active"))
    for data in patterns:
        prediction = Rule.from_dict(data).predict(tokens, app_exists)
        if prediction is not None:
            return {"rule": data, "mode": data["status"], **prediction}
    return None


# ---- Report ------------------------------------------------------------------------------------

def report(records: List[Dict[str, Any]], rules: List[Dict[str, Any]],
           app_exists: Callable[[str], bool] = lambda name: False) -> str:
    """What the log shows: who answered each turn, and how many model calls the rules would skip."""
    served: Dict[str, int] = {}
    model_turns = skippable = 0
    active = [r for r in rules if r["status"] == "active"]
    for record in records:
        kind = (record.get("served_by") or {}).get("kind") or ("route" if record.get("route") else "unlabeled (older log)")
        served[kind] = served.get(kind, 0) + 1
        decision = model_decision(record)
        if decision is None:
            continue
        model_turns += 1
        hit = match_rules(active, record.get("user_query", ""), app_exists, _top_probability(record))
        if hit and (hit["mode"] == "ignore" or decision["key"] == decision_key(hit["tool"], hit["args"])):
            skippable += 1
    lines = [f"{len(records)} turns logged: " + ", ".join(f"{n} {k}" for k, n in sorted(served.items(), key=lambda x: -x[1]))]
    pct = f" ({skippable / model_turns:.0%})" if model_turns else ""
    lines.append(f"Model decisions in the log: {model_turns}; active rules would have skipped {skippable}{pct}.")
    for r in rules:
        lines.append(f"  [{r['status']:6}] {r['kind']:7} \"{r['triggers'][0]}\" -> {r['tool']} {json.dumps(r['args'])}"
                     f"  support={r['support']} conflicts={r['conflicts']}  e.g. {r['examples'][:3]}")
    if not rules:
        lines.append("  No repeated patterns yet.")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Mine Jarvis transcripts for requests that can skip the model.")
    parser.add_argument("--dir", default=str(Path.home() / ".local" / "share" / "jarvis" / "transcripts"))
    parser.add_argument("--no-apps", action="store_true", help="don't scan installed apps (treat every name as missing)")
    opts = parser.parse_args()

    recs: List[Dict[str, Any]] = []
    for path in sorted(Path(opts.dir).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    from daemon.agent.fast_path_manager import FastPathManager
    import contextlib

    # Read-only: the tool manifests straight from disk (ToolRegistry() would rewrite the config folder).
    tools: Dict[str, List[str]] = {}
    manifests = [Path(__file__).resolve().parent.parent / "tools" / "daily_commands.json",
                 *sorted((Path.home() / ".config" / "jarvis" / "tools").glob("*.json"))]
    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for tool in data if isinstance(data, list) else [data]:
            if isinstance(tool, dict) and tool.get("id"):
                tools[tool["id"]] = list((tool.get("parameters") or {}).get("required", []))
    with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet):
        manager = FastPathManager(persist=False)
        if opts.no_apps:
            exists = lambda name: False
        else:
            from daemon.tools.app_scanner import get_app_scanner
            scanner = get_app_scanner()
            exists = lambda name: scanner.find_app(name) is not None
        mined = mine(recs, tools, app_exists=exists, handled_elsewhere=manager.handled_by_builtin,
                     rejected=manager.rejected)
    print(report(recs, mined, exists))
