"""
Jarvis Desktop AI Assistant: Main Application Entry Point
Wires together all subsystems:
1. IPC Domain Socket Server (/tmp/jarvis.sock)
2. Global Hotkey Interceptor (Ctrl + Space with held-key buffer & release timer)
3. Voice Core (Audio Capture, Faster-Whisper STT, Ollama LLM Router, Kokoro-ONNX TTS)
4. Memory Subsystem (Transcript Logger, S3 Backup Syncer, Event-Driven Profiler Agent)
5. Native PySide6 GUI (Main Settings Dashboard & Wispr Flow Bottom HUD Pill Overlay)
"""

import os
import shutil
import subprocess
import sys
import time
import threading
import urllib.request
from pathlib import Path
import json
from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, QUrl, QSize, QTimer, QObject, Signal, QPoint, Slot
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

# Force Qt to use X11/Xwayland platform plugin (xcb) on Linux.
# On Wayland native mode (wayland-egl), Wayland compositors (KWin/Mutter) strictly forbid
# applications from specifying absolute screen coordinates (move/setGeometry), forcing windows to center.
# Setting QT_QPA_PLATFORM=xcb gives Qt full authority over absolute screen positioning (x=2300, y=1350).
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--no-sandbox "
    "--disable-gpu "
    "--disable-software-rasterizer "
    "--disable-dev-shm-usage "
    "--disable-webrtc "
    "--disable-features=WebRtcHideLocalIpsWithMdns,MediaStream,WebRtc "
    "--disable-desktop-capture"
)
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.webenginecontext.debug=false"

# Load .env file variables into os.environ at startup
from daemon.utils.env_manager import get_env_manager
get_env_manager().load_env_dict()

# Import Jarvis Subsystem Modules
from daemon.ipc.socket_server import IPCServer
from daemon.ipc.hotkey_interceptor import HotkeyInterceptor
from daemon.stt.audio_recorder import AudioRecorder
from daemon.tools.registry import ToolRegistry
from daemon.tools.execution_engine import ExecutionEngine
from daemon.agent.orchestrator import AgentOrchestrator
from daemon.memory.transcript_logger import TranscriptLogger
from daemon.memory.profiler_agent import MemoryProfilerAgent

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML_PATH = BASE_DIR / "ui" / "index.html"
HUD_HTML_PATH = BASE_DIR / "ui" / "hud.html"
PANEL_HTML_PATH = BASE_DIR / "ui" / "panel.html"

# Always-on-top overlays (the pill, the task panel): XWayland override-redirect windows, which
# KWin stacks above every managed window, fullscreen ones included, and which never take focus
# or show up in the taskbar.
OVERLAY_FLAGS = (Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                 Qt.WindowDoesNotAcceptFocus | Qt.BypassWindowManagerHint | Qt.Tool)
KEEP_ON_TOP_MS = 1500  # re-raise while visible, in case another override-redirect popup lands on top


def overlay_screen():
    """The primary screen's rect and the room its Plasma panels take, for placing overlays."""
    from daemon.overlay_layout import plasma_panel_insets
    screen = QApplication.primaryScreen()
    geo = screen.geometry()
    return (geo.x(), geo.y(), geo.width(), geo.height()), plasma_panel_insets(0)

DEFAULT_HOTKEY = "Super + Space"
VALID_RISK_LEVELS = ("SAFE", "MEDIUM", "HIGH")

# Fixed replies the LLM providers return when they cannot answer, mapped to a fix the user can act on.
PROVIDER_FAILURE_HINTS = [
    ("error reaching local ollama server", "Ollama wasn't running. Start it with `ollama serve`, or switch model on Overview."),
    ("account credits required", "Your Anthropic account is out of credits. Add credits at console.anthropic.com or pick another model."),
    ("error reaching anthropic", "Couldn't reach Anthropic. Check your connection and API key in Settings."),
    ("unable to connect to anthropic", "Couldn't reach Anthropic. Check your connection and API key in Settings."),
    ("error reaching gemini", "Couldn't reach Gemini. Check your connection and API key in Settings."),
    ("unable to connect to google gemini", "Couldn't reach Gemini. Check your connection and API key in Settings."),
]


def classify_turn(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Annotates a transcript record with status ("ok" | "failed") and a recovery hint.
    A turn failed when the tool wrote to stderr or the LLM provider returned one of its fixed error replies.
    """
    spoken = (record.get("spoken_response") or "").lower()
    stderr = (record.get("execution_stderr") or "").strip()
    for needle, hint in PROVIDER_FAILURE_HINTS:
        if needle in spoken:
            return {**record, "status": "failed", "failure_hint": hint}
    # Newer turns record whether the tool succeeded: stderr alone isn't failure (git prints progress there).
    outcome = record.get("outcome")
    if outcome is not None and outcome != "failed":
        return {**record, "status": "ok", "failure_hint": ""}
    if stderr:
        first_line = stderr.splitlines()[0][:200]
        return {**record, "status": "failed", "failure_hint": f"The command reported an error: {first_line}"}
    if outcome == "failed":
        return {**record, "status": "failed", "failure_hint": ""}
    return {**record, "status": "ok", "failure_hint": ""}


class TriggerBridge(QObject):
    """
    Qt Signal Bridge for thread-safe cross-thread UI popups.
    """
    show_hud_signal = Signal()
    hide_hud_signal = Signal()
    update_hud_signal = Signal(str, str)
    # Live events for the dashboard page: (event name, JSON payload). Emitted from worker threads,
    # delivered on the GUI thread by Qt's queued connection.
    dashboard_event_signal = Signal(str, str)


class WebBridgeApi(QObject):
    def __init__(self, app_instance: 'JarvisApplication'):
        super().__init__()
        self.app_instance = app_instance

    @Slot(str, str, result=str)
    def call_ipc(self, action: str, params_json: str) -> str:
        try:
            params = json.loads(params_json) if params_json else {}
            res = self.app_instance.handle_ipc_command(action, params)
            return json.dumps(res)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})


class DashboardWindow(QMainWindow):
    def __init__(self, app_instance: 'JarvisApplication', bridge: Optional[TriggerBridge] = None):
        super().__init__()
        self.app_instance = app_instance
        self.bridge = bridge
        self.setWindowTitle("Jarvis Desktop AI Assistant")
        self.resize(920, 640)
        self.setMinimumSize(QSize(720, 520))

        self.web_view = QWebEngineView(self)
        self.setCentralWidget(self.web_view)

        # PySide6 QWebChannel IPC setup
        self.channel = QWebChannel(self.web_view.page())
        self.api = WebBridgeApi(self.app_instance)
        self.channel.registerObject("jarvisBridge", self.api)
        self.web_view.page().setWebChannel(self.channel)
        
        index_url = QUrl.fromLocalFile(str(INDEX_HTML_PATH))
        self.web_view.load(index_url)

        # In-app shortcut trigger for Super+Space
        self.shortcut = QShortcut(QKeySequence("Super+Space"), self)
        self.shortcut.activated.connect(self._on_shortcut_activated)

        if self.bridge:
            self.bridge.dashboard_event_signal.connect(self.push_event)

    def push_event(self, name: str, payload_json: str):
        """Hand a live voice-loop event to the page (see window.jarvisEvent in ui/js/app.js)."""
        js = f"window.jarvisEvent && window.jarvisEvent({json.dumps(name)}, {payload_json});"
        self.web_view.page().runJavaScript(js)

    def _on_shortcut_activated(self):
        if self.bridge:
            print("[Dashboard] Local QShortcut triggered: Super+Space", flush=True)
            self.bridge.show_hud_signal.emit()


class PanelBridgeApi(WebBridgeApi):
    """The task panel's page talks to Jarvis like the dashboard does, and also sizes its window."""

    def __init__(self, app_instance: 'JarvisApplication', window: 'EdgePanelWindow'):
        super().__init__(app_instance)
        self.window = window

    @Slot(bool, int, int)
    def layout(self, visible: bool, width: int, height: int):
        self.window.apply_layout(visible, width, height)


class EdgePanelWindow(QMainWindow):
    """
    Background tasks at the right edge of the screen, always on top. It appears while a task runs
    (or needs an OK), can be tucked into a small tab, and is sized to its content so it never
    blocks clicks anywhere else.
    """

    def __init__(self, app_instance: 'JarvisApplication', bridge: TriggerBridge):
        super().__init__()
        self.setWindowTitle("Jarvis Task Panel")
        self.setWindowFlags(OVERLAY_FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(360, 120)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setBackgroundColor(Qt.transparent)
        self.setCentralWidget(self.web_view)
        self.channel = QWebChannel(self.web_view.page())
        self.api = PanelBridgeApi(app_instance, self)
        self.channel.registerObject("jarvisBridge", self.api)
        self.web_view.page().setWebChannel(self.channel)
        self.web_view.load(QUrl.fromLocalFile(str(PANEL_HTML_PATH)))

        self._keep_on_top = QTimer(self)
        self._keep_on_top.setInterval(KEEP_ON_TOP_MS)
        self._keep_on_top.timeout.connect(self.raise_)
        bridge.dashboard_event_signal.connect(self.push_event)

    def push_event(self, name: str, payload_json: str):
        if name.startswith("task_"):
            js = f"window.panelEvent && window.panelEvent({json.dumps(name)}, {payload_json});"
            self.web_view.page().runJavaScript(js)

    def apply_layout(self, visible: bool, width: int, height: int):
        from daemon.overlay_layout import edge_panel_position
        if not visible or height <= 0:
            self._keep_on_top.stop()
            self.hide()
            return
        screen, insets = overlay_screen()
        max_h = screen[3] - insets["top"] - insets["bottom"] - 24
        width, height = max(48, min(width, 480)), max(48, min(height, max_h))
        x, y = edge_panel_position(screen, insets, width, height)
        self.setGeometry(x, y, width, height)
        if not self.isVisible():
            self.show()
            self._keep_on_top.start()
        self.raise_()


class HUDWindow(QMainWindow):
    def __init__(self, bridge: Optional[TriggerBridge] = None):
        super().__init__()
        self.bridge = bridge
        self.setWindowTitle("Jarvis HUD Pill")
        self.setWindowFlags(OVERLAY_FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setFixedSize(520, 68)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setBackgroundColor(Qt.transparent)
        self.setCentralWidget(self.web_view)

        hud_url = QUrl.fromLocalFile(str(HUD_HTML_PATH))
        self.web_view.load(hud_url)

        self._keep_on_top = QTimer(self)
        self._keep_on_top.setInterval(KEEP_ON_TOP_MS)
        self._keep_on_top.timeout.connect(self.raise_)

        if self.bridge:
            self.bridge.show_hud_signal.connect(self.show_hud)
            self.bridge.hide_hud_signal.connect(self.hide_hud)
            self.bridge.update_hud_signal.connect(self.update_hud_state)

    def position_at_bottom_center(self):
        """Bottom centre of the primary screen, just above the Plasma panel (not on top of it)."""
        from daemon.overlay_layout import pill_position
        if QApplication.primaryScreen():
            screen, insets = overlay_screen()
            x, y = pill_position(screen, insets, 520, 68)
            self.setGeometry(x, y, 520, 68)
            self.move(x, y)

    def _ensure_on_top(self):
        self.position_at_bottom_center()
        self.raise_()

    def show_hud(self):
        """
        Pops up HUD pill anchored at bottom center of screen always on top without taking focus.
        """
        print("[HUDWindow] 🔴 Popping up HUD Pill at bottom center (Always On Top)!", flush=True)
        self.position_at_bottom_center()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()
        QTimer.singleShot(20, self._ensure_on_top)
        self._keep_on_top.start()

    def hide_hud(self):
        """
        Hides HUD pill when idle.
        """
        print("[HUDWindow] ⏹️ Hiding HUD Pill...", flush=True)
        self._keep_on_top.stop()
        self.hide()

    def update_hud_state(self, event_name: str, text: str = ""):
        """
        Updates HUD pill JavaScript state safely using json.dumps escaping.
        """
        import json
        payload_json = json.dumps({"text": text, "spoken": text})
        event_json = json.dumps(event_name)
        js_code = f"if (typeof updateHUDState === 'function') updateHUDState({event_json}, {payload_json});"
        self.web_view.page().runJavaScript(js_code)


class JarvisApplication:
    def __init__(self):
        print("==================================================")
        print("      Starting Jarvis Desktop Voice Assistant     ")
        print("==================================================")

        # Qt Signal Bridge
        self.bridge = TriggerBridge()

        # Live voice-loop state shown on the dashboard: idle | listening | thinking | speaking
        self.voice_state = "idle"
        self._reanalyzing = False
        self._last_reanalysis: Optional[Dict[str, Any]] = None
        self._voice_test_running = False
        self._llm_check_cache: Dict[str, Any] = {"at": 0.0, "result": None}

        # 1. Memory & Providers Subsystem
        self.logger = TranscriptLogger()
        self.profiler = MemoryProfilerAgent(logger=self.logger)
        
        # Start optional S3 sync thread if enabled in .env
        self.logger.start_background_s3_sync(interval_sec=300)

        # Import ProviderFactory for Pluggable STT / LLM / TTS Providers
        from daemon.providers.factory import get_provider_factory
        self.provider_factory = get_provider_factory()

        # 2. Tools & Orchestrator
        self.registry = ToolRegistry()
        self.engine = ExecutionEngine(self.registry)
        self.tts = self.provider_factory.tts_provider
        self.orchestrator = AgentOrchestrator(
            model_name=self.provider_factory.settings.get("llm_model", "qwen3.5:9b"),
            registry=self.registry,
            engine=self.engine,
            tts=self.tts,
            logger=self.logger,
            llm_provider=self.provider_factory.llm_provider
        )

        from daemon.agent.fast_path_agent import FastPathCreatorAgent
        self.fast_path_agent = FastPathCreatorAgent(fast_path_manager=self.orchestrator.fast_path_manager)
        self._wire_stt_vocabulary()
        self._ensure_local_models()
        self._wire_routes()
        from daemon.agent.tasks import TaskBoard
        self.orchestrator.task_board = TaskBoard(listener=self._on_task_event)

        self.recorder = AudioRecorder()

        # 3. IPC Domain Socket Server
        self.ipc_server = IPCServer(command_handler=self.handle_ipc_command)
        self.ipc_server.start()

        # 4. Global Hotkey Interceptor (Super + Space)
        self.hotkey_interceptor = HotkeyInterceptor(
            shortcut_str=self.provider_factory.settings.get("hotkey") or DEFAULT_HOTKEY,
            on_press_callback=self.on_hotkey_press,
            on_release_callback=self.on_hotkey_release,
            release_buffer_ms=200
        )
        self.hotkey_interceptor.start()

        # GUI Window References
        self.qt_app: Optional[QApplication] = None
        self.dashboard_win: Optional[DashboardWindow] = None
        self.hud_win: Optional[HUDWindow] = None
        self.panel_win: Optional[EdgePanelWindow] = None

    def handle_ipc_command(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles incoming JSON-RPC commands from the GUI dashboard.
        """
        if action == "get_status":
            if params.get("recheck"):
                self._llm_check_cache = {"at": 0.0, "result": None}
            return self._build_status()
        elif action == "update_keybind":
            new_shortcut = " + ".join(p.strip() for p in str(params.get("keybind", "")).split("+") if p.strip())
            if not new_shortcut:
                return {"success": False, "error": "No keys were recorded. Click the shortcut box and hold the keys you want."}
            if len(new_shortcut.split(" + ")) > 4:
                return {"success": False, "error": "Use four keys or fewer for the talk shortcut."}
            self.hotkey_interceptor.update_shortcut(new_shortcut)
            self.provider_factory.settings["hotkey"] = new_shortcut
            self.provider_factory.save_settings()
            return {"success": True, "new_shortcut": new_shortcut}
        elif action == "get_tasks":
            return {"success": True, "tasks": self.orchestrator.task_board.snapshot()}
        elif action == "submit_text":
            return self.submit_text(params.get("text", ""))
        elif action == "answer_task":
            task = self.orchestrator.task_board.answer(bool(params.get("approve")), params.get("id") or None)
            if not task:
                return {"success": False, "error": "That step isn't waiting anymore."}
            return {"success": True, "id": task.id}
        elif action == "cancel_task":
            task = self.orchestrator.task_board.cancel(params.get("id") or None)
            if not task:
                return {"success": False, "error": "That task has already finished."}
            return {"success": True, "id": task.id}
        elif action == "get_tools":
            tools = []
            for t in sorted(self.registry.list_tools(), key=lambda m: m.id):
                tools.append({
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "command": t.execution.template if t.execution else "",
                    "examples": [ex.user_prompt for ex in t.examples],
                    "risk_level": t.risk_level,
                })
            return {"success": True, "tools": tools}
        elif action == "test_voice":
            return self._start_voice_test(params.get("voice"))
        elif action == "set_voice_sampling":
            try:
                count = max(0, min(200, int(params.get("count", 0))))
            except (TypeError, ValueError):
                return {"success": False, "error": "Count must be a whole number."}
            self.provider_factory.settings["voice_samples_remaining"] = count
            self.provider_factory.save_settings()
            return {"success": True, "voice_samples": self._voice_sample_status()}
        elif action == "get_settings":
            tts_provider = self.provider_factory.tts_provider
            available_voices = tts_provider.get_available_voices() if tts_provider else []
            return {
                "success": True,
                "settings": self.provider_factory.settings,
                "stt_providers": self.provider_factory.get_available_stt_providers(),
                "tts_providers": self.provider_factory.get_available_tts_providers(),
                "llm_providers": self.provider_factory.get_available_llm_providers(),
                "available_voices": available_voices
            }
        elif action == "get_voices_for_provider":
            tts_id = params.get("tts_provider", self.provider_factory.settings.get("tts_provider", "kokoro"))
            voices = self.provider_factory.get_voices_for_provider(tts_id)
            return {"success": True, "tts_provider": tts_id, "voices": voices}
        elif action == "update_provider_config":
            self.provider_factory.update_settings(params)
            self.orchestrator.set_llm_provider(self.provider_factory.llm_provider)
            self.orchestrator.tts = self.provider_factory.tts_provider
            self.tts = self.provider_factory.tts_provider
            self.profiler.set_llm_provider(self.provider_factory.llm_provider)
            self._wire_stt_vocabulary()
            self._ensure_local_models()
            self._apply_s3_settings_live()
            self._llm_check_cache = {"at": 0.0, "result": None}
            return {
                "success": True,
                "settings": self.provider_factory.settings,
                "available_voices": self.provider_factory.tts_provider.get_available_voices() if self.provider_factory.tts_provider else []
            }
        elif action == "register_custom_tool":
            tool_id = str(params.get("id", "")).strip()
            if not tool_id:
                return {"success": False, "error": "The command needs an ID."}
            if params.get("risk_level") not in VALID_RISK_LEVELS:
                return {"success": False, "error": "Choose a risk level: Safe, Medium or High."}
            if self.registry.get_tool(tool_id) and not params.get("overwrite"):
                return {"success": False, "error": f"A command with the ID '{tool_id}' already exists.", "exists": True}
            params = {k: v for k, v in params.items() if k != "overwrite"}
            manifest = self.registry.register_tool(params)
            self.orchestrator.registry.reload_tools()
            print(f"[Jarvis Main] Registered custom tool manifest: {manifest.id}", flush=True)
            return {"success": True, "tool_id": manifest.id}
        elif action == "get_transcripts":
            transcripts = [classify_turn(r) for r in self.logger.read_all_transcripts()]
            return {"success": True, "transcripts": transcripts}
        elif action == "get_memory_profile":
            from daemon.memory.profiler_agent import load_user_profile
            content = load_user_profile(self.profiler.profile_path)
            return {"success": True, "content": content, "reanalyzing": self._reanalyzing, "last_reanalysis": self._last_reanalysis}
        elif action == "reanalyze_memory":
            return self._start_reanalysis()
        elif action == "get_fast_path_rules":
            rules = self.orchestrator.fast_path_manager.get_all_rules()
            return {"success": True, "rules": rules}
        elif action == "delete_fast_path_rule":
            rule_id = params.get("rule_id", "")
            success = self.orchestrator.fast_path_manager.delete_rule(rule_id)
            return {"success": success, "rule_id": rule_id}
        elif action == "get_macros":
            from daemon.macros.macro_manager import get_macro_manager
            macros = get_macro_manager().list_macros()
            return {"success": True, "macros": macros}
        elif action == "save_macro":
            from daemon.macros.macro_manager import get_macro_manager
            name = params.get("name", "")
            steps = params.get("steps") or params.get("apps") or []
            directory = params.get("directory", "")
            spec = get_macro_manager().save_macro(name, steps, directory=directory)
            return {"success": True, "macro": spec}
        elif action == "run_macro":
            from daemon.macros.macro_manager import get_macro_manager
            name = params.get("name", "")
            res = get_macro_manager().run_macro(name)
            return res
        elif action == "delete_macro":
            from daemon.macros.macro_manager import get_macro_manager
            name = params.get("name", "")
            deleted = get_macro_manager().delete_macro(name)
            return {"success": deleted, "name": name}
        return {"success": False, "error": f"Unknown action '{action}'."}

    # ------------------------------------------------------------------
    # Dashboard status helpers
    # ------------------------------------------------------------------

    def _check_llm(self) -> Dict[str, Any]:
        """
        Cheap reachability check for the active LLM, cached for 10s so the dashboard can poll it.
        Ollama is probed over localhost (connection refused returns instantly); cloud providers
        only report whether an API key is configured.
        """
        now = time.monotonic()
        cached = self._llm_check_cache
        if cached["result"] is not None and now - cached["at"] < 10:
            return cached["result"]

        provider = self.provider_factory.llm_provider
        info = provider.get_provider_info() if provider else {}
        provider_id = info.get("id", "")
        result: Dict[str, Any] = {"ok": True, "message": ""}

        if provider_id.startswith("ollama"):
            from daemon.utils import ollama_service
            url = getattr(provider, "ollama_url", "http://localhost:11434").rstrip("/")
            if ollama_service.is_running(url, timeout=0.4):
                result = {"ok": True, "message": ""}
            elif ollama_service.is_starting():
                # Not cached: the dashboard should flip to Ready the moment Ollama answers.
                return {"ok": False, "starting": True, "message": "Starting Ollama…"}
            elif ollama_service.find_binary():
                # Selected but not running (never started, or it stopped): start it in the background.
                self._ensure_local_models()
                return {"ok": False, "starting": True, "message": "Starting Ollama…"}
            else:
                result = {"ok": False, "message": "Ollama isn't installed. Install it, or pick a cloud model in Settings."}
        elif provider_id == "anthropic_llm" and not os.environ.get("ANTHROPIC_API_KEY"):
            result = {"ok": False, "message": "No Anthropic API key is set. Add one in Settings."}
        elif provider_id == "gemini_llm" and not os.environ.get("GEMINI_API_KEY"):
            result = {"ok": False, "message": "No Gemini API key is set. Add one in Settings."}

        self._llm_check_cache = {"at": now, "result": result}
        return result

    def _build_status(self) -> Dict[str, Any]:
        factory = self.provider_factory
        stt_info = factory.stt_provider.get_provider_info() if factory.stt_provider else {}
        llm_info = factory.llm_provider.get_provider_info() if factory.llm_provider else {}
        tts_info = factory.tts_provider.get_provider_info() if factory.tts_provider else {}
        server_thread = getattr(self.ipc_server, "_server_thread", None)
        return {
            "success": True,
            # Kept for older IPC clients (bin/jarvis-macro etc.)
            "daemon_status": "active",
            "active_keybind": self.hotkey_interceptor.shortcut_str,
            "tasks_running": len(self.orchestrator.task_board.running(background_only=True)),
            "model_name": self.orchestrator.model_name,
            "s3_bucket": self.logger.bucket_name or "Not Configured",
            # Dashboard fields
            "voice_state": self.voice_state,
            "hotkey": self.hotkey_interceptor.shortcut_str,
            "ipc": {
                "running": bool(server_thread and server_thread.is_alive()),
                "socket_path": self.ipc_server.socket_path,
            },
            "s3": {
                "enabled": bool(self.logger.s3_sync_enabled),
                "bucket": self.logger.bucket_name or "",
                "arn": self.logger.s3_arn or "",
                "region": self.logger.aws_region or "",
            },
            "stt": {"name": stt_info.get("name", ""), "model": factory.settings.get("stt_model", "")},
            "llm": {"name": llm_info.get("name", ""), "model": llm_info.get("model_name", ""), "check": self._check_llm()},
            "tts": {"name": tts_info.get("name", ""), "voice": factory.settings.get("tts_voice", "")},
            "reanalyzing": self._reanalyzing,
            "voice_samples": self._voice_sample_status(),
        }

    def _apply_s3_settings_live(self):
        """
        Pushes S3 settings that update_settings wrote to os.environ into the running transcript logger,
        so the dashboard reflects them without a restart.
        """
        from daemon.memory.transcript_logger import parse_bucket_name
        self.logger.s3_arn = os.getenv("JARVIS_S3_BUCKET_ARN", "")
        self.logger.bucket_name = parse_bucket_name(self.logger.s3_arn)
        self.logger.aws_region = os.getenv("AWS_REGION", "us-east-1")
        enabled_env = os.getenv("JARVIS_S3_SYNC_ENABLED", "false").lower() in ("true", "1", "yes")
        self.logger.s3_sync_enabled = enabled_env and bool(self.logger.bucket_name)

    # ------------------------------------------------------------------
    # Speech recognition helpers
    # ------------------------------------------------------------------

    def _known_phrases(self):
        """Everything Jarvis already knows you say: shortcut phrases, command examples, macro names."""
        phrases = []
        for rule in self.orchestrator.fast_path_manager.get_all_rules():
            phrases.extend(rule.get("triggers") or [])
        for tool in self.registry.list_tools():
            phrases.extend(ex.user_prompt for ex in tool.examples)
        try:
            from daemon.macros.macro_manager import get_macro_manager
            for macro in get_macro_manager().list_macros().values():
                name = str(macro.get("name") or macro.get("id") or "").replace("_", " ").replace("-", " ").strip()
                if name:
                    phrases.extend([name, f"start {name}", f"run {name}"])
        except Exception as err:
            print(f"[Jarvis Main] Couldn't read macros for the STT vocabulary: {err}", flush=True)
        return phrases

    def _wire_routes(self):
        """'Hey Claude, ...' sends that one request to Claude Code (headless, the user's own login)."""
        import re
        from daemon.providers.llm.claude_code_llm_provider import ClaudeCodeLLMProvider, find_claude

        cache: Dict[str, Any] = {}

        def claude_code():
            if not find_claude():
                print("[Jarvis Main] 'Claude' route requested but the claude CLI isn't installed.", flush=True)
                return None
            model = self.provider_factory.settings.get("claude_code_model", "haiku")
            if cache.get("model") != model:
                cache["provider"], cache["model"] = ClaudeCodeLLMProvider(model_name=model), model
            return cache["provider"]

        # "Claude, ...", "Hey Claude ...", "Ask Claude (Code) to ...", plus common mishearings of the name.
        name = r"(?:claude|clawed|clod)(?:\s+code)?"
        leading = re.compile(
            # Up to two short lead-ins first: "No. Hey Claude, ...", "Okay, so Claude, ...".
            r"^\s*(?:(?:no|nope|okay|ok|actually|so|um|uh|wait|well|alright|sorry)[\s,.!]+){0,2}"
            r"(?:(?:hey|hi|ok(?:ay)?|yo)[\s,]+)?(?:ask[\s,]+)?" + name + r"\b[\s,:.!?-]*(?:to\s+)?",
            re.IGNORECASE,
        )
        # Addressed at the end: "..., Claude?" / "... thanks Claude." (needs a comma or 'hey' before the name).
        trailing = re.compile(
            r"(?:(?:,\s*|\s+hey\s+)" + name + r"\s*[.?!]*|\s+" + name + r"\s*\?)\s*$",  # bare name only when it ends a question
            re.IGNORECASE,
        )
        self.orchestrator.routes = [(leading, claude_code, "Claude Code"), (trailing, claude_code, "Claude Code")]
        self.orchestrator.route_listener = lambda label: self.bridge.update_hud_signal.emit("AGENT_THINKING", f"Asking {label}…")

    def _ensure_local_models(self):
        """If the thinking or learning model runs on Ollama, make sure `ollama serve` is up."""
        from daemon.utils import ollama_service
        wanted: Dict[str, set] = {}  # url -> models to keep loaded
        for provider in (self.provider_factory.llm_provider, getattr(self.provider_factory, "memory_llm_provider", None)):
            if provider is None:
                continue
            info = provider.get_provider_info() or {}
            if str(info.get("id", "")).startswith("ollama"):
                url = getattr(provider, "ollama_url", "http://localhost:11434").rstrip("/")
                wanted.setdefault(url, set()).add(getattr(provider, "model_name", ""))
        for url, models in wanted.items():
            def _warm(url=url, models=tuple(m for m in models if m)):
                for model in models:
                    ollama_service.warm_up(url, model)

            if ollama_service.is_running(url, timeout=0.3):
                threading.Thread(target=_warm, daemon=True, name="JarvisOllamaWarmup").start()
                continue
            if ollama_service.is_starting():
                continue

            def _done(result, warm=_warm):
                self._llm_check_cache = {"at": 0.0, "result": None}
                if not result.get("ok"):
                    print(f"[Jarvis Main] {result.get('message')}", flush=True)
                else:
                    warm()
                self._dashboard_event("status_changed")

            ollama_service.ensure_running_async(url, on_done=_done)

    def _on_task_event(self, event: str, task: Dict[str, Any]):
        """A background task started, moved to a new step, or finished (called from its own thread)."""
        self._dashboard_event(event, {"task": task})
        self.ipc_server.broadcast_event(event.upper(), {"task": task})
        if event == "task_finished" and task.get("status") != "cancelled":
            threading.Thread(target=self._announce_task, args=(task,), daemon=True,
                             name="JarvisTaskAnnounce").start()
        elif event == "task_needs_approval":
            from daemon.agent.orchestrator import approval_question
            threading.Thread(target=self._announce_task, args=(task, approval_question(task.get("approval") or {}), "Needs your OK"),
                             daemon=True, name="JarvisTaskAsk").start()

    def _announce_task(self, task: Dict[str, Any], text: str = "", title: str = ""):
        """Say that a background task finished (or needs an OK), once Jarvis isn't mid-request."""
        text = text or task.get("result") or "Finished."
        title = title or ("Done" if task.get("status") == "done" else "Couldn't finish")
        query = " ".join(str(task.get("title", "")).split())
        query = query if len(query) <= 60 else query[:59] + "…"
        notify = shutil.which("notify-send")
        if notify:
            subprocess.Popen([notify, "-a", "Jarvis", "-i", "audio-input-microphone", f"{title}: {query}", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 120
        while self.voice_state != "idle" and time.time() < deadline:
            time.sleep(0.2)
        self.bridge.show_hud_signal.emit()
        self.bridge.update_hud_signal.emit("TTS_SPEAKING", text)
        try:
            self.orchestrator._speak(text)
        except Exception as err:
            print(f"[Jarvis Main] Couldn't speak the task result: {err}", flush=True)
        time.sleep(1.5)
        if self.voice_state == "idle":
            self.bridge.hide_hud_signal.emit()

    def _dashboard_event(self, name: str, payload: Optional[Dict[str, Any]] = None):
        try:
            self.bridge.dashboard_event_signal.emit(name, json.dumps(payload or {}))
        except Exception as err:
            print(f"[Jarvis Main] Couldn't notify the dashboard ({name}): {err}", flush=True)

    def _wire_stt_vocabulary(self):
        stt = self.provider_factory.stt_provider
        if stt is not None and hasattr(stt, "set_vocabulary_source"):
            stt.set_vocabulary_source(self._known_phrases)

    def _voice_sample_status(self) -> Dict[str, Any]:
        sample_dir = Path.home() / ".local" / "share" / "jarvis" / "voice_samples"
        saved = len(list(sample_dir.glob("*.wav"))) if sample_dir.exists() else 0
        return {
            "remaining": int(self.provider_factory.settings.get("voice_samples_remaining", 0) or 0),
            "saved": saved,
            "dir": str(sample_dir),
        }

    def _maybe_save_voice_sample(self, pcm_buffer, heard: str, alternatives):
        """When the user opted in, keep this utterance's audio and what was heard, for accuracy testing."""
        remaining = int(self.provider_factory.settings.get("voice_samples_remaining", 0) or 0)
        if remaining <= 0 or pcm_buffer is None or len(pcm_buffer) == 0:
            return
        try:
            import numpy as np
            import soundfile as sf
            if isinstance(pcm_buffer, (bytes, bytearray)):
                audio = np.frombuffer(pcm_buffer[: len(pcm_buffer) - len(pcm_buffer) % 2], dtype=np.int16)
            else:
                audio = np.asarray(pcm_buffer).flatten()
                if audio.dtype != np.int16:
                    audio = (np.clip(audio.astype(np.float32), -1.0, 1.0) * 32767).astype(np.int16)
            sample_dir = Path.home() / ".local" / "share" / "jarvis" / "voice_samples"
            sample_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            wav_path = sample_dir / f"sample-{stamp}-{remaining}.wav"
            sf.write(wav_path, audio, 16000, subtype="PCM_16")
            entry = {"file": wav_path.name, "timestamp": stamp, "heard": heard, "alternatives": alternatives, "said": None}
            with open(sample_dir / "samples.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self.provider_factory.settings["voice_samples_remaining"] = remaining - 1
            self.provider_factory.save_settings()
            print(f"[Jarvis Main] Saved voice sample {wav_path.name} ({remaining - 1} left).", flush=True)
        except Exception as err:
            print(f"[Jarvis Main] Couldn't save voice sample: {err}", flush=True)

    def _start_voice_test(self, voice: Optional[str]) -> Dict[str, Any]:
        tts = self.provider_factory.tts_provider
        if not tts:
            return {"success": False, "error": "No voice engine is loaded."}
        if self._voice_test_running:
            return {"success": False, "error": "A voice test is already playing."}

        def _speak():
            self._voice_test_running = True
            try:
                tts.speak("Hi, this is how I'll sound when I answer you.", voice=voice or None, block=True)
            except Exception as err:
                print(f"[Jarvis Main] Voice test failed: {err}", flush=True)
            finally:
                self._voice_test_running = False

        threading.Thread(target=_speak, daemon=True, name="JarvisVoiceTestThread").start()
        return {"success": True}

    def _start_reanalysis(self) -> Dict[str, Any]:
        if self._reanalyzing:
            return {"success": True, "started": False, "reanalyzing": True}

        def _run():
            self._reanalyzing = True
            try:
                res = self.profiler.update_profile(force=True)
                ok = bool(res.get("success"))
                self._last_reanalysis = {"success": ok, "message": "" if ok else res.get("reason", "The profile couldn't be updated."), "at": time.time()}
                print(f"[Jarvis Main] Memory re-analysis finished: {res.get('reason', 'ok')}", flush=True)
            except Exception as err:
                self._last_reanalysis = {"success": False, "message": str(err), "at": time.time()}
                print(f"[Jarvis Main] Memory re-analysis failed: {err}", flush=True)
            finally:
                self._reanalyzing = False

        threading.Thread(target=_run, daemon=True, name="JarvisReanalyzeThread").start()
        return {"success": True, "started": True, "reanalyzing": True}

    def on_hotkey_press(self):
        """
        Callback when hold-to-talk key combination is pressed.
        Pops up bottom HUD pill and starts microphone recording.
        """
        print("\n[Jarvis Main] 🔴 Hotkey Pressed! Emitting show_hud_signal...", flush=True)
        self.voice_state = "listening"
        self._dashboard_event("listening")
        self.bridge.show_hud_signal.emit()
        self.bridge.update_hud_signal.emit("RECORDING_STARTED", "")

        self.ipc_server.broadcast_event("RECORDING_STARTED", {"mode": "hold_to_talk"})
        
        try:
            self.recorder.start_recording()
        except Exception as e:
            print(f"[Jarvis Main Error] Audio recording error: {e}", flush=True)

    def _handle_request(self, user_text: str, speak_output: bool = True):
        """Run one request (spoken or typed) through the agent, then refresh the dashboard and learn from it."""
        # 1 & 2. Agent Orchestrator processes query & executes tool calls if needed
        result = self.orchestrator.process_voice_query(user_text, speak_output=speak_output)

        final_spoken = result.get("final_spoken_summary", "Task complete.")
        # The orchestrator has logged the turn by now: refresh the dashboard's lists.
        self._dashboard_event("turn_logged", {"text": user_text, "reply": final_spoken})
        if speak_output:
            self.voice_state = "speaking"
            self.bridge.update_hud_signal.emit("TTS_SPEAKING", final_spoken)

        # 3 & 4. Memory profiler and shortcut learner run in the background so the reply returns instantly.
        def _bg_post_processing():
            try:
                mem_provider = self.provider_factory.memory_llm_provider
                old_p = self.profiler.llm_provider
                self.profiler.llm_provider = mem_provider
                profile_res = self.profiler.update_profile(force=False)
                self.profiler.llm_provider = old_p

                profile_content = profile_res.get("content", "") if isinstance(profile_res, dict) else ""
                self.fast_path_agent.update_fast_paths(
                    transcripts=self.logger.read_all_transcripts(),
                    user_profile=profile_content,
                    llm_provider=mem_provider
                )
            except Exception as err:
                print(f"[Jarvis Post-Processing Warning] Background profiling error: {err}", flush=True)

        threading.Thread(target=_bg_post_processing, daemon=True, name="JarvisPostProcessingThread").start()
        return result

    def submit_text(self, text: str) -> Dict[str, Any]:
        """A typed request from the dashboard: same pipeline as voice, without speech in or out."""
        text = " ".join(str(text or "").split())[:500]
        if not text:
            return {"success": False, "error": "Type a request first."}
        if self.voice_state != "idle":
            return {"success": False, "error": "Jarvis is busy with another request. Try again in a moment."}
        self.voice_state = "thinking"
        self._dashboard_event("thinking")
        self._dashboard_event("heard", {"text": text, "alternatives": []})
        print(f"[Jarvis Main] Typed request: \"{text}\"", flush=True)

        def _run():
            try:
                self.logger.set_next_turn_meta({"source": "typed"})
                self._handle_request(text, speak_output=False)
            except Exception as err:
                print(f"[Jarvis Main Error] Typed request error: {err}", flush=True)
            finally:
                self.voice_state = "idle"
                self._dashboard_event("idle")

        threading.Thread(target=_run, daemon=True, name="JarvisTypedRequest").start()
        return {"success": True}

    def on_hotkey_release(self):
        """
        Callback when hold-to-talk key is released (after 200ms buffer).
        Stops recording, runs STT -> LLM -> Tools -> TTS, and hides HUD pill.
        """
        print("[Jarvis Main] ⏹️ Hotkey Released! Processing voice session...", flush=True)
        self.voice_state = "thinking"
        self._dashboard_event("thinking")
        active_model = self.orchestrator.get_active_model_name()
        thinking_msg = f"Inferring action with {active_model}..."
        self.bridge.update_hud_signal.emit("AGENT_THINKING", thinking_msg)
        self.ipc_server.broadcast_event("AGENT_THINKING", {"text": thinking_msg})

        def _async_process():
            try:
                pcm_buffer = self.recorder.stop_recording()
                if pcm_buffer is None or len(pcm_buffer) == 0:
                    print("[Jarvis Main] No audio captured.", flush=True)
                    self.voice_state = "idle"
                    self.bridge.hide_hud_signal.emit()
                    return

                # Transcribe using active STT provider (Faster-Whisper local or Gemini Cloud API)
                stt_provider = self.provider_factory.stt_provider
                user_text = stt_provider.transcribe_buffer(pcm_buffer)
                print(f"[Jarvis Main] Transcribed ({stt_provider.get_provider_info()['name']}): \"{user_text}\"", flush=True)
                alternatives = list(getattr(stt_provider, "last_alternatives", []) or [])[:5]
                self._maybe_save_voice_sample(pcm_buffer, user_text, alternatives)

                if not user_text.strip():
                    self.voice_state = "idle"
                    self.bridge.hide_hud_signal.emit()
                    return

                self.ipc_server.broadcast_event("STT_PREVIEW", {"text": user_text})
                self._dashboard_event("heard", {"text": user_text, "alternatives": alternatives})
                if alternatives:
                    self.logger.set_next_turn_meta({"heard_alternatives": alternatives})

                self._handle_request(user_text, speak_output=True)

            except Exception as e:
                print(f"[Jarvis Main Error] Voice processing error: {e}", flush=True)
            finally:
                # Hide HUD pill after processing finishes
                time.sleep(1.5)
                self.voice_state = "idle"
                self._dashboard_event("idle")
                self.bridge.hide_hud_signal.emit()
                self.ipc_server.broadcast_event("IDLE")

        threading.Thread(target=_async_process, daemon=True, name="JarvisVoiceProcessThread").start()

    def run(self):
        """
        Launches PySide6 QApplication loop.
        """
        self.qt_app = QApplication(sys.argv)

        self.dashboard_win = DashboardWindow(app_instance=self, bridge=self.bridge)
        self.dashboard_win.show()

        if HUD_HTML_PATH.exists():
            self.hud_win = HUDWindow(bridge=self.bridge)
            # Wispr Flow Mechanic: Hidden by default when idle!
            self.hud_win.hide_hud()

        if PANEL_HTML_PATH.exists():
            self.panel_win = EdgePanelWindow(app_instance=self, bridge=self.bridge)

        print("[Jarvis Main] Native Desktop GUI & Wispr Flow HUD ready.")
        print("[Jarvis Main] Press & hold [Super + Space] anywhere on your computer to talk to Jarvis!")

        sys.exit(self.qt_app.exec())


if __name__ == "__main__":
    app = JarvisApplication()
    app.run()
