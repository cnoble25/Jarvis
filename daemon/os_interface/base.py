"""
The OS interface: everything Jarvis does to the computer that differs between operating systems.

Callers decide *what* to do (which volume, which player, what to say back); an OSInterface only
knows *how* on its own OS. Each OS gets one subclass (linux.py, macos.py, later windows.py).

A method an OS hasn't implemented yet returns an honest failure instead of pretending it worked,
so a new OS can be filled in one area at a time.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

MEDIA_ACTIONS = ("play", "pause", "toggle", "next", "previous")
POWER_ACTIONS = ("shutdown", "reboot", "suspend", "lock")


@dataclass
class OSResult:
    ok: bool
    detail: str = ""  # what ran, or what came back (stdout / a saved path)
    error: str = ""   # why it failed, in words a user can act on
    state: str = ""   # finer outcome where callers word it differently (close_app: closed, closing, not_running, denied)


class AppEntry:
    """
    One installed app, however the OS lists it: a .desktop file on Linux, an .app bundle on macOS.
      path      where it was found (the .desktop file, the .app folder)
      name      what the user sees ("Visual Studio Code")
      exec_cmd  how the OS starts it (a desktop Exec line, a bundle's executable)
      keywords  extra words it answers to ("camera", "webcam")
      app_id    the OS's id for it (desktop id, bundle id)
      binary    its process name, for matching "code" and for closing
    """

    def __init__(self, path: str, name: str, exec_cmd: str, keywords: List[str], app_id: str,
                 binary: Optional[str] = None):
        self.path = path
        self.name = name
        self.exec_cmd = exec_cmd
        self.keywords = keywords
        self.app_id = app_id
        self.binary = binary if binary is not None else (Path(exec_cmd.split()[0]).name if exec_cmd.strip() else "")

    def to_dict(self) -> Dict[str, object]:
        return {"app_id": self.app_id, "name": self.name, "exec": self.exec_cmd, "keywords": self.keywords}


@dataclass
class VolumeState:
    level: Optional[int]  # 0-100, None when the output device has no volume control
    muted: bool = False


@dataclass
class MediaPlayer:
    id: str    # what the OS addresses it by (an MPRIS bus name, an app name)
    name: str  # what to match spoken words against ("spotify", "firefox")
    extra: dict = field(default_factory=dict)


class OSInterface:
    name = "Unknown OS"
    # Opens a URL or file with the default app (named in prompts and error hints).
    open_command = ""
    # How Claude Code should treat this computer (its task briefing, claude_code_agent.py).
    claude_code_context = "the user's computer"

    def unsupported(self, what: str) -> OSResult:
        return OSResult(False, error=f"{what} isn't supported on {self.name} yet.")

    # ---- Sound ------------------------------------------------------------------------------

    def get_volume(self) -> Optional[VolumeState]:
        """The default output's volume, or None if it can't be read."""
        return None

    def set_volume(self, level: int) -> OSResult:
        """Set the default output to level percent (0-100)."""
        return self.unsupported("Changing the volume")

    def change_volume(self, delta: int) -> OSResult:
        """Raise (delta > 0) or lower the volume by delta percent, never above 100."""
        return self.unsupported("Changing the volume")

    def set_mute(self, muted: Optional[bool]) -> OSResult:
        """Mute (True), unmute (False) or toggle (None) the default output."""
        return self.unsupported("Muting")

    def play_wav(self, path: str, block: bool = True) -> bool:
        """Play a WAV file through the system mixer (alongside music). False if no player is available."""
        return False

    def temp_audio_dir(self) -> str:
        """Where short-lived speech WAVs are written (a RAM disk where there is one)."""
        import tempfile
        return tempfile.gettempdir()

    # ---- Media players ----------------------------------------------------------------------

    def media_players(self) -> List[MediaPlayer]:
        """Players that can take play/pause commands right now."""
        return []

    def media_command(self, player: MediaPlayer, action: str) -> OSResult:
        """Send one of MEDIA_ACTIONS to a player from media_players()."""
        return self.unsupported("Media control")

    def no_media_players_message(self) -> str:
        """Spoken when media_players() finds none (worded for what this OS can actually see)."""
        return "Nothing is playing right now."

    # ---- Context (read-only: what learned rules' scripts may look up) ---------------------------

    def front_app(self) -> Optional[str]:
        """The name of the app in front (the one being used), or None if it can't be told or is Jarvis."""
        return None

    def running_apps(self) -> List[str]:
        """Names of the installed apps that are running (by process name), best effort."""
        try:
            import psutil
            names = {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
        except Exception:
            return []
        return sorted({a.name for a in self.installed_apps() if a.binary and a.binary.lower() in names})

    def now_playing(self) -> Optional[Dict[str, str]]:
        """{"player", "state" (playing/paused), "title", "artist"} for the media playing, or None."""
        return None

    def clipboard(self) -> Optional[str]:
        """The clipboard's text, or None."""
        return None

    # ---- Apps -------------------------------------------------------------------------------

    def installed_apps(self) -> List[AppEntry]:
        """Every app the user could ask to open."""
        return []

    def launch_command(self, app: AppEntry) -> str:
        """A shell command that starts app in the background (empty if this OS can't)."""
        return ""

    def close_plan(self, app: AppEntry) -> Dict[str, str]:
        """How close_app should target only this app (its own processes, never a substring match)."""
        return {}

    def close_app(self, plan: Dict[str, str]) -> OSResult:
        """Close the app a close_plan describes. state: closed | closing | not_running | denied."""
        return self.unsupported("Closing apps")

    # ---- Talk shortcut ----------------------------------------------------------------------

    # Used when the user hasn't picked one. Each OS avoids its own system shortcuts (Cmd+Space is Spotlight).
    default_hotkey = "Super + Space"

    def keyboard(self, on_key, targets):
        """
        A system-wide key reader with start() -> OSResult, stop() and shortcut_released().
        on_key(name, is_press) gets every key it knows; targets() returns the shortcut's key set.
        None when this OS has no reader yet.
        """
        return None

    def unholdable_keys(self) -> Dict[str, str]:
        """Keys that can't be held to talk on this OS, with why (shown to the user)."""
        return {}

    # ---- Windows (Qt) -----------------------------------------------------------------------

    def qt_environment(self, background: bool = False) -> Dict[str, str]:
        """
        Environment variables Qt needs on this OS, set before the QApplication starts.
        background: Jarvis starts without its dashboard (at login).
        """
        return {}

    # Re-raise the always-on-top overlays every few seconds (a KWin workaround: other override-redirect
    # popups can land above them). Off where re-raising would also bring the whole app forward.
    overlays_need_reraise = False

    def show_in_dock(self, visible: bool) -> None:
        """
        Whether Jarvis appears as a normal app (Dock, app switcher) or runs in the background. Called
        with True while the dashboard is open or minimized, False while only the overlays are around.
        """

    def bring_app_forward(self) -> None:
        """Make Jarvis the active app (the user asked for the dashboard). Qt's activateWindow() does it on Linux."""

    def prepare_overlay_window(self, win_id: int) -> None:
        """
        Make a shown overlay (the pill, the task panel) behave as one on this OS: visible over every
        app, whether or not the dashboard is open, minimized or hidden. win_id is Qt's winId().
        """

    def overlay_insets(self, screen: tuple, available: tuple) -> Dict[str, int]:
        """
        Room the OS's own bars take on each screen edge (menu bar, Dock, panels), so overlays sit
        clear of them. screen and available are (x, y, width, height); Qt's available geometry is
        right on most systems.
        """
        sx, sy, sw, sh = screen
        ax, ay, aw, ah = available
        return {"top": max(0, ay - sy), "left": max(0, ax - sx),
                "bottom": max(0, (sy + sh) - (ay + ah)), "right": max(0, (sx + sw) - (ax + aw))}

    # ---- Desktop ----------------------------------------------------------------------------

    def screenshot(self, path: str) -> OSResult:
        """Capture the whole screen to path (PNG). ok only if the file was written."""
        return self.unsupported("Taking screenshots")

    def open_terminal(self) -> OSResult:
        return self.unsupported("Opening a terminal")

    def notify(self, title: str, body: str) -> bool:
        """Show a desktop notification. False if the OS has no way to."""
        return False

    def power_command(self, action: str) -> Optional[str]:
        """The shell command for one of POWER_ACTIONS, or None if this OS can't do it."""
        return None

    def system_status_command(self) -> Optional[str]:
        """A read-only shell command that prints uptime, memory and CPU load."""
        return None

    # ---- Helpers for subclasses -------------------------------------------------------------

    @staticmethod
    def _run(cmd: List[str], timeout: float = 10) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]} is not installed.")
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, "", f"{cmd[0]} timed out.")

    @classmethod
    def _result(cls, cmd: List[str], proc: subprocess.CompletedProcess, failed: str) -> OSResult:
        if proc.returncode == 0:
            return OSResult(True, detail=" ".join(cmd))
        return OSResult(False, detail=" ".join(cmd), error=(proc.stderr or "").strip() or failed)

    @staticmethod
    def _spawn(cmd: List[str]):
        """Start a program detached from Jarvis (it keeps running if Jarvis quits)."""
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)

    @staticmethod
    def _saved(path: str) -> bool:
        return os.path.exists(path) and os.path.getsize(path) > 0
