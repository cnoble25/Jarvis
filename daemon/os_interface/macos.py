"""
macOS: AppleScript (osascript) for volume, media apps, notifications and power, plus the built-in
afplay, screencapture and pmset tools. Nothing here needs Homebrew.

Some actions need a one-time permission prompt the first time they run: controlling Spotify or
Music (Automation), locking the screen with a keystroke (Accessibility), and screenshots showing
windows rather than just the wallpaper (Screen Recording).
"""

import glob
import os
import plistlib
import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .base import AppEntry, MediaPlayer, OSInterface, OSResult, VolumeState

# Searched in this order; the first app with a given name wins. Subfolders one level down hold
# suites ("/Applications/Python 3.13/IDLE.app").
# ~/Applications comes last: it also holds Safari web apps and Steam shortcuts, which shouldn't win
# over a real app with the same name ("Messages").
APP_DIRS = ["/Applications", "/System/Applications", "/Applications/Utilities", "/System/Applications/Utilities",
            os.path.expanduser("~/Applications")]
STEAM_URL = r"steam://(?:rungameid|run)/(\d+)"
# Quits an app the way Cmd-Q does (it can ask to save), by bundle id or by name. Never launches it.
QUIT_SCRIPT = [
    "on run argv",
    "set {lookup, target} to {item 1 of argv, item 2 of argv}",
    "if lookup is \"id\" then",
    "if not (application id target is running) then return \"not_running\"",
    "tell application id target to quit",
    "else",
    "if not (application target is running) then return \"not_running\"",
    "tell application target to quit",
    "end if",
    "return \"closed\"",
    "end run",
]

# Apps with an AppleScript player API. Browsers (YouTube) have none, so they can't be targeted.
MEDIA_APPS = ("Spotify", "Music")
APPLESCRIPT_MEDIA = {"play": "play", "pause": "pause", "toggle": "playpause", "next": "next track",
                     "previous": "previous track"}
TERMINAL_APPS = ("Ghostty", "iTerm", "WezTerm", "Alacritty", "kitty", "Warp")
POWER = {
    "shutdown": "osascript -e 'tell application \"System Events\" to shut down'",
    "reboot": "osascript -e 'tell application \"System Events\" to restart'",
    "suspend": "pmset sleepnow",
    # Ctrl+Cmd+Q is the system lock shortcut (needs Accessibility); turning the display off locks
    # when "require password immediately" is on.
    "lock": "osascript -e 'tell application \"System Events\" to keystroke \"q\" using {control down, command down}'"
            " || pmset displaysleepnow",
}


class MacOS(OSInterface):
    name = "macOS"
    open_command = "open"
    claude_code_context = ("their Mac (prefer Homebrew or user-level installs; open, osascript and the built-in "
                           "command-line tools are available)")
    default_hotkey = "Alt + Space"  # Option + Space: Cmd + Space is Spotlight

    def keyboard(self, on_key, targets):
        from .keyboard_macos import MacKeyboard
        return MacKeyboard(on_key, targets)

    def unholdable_keys(self) -> Dict[str, str]:
        from .keyboard_macos import UNHOLDABLE
        return dict(UNHOLDABLE)

    def _osascript(self, *lines: str, args: Optional[List[str]] = None) -> subprocess.CompletedProcess:
        cmd = ["osascript"]
        for line in lines:
            cmd += ["-e", line]
        return self._run(cmd + list(args or []))

    # ---- Sound ------------------------------------------------------------------------------

    def get_volume(self) -> Optional[VolumeState]:
        out = self._osascript("get volume settings").stdout or ""
        level = re.search(r"output volume:\s*(\d+|missing value)", out)
        muted = re.search(r"output muted:\s*(true|false|missing value)", out)
        if not level:
            return None
        # "missing value": the output (HDMI, some USB devices) has no software volume.
        return VolumeState(level=int(level.group(1)) if level.group(1).isdigit() else None,
                           muted=bool(muted and muted.group(1) == "true"))

    def set_volume(self, level: int) -> OSResult:
        level = max(0, min(100, int(level)))
        script = f"set volume output volume {level}"
        return self._result(["osascript", "-e", script], self._osascript(script), "Couldn't set the volume.")

    def change_volume(self, delta: int) -> OSResult:
        state = self.get_volume()
        if state is None or state.level is None:
            return OSResult(False, error="This sound output doesn't have a volume Jarvis can change.")
        return self.set_volume(state.level + delta)

    def set_mute(self, muted: Optional[bool]) -> OSResult:
        if muted is None:
            state = self.get_volume()
            if state is None:
                return OSResult(False, error="Couldn't read whether sound is muted.")
            muted = not state.muted
        script = f"set volume output muted {'true' if muted else 'false'}"
        return self._result(["osascript", "-e", script], self._osascript(script), "Couldn't change mute.")

    def play_wav(self, path: str, block: bool = True) -> bool:
        # afplay goes through Core Audio, which mixes with whatever is already playing.
        if block:
            subprocess.run(["afplay", path], check=False)
        else:
            subprocess.Popen(["afplay", path])
        return True

    # ---- Media players ----------------------------------------------------------------------

    def media_players(self) -> List[MediaPlayer]:
        # "is running" never launches the app (a plain tell block would).
        proc = self._osascript(
            'set out to ""',
            "repeat with a in {" + ", ".join(f'"{app}"' for app in MEDIA_APPS) + "}",
            "if application (a as text) is running then set out to out & a & linefeed",
            "end repeat",
            "return out",
        )
        running = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip() in MEDIA_APPS]
        return [MediaPlayer(id=app, name=app.lower()) for app in running]

    def no_media_players_message(self) -> str:
        # A browser playing YouTube is invisible here, so "nothing is playing" could be false.
        return "Spotify and Music aren't open, and those are the players I can control on a Mac."

    def media_command(self, player: MediaPlayer, action: str) -> OSResult:
        verb = APPLESCRIPT_MEDIA.get(action, "playpause")
        script = f'tell application "{player.id}" to {verb}'
        return self._result(["osascript", "-e", script], self._osascript(script), f"{player.id} didn't respond.")

    # ---- Context ----------------------------------------------------------------------------

    def front_app(self) -> Optional[str]:
        try:
            import AppKit
            app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if not app or app.processIdentifier() == os.getpid():
                return None  # Jarvis itself (its dashboard) is never "that"
            return str(app.localizedName())
        except Exception:
            return None

    def running_apps(self) -> List[str]:
        try:
            import AppKit
            apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            return sorted({str(a.localizedName()) for a in apps
                           if a.activationPolicy() == AppKit.NSApplicationActivationPolicyRegular and a.localizedName()})
        except Exception:
            return []

    def now_playing(self) -> Optional[Dict[str, str]]:
        # Only players with an AppleScript API (browsers have none); "is running" never launches them.
        for app in MEDIA_APPS:
            proc = self._osascript(
                f'if application "{app}" is running then',
                f'tell application "{app}" to return (player state as text) & "|" & (name of current track) & "|" & (artist of current track)',
                "end if")
            parts = (proc.stdout or "").strip().split("|")
            if proc.returncode == 0 and len(parts) == 3 and parts[0]:
                return {"player": app, "state": parts[0], "title": parts[1], "artist": parts[2]}
        return None

    def clipboard(self) -> Optional[str]:
        proc = self._run(["pbpaste"], timeout=3)
        return proc.stdout if proc.returncode == 0 else None

    # ---- Desktop ----------------------------------------------------------------------------

    def screenshot(self, path: str) -> OSResult:
        proc = self._run(["screencapture", "-x", path], timeout=20)  # -x: no shutter sound
        if self._saved(path):
            return OSResult(True, detail=path)
        return OSResult(False, error=(proc.stderr or "").strip()[:160] or
                        "screencapture didn't save a file (check Screen Recording permission).")

    def open_terminal(self) -> OSResult:
        app = next((a for a in TERMINAL_APPS
                    if any((root / f"{a}.app").exists() for root in (Path("/Applications"), Path.home() / "Applications"))),
                   "Terminal")
        proc = self._run(["open", "-a", app])
        if proc.returncode != 0:
            return OSResult(False, error=(proc.stderr or "").strip() or f"Couldn't open {app}.")
        return OSResult(True, detail=f"Started {app}")

    def notify(self, title: str, body: str) -> bool:
        # Text goes in as arguments, never into the script, so quotes in it can't break out.
        proc = self._osascript("on run argv",
                               "display notification (item 2 of argv) with title (item 1 of argv)",
                               "end run", args=[title, body])
        return proc.returncode == 0

    def power_command(self, action: str) -> Optional[str]:
        return POWER.get(action)

    def system_status_command(self) -> Optional[str]:
        return "uptime && top -l 1 -n 0 | grep -E '^(CPU usage|PhysMem|Load Avg)'"

    # ---- Apps (.app bundles) ----------------------------------------------------------------

    def installed_apps(self) -> List[AppEntry]:
        apps, seen = [], set()
        for root in APP_DIRS:
            for bundle in sorted(glob.glob(os.path.join(root, "*.app")) + glob.glob(os.path.join(root, "*", "*.app"))):
                entry = self._read_bundle(bundle)
                if entry and entry.path not in seen:
                    seen.add(entry.path)
                    apps.append(entry)
        return apps

    @staticmethod
    def _read_plist(path: str) -> dict:
        try:
            with open(path, "rb") as f:
                data = f.read()
            # Steam's game shortcuts indent the file and pad it with NUL bytes, which plistlib rejects.
            return plistlib.loads(data.strip(b"\0 \t\r\n"))
        except Exception:
            return {}

    def _read_bundle(self, bundle: str) -> Optional[AppEntry]:
        info = self._read_plist(os.path.join(bundle, "Contents", "Info.plist"))
        if info.get("LSBackgroundOnly") in (True, "1", "YES"):
            return None  # helpers with no window (URL handlers, agents)
        name = Path(bundle).stem  # what Finder and Launchpad show
        executable = str(info.get("CFBundleExecutable") or "")
        exec_cmd = os.path.join(bundle, "Contents", "MacOS", executable) if executable else ""
        binary = executable
        if executable.endswith(".sh"):
            # A script shortcut (Steam games: "open steam://run/123"): keep the URL for closing.
            try:
                game = re.search(STEAM_URL, Path(exec_cmd).read_text(errors="ignore"))
            except OSError:
                game = None
            exec_cmd, binary = (game.group(0) if game else exec_cmd), ""
        keywords = sorted({str(info.get(k)).lower() for k in ("CFBundleDisplayName", "CFBundleName")
                           if info.get(k) and str(info.get(k)).lower() != name.lower()})
        return AppEntry(bundle, name, exec_cmd, keywords, str(info.get("CFBundleIdentifier") or ""), binary=binary)

    def launch_command(self, app: AppEntry) -> str:
        # open -a takes a bundle path or an app name, and returns as soon as the app starts.
        return f"open -a {shlex.quote(app.path or app.name)}"

    def close_plan(self, app: AppEntry) -> Dict[str, str]:
        game = re.search(STEAM_URL, app.exec_cmd or "")
        if game:
            return {"kind": "steam_game", "appid": game.group(1)}
        if app.app_id:
            return {"kind": "mac_app", "by": "id", "target": app.app_id}
        return {"kind": "mac_app", "by": "name", "target": app.name}

    def close_app(self, plan: Dict[str, str]) -> OSResult:
        if plan.get("kind") == "steam_game":
            # Games run as their own processes with nothing tying them to the shortcut on macOS.
            return OSResult(False, error="Closing Steam games isn't supported on macOS yet; quit it from the game.")
        if plan.get("kind") != "mac_app":
            return self.unsupported("Closing this kind of app")
        proc = self._osascript(*QUIT_SCRIPT, args=[plan["by"], plan["target"]])
        state = (proc.stdout or "").strip()
        if proc.returncode != 0 or state not in ("closed", "not_running"):
            return OSResult(False, error=(proc.stderr or "").strip() or "The app didn't quit.")
        return OSResult(True, detail=f"quit {plan['target']}", state=state)

    # ---- Windows (Qt) -----------------------------------------------------------------------

    def show_in_dock(self, visible: bool) -> None:
        """
        Regular app (Dock icon, Cmd-Tab, menu bar) while the dashboard is around; an accessory app
        otherwise, like menu-bar apps. A regular app is activated the first time it shows any
        window, so starting in the background as one made the first pill take focus from the app
        you were typing in.
        """
        try:
            import AppKit
            policy = (AppKit.NSApplicationActivationPolicyRegular if visible
                      else AppKit.NSApplicationActivationPolicyAccessory)
            app = AppKit.NSApplication.sharedApplication()
            if app.activationPolicy() != policy:
                app.setActivationPolicy_(policy)
        except Exception as err:
            print(f"[MacOS] Couldn't change Dock presence: {err}", flush=True)

    def bring_app_forward(self) -> None:
        # Qt's raise() no longer activates the app (QT_MAC_SET_RAISE_PROCESS=0, so overlays don't steal
        # focus), so opening the dashboard on purpose activates it here.
        try:
            import AppKit
            AppKit.NSRunningApplication.currentApplication().activateWithOptions_(
                AppKit.NSApplicationActivateIgnoringOtherApps)
        except Exception as err:
            print(f"[MacOS] Couldn't bring Jarvis forward: {err}", flush=True)

    def prepare_overlay_window(self, win_id: int) -> None:
        """
        Qt makes overlays NSPanels that hide whenever Jarvis isn't the active app, so minimizing the
        dashboard (which activates another app) took the pill with it. Set the panel up directly:
          never hide on deactivation, or with Cmd-H (Hide Jarvis)
          status-bar level: above normal and floating windows
          on every Space and over full-screen apps, and left out of Cmd-` window cycling
        A full-screen app sits on its own Space, and macOS only lets another app's window in there if
        it is a non-activating panel (Qt's panels activate), so the pill follows you into it too.
        """
        try:
            import AppKit
            import objc
            window = objc.objc_object(c_void_p=win_id).window()  # winId() is the NSView
            if window is None:
                return
            if window.isKindOfClass_(AppKit.NSPanel):
                window.setStyleMask_(window.styleMask() | AppKit.NSWindowStyleMaskNonactivatingPanel)
            window.setHidesOnDeactivate_(False)
            window.setCanHide_(False)
            window.setLevel_(AppKit.NSStatusWindowLevel)
            window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                          | AppKit.NSWindowCollectionBehaviorStationary
                                          | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                                          | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        except Exception as err:
            print(f"[MacOS] Couldn't set up overlay window: {err}", flush=True)

    def qt_environment(self, background: bool = False) -> Dict[str, str]:
        # Qt's raise() also activates the whole app on macOS, which pulled the dashboard back in
        # front of whatever the user switched to. Overlays stay on top by window level instead.
        env = {"QT_MAC_SET_RAISE_PROCESS": "0"}
        if background:
            # Left to Qt, the process becomes a regular app as soon as Qt starts and takes focus. In the
            # background Jarvis stays an accessory app (show_in_dock) until the dashboard is opened.
            # A normal start keeps Qt's conversion: it's what lets the dashboard come to the front.
            env["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] = "1"
        return env
