"""
OS interface: one place for everything that differs between operating systems.

    from daemon.os_interface import get_os
    get_os().set_volume(40)

get_os() picks the implementation for the running OS once. Supported: Linux, macOS. On anything
else every action fails with a clear "not supported on <OS> yet" instead of running Linux commands.
"""

import sys
import threading
from typing import Optional

from .audio import play_samples
from .base import MEDIA_ACTIONS, POWER_ACTIONS, MediaPlayer, OSInterface, OSResult, VolumeState

_current: Optional[OSInterface] = None
_lock = threading.Lock()


def os_for_platform(platform: str) -> OSInterface:
    if platform.startswith("linux"):
        from .linux import LinuxOS
        return LinuxOS()
    if platform == "darwin":
        from .macos import MacOS
        return MacOS()
    unsupported = OSInterface()
    unsupported.name = {"win32": "Windows", "cygwin": "Windows"}.get(platform, platform)
    return unsupported


def get_os() -> OSInterface:
    global _current
    with _lock:
        if _current is None:
            _current = os_for_platform(sys.platform)
        return _current


def set_os(os_interface: Optional[OSInterface]):
    """Replace the OS implementation (tests); None goes back to detecting it."""
    global _current
    with _lock:
        _current = os_interface


__all__ = ["get_os", "set_os", "os_for_platform", "play_samples", "OSInterface", "OSResult", "VolumeState",
           "MediaPlayer", "MEDIA_ACTIONS", "POWER_ACTIONS"]
