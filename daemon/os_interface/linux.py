"""
Linux: PipeWire (wpctl, pw-play) for sound, MPRIS over D-Bus for media players, and the desktop's
own tools for screenshots, terminals and notifications.
"""

import glob
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .base import AppEntry, MediaPlayer, OSInterface, OSResult, VolumeState

DESKTOP_DIRS = [
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications",
]

SINK = "@DEFAULT_AUDIO_SINK@"
MPRIS_METHODS = {"play": "Play", "pause": "Pause", "toggle": "PlayPause", "next": "Next", "previous": "Previous"}
TERMINALS = ("konsole", "ptyxis", "gnome-terminal", "kitty", "alacritty", "wezterm", "foot", "xfce4-terminal", "xterm")
POWER = {
    "shutdown": "systemctl poweroff || loginctl poweroff || shutdown -h now",
    "reboot": "systemctl reboot || loginctl reboot || shutdown -r now",
    "suspend": "systemctl suspend || loginctl suspend",
    "lock": "loginctl lock-session || kscreenlocker_greet || xdg-screensaver lock",
}


class LinuxOS(OSInterface):
    name = "Linux"
    open_command = "xdg-open"
    overlays_need_reraise = True

    def keyboard(self, on_key, targets):
        from .keyboard_linux import LinuxKeyboard
        return LinuxKeyboard(on_key)

    def qt_environment(self, background: bool = False) -> Dict[str, str]:
        # X11/XWayland (xcb): Wayland compositors forbid absolute window positions, which the pill
        # and the task panel need.
        return {"QT_QPA_PLATFORM": "xcb"}

    def overlay_insets(self, screen: tuple, available: tuple) -> Dict[str, int]:
        # X11 clients on Plasma Wayland are told the work area is the whole screen: read the panel
        # sizes from Plasma's config instead.
        from daemon.overlay_layout import plasma_panel_insets
        return plasma_panel_insets(0)

    # ---- Sound ------------------------------------------------------------------------------

    def get_volume(self) -> Optional[VolumeState]:
        out = self._run(["wpctl", "get-volume", SINK]).stdout
        m = re.search(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?", out or "")
        if not m:
            return None
        return VolumeState(level=round(float(m.group(1)) * 100), muted=bool(m.group(2)))

    def set_volume(self, level: int) -> OSResult:
        cmd = ["wpctl", "set-volume", SINK, f"{max(0, min(100, int(level)))}%"]
        return self._result(cmd, self._run(cmd), "wpctl failed")

    def change_volume(self, delta: int) -> OSResult:
        if delta >= 0:
            cmd = ["wpctl", "set-volume", "-l", "1.0", SINK, f"{delta}%+"]  # -l: never past 100%
        else:
            cmd = ["wpctl", "set-volume", SINK, f"{-delta}%-"]
        return self._result(cmd, self._run(cmd), "wpctl failed")

    def set_mute(self, muted: Optional[bool]) -> OSResult:
        cmd = ["wpctl", "set-mute", SINK, "toggle" if muted is None else ("1" if muted else "0")]
        return self._result(cmd, self._run(cmd), "wpctl failed")

    def play_wav(self, path: str, block: bool = True) -> bool:
        # pw-play / paplay mix with music already playing (ALSA directly would underrun).
        player = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
        if not player:
            return False
        if block:
            subprocess.run([player, path], check=False)
        else:
            subprocess.Popen([player, path])
        return True

    def temp_audio_dir(self) -> str:
        return "/dev/shm" if os.path.exists("/dev/shm") else "/tmp"

    # ---- Media players (MPRIS) ----------------------------------------------------------------

    def media_players(self) -> List[MediaPlayer]:
        try:
            out = subprocess.run(["busctl", "--user", "list"], capture_output=True, text=True).stdout
        except Exception:
            return []
        players = []
        for line in (out or "").splitlines():
            parts = line.split()
            if parts and parts[0].startswith("org.mpris.MediaPlayer2."):
                players.append(MediaPlayer(id=parts[0], name=parts[0][len("org.mpris.MediaPlayer2."):].lower()))
        return players

    def media_command(self, player: MediaPlayer, action: str) -> OSResult:
        method = MPRIS_METHODS.get(action, "PlayPause")
        cmd = ["busctl", "--user", "call", player.id, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method]
        return self._result(cmd, self._run(cmd), f"The player didn't respond to {method}.")

    # ---- Desktop ----------------------------------------------------------------------------

    def screenshot(self, path: str) -> OSResult:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        wayland = os.environ.get("XDG_SESSION_TYPE", "") == "wayland" or "WAYLAND_DISPLAY" in os.environ
        candidates = []
        if shutil.which("spectacle") and ("kde" in desktop or not wayland):
            candidates.append(["spectacle", "-b", "-n", "-f", "-o", path])
        if shutil.which("gnome-screenshot") and "gnome" in desktop:
            candidates.append(["gnome-screenshot", "-f", path])
        if shutil.which("grim") and wayland and not any(d in desktop for d in ("kde", "gnome")):
            candidates.append(["grim", path])
        if shutil.which("import") and not wayland:
            candidates.append(["import", "-window", "root", path])
        if not candidates:
            return OSResult(False, error="No screenshot tool for this desktop.")
        errors = []
        for cmd in candidates:
            proc = self._run(cmd, timeout=20)
            if self._saved(path):
                return OSResult(True, detail=path)
            errors.append(f"{cmd[0]}: {(proc.stderr or '').strip()[:120] or 'no file written'}")
        return OSResult(False, error="; ".join(errors))

    def open_terminal(self) -> OSResult:
        terminal = next((t for t in TERMINALS if shutil.which(t)), None)
        if not terminal:
            return OSResult(False, error="No terminal app found.")
        self._spawn([terminal])
        return OSResult(True, detail=f"Started {terminal}")

    def notify(self, title: str, body: str) -> bool:
        notify = shutil.which("notify-send")
        if not notify:
            return False
        subprocess.Popen([notify, "-a", "Jarvis", "-i", "audio-input-microphone", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def power_command(self, action: str) -> Optional[str]:
        return POWER.get(action)

    def system_status_command(self) -> Optional[str]:
        return "free -h && uptime"

    # ---- Apps (.desktop entries, Flatpak, Steam) ----------------------------------------------

    def installed_apps(self) -> List[AppEntry]:
        apps = []
        for d in DESKTOP_DIRS:
            if os.path.exists(d):
                for filepath in glob.glob(os.path.join(d, "*.desktop")):
                    entry = self._parse_desktop_file(filepath)
                    if entry and entry.name:
                        apps.append(entry)
        return apps

    @staticmethod
    def _parse_desktop_file(filepath: str) -> Optional[AppEntry]:
        """Name, Exec, Keywords from the [Desktop Entry] section; None for hidden entries."""
        name, exec_cmd, keywords, no_display = "", "", [], False
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                in_main_section = False
                for line in f:
                    line = line.strip()
                    if line == "[Desktop Entry]":
                        in_main_section = True
                        continue
                    elif line.startswith("[") and line.endswith("]"):
                        in_main_section = False
                    if not in_main_section:
                        continue
                    if line.startswith("NoDisplay=true") or line.startswith("Hidden=true"):
                        no_display = True
                    elif line.startswith("Name=") and not name:
                        name = line.split("=", 1)[1].strip()
                    elif line.startswith("Exec=") and not exec_cmd:
                        exec_cmd = re.sub(r"%[a-zA-Z]", "", line.split("=", 1)[1].strip()).strip()  # drop %u, %F...
                    elif line.startswith("Keywords="):
                        keywords = [k.strip().lower() for k in line.split("=", 1)[1].split(";") if k.strip()]
        except Exception:
            return None
        if no_display or not name or not exec_cmd:
            return None
        return AppEntry(filepath, name, exec_cmd, keywords, Path(filepath).stem)

    def launch_command(self, app: AppEntry) -> str:
        clean_exec = app.exec_cmd.strip()
        if app.app_id and clean_exec:
            return f"nohup bash -c \"gtk-launch '{app.app_id}' 2>/dev/null || {clean_exec}\" >/dev/null 2>&1 &"
        elif app.app_id:
            return f"nohup gtk-launch '{app.app_id}' >/dev/null 2>&1 &"
        return f"nohup {clean_exec} >/dev/null 2>&1 &"

    def close_plan(self, app: AppEntry) -> Dict[str, str]:
        """
          {"kind": "flatpak", "id": "com.spotify.Client"}   flatpak kill, by app id
          {"kind": "steam"}                                  Steam's own shutdown
          {"kind": "steam_game", "appid": "3017860"}         processes Steam tagged with the game
          {"kind": "process", "name": "konsole"}             exact process name, never a substring
        """
        exec_cmd = app.exec_cmd or ""
        game = re.search(r"steam://rungameid/(\d+)", exec_cmd)
        if game:
            return {"kind": "steam_game", "appid": game.group(1)}
        flatpak_id = ""
        m = re.search(r"\bflatpak\s+run\s+(.*)", exec_cmd)
        if m:
            flatpak_id = next((t for t in m.group(1).split() if not t.startswith("-") and "." in t), "")
        elif "/flatpak/exports/" in app.path or re.fullmatch(r"[A-Za-z][\w-]*(\.[\w-]+){2,}", app.app_id):
            flatpak_id = app.app_id
        binary = app.binary
        if app.app_id.lower() == "steam" or binary in ("steam", "bazzite-steam"):
            return {"kind": "steam"}
        if flatpak_id:
            # Native fallback for wrappers that only look like Flatpak ids (checked against running apps).
            # A real Flatpak launch has no native process to fall back to; a native app whose desktop id
            # merely looks like one (org.kde.konsole) falls back to its exact binary name.
            return {"kind": "flatpak", "id": flatpak_id, "name": "" if binary == "flatpak" else binary}
        return {"kind": "process", "name": binary}

    def close_app(self, plan: Dict[str, str]) -> OSResult:
        not_running = OSResult(True, detail="Not running.", state="not_running")
        kind = plan.get("kind")
        if kind == "flatpak":
            running = subprocess.run(["flatpak", "ps", "--columns=application"], capture_output=True, text=True).stdout.split()
            if plan["id"] in running:
                proc = subprocess.run(["flatpak", "kill", plan["id"]], capture_output=True, text=True)
                ok = proc.returncode == 0
                return OSResult(ok, detail=f"flatpak kill {plan['id']}", error="" if ok else proc.stderr.strip() or "flatpak kill failed",
                                state="closed" if ok else "")
            kind, plan = "process", {"name": plan.get("name", "")}  # a native app with a Flatpak-style id
        if kind == "steam":
            if not self._pids_by_name("steam"):
                return not_running
            self._spawn(["steam", "-shutdown"])
            return OSResult(True, detail="steam -shutdown", state="closing")
        if kind == "steam_game":
            pids = [p for p in self._pids_for_steam_game(plan["appid"]) if p not in self._own_pids()]
        else:
            pids = [p for p in self._pids_by_name(plan.get("name", "")) if p not in self._own_pids()]
        if not pids:
            return not_running
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                return OSResult(False, error=f"Permission denied for PID {pid}.", state="denied")
        return OSResult(True, detail=f"Sent SIGTERM to {len(pids)} process(es).", state="closed")

    @staticmethod
    def _own_pids() -> set:
        """Jarvis itself and its parent shell: never killed by a close request."""
        return {os.getpid(), os.getppid()}

    @staticmethod
    def _pids_by_name(name: str) -> list:
        if not name:
            return []
        out = subprocess.run(["pgrep", "-x", name[:15]], capture_output=True, text=True).stdout
        return [int(p) for p in out.split() if p.isdigit()]

    @staticmethod
    def _pids_for_steam_game(appid: str) -> list:
        pids = []
        for env_path in Path("/proc").glob("[0-9]*/environ"):
            try:
                env = env_path.read_bytes().split(b"\0")
            except OSError:
                continue
            if f"SteamGameId={appid}".encode() in env or f"SteamAppId={appid}".encode() in env:
                pids.append(int(env_path.parent.name))
        return pids
