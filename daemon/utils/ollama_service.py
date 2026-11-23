"""
Start the local Ollama server on demand.

When the user picks an Ollama model, Jarvis makes sure `ollama serve` is running instead of
failing with "Ollama isn't running". The server is started detached and left running: it is
shared with anything else on the machine that uses Ollama.
"""

import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

DEFAULT_URL = "http://localhost:11434"
# Desktop launches may not have Homebrew on PATH, so check its usual locations too.
_FALLBACK_BINARIES = [
    "/home/linuxbrew/.linuxbrew/bin/ollama",
    str(Path.home() / ".linuxbrew/bin/ollama"),
    "/opt/homebrew/bin/ollama",  # Homebrew on Apple Silicon Macs
    "/Applications/Ollama.app/Contents/Resources/ollama",  # the Ollama Mac app
    "/usr/local/bin/ollama",
    "/usr/bin/ollama",
]
LOG_PATH = Path.home() / ".local" / "share" / "jarvis" / "ollama.log"

_lock = threading.Lock()
_starting = False


def is_starting() -> bool:
    return _starting


def is_running(base_url: str = DEFAULT_URL, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


# Ollama's official Linux build (bundles the CUDA libraries), unpacked in user space. Preferred over a
# package-manager build, which may be CPU-only (Homebrew's Linux bottle ships no GPU libraries).
OFFICIAL_BINARY = str(Path.home() / ".local/opt/ollama/bin/ollama")


def find_binary() -> Optional[str]:
    if os.access(OFFICIAL_BINARY, os.X_OK):
        return OFFICIAL_BINARY
    found = shutil.which("ollama")
    if found:
        return found
    return next((p for p in _FALLBACK_BINARIES if os.access(p, os.X_OK)), None)


def ensure_running(base_url: str = DEFAULT_URL, wait_seconds: float = 20.0) -> Dict[str, object]:
    """Start `ollama serve` if it isn't answering. Blocks until it answers or wait_seconds pass."""
    global _starting
    if is_running(base_url):
        return {"ok": True, "started": False, "message": ""}
    with _lock:
        if is_running(base_url):
            return {"ok": True, "started": False, "message": ""}
        binary = find_binary()
        if not binary:
            return {"ok": False, "started": False, "message": "Ollama isn't installed. Install it, or pick a cloud model."}
        _starting = True
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            log = open(LOG_PATH, "ab")
            env = dict(os.environ)
            host = base_url.split("://", 1)[-1].rstrip("/")
            if host and not host.startswith(("localhost:11434", "127.0.0.1:11434")):
                env["OLLAMA_HOST"] = host
            print(f"[Ollama] Not running; starting '{binary} serve' (log: {LOG_PATH})...", flush=True)
            subprocess.Popen(
                [binary, "serve"], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=env, start_new_session=True,
            )
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                if is_running(base_url):
                    print("[Ollama] Server is up.", flush=True)
                    return {"ok": True, "started": True, "message": ""}
                time.sleep(0.25)
            return {"ok": False, "started": True, "message": f"Ollama didn't start within {int(wait_seconds)}s. See {LOG_PATH}."}
        except Exception as err:
            return {"ok": False, "started": False, "message": f"Couldn't start Ollama: {err}"}
        finally:
            _starting = False


def warm_up(base_url: str, model: str, keep_alive: str = "30m"):
    """
    Load a model into GPU memory ahead of the first request. The first request after Ollama starts
    otherwise pays for loading the weights and preparing GPU kernels (about a minute on first run).
    """
    import json as _json
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/generate",
            data=_json.dumps({"model": model, "keep_alive": keep_alive}).encode(),
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
        print(f"[Ollama] Preloaded '{model}' in {time.monotonic() - started:.1f}s.", flush=True)
    except Exception as err:
        print(f"[Ollama] Couldn't preload '{model}': {err}", flush=True)


def ensure_running_async(base_url: str = DEFAULT_URL, on_done: Optional[Callable[[Dict[str, object]], None]] = None):
    """ensure_running on a background thread, so the dashboard never freezes while Ollama boots."""
    global _starting
    _starting = True  # Set before the thread runs, so a status check in between doesn't start a second one.

    def _run():
        global _starting
        try:
            result = ensure_running(base_url)
        finally:
            _starting = False  # ensure_running can return early (already running) without clearing it.
        if on_done:
            on_done(result)
    threading.Thread(target=_run, daemon=True, name="JarvisOllamaStarter").start()
