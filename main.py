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
import sys
import time
import threading
from pathlib import Path
import json
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
from daemon.stt.stt_engine import STTEngine
from daemon.tts.tts_engine import TTSEngine
from daemon.tools.registry import ToolRegistry
from daemon.tools.execution_engine import ExecutionEngine
from daemon.agent.orchestrator import AgentOrchestrator
from daemon.memory.transcript_logger import TranscriptLogger
from daemon.memory.profiler_agent import MemoryProfilerAgent

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML_PATH = BASE_DIR / "ui" / "index.html"
HUD_HTML_PATH = BASE_DIR / "ui" / "hud.html"


class TriggerBridge(QObject):
    """
    Qt Signal Bridge for thread-safe cross-thread UI popups.
    """
    show_hud_signal = Signal()
    hide_hud_signal = Signal()
    update_hud_signal = Signal(str, str)


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

        # In-app shortcut trigger for Ctrl+Space
        self.shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.shortcut.activated.connect(self._on_shortcut_activated)

    def _on_shortcut_activated(self):
        if self.bridge:
            print("[Dashboard] Local QShortcut triggered: Ctrl+Space", flush=True)
            self.bridge.show_hud_signal.emit()


class HUDWindow(QMainWindow):
    def __init__(self, bridge: Optional[TriggerBridge] = None):
        super().__init__()
        self.bridge = bridge
        self.setWindowTitle("Jarvis HUD Pill")
        self.setWindowFlags(
            Qt.Window |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus |
            Qt.BypassWindowManagerHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setFixedSize(520, 68)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setBackgroundColor(Qt.transparent)
        self.setCentralWidget(self.web_view)

        hud_url = QUrl.fromLocalFile(str(HUD_HTML_PATH))
        self.web_view.load(hud_url)

        if self.bridge:
            self.bridge.show_hud_signal.connect(self.show_hud)
            self.bridge.hide_hud_signal.connect(self.hide_hud)
            self.bridge.update_hud_signal.connect(self.update_hud_state)

    def position_at_bottom_center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = int(geo.x() + (geo.width() - 520) / 2)
            y = int(geo.y() + geo.height() - 90)
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

    def hide_hud(self):
        """
        Hides HUD pill when idle.
        """
        print("[HUDWindow] ⏹️ Hiding HUD Pill...", flush=True)
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
        self.tts = TTSEngine()
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

        self.recorder = AudioRecorder()

        # 3. IPC Domain Socket Server
        self.ipc_server = IPCServer(command_handler=self.handle_ipc_command)
        self.ipc_server.start()

        # 4. Global Hotkey Interceptor (Ctrl + Space)
        self.hotkey_interceptor = HotkeyInterceptor(
            shortcut_str="Ctrl + Space",
            on_press_callback=self.on_hotkey_press,
            on_release_callback=self.on_hotkey_release,
            release_buffer_ms=200
        )
        self.hotkey_interceptor.start()

        # GUI Window References
        self.qt_app: Optional[QApplication] = None
        self.dashboard_win: Optional[DashboardWindow] = None
        self.hud_win: Optional[HUDWindow] = None

    def handle_ipc_command(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles incoming JSON-RPC commands from the GUI dashboard.
        """
        if action == "get_status":
            return {
                "daemon_status": "active",
                "active_keybind": self.hotkey_interceptor.shortcut_str,
                "model_name": self.orchestrator.model_name,
                "s3_bucket": self.logger.bucket_name or "Not Configured"
            }
        elif action == "update_keybind":
            new_shortcut = params.get("keybind", "Ctrl + Space")
            self.hotkey_interceptor.update_shortcut(new_shortcut)
            return {"success": True, "new_shortcut": new_shortcut}
        elif action == "get_settings":
            return {
                "success": True,
                "settings": self.provider_factory.settings
            }
        elif action == "update_provider_config":
            self.provider_factory.update_settings(params)
            self.orchestrator.set_llm_provider(self.provider_factory.llm_provider)
            self.profiler.set_llm_provider(self.provider_factory.llm_provider)
            return {"success": True, "settings": self.provider_factory.settings}
        elif action == "register_custom_tool":
            manifest = self.registry.register_tool(params)
            self.orchestrator.registry.reload_tools()
            print(f"[Jarvis Main] Registered custom tool manifest: {manifest.id}", flush=True)
            return {"success": True, "tool_id": manifest.id}
        elif action == "get_transcripts":
            transcripts = self.logger.read_all_transcripts()
            return {"success": True, "transcripts": transcripts}
        elif action == "get_memory_profile":
            from daemon.memory.profiler_agent import load_user_profile
            content = load_user_profile(self.profiler.profile_path)
            return {"success": True, "content": content}
        elif action == "reanalyze_memory":
            res = self.profiler.update_profile(force=True)
            from daemon.memory.profiler_agent import load_user_profile
            res["content"] = load_user_profile(self.profiler.profile_path)
            return res
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
        return {"status": "ok", "action": action}

    def on_hotkey_press(self):
        """
        Callback when hold-to-talk key combination is pressed.
        Pops up bottom HUD pill and starts microphone recording.
        """
        print("\n[Jarvis Main] 🔴 Hotkey Pressed! Emitting show_hud_signal...", flush=True)
        self.bridge.show_hud_signal.emit()
        self.bridge.update_hud_signal.emit("RECORDING_STARTED", "")

        self.ipc_server.broadcast_event("RECORDING_STARTED", {"mode": "hold_to_talk"})
        
        try:
            self.recorder.start_recording()
        except Exception as e:
            print(f"[Jarvis Main Error] Audio recording error: {e}", flush=True)

    def on_hotkey_release(self):
        """
        Callback when hold-to-talk key is released (after 200ms buffer).
        Stops recording, runs STT -> LLM -> Tools -> TTS, and hides HUD pill.
        """
        print("[Jarvis Main] ⏹️ Hotkey Released! Processing voice session...", flush=True)
        active_model = self.orchestrator.get_active_model_name()
        thinking_msg = f"Inferring action with {active_model}..."
        self.bridge.update_hud_signal.emit("AGENT_THINKING", thinking_msg)
        self.ipc_server.broadcast_event("AGENT_THINKING", {"text": thinking_msg})

        def _async_process():
            try:
                pcm_buffer = self.recorder.stop_recording()
                if pcm_buffer is None or len(pcm_buffer) == 0:
                    print("[Jarvis Main] No audio captured.", flush=True)
                    self.bridge.hide_hud_signal.emit()
                    return

                # Transcribe using active STT provider (Faster-Whisper local or Gemini Cloud API)
                stt_provider = self.provider_factory.stt_provider
                user_text = stt_provider.transcribe_buffer(pcm_buffer)
                print(f"[Jarvis Main] Transcribed ({stt_provider.get_provider_info()['name']}): \"{user_text}\"", flush=True)

                if not user_text.strip():
                    self.bridge.hide_hud_signal.emit()
                    return

                self.ipc_server.broadcast_event("STT_PREVIEW", {"text": user_text})

                # 1 & 2. Agent Orchestrator processes query & executes tool calls if needed
                result = self.orchestrator.process_voice_query(user_text, speak_output=True)

                final_spoken = result.get("final_spoken_summary", "Task complete.")
                self.bridge.update_hud_signal.emit("TTS_SPEAKING", final_spoken)

                # 3 & 4. Run Memory Profiler & Fast-Path Creator Agent in background thread so voice response returns instantly!
                def _bg_post_processing():
                    try:
                        mem_provider = self.provider_factory.memory_llm_provider
                        # Temporarily update profiler's provider if overridden
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

            except Exception as e:
                print(f"[Jarvis Main Error] Voice processing error: {e}", flush=True)
            finally:
                # Hide HUD pill after processing finishes
                time.sleep(1.5)
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

        print("[Jarvis Main] Native Desktop GUI & Wispr Flow HUD ready.")
        print("[Jarvis Main] Press & hold [Ctrl + Space] anywhere on your computer to talk to Jarvis!")

        sys.exit(self.qt_app.exec())


if __name__ == "__main__":
    app = JarvisApplication()
    app.run()
