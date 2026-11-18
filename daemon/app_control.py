"""
Talk to a running Jarvis over its IPC socket: is it up, bring the dashboard forward, quit.

Used by `main.py` (so a second launch raises the running dashboard instead of starting a second
Jarvis that would steal the socket and the hotkey) and by `bin/jarvis`:

    python -m daemon.app_control running        # exit 0 if Jarvis answers
    python -m daemon.app_control show_dashboard
    python -m daemon.app_control quit
"""

import json
import socket
import sys
from typing import Any, Dict, Optional

from daemon.ipc.socket_server import DEFAULT_SOCKET_PATH


def request(action: str, params: Optional[Dict[str, Any]] = None, path: str = DEFAULT_SOCKET_PATH,
            timeout: float = 2.0) -> Dict[str, Any]:
    """Send one request and return its response (skipping any broadcast events in between)."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall((json.dumps({"action": action, "params": params or {}}) + "\n").encode("utf-8"))
        buf = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Jarvis closed the connection without answering")
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if not line.strip():
                    continue
                message = json.loads(line)
                if message.get("type") != "event":
                    return message


def is_running(path: str = DEFAULT_SOCKET_PATH) -> bool:
    try:
        return request("ping", path=path, timeout=1.0).get("status") == "ok"
    except (OSError, ValueError, ConnectionError):
        return False


def main(argv) -> int:
    action = argv[1] if len(argv) > 1 else "running"
    if action == "running":
        return 0 if is_running() else 1
    if not is_running():
        print("Jarvis isn't running.")
        return 1
    print(json.dumps(request(action)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
