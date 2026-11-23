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
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MIN_SUPPORT = 4          # agreeing model decisions before a rule skips the model
SHADOW_SUPPORT = 2       # agreeing decisions before a rule is tracked at all
AUTHORED_MIN_SUPPORT = 2 # a rule Claude Code wrote: the request it came from plus one more agreeing decision
MAX_TEMPLATES = 8
CORRECTION_WINDOW = 20   # seconds after a learned answer in which "no" / a rephrase counts as a correction
SLOT_KINDS = ("number", "app", "enum")
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


# ---- Corrections --------------------------------------------------------------------------------
#
# Right after a learned rule answers, the user saying "no" / "undo" / "not that", or rephrasing the same
# request (and the model then doing something else), is a correction. One sends the rule back to
# watching until the model agrees with it twice more; a second drops it.

_CORRECTION = re.compile(r"^(?:no|nope|nah|wrong|undo|stop|wait no|not that|thats not|thats wrong|that was wrong|"
                         r"i said|i meant|cancel that|not what i)\b")


def _seconds(timestamp: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(timestamp)).timestamp()
    except ValueError:
        return None


def find_corrections(records: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Rule id -> timestamps of its answers the user corrected right afterwards."""
    found: Dict[str, List[str]] = {}
    for record, following in zip(records, records[1:]):
        served = record.get("served_by") or {}
        if served.get("kind") != "learned" or not served.get("rule_id"):
            continue
        start, end = _seconds(record.get("timestamp")), _seconds(following.get("timestamp"))
        if start is None or end is None or not 0 <= end - start <= CORRECTION_WINDOW:
            continue
        words = normalize(following.get("user_query", ""))
        corrected = bool(_CORRECTION.match(" ".join(words)))
        if not corrected:
            before, after = set(normalize(record.get("user_query", ""))), set(words)
            overlap = len(before & after) / max(1, len(before | after))
            then = model_decision(following)
            corrected = (overlap >= 0.5 and then is not None
                         and then["key"] != decision_key(record.get("tool_executed"), record.get("tool_args")))
        if corrected:
            found.setdefault(served["rule_id"], []).append(str(record.get("timestamp", "")))
    return found


def corrected_status(status: Optional[str], corrections: List[str], agreements: List[str]) -> Optional[str]:
    """Apply corrections to a status: one -> watching until two agreements after it; two -> dropped."""
    if not corrections or status is None:
        return status
    if len(corrections) >= 2:
        return "dropped"
    return status if sum(1 for t in agreements if t > corrections[-1]) >= 2 else "shadow"


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
        self.corrections: List[str] = []
        self.agreement_times: List[str] = []

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
        status = ("active" if self.support >= MIN_SUPPORT and self.last_ok else
                  "shadow" if self.support >= SHADOW_SUPPORT else None)
        status = corrected_status(status, self.corrections, self.agreement_times)
        return None if status == "dropped" else status

    def to_dict(self) -> Dict[str, Any]:
        shown = " ".join(self.template)
        return {
            "id": self.id, "kind": "pattern", "name": f"Learned: {shown}", "template": self.template,
            "triggers": [shown], "examples": self.examples[-MAX_EXAMPLES:], "tool": self.tool,
            "args": {**self.const, **{k: "{%s}" % k for k in self.slots}}, "const_args": self.const,
            "slots": self.slots, "support": self.support, "conflicts": self.conflicts, "failures": self.failures,
            "corrections": len(self.corrections), "status": self.status, "last_seen": self.last_seen,
            "action_type": "tool", "is_system": False,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rule":
        rule = cls(list(data["template"]), data["tool"], dict(data.get("slots") or {}), dict(data.get("const_args") or {}))
        rule.support, rule.conflicts = int(data.get("support", 0)), int(data.get("conflicts", 0))
        rule.failures, rule.examples = int(data.get("failures", 0)), list(data.get("examples") or [])
        rule.id = data.get("id", rule.id)
        return rule


# ---- Rules Claude Code writes ("authored") ---------------------------------------------------------
#
# The background learner (pattern_learner.py) has Claude Code generalize one request into a rule:
#
#   {"templates": ["set a timer for {n} minutes", "{n} minute timer"],
#    "slots": {"n": {"kind": "number"}},
#    "tool": "set_timer", "args": {"duration": "{n}m"}}
#
# Slots: number (digits), app (an installed app), enum ({"values": {"louder": "5%+", ...}}: only
# these words). Argument strings fill in slot values; an argument that is exactly "{slot}" keeps the
# slot's type. An authored rule is verified like a mined one, but trusted after fewer agreements
# (AUTHORED_MIN_SUPPORT), since it was written from the request it was checked against.
#
# Context rules add "needs" (helpers to read) and a "resolver" (Python that turns the slots and that
# context into the arguments; see context_runtime.py): "close that" -> the app in front. The model
# can't see that context, so agreeing with it proves little: a context rule is active as soon as its
# helpers are available, and corrections (find_corrections) send it back to watching or drop it.

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _template_tokens(template: str) -> List[str]:
    """Template text -> tokens, with {slot} kept as one token and the rest normalized like requests."""
    tokens: List[str] = []
    for part in re.split(r"(\{\w+\})", str(template)):
        tokens += [part] if _PLACEHOLDER.fullmatch(part) else tokenize(part)
    return tokens


def authored_problems(spec: Dict[str, Any], required_args: Dict[str, List[str]],
                      helper_status: Optional[Callable[[str], str]] = None) -> List[str]:
    """
    Why this authored rule can't be used (empty when it can). helper_status(name) -> built_in |
    approved | pending | unknown; without it only built-in helpers are known.
    """
    problems = []
    resolver = spec.get("resolver")
    if resolver is not None:
        from daemon.agent.context_runtime import BUILTIN_HELPERS, ContextRuntime, resolver_problems
        status_of = helper_status or (lambda name: "built_in" if name in BUILTIN_HELPERS else "unknown")
        problems += [f"resolver: {p}" for p in resolver_problems(str(resolver))]
        needs = spec.get("needs") or []
        if not isinstance(needs, list):
            problems.append("needs must be a list of helper names.")
            needs = []
        for need in needs:
            if status_of(ContextRuntime.need_name(need)) == "unknown":
                problems.append(f"needs unknown helper '{ContextRuntime.need_name(need)}' (propose it first).")
    tool = spec.get("tool")
    if tool not in required_args:
        problems.append(f"'{tool}' isn't a Jarvis tool.")
    elif tool in NEVER_LEARN:
        problems.append(f"'{tool}' is never replayed without the model.")
    templates = spec.get("templates")
    if not isinstance(templates, list) or not 1 <= len(templates) <= MAX_TEMPLATES:
        return problems + [f"templates must be a list of 1-{MAX_TEMPLATES} phrasings."]
    slots = spec.get("slots") or {}
    if not isinstance(slots, dict):
        return problems + ["slots must be an object."]
    for name, slot in slots.items():
        kind = (slot or {}).get("kind")
        if kind not in SLOT_KINDS:
            problems.append(f"slot '{name}' kind must be one of {SLOT_KINDS}.")
        if kind == "enum" and not ((slot or {}).get("values") and isinstance(slot["values"], dict)):
            problems.append(f"enum slot '{name}' needs values: {{spoken words: argument value}}.")
    for template in templates:
        tokens = _template_tokens(template)
        used = {_slot_name(t) for t in tokens} - {None}
        if not any(_slot_name(t) is None for t in tokens):
            problems.append(f"\"{template}\" needs at least one fixed word.")
        if used - set(slots):
            problems.append(f"\"{template}\" uses undeclared slots {sorted(used - set(slots))}.")
        if any(_slot_name(a) and _slot_name(b) for a, b in zip(tokens, tokens[1:])):
            problems.append(f"\"{template}\" has two slots in a row, which is ambiguous.")
    args = spec.get("args")
    if not isinstance(args, dict):
        return problems + ["args must be an object."]
    for key, value in args.items():
        for name in _PLACEHOLDER.findall(value) if isinstance(value, str) else []:
            if name not in slots:
                problems.append(f"argument '{key}' uses undeclared slot '{name}'.")
    if resolver is None:  # a resolver may fill arguments and use slots itself
        for key in required_args.get(tool, []):
            if args.get(key) in (None, ""):
                problems.append(f"'{tool}' needs the argument '{key}'.")
        for name in slots:
            if not any(name in _PLACEHOLDER.findall(v) for v in args.values() if isinstance(v, str)):
                problems.append(f"slot '{name}' isn't used in any argument.")
    return problems


def _enum_values(slot: Dict[str, Any]) -> Dict[str, Any]:
    return {" ".join(tokenize(k)): v for k, v in (slot.get("values") or {}).items()}


def predict_authored(spec: Dict[str, Any], tokens: List[str], app_exists: Callable[[str], bool]) -> Optional[Dict[str, Any]]:
    """
    The tool call an authored rule makes for this request ({"tool", "args", "slots"}), or None if no
    template matches. For a context rule this is the call before its resolver runs.
    """
    slots = spec.get("slots") or {}

    def slot_ok(name: str, value: str) -> bool:
        kind = slots.get(name, {}).get("kind")
        if kind == "number":
            return bool(_NUMBER.fullmatch(value))
        if kind == "app":
            return app_exists(value)
        return value in _enum_values(slots.get(name, {}))

    for template in spec.get("templates") or []:
        found = match_template(_template_tokens(template), tokens, slot_ok)
        if found is None:
            continue

        def value_of(name: str) -> Any:
            slot, raw = slots[name], found[name]
            if slot.get("kind") == "enum":
                return _enum_values(slot)[raw]
            if slot.get("kind") == "number" and not raw.endswith("%"):
                return int(float(raw)) if float(raw).is_integer() else float(raw)
            return raw

        args = {}
        for key, value in (spec.get("args") or {}).items():
            if isinstance(value, str) and _PLACEHOLDER.fullmatch(value):
                args[key] = value_of(_PLACEHOLDER.fullmatch(value).group(1))
            elif isinstance(value, str):
                args[key] = _PLACEHOLDER.sub(lambda m: str(value_of(m.group(1))), value)
            else:
                args[key] = value
        return {"tool": spec["tool"], "args": args, "slots": {name: value_of(name) for name in found}}
    return None


def authored_id(spec: Dict[str, Any]) -> str:
    key = json.dumps([sorted(spec.get("templates") or []), spec.get("tool"), spec.get("args")], sort_keys=True, default=str)
    return "authored_" + hashlib.sha1(key.encode()).hexdigest()[:10]


def evaluate_authored(spec: Dict[str, Any], decided: List[Tuple[Dict[str, Any], List[str], Dict[str, Any]]],
                      app_exists: Callable[[str], bool], corrections: List[str] = (),
                      shadow: List[Tuple[str, bool]] = (), helpers_ready: bool = True) -> Dict[str, Any]:
    """
    Check an authored rule against the log. Plain rules: every past model decision they would have
    made. Context rules: the log doesn't hold the context they'd have read, so only corrections and
    their logged predictions while watching (shadow: (timestamp, agreed with the model)) count.
    """
    if spec.get("resolver") is not None:
        agreements = [t for t, agreed in shadow if agreed]
        status = corrected_status("active" if helpers_ready else "waiting", list(corrections), agreements)
        return {"support": len(agreements), "failures": 0, "conflicts": [], "examples": [], "status": status,
                "last_seen": max([t for t, _ in shadow], default="")}
    support = failures = 0
    support_times: List[str] = []
    last_ok = True
    examples: List[str] = []
    conflicts: List[Dict[str, Any]] = []
    last_seen = ""
    for record, tokens, decision in decided:
        prediction = predict_authored(spec, tokens, app_exists)
        if prediction is None:
            continue
        query = record.get("user_query", "")
        if decision["key"] != decision_key(prediction["tool"], prediction["args"]):
            conflicts.append({"request": query, "rule_would": prediction,
                              "model_did": {"tool": decision["tool"], "args": decision["args"]}})
            continue
        if _succeeded(record):
            support, last_ok = support + 1, True
            support_times.append(str(record.get("timestamp", "")))
            if query not in examples:
                examples.append(query)
        else:
            failures, last_ok = failures + 1, False
        last_seen = record.get("timestamp", last_seen)
    status = ("conflicted" if conflicts else
              corrected_status("active" if support >= AUTHORED_MIN_SUPPORT and last_ok else "shadow",
                               list(corrections), support_times))
    return {"support": support, "failures": failures, "conflicts": conflicts, "examples": examples[-MAX_EXAMPLES:],
            "status": status, "last_seen": last_seen}


def decided_records(records: Iterable[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], List[str], Dict[str, Any]]]:
    """(record, normalized words, model decision) for every turn the model decided."""
    out = []
    for record in records:
        decision = model_decision(record)
        tokens = normalize(record.get("user_query", ""))
        if decision is not None and tokens:
            out.append((record, tokens, decision))
    return out


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
         rejected: Iterable[str] = (), authored: Iterable[Dict[str, Any]] = (),
         helper_status: Optional[Callable[[str], str]] = None) -> List[Dict[str, Any]]:
    """
    Every rule the log supports, active and shadow, plus noise rules.
      required_args      tool id -> its required arguments (only these tools can be learned)
      app_exists         whether an app name is installed (fills "{app_name}" slots)
      handled_elsewhere  the request already has a built-in shortcut (learning it would duplicate it)
      rejected           rule ids the user deleted: never brought back
      authored           rules Claude Code wrote (pattern_learner.py), re-verified here like the rest
      helper_status      context helper name -> built_in | approved | pending | unknown
    """
    records = list(records)
    corrections = find_corrections(records)
    rejected = set(rejected)
    app_cache: Dict[str, bool] = {}

    def has_app(name: str) -> bool:
        if name not in app_cache:
            try:
                app_cache[name] = bool(app_exists(name))
            except Exception:
                app_cache[name] = False
        return app_cache[name]

    decided = decided_records(records)

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
                rule.agreement_times.append(str(record.get("timestamp", "")))
                if query not in rule.examples:
                    rule.examples.append(query)
            else:
                rule.failures += 1
                rule.last_ok = False
            rule.last_seen = record.get("timestamp", rule.last_seen)
        rule.corrections = corrections.get(rule.id, [])

    rules = [r.to_dict() for r in candidates.values() if r.status and r.id not in rejected]

    # Rules Claude Code wrote: plain ones kept while every decision they cover agrees; context ones
    # while nobody corrects them. "dropped" tells the manager to retire them for good.
    shadow: Dict[str, List[Tuple[str, bool]]] = {}
    for record in records:
        predicted = record.get("pattern_prediction") or {}
        decision = model_decision(record)
        if predicted.get("rule_id") and decision is not None:
            agreed = decision["key"] == decision_key(predicted.get("tool"), predicted.get("args"))
            shadow.setdefault(predicted["rule_id"], []).append((str(record.get("timestamp", "")), agreed))
    for spec in authored:
        rule_id = spec.get("id") or authored_id(spec)
        if rule_id in rejected or authored_problems(spec, required_args, helper_status):
            continue
        needs = spec.get("needs") or []
        from daemon.agent.context_runtime import ContextRuntime
        ready = all((helper_status or (lambda n: "built_in"))(ContextRuntime.need_name(n)) in ("built_in", "approved")
                    for n in needs)
        result = evaluate_authored(spec, decided, has_app, corrections.get(rule_id, []), shadow.get(rule_id, []), ready)
        if result["status"] == "conflicted":
            continue
        templates = list(spec["templates"])
        rules.append({
            "id": rule_id, "kind": "authored", "name": f"Learned: {templates[0]}", "templates": templates,
            "triggers": templates, "slots": spec.get("slots") or {}, "tool": spec["tool"], "args": spec["args"],
            "needs": needs, "resolver": spec.get("resolver"), "context_rule": spec.get("resolver") is not None,
            "examples": result["examples"] or [spec.get("source_request", "")], "support": result["support"],
            "conflicts": 0, "corrections": len(corrections.get(rule_id, [])), "failures": result["failures"],
            "status": result["status"], "last_seen": result["last_seen"], "author": "claude_code",
            "reason": spec.get("reason", ""), "action_type": "tool", "is_system": False,
        })

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
                heard_confidence: Optional[float] = None, runtime: Any = None) -> Optional[Dict[str, Any]]:
    """
    The rule this request matches, as {"rule", "mode": active|shadow|ignore, "tool", "args"} (plus
    "context" for a context rule), or None. Plain templates win over ones with slots; a noise rule needs
    this turn's confidence to be low too; a context rule needs the runtime (ContextRuntime) and a
    resolver that's sure. heard_confidence is None for typed requests.
    """
    tokens = normalize(query)
    if not tokens:
        return None
    text = " ".join(tokens)
    for data in rules:
        if data.get("kind") == "noise" and data.get("triggers") == [text]:
            if heard_confidence is not None and heard_confidence < NOISE_CONFIDENCE:
                return {"rule": data, "mode": "ignore", "tool": "none", "args": {}}
    patterns = [d for d in rules if d.get("kind") in ("pattern", "authored") and d.get("status") in ("active", "shadow")]
    patterns.sort(key=lambda d: (len(d.get("slots") or {}), d.get("status") != "active"))
    for data in patterns:
        if data["kind"] == "pattern":
            prediction = Rule.from_dict(data).predict(tokens, app_exists)
            if prediction is not None:
                return {"rule": data, "mode": data["status"], **prediction}
            continue
        prediction = predict_authored(data, tokens, app_exists)
        if prediction is None:
            continue
        if data.get("resolver") is None:
            return {"rule": data, "mode": data["status"], "tool": prediction["tool"], "args": prediction["args"]}
        if runtime is None:
            continue
        resolved = runtime.resolve(data, prediction["slots"], prediction["args"], query)
        if resolved is not None:
            return {"rule": data, "mode": data["status"], **resolved}
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
