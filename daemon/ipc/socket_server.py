"""
Unix Domain Socket IPC Protocol Server (Sub-Task 4.1)
Provides low-latency, bidirectional inter-process communication between the Python AI daemon
and the Tauri v2 Desktop GUI client over a local Unix domain socket (/tmp/jarvis.sock).
"""

import os
import json
import socket
import select
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

DEFAULT_SOCKET_PATH = "/tmp/jarvis.sock"


class IPCServer:
    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        command_handler: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None
    ):
        """
        Initialize Unix Domain Socket IPCServer.
        
        :param socket_path: Path to Unix domain socket file (default: /tmp/jarvis.sock).
        :param command_handler: Callback function `func(action: str, params: dict) -> dict` for handling client commands.
        """
        self.socket_path = socket_path
        self.command_handler = command_handler
        
        self.server_socket: Optional[socket.socket] = None
        self.clients: List[socket.socket] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_thread: Optional[threading.Thread] = None

    def _cleanup_stale_socket(self):
        """
        Removes any stale socket file before binding.
        """
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError as e:
                print(f"[IPCServer Warning] Unable to remove stale socket {self.socket_path}: {e}", flush=True)

    def start(self):
        """
        Starts the Unix Domain Socket IPC server in a background thread.
        """
        self._cleanup_stale_socket()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(self.socket_path)
        # Restrict permissions to owner only for security
        os.chmod(self.socket_path, 0o600)
        self.server_socket.listen(10)
        self.server_socket.setblocking(False)

        self._stop_event.clear()
        self._server_thread = threading.Thread(target=self._run_server, daemon=True, name="JarvisIPCServerThread")
        self._server_thread.start()
        print(f"[IPCServer] Active and listening on {self.socket_path}", flush=True)

    def _run_server(self):
        """
        Main server loop using select to accept connections and process incoming messages.
        """
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    if not self.server_socket:
                        break
                    read_sockets = [self.server_socket] + list(self.clients)

                readable, _, _ = select.select(read_sockets, [], [], 0.5)

                for sock in readable:
                    if sock is self.server_socket:
                        # Accept new client connection
                        client_sock, _ = self.server_socket.accept()
                        client_sock.setblocking(False)
                        with self._lock:
                            self.clients.append(client_sock)
                        print(f"[IPCServer] Client connected (Total active clients: {len(self.clients)})", flush=True)
                    else:
                        # Read incoming message from existing client
                        self._handle_client_data(sock)

            except Exception as e:
                if not self._stop_event.is_set():
                    print(f"[IPCServer Error] Loop error: {e}", flush=True)

    def _handle_client_data(self, client_sock: socket.socket):
        """
        Reads line-delimited JSON RPC requests from client.
        """
        try:
            data = client_sock.recv(4096)
            if not data:
                # Client disconnected
                self._disconnect_client(client_sock)
                return

            lines = data.decode("utf-8").split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                    response = self._process_request(payload)
                    if response:
                        res_bytes = (json.dumps(response) + "\n").encode("utf-8")
                        client_sock.sendall(res_bytes)
                except json.JSONDecodeError:
                    err_res = {"status": "error", "error": "Invalid JSON format"}
                    client_sock.sendall((json.dumps(err_res) + "\n").encode("utf-8"))

        except (ConnectionResetError, BrokenPipeError, OSError):
            self._disconnect_client(client_sock)
        except Exception as e:
            print(f"[IPCServer Warning] Error handling client data: {e}", flush=True)

    def _process_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes a parsed JSON RPC request dictionary.
        """
        request_id = payload.get("id")
        action = payload.get("action") or payload.get("method")
        params = payload.get("params") or payload.get("args") or {}

        if not action:
            return {"id": request_id, "status": "error", "error": "Missing 'action' parameter"}

        # Ping health check
        if action == "ping":
            return {"id": request_id, "status": "ok", "result": "pong"}

        # Route through command handler if registered
        if self.command_handler:
            try:
                res = self.command_handler(action, params)
                return {"id": request_id, "status": "ok", "result": res}
            except Exception as e:
                return {"id": request_id, "status": "error", "error": str(e)}

        return {"id": request_id, "status": "ok", "result": f"Executed action: {action}"}

    def broadcast_event(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """
        Broadcasts an event packet (e.g. RECORDING_STARTED, STT_PREVIEW, AGENT_THINKING)
        to all connected GUI clients.
        """
        event_packet = {
            "type": "event",
            "event": event_type,
            "data": data or {}
        }
        msg_bytes = (json.dumps(event_packet) + "\n").encode("utf-8")

        with self._lock:
            disconnected = []
            for client in self.clients:
                try:
                    client.sendall(msg_bytes)
                except Exception:
                    disconnected.append(client)

            for dead in disconnected:
                self._disconnect_client(dead)

    def _disconnect_client(self, client_sock: socket.socket):
        """
        Removes and closes a client socket connection.
        """
        with self._lock:
            if client_sock in self.clients:
                self.clients.remove(client_sock)
                try:
                    client_sock.close()
                except Exception:
                    pass
                print(f"[IPCServer] Client disconnected (Remaining active clients: {len(self.clients)})", flush=True)

    def stop(self):
        """
        Stops the IPC server and closes all socket connections.
        """
        self._stop_event.set()

        with self._lock:
            for client in self.clients:
                try:
                    client.close()
                except Exception:
                    pass
            self.clients.clear()

            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass
                self.server_socket = None

        self._cleanup_stale_socket()
        print("[IPCServer] Stopped cleanly.", flush=True)
