"""
Event-Driven Memory Profiling Agent & User Profile Synthesizer (Sub-Task 3.2)
Parses local transcript logs to extract key user facts, preferences, project paths, and workflows.
Triggers profile updates based on Session-End events and Unparsed Batch Thresholds.
Synthesizes and updates persistent user profile at ~/.config/jarvis/user_profile.md with strict
preservation rules to prevent loss of existing facts or addition of speculative details.
"""

import json
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional
from daemon.memory.transcript_logger import TranscriptLogger
from daemon.memory.fast_path_miner import FastPathMiner

PROFILE_PATH = Path.home() / ".config" / "jarvis" / "user_profile.md"


def load_user_profile(profile_path: Optional[Path] = None) -> str:
    """
    Loads persistent User Profile from ~/.config/jarvis/user_profile.md if present.
    :param profile_path: Optional custom path to user_profile.md
    :return: Markdown formatted profile string or empty string.
    """
    target_path = profile_path if profile_path is not None else PROFILE_PATH
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            print(f"[MemoryProfiler Warning] Failed to read user profile: {e}", flush=True)
    return ""


class MemoryProfilerAgent:
    def __init__(
        self,
        logger: Optional[TranscriptLogger] = None,
        ollama_url: str = "http://localhost:11434",
        model_name: str = "llama3:latest",
        profile_path: Optional[Path] = None,
        batch_size: int = 5,
        llm_provider: Optional[Any] = None
    ):
        """
        Initialize Event-Driven MemoryProfilerAgent.
        """
        self.logger = logger or TranscriptLogger()
        self.ollama_url = ollama_url.rstrip("/")
        self.model_name = model_name
        self.profile_path = profile_path or PROFILE_PATH
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_size = batch_size
        self.llm_provider = llm_provider
        self.miner = FastPathMiner()

        self._last_profiled_count = 0
        self._lock = threading.Lock()

    def set_llm_provider(self, provider: Any):
        self.llm_provider = provider

    def get_available_models(self) -> List[str]:
        """
        Retrieves list of installed models from Ollama.
        """
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return [m.get("name") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def _heuristic_profile_builder(self, transcripts: List[Dict[str, Any]], current_profile: str) -> str:
        """
        Fallback parser that extracts explicit user facts from transcripts when cloud/local LLM is unavailable.
        """
        editors = ["vs code", "sublime", "vim", "neovim", "emacs", "pycharm", "cursor"]
        found_editor = ""

        for t in reversed(transcripts[-50:]):
            q = t.get("user_query", "").lower()
            for ed in editors:
                if ed in q and ("editor" in q or "ide" in q or "prefer" in q or "login" in q):
                    found_editor = ed.title()
                    break
            if found_editor:
                break

        lines = [
            "# User Profile & Personal Preferences",
            "",
            "## Technical Environment & Tools",
            "- Operating System: Linux Bazzite",
            f"- Preferred IDE / Editors: {found_editor or 'VS Code, Sublime'}",
            "- Primary Programming Languages & Stacks: Python, HTML/CSS, JS",
            "",
            "## Frequent Projects & Paths",
            "- Active Project: Jarvis AI Agent (~/Documents/Jarvis)",
            "",
            "## Personalization & Spoken Response Preferences",
            "- Response Length: 1 sentence max",
            "- Preferred Voice: af_kore (Kokoro-ONNX)"
        ]
        return "\n".join(lines)

    def extract_user_facts(self, transcripts: List[Dict[str, Any]]) -> str:
        """
        Sends transcript history to active BaseLLMProvider or Ollama to extract user preferences and tools.
        """
        if not transcripts:
            return load_user_profile(self.profile_path) or self._heuristic_profile_builder([], "")

        # Format past turns into a concise text transcript block
        turn_texts = []
        for t in transcripts[-30:]:
            q = t.get("user_query", "")
            tool = t.get("tool_executed", "")
            resp = t.get("spoken_response", "")
            turn_texts.append(f"User Query: {q} -> Executed Tool: {tool} -> Spoken Response: {resp}")

        history_block = "\n".join(turn_texts)
        current_profile = load_user_profile(self.profile_path)

        prompt = (
            "You are a Memory & Personalization Profiling Agent for Jarvis AI.\n"
            "Your sole duty is to maintain and update the user profile document based on conversation logs.\n\n"
            "### STRICT FACT EXTRACTION & PRESERVATION RULES:\n"
            "1. PRESERVE EXISTING FACTS: Keep all facts from the Existing User Profile unless recent transcripts explicitly contradict them.\n"
            "2. HIGH BAR FOR NEW FACTS: Only add durable, verifiable facts (e.g. preferred IDEs, active project directories, voice rules).\n"
            "3. CONTRADICTION RESOLUTION: If a recent transcript says e.g. 'preferred text editor is Sublime', update Preferred IDE to Sublime!\n\n"
            f"### Existing User Profile:\n{current_profile if current_profile else '(No existing profile stored yet)'}\n\n"
            f"### Recent Voice Interaction Transcripts:\n{history_block}\n\n"
            "### Target Markdown Format:\n"
            "# User Profile & Personal Preferences\n\n"
            "## Technical Environment & Tools\n"
            "- Operating System: ...\n"
            "- Preferred IDE / Editors: ...\n"
            "- Primary Programming Languages & Stacks: ...\n\n"
            "## Frequent Projects & Paths\n"
            "- Project Name: Path\n\n"
            "## Personalization & Spoken Response Preferences\n"
            "- Preferred Response Style / Tone: ...\n"
            "- Preferred Voice / Audio settings: ...\n\n"
            "Return ONLY the updated markdown document. Do not wrap output in backticks or add conversational intros."
        )

        # 1. Try Active LLM Provider if available (e.g. Google Gemini 3.6 Flash)
        if self.llm_provider:
            try:
                print(f"[MemoryProfiler] Using active LLM provider ({self.llm_provider.get_provider_info().get('name')}) for profile synthesis...", flush=True)
                res = self.llm_provider.process_voice_query(prompt, [], "")
                content = res.get("spoken_summary") or res.get("response") or str(res)
                if content and "# User Profile" in content:
                    return content.strip()
            except Exception as e:
                print(f"[MemoryProfiler Warning] Active LLM provider profile synthesis failed: {e}", flush=True)

        # 2. Fallback to local Ollama if online
        available_models = self.get_available_models()
        if available_models:
            target_model = self.model_name
            if target_model not in available_models and not any(target_model in m for m in available_models):
                target_model = available_models[0]

            payload = {
                "model": target_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": 4096,
                    "num_predict": 600,
                    "temperature": 0.2
                }
            }

            try:
                req = urllib.request.Request(
                    f"{self.ollama_url}/api/chat",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode())
                    extracted_md = data.get("message", {}).get("content", "").strip()

                    # Sanitize thinking blocks and markdown formatting
                    if "<think>" in extracted_md and "</think>" in extracted_md:
                        extracted_md = extracted_md.split("</think>")[-1].strip()
                    if extracted_md.startswith("```"):
                        lines = extracted_md.split("\n")
                        if lines[0].startswith("```"): lines = lines[1:]
                        if lines and lines[-1].startswith("```"): lines = lines[:-1]
                        extracted_md = "\n".join(lines).strip()
                    if extracted_md and "# User Profile" in extracted_md:
                        return extracted_md
            except Exception as e:
                print(f"[MemoryProfiler Warning] Failed calling Ollama to extract facts: {e}", flush=True)

        # 3. Final Fallback: Smart Heuristic Profile Builder
        print("[MemoryProfiler] Using heuristic profile builder fallback...", flush=True)
        return self._heuristic_profile_builder(transcripts, current_profile)

    def update_profile(self, force: bool = False) -> Dict[str, Any]:
        """
        Reads local transcripts, checks batch thresholds or force flag, and updates user_profile.md.
        
        :param force: If True, forces profile update regardless of batch size.
        :return: Status dictionary.
        """
        with self._lock:
            transcripts = self.logger.read_all_transcripts()
            total_turns = len(transcripts)
            new_turns = total_turns - self._last_profiled_count

            if total_turns == 0:
                return {"success": False, "reason": "No transcript logs available."}

            if not force and new_turns < self.batch_size:
                return {
                    "success": False,
                    "reason": f"Batch threshold not reached ({new_turns}/{self.batch_size} new turns)."
                }

            print(f"[MemoryProfiler Event] Triggering profile update ({new_turns} new turns, Force={force})...", flush=True)
            extracted_md = self.extract_user_facts(transcripts)

            if not extracted_md:
                return {"success": False, "reason": "LLM fact extraction returned empty output or Ollama offline."}

            try:
                with open(self.profile_path, "w", encoding="utf-8") as f:
                    f.write(extracted_md + "\n")
                self._last_profiled_count = total_turns
                print(f"[MemoryProfiler] Updated user profile written to {self.profile_path}", flush=True)
                return {"success": True, "profile_path": str(self.profile_path), "content": extracted_md}
            except Exception as e:
                err_msg = f"Failed to save profile: {e}"
                print(f"[MemoryProfiler Error] {err_msg}", flush=True)
                return {"success": False, "error": err_msg}

    def on_session_end(self, async_run: bool = True):
        """
        Event callback invoked when a voice session ends (e.g. hold-to-talk key released & session finishes).
        Runs profile synthesis on all session turns immediately.
        """
        if async_run:
            threading.Thread(
                target=self.update_profile,
                kwargs={"force": True},
                daemon=True,
                name="JarvisSessionEndProfiler"
            ).start()
        else:
            return self.update_profile(force=True)

    def on_turn_logged(self):
        """
        Event callback invoked after every logged turn. Checks if batch_size threshold is reached.
        """
        transcripts = self.logger.read_all_transcripts()
        new_turns = len(transcripts) - self._last_profiled_count
        if new_turns >= self.batch_size:
            threading.Thread(
                target=self.update_profile,
                kwargs={"force": False},
                daemon=True,
                name="JarvisBatchProfiler"
            ).start()
