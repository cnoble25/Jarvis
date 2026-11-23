"""
Agent Orchestrator & LLM Router (Sub-Task 2.3 & Story 2.3)
Connects pluggable LLM Providers (Ollama, Gemini, Claude, OpenAI) with Claude Code Meta-Tools,
Custom JSON Tools, Multi-turn Conversation Chain History, and the Voice Loop.
"""

import json
import re
import threading
import time
import uuid
from typing import Callable, Dict, Any, Optional, List
from daemon.tools.registry import ToolRegistry
from daemon.tools.execution_engine import ExecutionEngine
from daemon.memory.transcript_logger import TranscriptLogger
from daemon.memory.profiler_agent import load_user_profile
from daemon.providers.base import VOLATILE_CONTEXT_TAG, BaseLLMProvider, BaseTTSProvider
from daemon.providers.llm.ollama_llm_provider import OllamaLLMProvider
from daemon.agent.fast_path_manager import FastPathManager
from daemon.agent.pattern_miner import clean_args
from daemon.agent.tasks import BackgroundTask, TaskBoard, describe_step
from daemon.agent.approval import approval_needed, is_approval, is_refusal
from daemon.os_interface import get_os

# Background tasks: a request still working after PROMOTE_AFTER seconds, or about to run one of
# BACKGROUND_TOOLS, gets a quick spoken reply and keeps going in the background.
PROMOTE_AFTER = 4.0
COMMAND_GRACE = 1.5
APPROVAL_TIMEOUT = 300  # seconds a step waits for the user's OK
BACKGROUND_TOOLS = {"execute_terminal_command", "Bash", "Edit", "claude_code_task"}
BACKGROUND_MAX_STEPS = 6
BACKGROUND_COMMAND_TIMEOUT = 300
OBSERVATION_CHARS = 2000
CLAUDE_FOLLOWUP_SECONDS = 120
JARVIS_ADDRESS = re.compile(r"^\s*(?:(?:hey|ok(?:ay)?|yo)[\s,]+)?jarvis\b", re.IGNORECASE)
# Claude Code tools that only read: they run without asking (as Jarvis's own searches do).
# Jarvis tools not offered to Claude Code: it has its own shell, web search and file search.
CLAUDE_CODE_SKIPS = {"execute_terminal_command", "claude_code_task", "web_search", "search_files"}
CLAUDE_CODE_READ_ONLY = {"Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "TodoWrite", "Task", "Agent", "NotebookRead"}
INSPECTION_TOOLS = {"web_search", "get_current_time", "system_status", "search_files", "View", "Grep"}
_TASK_WORDS = r"the\s+(?:task|install\w*|download\w*|command)"
# "Cancel", "never mind", "stop that", "stop the task" (a bare "stop" is left to media controls).
CANCEL_PATTERN = re.compile(
    r"^\s*(?:(?:hey\s+)?jarvis[\s,]*)?(?:(?:cancel|abort|never\s*mind)(?:\s+(?:that|it|this|" + _TASK_WORDS + r"))?"
    r"|stop\s+(?:that|it|this|" + _TASK_WORDS + r"|what\s+you'?re\s+doing))\s*[.!]*\s*$",
    re.IGNORECASE,
)
# A quick reply must not claim the work is finished before it ran ("I created the folder...").
CLAIMS_DONE = re.compile(r"^\s*(?:i(?:'ve|\s+have)?\s+\w+ed\b|i\s+(?:made|wrote|put|set|ran|got|found|built|sent|did)\b|done\b|all\s+set\b|\w+ed\s)", re.IGNORECASE)
# A bare trailing "Claude" after one of these is the object of the sentence, not an address.
OBJECT_WORDS = {"for", "to", "in", "into", "with", "on", "about", "of", "using", "from", "via", "through",
                "the", "my", "your", "and", "or"}


def approval_question(approval: Dict[str, str]) -> str:
    label = str(approval.get("label", "")).strip().rstrip(".")
    return f"I need your OK first: {label}. Say go ahead, or no."


class AgentOrchestrator:
    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model_name: str = "llama3.2:1b",
        registry: Optional[ToolRegistry] = None,
        engine: Optional[ExecutionEngine] = None,
        tts: Optional[BaseTTSProvider] = None,
        logger: Optional[TranscriptLogger] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        max_history_turns: int = 10,
        fast_path_manager: Optional[FastPathManager] = None
    ):
        """
        Initialize AgentOrchestrator with pluggable LLM provider support.
        """
        self.ollama_url = ollama_url.rstrip("/")
        self.model_name = model_name
        
        self.registry = registry if registry is not None else ToolRegistry()
        self.engine = engine if engine is not None else ExecutionEngine(self.registry)
        self.tts = tts  # Optional: Pass BaseTTSProvider instance

        self.logger = logger if logger is not None else TranscriptLogger()
        self.fast_path_manager = fast_path_manager or FastPathManager()
        
        self.llm_provider = llm_provider or OllamaLLMProvider(ollama_url=ollama_url, model_name=model_name)
        self.max_history_turns = max_history_turns
        self.conversation_history: List[Dict[str, str]] = []

        # Named routes: a spoken prefix sends one request to another provider ("Hey Claude, ...").
        # Each entry: (compiled prefix pattern, provider factory, label shown while it thinks).
        self.routes: List[tuple] = []
        # Called with the route label when a request is routed, so the HUD can say who's answering.
        self.route_listener: Optional[Callable[[str], None]] = None

        # Set by the app to run slow requests as background tasks; None keeps everything inline.
        self.task_board: Optional[TaskBoard] = None
        self._history_lock = threading.Lock()
        self.speech_lock = threading.RLock()
        # The model Claude Code tasks run on (the app reads it from settings).
        self.claude_code_model: Callable[[], str] = lambda: "haiku"
        self._claude_session: Optional[Dict[str, Any]] = None  # {"id", "until"}: the follow-up window
        # Called with the reply text right before it is spoken (the app shows it in the pill).
        self.speak_listener: Optional[Callable[[str], None]] = None

    def set_llm_provider(self, new_provider: BaseLLMProvider):
        """
        Hot-swaps active LLM Orchestrator provider instance live.
        """
        self.llm_provider = new_provider
        print(f"[AgentOrchestrator] Swapped LLM provider to: {new_provider.get_provider_info()['name']}", flush=True)

    def get_available_models(self) -> List[str]:
        """
        Retrieves list of models supported by active LLM provider.
        """
        return self.llm_provider.get_available_models()

    def check_ollama_status(self) -> bool:
        """
        Verifies if LLM provider is active.
        """
        return True

    def clear_history(self):
        """
        Clears multi-turn conversation memory.
        """
        with self._history_lock:
            self.conversation_history.clear()
        print("[AgentOrchestrator] Conversation chain history cleared.", flush=True)

    def get_active_model_name(self) -> str:
        """
        Returns display name of currently active LLM provider and model.
        """
        if self.llm_provider:
            info = self.llm_provider.get_provider_info()
            return info.get("name", self.model_name)
        return self.model_name

    def build_system_prompt(self, profile_path: Optional[Any] = None) -> str:
        """
        Constructs system prompt defining Jarvis as a voice-activated desktop assistant.
        Uses Anthropic/SOTA XML structural tags for clean parsing and dynamic context injection.
        """
        from datetime import datetime
        now = datetime.now()
        current_time_str = now.strftime("%A, %B %d, %Y")

        user_profile = load_user_profile(profile_path)
        profile_xml = f"  <user_profile>\n{user_profile}\n  </user_profile>\n" if user_profile else ""
        active_model = self.get_active_model_name()

        from daemon.tools.app_scanner import get_app_scanner
        apps_summary = get_app_scanner().get_prompt_app_summary()

        # Check active locked_in status safely
        locked_in_status = "INACTIVE (Relax Mode)"
        try:
            from locked_in.config import ConfigManager
            cfg = ConfigManager()
            if cfg.is_enabled:
                locked_in_status = "ACTIVE (Locked-In Focus Mode)"
        except Exception:
            pass

        # Get active macros list summary
        macro_summary = "  (No custom macros created yet)"
        try:
            from daemon.macros.macro_manager import get_macro_manager
            macros = get_macro_manager().list_macros()
            if macros:
                m_lines = []
                for m_id, m_info in sorted(macros.items()):  # glob order isn't stable: it would break the cache
                    name = m_info.get("name", m_id)
                    steps = m_info.get("steps", [])
                    m_lines.append(f"  - '{m_id}' (Name: \"{name}\"): steps={steps}")
                macro_summary = "\n".join(m_lines)
        except Exception:
            pass

        prompt = (
            "<persona>\n"
            f"You are Jarvis, a helpful, intelligent voice-activated desktop assistant for {get_os().name}.\n"
            f"You are currently powered by the AI model: '{active_model}'.\n"
            "You help the user answer questions, hold natural conversations, and execute desktop commands.\n"
            "</persona>\n\n"
            "<system_instructions>\n"
            "1. **Analyze Intent & Category**:\n"
            "   - **Category A (Inspection & Discovery Tools)**: 'web_search', 'search_files', 'get_current_time', 'system_status'. Use tool and set \"status\": \"continue\". This allows the ReAct engine to read tool search results / stdout before executing terminal commands or answering.\n"
            "   - **Category B (Action & Execution Tools)**: 'macro_control', 'execute_terminal_command', 'claude_code_task', 'app_launcher', 'close_app', 'system_power_control', 'volume_control', 'media_play_pause', 'set_timer', 'locked_in_mode', 'update_memory_profile', 'take_screenshot', 'open_terminal', 'calendar_create_event'. Use tool and set \"status\": \"complete\" (or \"status\": \"continue\" if you need to read command stdout before answering).\n"
            "   - **Category C (General Conversation & Greetings)**: 'hello', 'who are you', 'thank you', 'tell me a joke'. Set \"tool\": \"none\", \"args\": {}, \"status\": \"complete\".\n"
            "   - **Category D (Fallback for Unsupported Tasks & Missing Tools)**: If the user requests an action or information that CANNOT be accomplished with the tools in <available_tools> (such as tracking Saturn V rocket GPS, smart home appliance control, ordering pizza, cooking, or physical world tasks), set \"tool\": \"none\", \"args\": {}, \"status\": \"complete\", and explain in 'spoken_summary' that you do not have a tool to perform that specific task.\n"
            "2. **Strict Tool & Output Format Rules**:\n"
            "   - CRITICAL OUTPUT FORMAT RULE: Respond ONLY with a single raw JSON object matching <response_schema>. Do NOT output markdown code blocks (```json), conversational text, commentary, preambles, or internal monologue before/after the JSON!\n"
            "   - The \"tool\" field MUST be an exact registered tool identifier string from <available_tools> or 'none'.\n"
            "   - For creating, running, or modifying multi-step workspace modes (like Gaming Mode, Work Mode, or Usual Apps), use 'macro_control'.\n"
            "   - CRITICAL MACRO RULE: Do NOT invent or hallucinate non-existent macro names! For `macro_control` with `action: \"run\"`, `macro_name` MUST be an exact existing macro ID from <available_user_macros>. If the user asks to perform multiple individual actions (such as pausing Spotify and opening Steam) and no matching macro exists, do NOT run `macro_control`! Instead, execute each action using individual tools (e.g. `media_play_pause` and `app_launcher`).\n"
            "   - SINGLE-TOOL MULTI-ACTION EFFICIENCY: `media_play_pause` accepts an ARRAY of action objects! For multi-intent media requests (such as \"Pause Spotify, play YouTube\"), execute ALL media actions in a single array `[{\"action\": \"pause\", \"player\": \"spotify\"}, {\"action\": \"play\", \"player\": \"youtube\"}]` in Step 1 with \"status\": \"complete\". Do NOT split single-tool media queries across multiple ReAct steps!\n"
            "   - MULTI-TOOL QUERIES (DIFFERENT TOOLS): ONLY set \"status\": \"continue\" across ReAct steps if a query requires TWO DIFFERENT tools (e.g. `close_app` for Steam AND `media_play_pause` for Spotify) that cannot be combined into a single tool call.\n"
            "   - For multi-step jobs (installing or setting something up, organizing or editing files, coding, research across several pages), use 'claude_code_task' with the whole task described in plain words: Claude Code works through it on its own. Use 'execute_terminal_command' only for a single, simple command.\n"
            "   - For file system operations (creating directories with mkdir, writing text to files, reading files, process checks), use \"tool\": \"execute_terminal_command\" with \"args\": {\"command\": \"...\"}.\n"
            "   - CRITICAL: To launch desktop apps, ALWAYS set \"tool\": \"app_launcher\" and pass app name in args.\n"
            "   - CRITICAL: To close, exit, or terminate running desktop apps, ALWAYS set \"tool\": \"close_app\" and pass app_name in args (e.g. {\"app_name\": \"steam\"}).\n"
            "   - CRITICAL FALLBACK: Do NOT hallucinate tool calls or attempt to use unrelated tools for unsupported tasks! If no tool matches, set \"tool\": \"none\".\n"
            "   - The \"thought\" field MUST be at most 6 words naming the intent and the tool choice (e.g. \"resume paused media\", \"search install steps\").\n"
            "   - The \"spoken_summary\" MUST be a natural, friendly, voice-ready sentence for Text-to-Speech audio output confirming the action taken or explaining missing capability.\n"
            "   - For 'execute_terminal_command' the \"spoken_summary\" is spoken BEFORE the command runs, so say what you are doing in the present tense (\"Installing it now.\"), never that it is already done.\n"
            "3. **Audio / Voice Response Formatting Rules**:\n"
            "   - CRITICAL: Remember that your responses are SPOKEN aloud to the user via Text-to-Speech audio, NOT read on a screen! Speak naturally in clear, concise spoken English (1-2 sentences max).\n"
            "   - For INFORMATIONAL / HOW-TO queries (e.g. 'how to install Steam using flatpak' or 'how do I check IP address'): Step 1 uses 'web_search' to find the command. Once the search results arrive in Step 2, DO NOT search again! Set \"tool\": \"none\", \"status\": \"complete\", and synthesize a clear, spoken explanation describing how to do it (e.g. 'To install Steam using Flatpak, open your terminal and run flatpak install flathub com.valvesoftware.Steam.').\n"
            "   - Do NOT run redundant web searches if you already have the answer in the previous tool observation!\n"
            "</system_instructions>\n\n"
            "<installed_desktop_applications>\n"
            f"{apps_summary}\n"
            "</installed_desktop_applications>\n\n"
            "<available_user_macros>\n"
            f"{macro_summary}\n"
            "</available_user_macros>\n\n"
            "<few_shot_examples>\n"
            "User: \"Hello Jarvis\"\n"
            "Response: {\"thought\": \"greeting, just reply\", \"tool\": \"none\", \"args\": {}, \"status\": \"complete\", \"spoken_summary\": \"Hello! How can I assist you with your desktop today?\"}\n\n"
            "User: \"Start gaming mode\"\n"
            "Response: {\"thought\": \"run gaming_mode macro\", \"tool\": \"macro_control\", \"args\": {\"action\": \"run\", \"macro_name\": \"gaming_mode\"}, \"status\": \"complete\", \"spoken_summary\": \"Activated Gaming Mode.\"}\n\n"
            "User: \"Create a gaming mode macro with Steam, Discord, and locked in mode\"\n"
            "Response: {\"thought\": \"create gaming macro\", \"tool\": \"macro_control\", \"args\": {\"action\": \"create\", \"macro_name\": \"gaming_mode\", \"steps\": [\"steam\", \"discord\", \"locked-in start -d 2h\"]}, \"status\": \"complete\", \"spoken_summary\": \"Created Gaming Mode macro with Steam, Discord, and locked in mode.\"}\n\n"
            "User: \"Add Slack to my usual apps mode\"\n"
            "Response: {\"thought\": \"add step to macro\", \"tool\": \"macro_control\", \"args\": {\"action\": \"add_step\", \"macro_name\": \"usual_apps\", \"step\": \"slack\"}, \"status\": \"complete\", \"spoken_summary\": \"Added Slack to your usual apps mode.\"}\n\n"
            "User: \"Can you look up how to install steam using flatpak?\"\n"
            "Response: {\"thought\": \"look up install command\", \"tool\": \"web_search\", \"args\": {\"query\": \"how to install steam flatpak command flathub\"}, \"status\": \"continue\", \"spoken_summary\": \"Looking up Steam Flatpak installation instructions.\"}\n\n"
            "User: \"Create a directory called Projects in my Documents folder\"\n"
            "Response: {\"thought\": \"make the directory\", \"tool\": \"execute_terminal_command\", \"args\": {\"command\": \"mkdir -p ~/Documents/Projects\", \"explanation\": \"Created directory Projects in Documents folder.\"}, \"status\": \"complete\", \"spoken_summary\": \"Created directory Projects in your Documents folder.\"}\n\n"
            "User: \"Open VS Code\"\n"
            "Response: {\"thought\": \"launch VS Code\", \"tool\": \"app_launcher\", \"args\": {\"app_name\": \"code\"}, \"status\": \"complete\", \"spoken_summary\": \"Opening Visual Studio Code.\"}\n\n"
            "User: \"Close Steam\"\n"
            "Response: {\"thought\": \"close Steam\", \"tool\": \"close_app\", \"args\": {\"app_name\": \"steam\"}, \"status\": \"complete\", \"spoken_summary\": \"Closed Steam.\"}\n\n"
            "User: \"Unpause YouTube and pause Spotify playback\"\n"
            "Response: {\"thought\": \"two media actions\", \"tool\": \"media_play_pause\", \"args\": [{\"action\": \"play\", \"player\": \"youtube\"}, {\"action\": \"pause\", \"player\": \"spotify\"}], \"status\": \"complete\", \"spoken_summary\": \"Unpaused YouTube and paused Spotify playback.\"}\n\n"
            "User: \"Turn off my smart kitchen lights\"\n"
            "Response: {\"thought\": \"unsupported, explain\", \"tool\": \"none\", \"args\": {}, \"status\": \"complete\", \"spoken_summary\": \"I don't have a tool to control kitchen lights, but I can help manage your computer.\"}\n"
            "</few_shot_examples>\n\n"
            "<available_tools>\n"
            f"{self.registry.get_llm_tool_descriptions()}\n"
            "</available_tools>\n\n"
            "<response_schema>\n"
            "You MUST respond ONLY with a raw JSON object matching:\n"
            "{\n"
            '  "thought": "intent, tool (max 6 words)",\n'
            '  "tool": "<exact_tool_id_or_none>",\n'
            '  "args": { ... },\n'
            '  "status": "continue" | "complete",\n'
            '  "spoken_summary": "Conversational reply or brief action status."\n'
            "}\n"
            "</response_schema>\n\n"
            # Last on purpose: everything above is the same request after request and is cached
            # (providers cache the prefix); this part changes daily, with focus mode, and whenever
            # the memory profile is rewritten. Earlier, it would invalidate the whole cache.
            f"{VOLATILE_CONTEXT_TAG}\n"
            f"  <current_time>{current_time_str}</current_time>\n"
            f"  <focus_mode_status>{locked_in_status}</focus_mode_status>\n"
            f"{profile_xml}"
            "</active_context>\n"
        )
        return prompt

    # ----------------------------------------------------------------------------------------------
    # Voice requests
    # ----------------------------------------------------------------------------------------------

    def _speak(self, text: str):
        if self.tts and text:
            with self.speech_lock:
                if self.speak_listener:
                    self.speak_listener(text)  # show the words as they start, not after
                self.tts.speak(text, block=True)

    def _strip_address(self, user_query: str, m: "re.Match") -> str:
        """
        Drop the spoken address ("Hey Claude," at the start, ", Claude?" at the end). A bare trailing
        name after words like "for" or "with" is the object of the sentence ("...install it for Claude
        Code?"), so the request is still routed but keeps its full text.
        """
        if m.start() > 0 and not re.match(r"\s*(?:,|hey\b)", m.group(0), re.IGNORECASE):
            prev = re.search(r"(\w+)\W*$", user_query[:m.start()])
            if prev and prev.group(1).lower() in OBJECT_WORDS:
                return user_query.strip()
        return f"{user_query[:m.start()]} {user_query[m.end():]}".strip(" ,") or "Hello"

    def process_voice_query(self, user_query: str, speak_output: bool = True, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Processes transcribed voice text through the active LLM provider with multi-turn context.

        With a task board attached, the reasoning loop runs on its own thread. If it finishes within
        PROMOTE_AFTER seconds the answer is spoken as usual; if it is still going (or reaches a terminal
        command) Jarvis speaks a quick acknowledgement and the task continues in the background,
        announced through the board's listener when it finishes.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        # This turn's metadata (what speech recognition heard, the route). Taken now so a background
        # task and the next voice request can't mix up each other's.
        meta = self.logger.pop_next_turn_meta()

        print(f"\n[AgentOrchestrator] Processing voice query: \"{user_query}\"", flush=True)

        # "Go ahead" / "no" answers a step that is waiting for the user's OK.
        if self.task_board and self.task_board.awaiting_approval() and (is_approval(user_query) or is_refusal(user_query)):
            approve = is_approval(user_query)
            task = self.task_board.answer(approve)
            spoken = "Okay, going ahead." if approve else "Okay, I won't do that."
            print(f"[AgentOrchestrator] {'Approved' if approve else 'Refused'} task {task.id}: {task.approval}", flush=True)
            if speak_output:
                self._speak(spoken)
            self.logger.log_turn(session_id, user_query, tool_executed="approve_task" if approve else "refuse_task",
                                 spoken_response=spoken, meta={**meta, "outcome": "ok"})
            return {"success": True, "tool": "approve_task", "final_spoken_summary": spoken}

        if self.task_board and CANCEL_PATTERN.match(user_query):
            cancelled = self.task_board.cancel()
            if cancelled:
                spoken = "Okay, stopping that."
                print(f"[AgentOrchestrator] Cancelling background task {cancelled.id}: \"{cancelled.title}\"", flush=True)
                if speak_output:
                    self._speak(spoken)
                self.logger.log_turn(session_id, user_query, tool_executed="cancel_task",
                                     spoken_response=spoken, meta=meta)
                return {"success": True, "tool": "cancel_task", "final_spoken_summary": spoken}

        # Named routes ("Hey Claude, ...") bypass fast paths and use their own provider for this request.
        provider = self.llm_provider
        route_label = None
        for pattern, make_provider, label in self.routes:
            m = pattern.search(user_query)
            if m:
                routed = make_provider()
                if routed is not None:
                    provider, route_label = routed, label
                    # How sure speech recognition was about the routing word: the probability mass
                    # of the alternatives that also address the route ("Claude?" vs "on?").
                    alts = meta.get("heard_alternatives") or []
                    confidence = None
                    if len(alts) > 1:
                        confidence = round(sum(a.get("probability", 0) for a in alts
                                               if any(p.search(a.get("text", "")) for p, _, l in self.routes if l == label)), 2)
                    info = provider.get_provider_info() if hasattr(provider, "get_provider_info") else {}
                    meta["route"] = {"label": label, "model": info.get("model_name", ""), "confidence": confidence}
                    user_query = self._strip_address(user_query, m)
                    print(f"[AgentOrchestrator] Routed to {label}: \"{user_query}\"", flush=True)
                    if self.route_listener:
                        self.route_listener(label)
                break

        # Built-in shortcuts first, then what Jarvis learned from the log (daemon/agent/pattern_miner.py).
        fast_match = None if provider is not self.llm_provider else self.fast_path_manager.match(user_query, active_model_name=self.get_active_model_name())
        if route_label:
            meta["served_by"] = {"kind": "claude_code" if route_label == "Claude Code" else "route", "label": route_label}
        elif fast_match:
            meta["served_by"] = {"kind": "fast_path", "rule_id": fast_match.get("rule_id")}
        else:
            learned = self._match_learned(user_query, meta)
            if learned and learned["mode"] == "ignore":
                return self._ignore_noise(user_query, learned, session_id, meta)
            if learned and learned["mode"] == "active":
                fast_match = {"rule_id": learned["rule"]["id"], "tool": learned["tool"], "args": learned["args"],
                              "spoken_summary": learned["rule"].get("spoken_summary", ""), "action_type": "tool"}
                meta["served_by"] = {"kind": "learned", "rule_id": learned["rule"]["id"]}
            elif learned:
                # Shadow: the model still answers; the log keeps what the rule would have done.
                meta["pattern_prediction"] = {"rule_id": learned["rule"]["id"], "tool": learned["tool"],
                                              "args": clean_args(learned["args"])}
        first_step = None
        # "Jarvis, ..." ends a Claude follow-up window; anything else said in it goes back to Claude
        # (shortcut commands like "pause music" still run instantly).
        if JARVIS_ADDRESS.match(user_query):
            self._claude_session = None
        followup = route_label is None and fast_match is None and self.claude_followup_active()
        if followup:
            route_label = "Claude Code"
            meta["route"] = {"label": "Claude Code", "model": self.claude_code_model(), "followup": True}
            meta["served_by"] = {"kind": "claude_code", "label": "Claude Code", "followup": True}
            meta.pop("pattern_prediction", None)
            print(f"[AgentOrchestrator] Follow-up to Claude Code: \"{user_query}\"", flush=True)
            if self.route_listener:
                self.route_listener("Claude Code")
        if route_label == "Claude Code":
            # "Hey Claude, ..." opens a Claude Code session directly: it can use its own tools and
            # Jarvis's desktop tools, so there is no separate model call to pick a tool first.
            # Within the follow-up window the same session continues, so Claude remembers it.
            resume = self._claude_session["id"] if self.claude_followup_active() else None
            task_text = user_query
            if not resume:
                with self._history_lock:
                    recent = self.conversation_history[-4:]
                context = "\n".join(f"{'User' if m['role'] == 'user' else 'Jarvis'}: {str(m['content'])[:300]}" for m in recent)
                task_text += f"\n\nEarlier in the conversation, for context:\n{context}" if context else ""
            first_step = {"tool": "claude_code_task", "args": {"task": task_text, "resume": resume},
                          "status": "complete", "spoken_summary": "Asking Claude Code."}
        if fast_match:
            print(f"[AgentOrchestrator] Intercepted Fast-Path Query ('{user_query}') -> Rule '{fast_match.get('rule_id')}'", flush=True)
            fp_args = {**fast_match.get("args", {}), "_raw_user_query": user_query}
            if fast_match.get("tool", "none") != "none" and approval_needed(fast_match["tool"], fp_args):
                # Shutting down etc.: same shortcut, but it waits for the user's OK like any other step.
                first_step = {"tool": fast_match["tool"], "args": fast_match.get("args", {}), "status": "complete",
                              "spoken_summary": fast_match.get("spoken_summary", "")}
            else:
                return self._execute_fast_path_match(fast_match, user_query, session_id, speak_output, meta)

        with self._history_lock:
            prior = list(self.conversation_history[-self.max_history_turns * 2:])
        run = dict(provider=provider, user_query=user_query, system_prompt=self.build_system_prompt(),
                   prior=prior, meta=meta, session_id=session_id, first_step=first_step)

        if self.task_board is None:
            task = BackgroundTask(user_query, route_label)
            result = self._run_react(task, **run)
            if speak_output:
                self._speak(result.get("final_spoken_summary", ""))
            return result

        task = self.task_board.create(user_query, route_label)
        threading.Thread(target=self._run_react, args=(task,), kwargs=run, daemon=True,
                         name=f"JarvisTask-{task.id}").start()
        task.settled.wait(PROMOTE_AFTER)
        with task.lock:
            if not task.finished:
                task.background = True
        if task.finished:
            result = task.final_result
            if speak_output:
                self._speak(result.get("final_spoken_summary", ""))
            return result

        if task.approval and task.approval.get("state") == "waiting":
            ack = approval_question(task.approval)
        else:
            ack = task.ack if task.ack and not CLAIMS_DONE.match(task.ack) else "On it."
            ack = ack.rstrip()
            if ack[-1:] not in ".!?":
                ack += "."
            ack += " I'll let you know when it's done."
        print(f"[AgentOrchestrator] Task {task.id} continues in the background.", flush=True)
        self.task_board.emit("task_started", task)
        if speak_output:
            self._speak(ack)
        return {"success": True, "tool": "background_task", "background_task_id": task.id,
                "final_spoken_summary": ack}

    def _wait_for_approval(self, task: BackgroundTask, needs: Dict[str, str], update: Callable) -> str:
        """Hold the step until the user says go ahead or no. Returns approved|refused|expired|cancelled|unavailable."""
        if self.task_board is None:
            return "unavailable"
        task.approved = False
        task.approval_event.clear()
        task.approval = {"label": needs["label"], "detail": needs.get("detail", ""), "state": "waiting"}
        task.current = "Waiting for your OK"
        with task.lock:
            already_background = task.background
        if already_background:
            update("task_needs_approval")  # the app asks out loud
        else:
            task.settled.set()  # the voice request replies now, with the question
            update()
        print(f"[AgentOrchestrator] Task {task.id} waiting for approval: {task.approval}", flush=True)
        deadline = time.monotonic() + APPROVAL_TIMEOUT
        state = ""
        while not task.approval_event.wait(0.2):
            if task.cancel_event.is_set():
                state = "cancelled"
                break
            if time.monotonic() > deadline:
                state = "expired"
                break
        if not state:
            state = "approved" if task.approved else "refused"
        task.approval["state"] = state
        update()
        return state

    def claude_followup_active(self) -> bool:
        s = self._claude_session
        return bool(s and time.monotonic() < s["until"])

    def _run_claude_code(self, task: BackgroundTask, task_text: str, update: Callable,
                         resume: Optional[str] = None) -> Dict[str, Any]:
        """Hand the task to Claude Code; its steps join this task, its risky steps wait for an OK."""
        from daemon.agent.claude_code_agent import ClaudeCodeSession
        from daemon.agent.approval import command_risk
        from daemon.providers.llm.claude_code_llm_provider import _shorten

        def decide(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
            if tool_name in CLAUDE_CODE_READ_ONLY or tool_name.startswith("mcp__jarvis__"):
                # Jarvis's own tools apply Jarvis's approval rules when they run (call_tool below).
                return {"behavior": "allow", "updatedInput": tool_input}
            if tool_name == "Bash":
                command = str(tool_input.get("command", ""))
                risk, reason = command_risk(command)
                if risk == "safe":
                    return {"behavior": "allow", "updatedInput": tool_input}
                if risk == "block":
                    return {"behavior": "deny", "message": reason}
                needs = {"label": str(tool_input.get("description") or "Run a command"), "detail": command}
            elif tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "a file")
                change = str(tool_input.get("content") or tool_input.get("new_string") or tool_input.get("new_source") or "")
                verb = "Write" if tool_name == "Write" else "Edit"
                needs = {"label": f"{verb} {path}", "detail": f"{path}\n{change[:600]}" if change else path}
            else:
                needs = {"label": f"Let Claude Code use {tool_name}", "detail": json.dumps(tool_input)[:600]}
            with task.approval_lock:  # one question at a time, even if Claude Code asks in parallel
                state = self._wait_for_approval(task, {**needs, "risk": "confirm"}, update)
            if state == "approved":
                return {"behavior": "allow", "updatedInput": tool_input}
            return {"behavior": "deny", "message": "The user said no to this step." if state == "refused"
                    else "No answer from the user, so this step didn't run."}

        def jarvis_tools() -> List[Dict[str, Any]]:
            out = []
            for tool_id, manifest in sorted(self.registry._tools.items()):
                if tool_id in CLAUDE_CODE_SKIPS or manifest is None:
                    continue
                out.append({"name": tool_id, "description": manifest.description,
                            "inputSchema": manifest.parameters or {"type": "object", "properties": {}}})
            return out

        def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
            if name not in self.registry._tools or name in CLAUDE_CODE_SKIPS:
                return {"text": f"Unknown Jarvis tool '{name}'.", "is_error": True}
            run_args = {**args, "_raw_user_query": task_text}
            needs = approval_needed(name, run_args)
            if needs and needs["risk"] == "block":
                return {"text": needs["label"], "is_error": True}
            if needs:
                with task.approval_lock:
                    if self._wait_for_approval(task, needs, update) != "approved":
                        return {"text": "The user said no to this.", "is_error": True}
            res = self.engine.execute_custom_tool(name, run_args)
            text = " ".join(str(x) for x in (res.get("spoken_confirmation"), res.get("stdout")) if x)
            return {"text": text or "Done.", "is_error": res.get("success") is False}

        def on_step(event: str, step: Dict[str, str]):
            if event == "step":
                task.steps.append(step)
                task.current = step["label"]
            update()

        def on_note(text: str):
            task.current = text.splitlines()[0][:120]
            update()

        session = ClaudeCodeSession(task_text, self.claude_code_model(), decide, on_step, task.cancel_event, on_note,
                                    tools=jarvis_tools, call_tool=call_tool, resume=resume)
        print(f"[AgentOrchestrator] Task {task.id}: handing to Claude Code ({self.claude_code_model()}): {task_text!r}", flush=True)
        self._claude_session = None  # no follow-ups into a session that is still running
        outcome = session.run()
        # Spoken aloud: drop markdown the model slipped in (`code`, **bold**, # headings).
        text = re.sub(r"`|\*\*|^#+\s*", "", outcome.get("text", ""), flags=re.MULTILINE)
        sid = outcome.get("session_id")
        if sid and not outcome.get("cancelled"):
            # Follow-ups in the next CLAUDE_FOLLOWUP_SECONDS continue this session.
            self._claude_session = {"id": sid, "until": time.monotonic() + CLAUDE_FOLLOWUP_SECONDS}
        return {
            "success": bool(outcome.get("ok")),
            "cancelled": bool(outcome.get("cancelled")),
            "stdout": text if outcome.get("ok") else "",
            "stderr": "" if outcome.get("ok") else text,
            "spoken_confirmation": _shorten(text) or ("Claude Code finished." if outcome.get("ok") else "Claude Code couldn't finish."),
        }

    def _run_react(self, task: BackgroundTask, provider: BaseLLMProvider, user_query: str, system_prompt: str,
                   prior: List[Dict[str, str]], meta: Dict[str, Any], session_id: str,
                   first_step: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """The ReAct loop: ask the model, run the tool it picks, feed observations back, repeat."""
        in_worker = self.task_board is not None
        if in_worker:
            self.engine.set_run_context(task.cancel_event, BACKGROUND_COMMAND_TIMEOUT)
        max_steps = BACKGROUND_MAX_STEPS if in_worker else 3

        # This request's own reasoning trail. Observations must reach the model on the next step.
        trail: List[Dict[str, str]] = [{"role": "user", "content": user_query}]
        last_result: Dict[str, Any] = {"success": True}
        final_spoken = ""
        executed_tools: List[str] = []
        tool_args: Any = {}
        last_parsed: Dict[str, Any] = {}
        status = "done"

        def update(event="task_updated"):
            self.task_board and self.task_board.emit(event, task)

        try:
            for step in range(1, max_steps + 1):
                if task.cancel_event.is_set():
                    status, final_spoken = "cancelled", "Stopped."
                    break
                task.current = "Thinking…"
                update()
                history = prior if step == 1 else prior + trail
                if step == 1 and first_step:
                    parsed = first_step  # a shortcut that still needs the user's OK
                else:
                    parsed = provider.process_voice_query(user_query, history, system_prompt)
                model_decided = step == 1 and not first_step
                print(f"[AgentOrchestrator ReAct Step {step}] LLM Response: {parsed}", flush=True)
                if task.cancel_event.is_set():
                    status, final_spoken = "cancelled", "Stopped."
                    break
                last_parsed = parsed if isinstance(parsed, dict) else {}

                tool_name = last_parsed.get("tool", "none")
                tool_args = last_parsed.get("args", {})
                spoken_summary = (last_parsed.get("spoken_summary") or last_parsed.get("response")
                                  or last_parsed.get("answer") or last_parsed.get("message") or "")
                if spoken_summary:
                    task.ack = task.ack or spoken_summary

                # Validate tool name against registered tools & meta-tools
                known_meta_tools = ["none", "None", "", None, "Bash", "View", "Edit", "Grep", "ManageTools"]
                known_custom_tools = list(self.registry._tools.keys())
                if tool_name not in known_meta_tools and tool_name not in known_custom_tools:
                    # If tool_name is an executable path (e.g. '/usr/bin/steam') or app binary, normalize to app_launcher
                    if str(tool_name).startswith("/") or any(app_kw in str(tool_name).lower() for app_kw in ["steam", "discord", "code", "firefox", "chrome", "spotify"]):
                        from pathlib import Path
                        app_extracted = Path(str(tool_name)).name
                        print(f"[AgentOrchestrator] Normalizing LLM executable path tool '{tool_name}' -> app_launcher(app_name='{app_extracted}')", flush=True)
                        tool_name = "app_launcher"
                        tool_args = {"app_name": app_extracted}
                    else:
                        print(f"[AgentOrchestrator Warning] Unknown tool '{tool_name}' requested. Treating as conversational response.", flush=True)
                        tool_name = "none"

                trail.append({"role": "assistant", "content": json.dumps(last_parsed)})
                if model_decided and "served_by" not in meta:
                    # What the model chose for this request: the shortcut learner's evidence.
                    info = provider.get_provider_info() if hasattr(provider, "get_provider_info") else {}
                    meta["served_by"] = {"kind": "llm", "model": info.get("model_name", "")}
                    meta["llm_decision"] = {"tool": tool_name or "none", "args": clean_args(tool_args)}

                if tool_name in ["none", "None", "", None]:
                    final_spoken = spoken_summary or "I'm here to help."
                    last_result = {"success": True, "tool": "none", "spoken_confirmation": final_spoken}
                    break

                executed_tools.append(tool_name)
                step_info = describe_step(tool_name, tool_args)
                step_info["state"] = "running"
                task.steps.append(step_info)
                gate_args = {**tool_args, "_raw_user_query": user_query} if isinstance(tool_args, dict) else tool_args
                needs = approval_needed(tool_name, gate_args)
                if needs and needs["risk"] == "block":
                    step_info["state"] = "failed"
                    last_result = {"success": False, "stderr": needs["label"], "spoken_confirmation": needs["label"]}
                    final_spoken, status = needs["label"], "failed"
                    break
                if needs:
                    decision = self._wait_for_approval(task, needs, update)
                    if decision != "approved":
                        step_info["state"] = "skipped"
                        last_result = {"success": True, "spoken_confirmation": ""}
                        status = "cancelled"
                        final_spoken = {
                            "refused": "Okay, I didn't do it.",
                            "expired": "I didn't hear an OK, so I didn't do it.",
                            "cancelled": "Stopped.",
                        }.get(decision, "That needs your OK, and I can't ask right now.")
                        break
                task.current = step_info["label"]
                if tool_name in BACKGROUND_TOOLS:
                    task.ack = spoken_summary or task.ack
                    # A quick command (open a URL, make a folder) finishes in the foreground; a slow
                    # one lets the voice request reply after COMMAND_GRACE seconds.
                    grace = threading.Timer(COMMAND_GRACE, task.settled.set)
                    grace.daemon = True
                    grace.start()
                update()

                # Route tool execution (supports single dict or array of multi-call dicts)
                args_list = tool_args if isinstance(tool_args, list) else [tool_args]
                for single_args in args_list:
                    if not isinstance(single_args, dict):
                        continue
                    if tool_name == "claude_code_task":
                        last_result = self._run_claude_code(task, str(single_args.get("task") or user_query), update,
                                                            resume=single_args.get("resume"))
                    elif tool_name in ["Bash", "View", "Edit", "Grep", "ManageTools"]:
                        if tool_name == "Bash":
                            last_result = self.engine.execute_bash(single_args.get("command", ""))
                        elif tool_name == "View":
                            last_result = self.engine.execute_view(single_args.get("path", ""))
                        elif tool_name == "Edit":
                            last_result = self.engine.execute_edit(single_args.get("path", ""), single_args.get("content", ""))
                        elif tool_name == "Grep":
                            last_result = self.engine.execute_grep(single_args.get("pattern", ""), single_args.get("path", "."))
                        elif tool_name == "ManageTools":
                            last_result = self.engine.execute_manage_tools(single_args.get("action", "list"))
                    else:
                        last_result = self.engine.execute_custom_tool(tool_name, {**single_args, "_raw_user_query": user_query})

                step_info["state"] = "done" if last_result.get("success", True) else "failed"
                update()
                if last_result.get("cancelled") or task.cancel_event.is_set():
                    status, final_spoken = "cancelled", "Stopped."
                    break

                if "exit_code" in last_result:  # a shell command: report what it actually printed
                    tool_output = str(last_result.get("stdout") or f"(no output, exit code {last_result.get('exit_code')})")
                else:
                    tool_output = str(last_result.get("stdout") or last_result.get("spoken_confirmation") or "Command executed.")
                tool_error = str(last_result.get("stderr", ""))
                if tool_name == "claude_code_task":
                    # Claude Code ends with a sentence written to be read aloud: say that, no extra model call.
                    final_spoken = last_result.get("spoken_confirmation") or "Claude Code finished."
                    break
                inspecting = tool_name in INSPECTION_TOOLS or last_parsed.get("status") == "continue"
                # A failed action goes back to the model, which can try another way (an app that isn't
                # installed may be a website) or explain the failure, instead of a canned error.
                failed_action = last_result.get("success") is False and step < max_steps
                # A background task gets one more look at the result, so its closing line says what
                # actually happened ("Installed it.") rather than what it was about to do.
                if inspecting or failed_action or (task.background and step < max_steps):
                    print(f"[AgentOrchestrator ReAct Step {step}] Feeding tool observation back to LLM...", flush=True)
                    trail.append({"role": "user", "content": (
                        f"[Observation from tool '{tool_name}']: Output: {tool_output[:OBSERVATION_CHARS]}. "
                        f"Stderr: {tool_error[:OBSERVATION_CHARS]}. Perform the next step if one is needed. "
                        "If the request is done, reply with tool \"none\", status \"complete\" and a short "
                        "past-tense spoken_summary of what happened, including any failure.")})
                    continue
                # Action tool completed: prefer the engine's confirmation over the pre-execution guess,
                # except for shell commands, where the engine only has the model's "explanation" (a
                # description of the command), and the spoken line reads better.
                if tool_name in BACKGROUND_TOOLS and spoken_summary:
                    final_spoken = spoken_summary
                else:
                    final_spoken = last_result.get("spoken_confirmation") or spoken_summary or "Task complete."
                break

            if not final_spoken:
                final_spoken = last_result.get("spoken_confirmation") or "Finished."
            if status == "done" and last_result.get("success") is False:
                status = "failed"
        except Exception as e:
            print(f"[AgentOrchestrator Error] Error processing query with LLM provider: {e}", flush=True)
            last_result = {"success": False, "stderr": f"Error processing query with LLM provider: {e}"}
            final_spoken = "Something went wrong while working on that."
            status = "failed"
        finally:
            if in_worker:
                self.engine.set_run_context(None, None)

        last_result["final_spoken_summary"] = final_spoken
        with self._history_lock:
            self.conversation_history.append({"role": "user", "content": user_query})
            self.conversation_history.append({"role": "assistant", "content": json.dumps(
                {**last_parsed, "spoken_summary": final_spoken} if last_parsed else {"tool": "none", "spoken_summary": final_spoken})})
            del self.conversation_history[:-self.max_history_turns * 2]

        with task.lock:
            task.status = status
            task.result = final_spoken
            task.current = ""
            task.finished_at = time.time()
            task.final_result = last_result
            background = task.background
        meta = {**meta, "outcome": "failed" if status == "failed" else ("cancelled" if status == "cancelled" else "ok")}
        if background:
            meta["background_task"] = {"id": task.id, "status": status, "steps": task.steps}
        self.logger.log_turn(
            session_id=session_id,
            user_query=user_query,
            tool_executed=" -> ".join(executed_tools) if executed_tools else "none",
            tool_args=tool_args,
            execution_stdout=last_result.get("stdout", ""),
            execution_stderr=last_result.get("stderr", ""),
            spoken_response=final_spoken,
            meta=meta,
        )
        task.settled.set()
        update("task_finished")
        return last_result

    def _match_learned(self, user_query: str, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A learned rule for this request (see FastPathManager.match_learned), or None."""
        alts = meta.get("heard_alternatives") or []
        confidence = None
        if alts and meta.get("source") != "typed":
            try:
                confidence = max(float(a.get("probability", 0)) for a in alts)
            except (TypeError, ValueError):
                confidence = None
        match_learned = getattr(self.fast_path_manager, "match_learned", None)
        if match_learned is None:
            return None
        try:
            return match_learned(user_query, heard_confidence=confidence)
        except Exception as err:
            print(f"[AgentOrchestrator Warning] Learned rule matching failed: {err}", flush=True)
            return None

    def _ignore_noise(self, user_query: str, learned: Dict[str, Any], session_id: str,
                      meta: Dict[str, Any]) -> Dict[str, Any]:
        """Background speech Jarvis has learned isn't meant for it: no model call, no reply."""
        rule_id = learned["rule"]["id"]
        print(f"[AgentOrchestrator] Ignoring \"{user_query}\": low-confidence speech that was never a request "
              f"(rule {rule_id}).", flush=True)
        self.logger.log_turn(session_id, user_query, tool_executed="ignored", spoken_response="",
                             meta={**meta, "served_by": {"kind": "noise", "rule_id": rule_id}, "outcome": "ok"})
        return {"success": True, "tool": "none", "ignored": True, "final_spoken_summary": ""}

    def _execute_fast_path_match(
        self,
        match: Dict[str, Any],
        user_query: str,
        session_id: str,
        speak_output: bool = True,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a matched fast-path rule (tool call, static response, or identity info).
        """
        action_type = match.get("action_type")
        tool = match.get("tool", "none")
        tool_args = dict(match.get("args", {}))
        spoken_summary = match.get("spoken_summary", "")

        exec_res: Dict[str, Any] = {"success": True}

        if action_type in ["dynamic_identity", "static_response"] or tool == "none":
            final_spoken = spoken_summary
            exec_res = {
                "success": True,
                "tool": "none",
                "spoken_confirmation": final_spoken,
                "final_spoken_summary": final_spoken
            }
        else:
            tool_args["_raw_user_query"] = user_query
            exec_res = self.engine.execute_custom_tool(tool, tool_args)
            final_spoken = exec_res.get("spoken_confirmation") or spoken_summary or "Executed fast path command."

        parsed = {
            "tool": tool,
            "args": {k: v for k, v in tool_args.items() if not k.startswith("_")},
            "spoken_summary": final_spoken
        }
        with self._history_lock:
            self.conversation_history.append({"role": "user", "content": user_query})
            self.conversation_history.append({"role": "assistant", "content": json.dumps(parsed)})

        if speak_output:
            self._speak(final_spoken)

        self.logger.log_turn(
            session_id=session_id,
            user_query=user_query,
            tool_executed=tool,
            tool_args=tool_args,
            execution_stdout=exec_res.get("stdout", ""),
            execution_stderr=exec_res.get("stderr", ""),
            spoken_response=final_spoken,
            meta={**(meta or {}), "outcome": "failed" if exec_res.get("success") is False else "ok"},
        )

        exec_res["final_spoken_summary"] = final_spoken
        return exec_res
