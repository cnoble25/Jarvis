#!/usr/bin/env python3
"""
Jarvis Standalone External Visual Timer Widget Addon
Independent background process that displays an always-on-top glassmorphic 
countdown timer widget on the desktop without modifying or bloating the main Jarvis application core.
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Force Qt to use X11/Xwayland platform plugin (xcb) on Linux for absolute screen positioning
os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu --disable-software-rasterizer --disable-dev-shm-usage --autoplay-policy=no-user-gesture-required"
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.webenginecontext.debug=false"

from PySide6.QtCore import Qt, QUrl, QTimer, Slot, QObject
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
TIMER_HTML_PATH = BASE_DIR / "ui" / "timer_widget.html"
BELL_WAV_PATH = BASE_DIR / "daemon" / "tools" / "scripts" / "bell.wav"


class WebBridgeApi(QObject):
    def __init__(self, window_instance: 'TimerWidgetApp'):
        super().__init__()
        self.window_instance = window_instance

    @Slot(str, str, result=str)
    def call_ipc(self, action: str, params_json: str) -> str:
        if action in ["hide_timer_widget", "close_timer_widget"]:
            self.window_instance.close_app()
        elif action == "timer_expired":
            self.window_instance.on_timer_expired()
        return json.dumps({"success": True})


class TimerWidgetApp(QMainWindow):
    def __init__(self, duration_sec: int, label: str):
        super().__init__()
        self.duration_sec = duration_sec
        self.label = label
        self.is_expired = False
        
        self.setWindowTitle(f"Jarvis Timer - {label}")
        self.setWindowFlags(
            Qt.Window |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.WindowDoesNotAcceptFocus |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setFixedSize(290, 140)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setBackgroundColor(Qt.transparent)
        self.setCentralWidget(self.web_view)

        # PySide6 QWebChannel setup for close button click
        self.channel = QWebChannel(self.web_view.page())
        self.api = WebBridgeApi(self)
        self.channel.registerObject("jarvisBridge", self.api)
        self.web_view.page().setWebChannel(self.channel)

        if TIMER_HTML_PATH.exists():
            timer_url = QUrl.fromLocalFile(str(TIMER_HTML_PATH))
            self.web_view.load(timer_url)

        # Position at top-right of screen
        self.position_top_right()

        # Trigger timer initialization after page load
        QTimer.singleShot(150, self._init_widget)
        
        # Periodic 2-second timer to ensure window stays pinned on top of all apps
        self.top_timer = QTimer(self)
        self.top_timer.setInterval(2000)
        self.top_timer.timeout.connect(self._keep_on_top)
        self.top_timer.start()

        # Python-level backup timer for expiration sound & auto-close
        QTimer.singleShot(int((self.duration_sec + 0.2) * 1000), self.on_timer_expired)

    def position_top_right(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = int(geo.x() + geo.width() - 310)
            y = int(geo.y() + 60)
            self.setGeometry(x, y, 290, 140)
            self.move(x, y)
        self.raise_()
        os.system(f"wmctrl -r 'Jarvis Timer' -b add,above,sticky 2>/dev/null &")

    def _keep_on_top(self):
        self.raise_()

    def _init_widget(self):
        label_json = json.dumps(self.label)
        js_code = f"if (typeof window.initTimerWidget === 'function') window.initTimerWidget({self.duration_sec}, {label_json});"
        self.web_view.page().runJavaScript(js_code)

    def _ring_bell(self):
        import threading
        def _play():
            try:
                if BELL_WAV_PATH.exists():
                    os.system(f"paplay '{BELL_WAV_PATH}' 2>/dev/null || pw-play '{BELL_WAV_PATH}' 2>/dev/null || aplay '{BELL_WAV_PATH}' 2>/dev/null")
                else:
                    os.system("canberra-gtk-play -i bell 2>/dev/null || printf '\a'")
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    def on_timer_expired(self):
        if self.is_expired:
            return
        self.is_expired = True
        print(f"[Jarvis Timer Addon] 🔔 Timer '{self.label}' expired! Ringing alarm continuously for 10 seconds...", flush=True)

        os.system(f"notify-send -u critical 'Jarvis Timer' '{self.label} timer is complete!' &")

        # Ring immediately, then repeat every 1200ms for full 10 seconds
        self._ring_bell()
        self.alarm_timer = QTimer(self)
        self.alarm_timer.setInterval(1200)
        self.alarm_timer.timeout.connect(self._ring_bell)
        self.alarm_timer.start()

        # Stop alarm and close window after 10 seconds
        print(f"[Jarvis Timer Addon] Alarm will ring for full 10 seconds before auto-closing...", flush=True)
        QTimer.singleShot(10000, self.close_app)

    def close_app(self):
        if hasattr(self, 'alarm_timer') and self.alarm_timer and self.alarm_timer.isActive():
            self.alarm_timer.stop()
        if hasattr(self, 'top_timer') and self.top_timer and self.top_timer.isActive():
            self.top_timer.stop()
        print(f"[Jarvis Timer Addon] Closing timer widget for '{self.label}'...", flush=True)
        self.close()
        QApplication.quit()


def main():
    parser = argparse.ArgumentParser(description="Jarvis Standalone Visual Timer Widget Addon")
    parser.add_argument("--duration", type=int, default=60, help="Timer duration in seconds")
    parser.add_argument("--label", type=str, default="Jarvis Timer", help="Label or title for the timer")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    widget = TimerWidgetApp(duration_sec=args.duration, label=args.label)
    widget.show()
    widget.raise_()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
