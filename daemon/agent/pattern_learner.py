"""
Background learning: after the model handles a request no shortcut knew, decide whether it's worth
caching and, if so, have Claude Code write the rule. Nobody is asked anything.

    turn handled by the model
      -> pre-filter (no model call): one safe tool, it worked, nothing already covers it, not graded before
      -> grader (one cheap model call): is the tool call decided by the words, plus context Jarvis can
         look up (the app in front, what's playing...), and will it recur?
      -> Claude Code, locked down: it can read, and use three Jarvis tools:
           test_pattern    try a rule against the transcript log, sample phrasings and sample context
           save_pattern    keep it (refused if it contradicts the log, or a context rule fails its own examples)
           propose_helper  ask for a new read-only context helper (waits for the user's approval)
      -> the miner keeps re-checking the rule after every turn (pattern_miner.py):
           plain rules    answer once the model has made the same call one more time; any
                          disagreement drops them
           context rules  answer right away (the model can't see that context, so it's no judge);
                          a correction from the user sends them back to watching, two drop them

Rules are data plus, for context rules, a resolver that only computes from context Jarvis looked up
(context_runtime.py). Code that can act or reach the system - skills and new helpers - always waits
for the user's approval.
"""

import json
import queue
import threading
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from daemon.agent import pattern_miner as pm

DAILY_LIMIT = 20          # Claude Code runs per day, at most
SESSION_TIMEOUT = 5 * 60  # seconds for one Claude Code run
READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "LS", "TodoWrite"}
JARVIS_TOOLS = ("test_pattern", "save_pattern", "propose_helper")

GRADER_SYSTEM = """You decide whether a voice assistant should cache how it handled a request, so the
same request is answered next time without asking the language model. Reply with ONLY a JSON object:
{"cache": true or false, "context": true or false, "reason": "<one short sentence>"}

Judge the tool call, not its result. "Take a screenshot" is cacheable: the call is always the same,
even though the picture differs. "Turn the volume down" is cacheable: it lowers the volume from
wherever it is, every time. A cached request still runs its tool every time (so "what time is it" ->
get_current_time stays correct); only the choice of tool and arguments is reused.

A cached rule can also look up context when it runs: the app in front, running apps, what's
playing, the volume, what Jarvis did on the previous request, the clipboard, the newest files in a
folder, the time. So "close that" (the app in front), "skip this song" (what's playing) or "do that
again" (the previous action) are cacheable with "context": true. Context that isn't in that list but
can be looked up read-only on the computer (which apps were opened recently, the folder open in the
file manager, today's calendar) also counts: a new helper can be written for it.

Cache when ALL of these hold:
- The words, plus context like the above, decide the tool and its arguments.
- Making that call is the right response every time these words are said, and it is cheap and
  harmless to repeat.
- The user is likely to say this, or the same thing with different values, again: routine commands
  such as timers, volume, apps, media, focus modes, toggles, their own skills.
Don't cache one-off tasks, or anything that needed judgment or the conversation's meaning beyond
"what Jarvis just did"."""

LEARNER_RULES = """You write cache rules for Jarvis, a voice assistant. A rule lets Jarvis answer a
request without its language model by matching the whole request against templates and calling a
tool it already has. You are running in the background: nobody will answer questions or approve
steps. You can read files and use mcp__jarvis__test_pattern, mcp__jarvis__save_pattern and
mcp__jarvis__propose_helper; other tools are switched off.

A rule is a JSON object:
  templates  1-8 phrasings with {slots}, written the way people say the request. Requests are
             compared after lowercasing, removing punctuation, a leading "hey Jarvis", and polite
             filler at the edges ("can you", "please", "for me"), so leave those out.
  slots      {"name": {"kind": "number"}} digits; {"kind": "app"} an installed app's name;
             {"kind": "enum", "values": {"spoken words": <argument value>}} only these words
  tool       the tool the model used
  args       the arguments, with "{slot}" where a value comes from the request ("{n}m" works);
             an argument that is exactly "{slot}" keeps the slot's type
  reason     one sentence: why this is safe to cache

Context rules, for requests that depend on the moment ("close that", "skip this song", "turn it
down a bit", "do that again"), add:
  needs      helpers to read, from the catalog in the task: ["front_app"] or
             [{"helper": "recent_files", "args": {"folder": "~/Downloads", "limit": 3}}]
  resolver   Python source defining resolve(slots, ctx). slots holds the slot values heard; ctx holds
             each need by name, plus "request" (the words) and "base_args" (args with slots filled).
             Return {"args": {...}} (merged over base_args; add "tool" to call a different tool) or
             None when unsure, and the model answers instead. It only computes: imports are limited
             to json, re, math, datetime, difflib, statistics, string, itertools and collections;
             no files, no eval, no attribute names starting with "_".
  examples   required for context rules: 1-6 {"request", "context", "expect": {"tool", "args"}}
             cases, including the request you're writing it for. save_pattern runs the resolver
             on each and refuses the rule if any comes out differently.
If a rule needs context no helper gives, call propose_helper: a read-only Python script that looks
it up and prints JSON. The user approves it later; save the rule now (it waits for the helper).

Generalize the way the user will vary the request (other numbers, other apps, close rewordings),
but every phrasing a template matches must mean exactly this action. When unsure, cover less, or
have the resolver return None. Use test_pattern with phrasings (and, for context rules, sample
contexts) that should and should not match, fix what it reports, then save_pattern once. If the
request can't be cached safely, don't save anything. Finish with one sentence saying what you saved
or why not."""

TEST_PATTERN_TOOL = {
    "name": "test_pattern",
    "description": ("Check a cache rule without saving it: lists problems with it, the past requests it would have "
                    "handled and whether the model did the same thing, and what it does for sample phrasings. For a "
                    "context rule, each phrasing is run with every sample context you give, and once with the live "
                    "context right now."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "rule": {"type": "object", "description": "templates, slots, tool, args, reason; for context rules "
                                                      "also needs, resolver, examples (see the rules)."},
            "phrases": {"type": "array", "items": {"type": "string"},
                        "description": "Sample requests to try: ones that should match and ones that shouldn't."},
            "contexts": {"type": "array", "items": {"type": "object"},
                         "description": "Context rules: sample ctx values (keyed by need name) to run the resolver with."},
        },
        "required": ["rule"],
    },
}
SAVE_PATTERN_TOOL = {
    "name": "save_pattern",
    "description": ("Save a cache rule. Refused if it has problems, contradicts what the model did for a past request "
                    "it matches, or (context rules) its resolver gets one of its examples wrong."),
    "inputSchema": {"type": "object", "properties": {"rule": {"type": "object"}}, "required": ["rule"]},
}


class PatternLearner:
    def __init__(self, fast_paths, registry, records: Callable[[], List[Dict[str, Any]]],
                 grader: Callable[[], Any], claude_model: Callable[[], str] = lambda: "haiku",
                 enabled: Callable[[], bool] = lambda: True, on_saved: Optional[Callable[[], None]] = None,
                 app_exists: Optional[Callable[[str], bool]] = None, session_factory=None,
                 daily_limit: int = DAILY_LIMIT, runtime: Any = None,
                 on_helper_proposed: Optional[Callable[[Dict[str, Any]], None]] = None):
        """
        fast_paths          the FastPathManager (rules, grades, matching)
        registry            the ToolRegistry (which tools exist, their schemas)
        records             reads the transcript log
        grader              returns the LLM provider used for grading (the memory model)
        on_saved            called after a rule is saved (re-mine, so it shows up right away)
        session_factory     builds the Claude Code session (tests pass a fake)
        runtime             the ContextRuntime (helpers, resolvers); defaults to fast_paths.runtime
        on_helper_proposed  called with a helper Claude Code proposed (it waits for the user's approval)
        """
        self.fast_paths, self.registry, self.records = fast_paths, registry, records
        self.grader, self.claude_model, self.enabled, self.on_saved = grader, claude_model, enabled, on_saved
        self.daily_limit = daily_limit
        self.on_helper_proposed = on_helper_proposed
        self._runtime = runtime
        self._session_factory = session_factory
        self._app_exists = app_exists
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._runs = (date.today(), 0)
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def runtime(self):
        if self._runtime is None:
            self._runtime = getattr(self.fast_paths, "runtime", None)
        if self._runtime is None:
            from daemon.agent.context_runtime import ContextRuntime
            self._runtime = ContextRuntime()
        return self._runtime

    # ---- Entry point ----------------------------------------------------------------------------

    def consider(self, record: Dict[str, Any]) -> bool:
        """Queue a just-logged turn for background learning. False when it isn't a candidate."""
        reason = self.skip_reason(record)
        if reason:
            print(f"[PatternLearner] Not learning \"{record.get('user_query', '')}\": {reason}", flush=True)
            return False
        self._queue.put(record)
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, daemon=True, name="JarvisPatternLearner")
                self._worker.start()
        return True

    def skip_reason(self, record: Dict[str, Any]) -> str:
        """Why this turn isn't worth a model call to grade ("" when it is)."""
        if not self.enabled():
            return "background learning is off"
        if (record.get("served_by") or {}).get("kind") != "llm":
            return "the model didn't answer it"
        if record.get("pattern_prediction"):
            return "a rule is already learning it"
        decision = pm.model_decision(record)
        if decision is None or decision["multi"] or decision["tool"] == "none":
            return "no single tool call to cache"
        if decision["tool"] in pm.NEVER_LEARN or self.registry.get_tool(decision["tool"]) is None:
            return f"'{decision['tool']}' is never cached"
        if not pm._succeeded(record):
            return "it didn't work"
        words = " ".join(pm.normalize(record.get("user_query", "")))
        if not words:
            return "nothing to match"
        if words in self.fast_paths.graded:
            return "already graded"
        if self.fast_paths.match_learned(record.get("user_query", ""), app_exists=self.app_exists) is not None:
            return "a learned rule covers it"
        return ""

    # ---- Worker ---------------------------------------------------------------------------------

    def _work(self):
        while True:
            try:
                record = self._queue.get(timeout=5)
            except queue.Empty:
                return
            try:
                self.learn(record)
            except Exception as err:
                print(f"[PatternLearner] Learning from \"{record.get('user_query', '')}\" failed: {err}", flush=True)

    def learn(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Grade one turn and, if it's worth it, have Claude Code write the rule. Returns the saved rule."""
        words = " ".join(pm.normalize(record.get("user_query", "")))
        verdict = self.grade(record)
        self.fast_paths.record_grade(words, {**verdict, "request": record.get("user_query", "")})
        kind = "with context" if verdict.get("context") else "plain"
        print(f"[PatternLearner] \"{record.get('user_query', '')}\": "
              f"{f'worth caching ({kind})' if verdict['cache'] else 'not caching'} ({verdict['reason']})", flush=True)
        if not verdict["cache"]:
            return None
        today = date.today()
        with self._lock:
            if self._runs[0] != today:
                self._runs = (today, 0)
            if self._runs[1] >= self.daily_limit:
                print(f"[PatternLearner] Daily limit of {self.daily_limit} Claude Code runs reached.", flush=True)
                return None
            self._runs = (today, self._runs[1] + 1)
        return self.remember(record, needs_context=bool(verdict.get("context")))

    # ---- Grading --------------------------------------------------------------------------------

    def grade(self, record: Dict[str, Any]) -> Dict[str, Any]:
        decision = pm.model_decision(record) or {}
        tool = self.registry.get_tool(decision.get("tool", ""))
        prompt = (f"Request (spoken): {record.get('user_query', '')!r}\n"
                  f"Tool the model called: {decision.get('tool')} with arguments {json.dumps(decision.get('args', {}))}\n"
                  f"What that tool does: {tool.description if tool else 'unknown'}\n"
                  "Should this be cached?")
        try:
            provider = self.grader()
            reply = provider.process_voice_query(prompt, [], GRADER_SYSTEM) if provider else {}
        except Exception as err:
            return {"cache": False, "context": False, "reason": f"grader failed: {err}"}
        if not isinstance(reply, dict) or not isinstance(reply.get("cache"), bool):
            return {"cache": False, "context": False, "reason": "the grader didn't answer in the expected form"}
        return {"cache": reply["cache"], "context": bool(reply.get("context")), "reason": str(reply.get("reason", ""))[:200]}

    # ---- Claude Code ----------------------------------------------------------------------------

    def app_exists(self, name: str) -> bool:
        if self._app_exists is not None:
            return self._app_exists(name)
        from daemon.tools.app_scanner import get_app_scanner
        return get_app_scanner().find_app(name) is not None

    def required_args(self) -> Dict[str, List[str]]:
        return {t.id: list(t.parameters.get("required", [])) for t in self.registry.list_tools()}

    def tools_for_claude(self) -> List[Dict[str, Any]]:
        from daemon.agent.context_runtime import PROPOSE_HELPER_TOOL
        return [TEST_PATTERN_TOOL, SAVE_PATTERN_TOOL, PROPOSE_HELPER_TOOL]

    def remember(self, record: Dict[str, Any], needs_context: bool = False) -> Optional[Dict[str, Any]]:
        decision = pm.model_decision(record) or {}
        tool = self.registry.get_tool(decision["tool"])
        catalog = "\n".join(f"  {h['name']} ({h['status']}): {h['description']}" for h in self.runtime.catalog())
        prompt = (f"The user said: {record.get('user_query', '')!r}\n"
                  f"Jarvis's model handled it by calling the tool {decision['tool']!r} with "
                  f"{json.dumps(decision['args'])}, and it worked.\n"
                  f"Tool description: {tool.description if tool else ''}\n"
                  f"Tool arguments (JSON Schema): {json.dumps(tool.parameters if tool else {})}\n"
                  + ("The grader thinks this depends on context, so it probably needs a context rule.\n" if needs_context else "")
                  + f"Context helpers:\n{catalog}\n"
                  "Write a cache rule for this request and the ways the user will vary it, test it, and save it.")
        saved: Dict[str, Any] = {}

        def decide(name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
            if name in READ_ONLY_TOOLS or name in {f"mcp__jarvis__{t}" for t in JARVIS_TOOLS}:
                return {"behavior": "allow", "updatedInput": tool_input}
            return {"behavior": "deny", "message": "Not available while learning in the background."}

        def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
            if name == "test_pattern":
                result = self.test(args.get("rule") or {}, args.get("phrases") or [], args.get("contexts") or [])
                return {"text": json.dumps(result, default=str), "is_error": False}
            if name == "save_pattern":
                result = self.save(args.get("rule") or {}, record)
                if result.get("saved"):
                    saved.update(result["rule"])
                return {"text": json.dumps(result, default=str), "is_error": not result.get("saved")}
            if name == "propose_helper":
                result = self.propose_helper(args, record)
                return {"text": json.dumps(result, default=str), "is_error": not result.get("saved")}
            return {"text": f"'{name}' isn't available here.", "is_error": True}

        session = self._make_session(prompt, decide, call_tool)
        print(f"[PatternLearner] Asking Claude Code to write a rule for \"{record.get('user_query', '')}\"...", flush=True)
        outcome = session.run()
        print(f"[PatternLearner] Claude Code: {str(outcome.get('text', '')).strip()[:200]}", flush=True)
        return saved or None

    def _make_session(self, prompt: str, decide, call_tool):
        if self._session_factory is not None:
            return self._session_factory(prompt, decide, call_tool)
        from daemon.agent.claude_code_agent import ClaudeCodeSession
        return ClaudeCodeSession(prompt, self.claude_model(), decide, lambda *_: None, threading.Event(),
                                 tools=self.tools_for_claude, call_tool=call_tool, rules=LEARNER_RULES,
                                 timeout=SESSION_TIMEOUT)

    # ---- The tools Claude Code gets -------------------------------------------------------------

    def _problems(self, rule: Dict[str, Any]) -> List[str]:
        return pm.authored_problems(rule, self.required_args(), self.runtime.helper_status)

    def _try_resolver(self, rule: Dict[str, Any], request: str, ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Run a context rule on one request: the call it makes, or why it doesn't match / declines."""
        from daemon.agent.context_runtime import run_resolver
        base = pm.predict_authored(rule, pm.normalize(request), self.app_exists)
        if base is None:
            return {"matches": False}
        if ctx is None:
            ctx = self.runtime.gather(rule.get("needs") or [])
        out = run_resolver(rule.get("resolver", ""), base["slots"], {**ctx, "request": request, "base_args": base["args"]})
        if "error" in out:
            return {"matches": True, "error": out["error"], "context": ctx}
        result = out.get("result")
        if result is None:
            return {"matches": True, "declined": True, "context": ctx}
        if not isinstance(result, dict) or not isinstance(result.get("args", {}), dict):
            return {"matches": True, "error": "resolve() must return {\"args\": {...}} or None", "context": ctx}
        return {"matches": True, "context": ctx,
                "would_call": {"tool": result.get("tool") or rule["tool"], "args": {**base["args"], **(result.get("args") or {})}}}

    def test(self, rule: Dict[str, Any], phrases: List[str], contexts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        problems = self._problems(rule)
        if problems:
            return {"problems": problems}
        tried = []
        if rule.get("resolver") is not None:
            for phrase in phrases[:12]:
                for ctx in list(contexts or [])[:6] + [None]:  # None: the live context right now
                    tried.append({"phrase": phrase, "context_given": ctx is not None, **self._try_resolver(rule, phrase, ctx)})
            return {"problems": [], "runs": tried}
        result = pm.evaluate_authored(rule, pm.decided_records(self.records()), self.app_exists)
        for phrase in phrases[:20]:
            prediction = pm.predict_authored(rule, pm.normalize(phrase), self.app_exists)
            tried.append({"phrase": phrase, "matches": prediction is not None,
                          **({"would_call": {"tool": prediction["tool"], "args": prediction["args"]}} if prediction else {})})
        return {"problems": [], "past_requests_it_matches": result["support"] + len(result["conflicts"]),
                "agreeing": result["support"], "contradictions": result["conflicts"][:10], "phrases": tried}

    def save(self, rule: Dict[str, Any], origin: Dict[str, Any]) -> Dict[str, Any]:
        problems = self._problems(rule)
        if problems:
            return {"saved": False, "problems": problems}
        origin_tokens = pm.normalize(origin.get("user_query", ""))
        if rule.get("resolver") is not None:
            failures = self._check_examples(rule, origin)
            if failures:
                return {"saved": False, "problems": failures}
        else:
            result = pm.evaluate_authored(rule, pm.decided_records(self.records()), self.app_exists)
            if result["conflicts"]:
                return {"saved": False, "problems": ["It contradicts what the model did for these requests."],
                        "contradictions": result["conflicts"][:10]}
            origin_decision = pm.model_decision(origin) or {}
            predicted = pm.predict_authored(rule, origin_tokens, self.app_exists)
            if predicted is None or pm.decision_key(predicted["tool"], predicted["args"]) != origin_decision.get("key"):
                return {"saved": False, "problems": ["It doesn't reproduce the request it was written for: "
                                                     f"{origin.get('user_query', '')!r} -> {predicted}."]}
        spec = {"templates": list(rule["templates"]), "slots": rule.get("slots") or {}, "tool": rule["tool"],
                "args": rule["args"], "reason": str(rule.get("reason", ""))[:300],
                "source_request": origin.get("user_query", "")}
        if rule.get("resolver") is not None:
            spec.update(needs=list(rule.get("needs") or []), resolver=rule["resolver"], examples=rule["examples"])
        spec["id"] = pm.authored_id(spec)
        if spec["id"] in self.fast_paths.rejected:
            return {"saved": False, "problems": ["The user deleted this rule before; don't recreate it."]}
        self.fast_paths.add_authored(spec)
        waiting = [self.runtime.need_name(n) for n in spec.get("needs", [])
                   if self.runtime.helper_status(self.runtime.need_name(n)) == "pending"]
        print(f"[PatternLearner] Saved rule {spec['id']}: {spec['templates']} -> {spec['tool']} {json.dumps(spec['args'])}"
              + (" (context rule)" if "resolver" in spec else "")
              + (f", waiting for helpers {waiting}" if waiting else ""), flush=True)
        if self.on_saved:
            try:
                self.on_saved()
            except Exception as err:
                print(f"[PatternLearner] Re-mining after save failed: {err}", flush=True)
        if "resolver" in spec:
            status = (f"Saved. It starts once the user approves the helpers {waiting}." if waiting else
                      "Saved. It answers right away; if the user corrects it, it goes back to watching.")
        else:
            status = "Saved. It answers instead of the model once the model makes the same call once more."
        return {"saved": True, "rule": spec, "status": status}

    def _check_examples(self, rule: Dict[str, Any], origin: Dict[str, Any]) -> List[str]:
        """A context rule's own examples, run through its resolver: every one must come out as expected."""
        examples = rule.get("examples")
        if not isinstance(examples, list) or not 1 <= len(examples) <= 6:
            return ["Context rules need 1-6 examples: {\"request\", \"context\", \"expect\": {\"tool\", \"args\"}}."]
        origin_words = pm.normalize(origin.get("user_query", ""))
        if not any(pm.normalize(str(e.get("request", ""))) == origin_words for e in examples if isinstance(e, dict)):
            return [f"Include an example for the request this is for: {origin.get('user_query', '')!r}."]
        failures = []
        for example in examples:
            if not isinstance(example, dict) or not isinstance(example.get("expect"), dict):
                failures.append(f"Malformed example: {example!r}")
                continue
            got = self._try_resolver(rule, str(example.get("request", "")), dict(example.get("context") or {}))
            expect = example["expect"]
            want = pm.decision_key(expect.get("tool", rule["tool"]), expect.get("args") or {})
            call = got.get("would_call")
            if call is None or pm.decision_key(call["tool"], call["args"]) != want:
                failures.append(f"Example {example.get('request')!r} expected {expect}, got "
                                f"{call or ('no match' if not got.get('matches') else got.get('error') or 'None (declined)')}.")
        return failures

    def propose_helper(self, spec: Dict[str, Any], origin: Dict[str, Any]) -> Dict[str, Any]:
        from daemon.tools.skills import SkillError
        try:
            helper = self.runtime.helpers.save(spec, source_request=origin.get("user_query", ""))
        except SkillError as err:
            return {"saved": False, "problems": [str(err)]}
        print(f"[PatternLearner] Claude Code proposed context helper '{helper['id']}'; waiting for approval.", flush=True)
        if self.on_helper_proposed:
            try:
                self.on_helper_proposed(helper)
            except Exception as err:
                print(f"[PatternLearner] Helper notification failed: {err}", flush=True)
        return {"saved": True, "status": f"Proposed '{helper['id']}'. It runs once the user approves it; rules can "
                                         "already name it in needs and will wait for it."}
