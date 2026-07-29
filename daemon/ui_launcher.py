"""
Jarvis Native PySide6 Desktop UI Launcher (Sub-Task 4.2 & 4.4)
Renders the Jarvis Desktop Dashboard and floating Wispr Flow Bottom HUD Overlay Pill.
The HUD Pill stays HIDDEN when idle and pops up anchored at the bottom-center of the screen
only when hold-to-talk voice commands are active.
"""

import os
import sys
from pathlib import Path

# Fix Linux Wayland / Chromium GPU Segmentation Faults
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu --disable-software-rasterizer --disable-dev-shm-usage"
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.webenginecontext.debug=false"

from PySide6.QtCore import Qt, QUrl, QSize, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = BASE_DIR / "ui" / "index.html"
HUD_HTML_PATH = BASE_DIR / "ui" / "hud.html"


class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis Desktop AI Assistant")
        self.resize(920, 640)
        self.setMinimumSize(QSize(720, 520))

        self.web_view = QWebEngineView(self)
        self.setCentralWidget(self.web_view)
        
        index_url = QUrl.fromLocalFile(str(INDEX_HTML_PATH))
        self.web_view.load(index_url)


class HUDWindow(QMainWindow):
    def __init__(self):
        super().__init__()
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
        self.setFixedSize(460, 60)

        self.web_view = QWebEngineView(self)
        self.web_view.page().setBackgroundColor(Qt.transparent)
        self.setCentralWidget(self.web_view)

        hud_url = QUrl.fromLocalFile(str(HUD_HTML_PATH))
        self.web_view.load(hud_url)

    def position_at_bottom_center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - 460) // 2
            y = geo.y() + geo.height() - 90
            self.setGeometry(x, y, 460, 60)
            self.move(x, y)

    def show_hud(self):
        """
        Shows HUD pill anchored at bottom center of screen always on top without taking focus.
        """
        self.position_at_bottom_center()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()
        QTimer.singleShot(50, self.position_at_bottom_center)

    def hide_hud(self):
        """
        Hides HUD pill when idle.
        """
        self.hide()


def launch_desktop_gui():
    print("==================================================")
    print("      Launching Jarvis Desktop GUI (PySide6)      ")
    print("==================================================")

    if not INDEX_HTML_PATH.exists():
        raise FileNotFoundError(f"Dashboard HTML file not found at {INDEX_HTML_PATH}")

    app = QApplication(sys.argv)

    dashboard = DashboardWindow()
    dashboard.show()

    hud = None
    if HUD_HTML_PATH.exists():
        hud = HUDWindow()
        # Wispr Flow Mechanic: Keep HUD pill HIDDEN by default when idle!
        # It pops up at bottom-center when hold-to-talk key is pressed.
        print("[UILauncher] Wispr Flow HUD Overlay Pill initialized (Hidden when idle).")

    print(f"[UILauncher] Main Dashboard: file://{INDEX_HTML_PATH}")
    print(f"[UILauncher] Wispr Flow HUD:  file://{HUD_HTML_PATH}")

    sys.exit(app.exec())


if __name__ == "__main__":
    launch_desktop_gui()
