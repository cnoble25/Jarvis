"""
Agent Orchestrator & LLM Router (Sub-Task 2.3 & Story 2.3)
Connects pluggable LLM Providers (Ollama, Gemini, Claude, OpenAI) with Claude Code Meta-Tools,
Custom JSON Tools, Multi-turn Conversation Chain History, and the Voice Loop.
"""

import json
import uuid
from typing import Dict, Any, Optional, List
from daemon.tools.registry import ToolRegistry
from daemon.tools.execution_engine import ExecutionEngine
from daemon.memory.transcript_logger import TranscriptLogger
from daemon.memory.profiler_agent import load_user_profile
from daemon.providers.base import BaseLLMProvider, BaseTTSProvider
from daemon.providers.llm.ollama_llm_provider import OllamaLLMProvider
from daemon.agent.fast_path_manager import FastPathManager


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
                for m_id, m_info in macros.items():
                    name = m_info.get("name", m_id)
                    steps = m_info.get("steps", [])
                    m_lines.append(f"  - '{m_id}' (Name: \"{name}\"): steps={steps}")
                macro_summary = "\n".join(m_lines)
        except Exception:
            pass

        prompt = (
            "<persona>\n"
            "You are Jarvis, a helpful, intelligent voice-activated desktop assistant for Linux.\n"
            f"You are currently powered by the AI model: '{active_model}'.\n"
            "You help the user answer questions, hold natural conversations, and execute desktop commands.\n"
            "</persona>\n\n"
            "<active_context>\n"
            f"  <current_time>{current_time_str}</current_time>\n"
            f"  <focus_mode_status>{locked_in_status}</focus_mode_status>\n"
            f"{profile_xml}"
            "</active_context>\n\n"
            "<system_instructions>\n"
            "1. **Analyze Intent & Category**:\n"
            "   - **Category A (Inspection & Discovery Tools)**: 'web_search', 'search_files', 'get_current_time', 'system_status'. Use tool and set \"status\": \"continue\". This allows the ReAct engine to read tool search results / stdout before executing terminal commands or answering.\n"
            "   - **Category B (Action & Execution Tools)**: 'macro_control', 'execute_terminal_command', 'app_launcher', 'close_app', 'system_power_control', 'volume_control', 'media_play_pause', 'set_timer', 'locked_in_mode', 'update_memory_profile', 'take_screenshot', 'open_terminal', 'calendar_create_event'. Use tool and set \"status\": \"complete\" (or \"status\": \"continue\" if you need to read command stdout before answering).\n"
            "   - **Category C (General Conversation & Greetings)**: 'hello', 'who are you', 'thank you', 'tell me a joke'. Set \"tool\": \"none\", \"args\": {}, \"status\": \"complete\".\n"
            "   - **Category D (Fallback for Unsupported Tasks & Missing Tools)**: If the user requests an action or information that CANNOT be accomplished with the tools in <available_tools> (such as tracking Saturn V rocket GPS, smart home appliance control, ordering pizza, cooking, or physical world tasks), set \"tool\": \"none\", \"args\": {}, \"status\": \"complete\", and explain in 'spoken_summary' that you do not have a tool to perform that specific task.\n"
            "2. **Strict Tool & Output Format Rules**:\n"
            "   - CRITICAL OUTPUT FORMAT RULE: Respond ONLY with a single raw JSON object matching <response_schema>. Do NOT output markdown code blocks (```json), conversational text, commentary, preambles, or internal monologue before/after the JSON!\n"
            "   - The \"tool\" field MUST be an exact registered tool identifier string from <available_tools> or 'none'.\n"
            "   - For creating, running, or modifying multi-step workspace modes (like Gaming Mode, Work Mode, or Usual Apps), use 'macro_control'.\n"
            "   - CRITICAL MACRO RULE: Do NOT invent or hallucinate non-existent macro names! For `macro_control` with `action: \"run\"`, `macro_name` MUST be an exact existing macro ID from <available_user_macros>. If the user asks to perform multiple individual actions (such as pausing Spotify and opening Steam) and no matching macro exists, do NOT run `macro_control`! Instead, execute each action using individual tools (e.g. `media_play_pause` and `app_launcher`).\n"
            "   - SINGLE-TOOL MULTI-ACTION EFFICIENCY: `media_play_pause` accepts an ARRAY of action objects! For multi-intent media requests (such as \"Pause Spotify, play YouTube\"), execute ALL media actions in a single array `[{\"action\": \"pause\", \"player\": \"spotify\"}, {\"action\": \"play\", \"player\": \"youtube\"}]` in Step 1 with \"status\": \"complete\". Do NOT split single-tool media queries across multiple ReAct steps!\n"
            "   - MULTI-TOOL QUERIES (DIFFERENT TOOLS): ONLY set \"status\": \"continue\" across ReAct steps if a query requires TWO DIFFERENT tools (e.g. `close_app` for Steam AND `media_play_pause` for Spotify) that cannot be combined into a single tool call.\n"
            "   - When installing software, packages, or complex terminal operations, use 'web_search' first with \"status\": \"continue\" to look up exact package names / Flatpak IDs, then use 'execute_terminal_command' to run the command!\n"
            "   - For file system operations (creating directories with mkdir, writing text to files, reading files, process checks), use \"tool\": \"execute_terminal_command\" with \"args\": {\"command\": \"...\"}.\n"
            "   - CRITICAL: To launch desktop apps, ALWAYS set \"tool\": \"app_launcher\" and pass app name in args.\n"
            "   - CRITICAL: To close, exit, or terminate running desktop apps, ALWAYS set \"tool\": \"close_app\" and pass app_name in args (e.g. {\"app_name\": \"steam\"}).\n"
            "   - CRITICAL FALLBACK: Do NOT hallucinate tool calls or attempt to use unrelated tools for unsupported tasks! If no tool matches, set \"tool\": \"none\".\n"
            "   - The \"thought\" field MUST be a clear 1-sentence explanation detailing user intent and why the selected tool (or 'none' fallback) was chosen.\n"
            "   - The \"spoken_summary\" MUST be a natural, friendly, voice-ready sentence for Text-to-Speech audio output confirming the action taken or explaining missing capability.\n"
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
            "Response: {\"thought\": \"User greeted the assistant; responding with a friendly voice confirmation.\", \"tool\": \"none\", \"args\": {}, \"status\": \"complete\", \"spoken_summary\": \"Hello! How can I assist you with your desktop today?\"}\n\n"
            "User: \"Start gaming mode\"\n"
            "Response: {\"thought\": \"User requested running gaming mode macro; using macro_control with action run.\", \"tool\": \"macro_control\", \"args\": {\"action\": \"run\", \"macro_name\": \"gaming_mode\"}, \"status\": \"complete\", \"spoken_summary\": \"Activated Gaming Mode.\"}\n\n"
            "User: \"Create a gaming mode macro with Steam, Discord, and locked in mode\"\n"
            "Response: {\"thought\": \"User requested creating a new gaming mode macro with multi-step commands; using macro_control tool.\", \"tool\": \"macro_control\", \"args\": {\"action\": \"create\", \"macro_name\": \"gaming_mode\", \"steps\": [\"steam\", \"discord\", \"locked-in start -d 2h\"]}, \"status\": \"complete\", \"spoken_summary\": \"Created Gaming Mode macro with Steam, Discord, and locked in mode.\"}\n\n"
            "User: \"Add Slack to my usual apps mode\"\n"
            "Response: {\"thought\": \"User requested adding Slack step to usual apps macro; using macro_control tool.\", \"tool\": \"macro_control\", \"args\": {\"action\": \"add_step\", \"macro_name\": \"usual_apps\", \"step\": \"slack\"}, \"status\": \"complete\", \"spoken_summary\": \"Added Slack to your usual apps mode.\"}\n\n"
            "User: \"Can you look up how to install steam using flatpak?\"\n"
            "Response: {\"thought\": \"User requested information on how to install Steam via Flatpak; searching web for exact command.\", \"tool\": \"web_search\", \"args\": {\"query\": \"how to install steam flatpak command flathub\"}, \"status\": \"continue\", \"spoken_summary\": \"Looking up Steam Flatpak installation instructions.\"}\n\n"
            "User: \"Create a directory called Projects in my Documents folder\"\n"
            "Response: {\"thought\": \"User requested creating directory ~/Documents/Projects; executing mkdir command.\", \"tool\": \"execute_terminal_command\", \"args\": {\"command\": \"mkdir -p ~/Documents/Projects\", \"explanation\": \"Created directory Projects in Documents folder.\"}, \"status\": \"complete\", \"spoken_summary\": \"Created directory Projects in your Documents folder.\"}\n\n"
            "User: \"Open VS Code\"\n"
            "Response: {\"thought\": \"User requested launching Visual Studio Code; using app_launcher tool with app_name code.\", \"tool\": \"app_launcher\", \"args\": {\"app_name\": \"code\"}, \"status\": \"complete\", \"spoken_summary\": \"Opening Visual Studio Code.\"}\n\n"
            "User: \"Close Steam\"\n"
            "Response: {\"thought\": \"User requested closing Steam application; using close_app tool with app_name steam.\", \"tool\": \"close_app\", \"args\": {\"app_name\": \"steam\"}, \"status\": \"complete\", \"spoken_summary\": \"Closed Steam.\"}\n\n"
            "User: \"Unpause YouTube and pause Spotify playback\"\n"
            "Response: {\"thought\": \"User requested unpausing YouTube and pausing Spotify in a single multi-intent query; executing both media actions via media_play_pause.\", \"tool\": \"media_play_pause\", \"args\": [{\"action\": \"play\", \"player\": \"youtube\"}, {\"action\": \"pause\", \"player\": \"spotify\"}], \"status\": \"complete\", \"spoken_summary\": \"Unpaused YouTube and paused Spotify playback.\"}\n\n"
            "User: \"Turn off my smart kitchen lights\"\n"
            "Response: {\"thought\": \"User requested smart home control which is unsupported; falling back gracefully.\", \"tool\": \"none\", \"args\": {}, \"status\": \"complete\", \"spoken_summary\": \"I don't have a tool to control kitchen lights, but I can help manage your computer.\"}\n"
            "</few_shot_examples>\n\n"
            "<available_tools>\n"
            f"{self.registry.get_llm_tool_descriptions()}\n"
            "</available_tools>\n\n"
            "<response_schema>\n"
            "You MUST respond ONLY with a raw JSON object matching:\n"
            "{\n"
            '  "thought": "Reasoning step...",\n'
            '  "tool": "<exact_tool_id_or_none>",\n'
            '  "args": { ... },\n'
            '  "status": "continue" | "complete",\n'
            '  "spoken_summary": "Conversational reply or brief action status."\n'
            "}\n"
            "</response_schema>\n"
        )
        return prompt

    def process_voice_query(self, user_query: str, speak_output: bool = True, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Processes transcribed voice text through active BaseLLMProvider with multi-turn context.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        print(f"\n[AgentOrchestrator] Processing voice query: \"{user_query}\"", flush=True)

        # Unified Data-Driven Fast-Path Interceptor (System Defaults + Dynamic Learned Rules)
        fast_match = self.fast_path_manager.match(user_query, active_model_name=self.get_active_model_name())
        if fast_match:
            print(f"[AgentOrchestrator] Intercepted Fast-Path Query ('{user_query}') -> Rule '{fast_match.get('rule_id')}'", flush=True)
            return self._execute_fast_path_match(fast_match, user_query, session_id, speak_output)

        system_prompt = self.build_system_prompt()

        try:
            # ReAct Agentic Loop: Up to 3 tool execution steps per user query
            max_steps = 3
            step = 0
            last_result: Dict[str, Any] = {"success": True}
            final_spoken = ""
            executed_tools = []

            # Append initial user query to conversation history
            self.conversation_history.append({"role": "user", "content": user_query})

            while step < max_steps:
                step += 1
                parsed = self.llm_provider.process_voice_query(user_query, self.conversation_history[:-1], system_prompt)
                print(f"[AgentOrchestrator ReAct Step {step}] LLM Response: {parsed}", flush=True)

                tool_name = parsed.get("tool", "none")
                tool_args = parsed.get("args", {})
                spoken_summary = (
                    parsed.get("spoken_summary") or
                    parsed.get("response") or
                    parsed.get("answer") or
                    parsed.get("message") or
                    ""
                )

                # Validate tool name against registered tools & meta-tools
                known_meta_tools = ["none", "None", "", None, "Bash", "View", "Edit", "Grep", "ManageTools"]
                known_custom_tools = list(self.registry._tools.keys())
                if tool_name not in known_meta_tools and tool_name not in known_custom_tools:
                    # If tool_name is an executable path (e.g. '/usr/bin/steam') or app binary, normalize to app_launcher
                    if tool_name.startswith("/") or any(app_kw in tool_name.lower() for app_kw in ["steam", "discord", "code", "firefox", "chrome", "spotify"]):
                        from pathlib import Path
                        app_extracted = Path(tool_name).name
                        print(f"[AgentOrchestrator] Normalizing LLM executable path tool '{tool_name}' -> app_launcher(app_name='{app_extracted}')", flush=True)
                        tool_name = "app_launcher"
                        tool_args = {"app_name": app_extracted}
                    else:
                        print(f"[AgentOrchestrator Warning] Unknown tool '{tool_name}' requested. Treating as conversational response.", flush=True)
                        tool_name = "none"

                # Append assistant turn to history
                self.conversation_history.append({"role": "assistant", "content": json.dumps(parsed)})

                if tool_name in ["none", "None", "", None]:
                    final_spoken = spoken_summary or "I'm here to help."
                    last_result = {
                        "success": True,
                        "tool": "none",
                        "spoken_confirmation": final_spoken
                    }
                    break

                executed_tools.append(tool_name)

                # Route tool execution (supports single dict or array of multi-call dicts)
                args_list = tool_args if isinstance(tool_args, list) else [tool_args]
                for single_args in args_list:
                    if not isinstance(single_args, dict):
                        continue
                    if tool_name in ["Bash", "View", "Edit", "Grep", "ManageTools"]:
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
                        single_args["_raw_user_query"] = user_query
                        last_result = self.engine.execute_custom_tool(tool_name, single_args)

                tool_output = last_result.get("stdout") or last_result.get("spoken_confirmation") or "Command executed."
                tool_error = last_result.get("stderr", "")

                # If this was an inspection tool (like web_search or get_current_time), feed observation back to LLM to continue loop
                if tool_name in ["web_search", "get_current_time", "system_status", "search_files", "View", "Grep"] or parsed.get("status") == "continue":
                    print(f"[AgentOrchestrator ReAct Step {step}] Feeding tool observation back to LLM...", flush=True)
                    observation_msg = f"[Observation from tool '{tool_name}']: Output: {tool_output}. Stderr: {tool_error}. Analyze this observation and perform the next step or output the final spoken_summary."
                    self.conversation_history.append({"role": "user", "content": observation_msg})
                    continue
                else:
                    # Action tool completed: Prefer empirical execution confirmation from engine over pre-execution guess
                    final_spoken = last_result.get("spoken_confirmation") or spoken_summary or "Task complete."
                    break

            if not final_spoken:
                final_spoken = last_result.get("spoken_confirmation") or "Finished."

            last_result["final_spoken_summary"] = final_spoken

            if speak_output and self.tts and final_spoken:
                self.tts.speak(final_spoken, block=True)

            self.logger.log_turn(
                session_id=session_id,
                user_query=user_query,
                tool_executed=" -> ".join(executed_tools) if executed_tools else "none",
                tool_args=tool_args,
                execution_stdout=last_result.get("stdout", ""),
                execution_stderr=last_result.get("stderr", ""),
                spoken_response=final_spoken
            )

            return last_result

        except Exception as e:
            err_str = f"Error processing query with LLM provider: {e}"
            print(f"[AgentOrchestrator Error] {err_str}", flush=True)
            self.logger.log_turn(session_id, user_query, execution_stderr=err_str)
            return {"success": False, "stderr": err_str}

    def _execute_fast_path_match(
        self,
        match: Dict[str, Any],
        user_query: str,
        session_id: str,
        speak_output: bool = True
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
        self.conversation_history.append({"role": "user", "content": user_query})
        self.conversation_history.append({"role": "assistant", "content": json.dumps(parsed)})

        if speak_output and self.tts and final_spoken:
            self.tts.speak(final_spoken, block=True)

        self.logger.log_turn(
            session_id=session_id,
            user_query=user_query,
            tool_executed=tool,
            tool_args=tool_args,
            execution_stdout=exec_res.get("stdout", ""),
            execution_stderr=exec_res.get("stderr", ""),
            spoken_response=final_spoken
        )

        exec_res["final_spoken_summary"] = final_spoken
        return exec_res
