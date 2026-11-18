"""
The control client a second launch uses to find the running Jarvis (bin/jarvis, main.py --quit).
Runs against a real IPCServer on a temporary socket; nothing touches the running Jarvis.
"""

import time

from daemon import app_control
from daemon.ipc.socket_server import IPCServer


def start_server(path, calls):
    def handler(action, params):
        calls.append(action)
        return {"success": True}

    server = IPCServer(socket_path=str(path), command_handler=handler)
    server.start()
    for _ in range(50):
        if path.exists():
            break
        time.sleep(0.02)
    return server


def test_not_running_without_a_socket(tmp_path):
    assert app_control.is_running(str(tmp_path / "none.sock")) is False


def test_ping_and_actions_reach_the_running_jarvis(tmp_path):
    path = tmp_path / "jarvis.sock"
    calls = []
    server = start_server(path, calls)
    try:
        assert app_control.is_running(str(path)) is True
        reply = app_control.request("show_dashboard", path=str(path))
        assert reply["status"] == "ok" and reply["result"] == {"success": True}
        assert calls == ["show_dashboard"]  # ping is answered by the server itself
    finally:
        server.stop()


def test_broadcast_events_are_skipped_while_waiting_for_the_answer(tmp_path):
    path = tmp_path / "jarvis.sock"
    server = None

    def handler(action, params):
        server.broadcast_event("RECORDING_STARTED")  # arrives before the reply
        return {"success": True}

    server = IPCServer(socket_path=str(path), command_handler=handler)
    server.start()
    try:
        for _ in range(50):
            if path.exists():
                break
            time.sleep(0.02)
        assert app_control.request("quit", path=str(path))["result"] == {"success": True}
    finally:
        server.stop()
