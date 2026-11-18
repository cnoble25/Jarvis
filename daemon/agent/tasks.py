"""
Background tasks: requests that take more than a moment (installs, multi-step searches) keep
running after Jarvis has given a quick spoken reply. The board tracks each task's steps so the
dashboard can show what is happening now, and announces when a task finishes.
"""

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

MAX_KEPT = 8  # finished tasks kept for the dashboard


def describe_step(tool: str, args: Any) -> Dict[str, str]:
    """A short, human label for a tool call, plus the raw detail (command, query) underneath."""
    a = args if isinstance(args, dict) else (args[0] if isinstance(args, list) and args and isinstance(args[0], dict) else {})
    if tool == "web_search":
        q = str(a.get("query", "")).strip()
        return {"label": f"Searching the web for “{q}”" if q else "Searching the web", "detail": ""}
    if tool in ("execute_terminal_command", "Bash"):
        why = str(a.get("explanation", "")).strip()
        return {"label": why or "Running a command", "detail": str(a.get("command", "")).strip()}
    if tool in ("View", "Grep", "search_files"):
        target = a.get("path") or a.get("pattern") or a.get("query") or ""
        return {"label": "Looking through files", "detail": str(target)}
    if tool == "Edit":
        return {"label": "Editing a file", "detail": str(a.get("path", ""))}
    return {"label": tool.replace("_", " ").capitalize(), "detail": ""}


class BackgroundTask:
    def __init__(self, title: str, route: Optional[str] = None):
        self.id = uuid.uuid4().hex[:8]
        self.title = title
        self.route = route
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.status = "running"  # running | done | failed | cancelled
        self.current = "Thinking…"
        self.steps: List[Dict[str, str]] = []
        self.result = ""
        self.ack = ""  # first spoken line from the model, used for the quick reply
        self.final_result: Dict[str, Any] = {}
        # Set once the foreground stops waiting and the task is announced on completion instead.
        self.background = False
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        # Set when the foreground should stop waiting: the task finished, or it started slow work.
        self.settled = threading.Event()

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "route": self.route,
            "status": self.status,
            "current": self.current,
            "steps": [dict(s) for s in self.steps],
            "result": self.result,
            "background": self.background,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class TaskBoard:
    """Thread-safe list of recent tasks, with one listener for every change."""

    def __init__(self, listener: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.listener = listener
        self._tasks: List[BackgroundTask] = []
        self._lock = threading.Lock()

    def create(self, title: str, route: Optional[str] = None) -> BackgroundTask:
        task = BackgroundTask(title, route)
        with self._lock:
            self._tasks.append(task)
            finished = [t for t in self._tasks if t.finished]
            for old in finished[: max(0, len(finished) - MAX_KEPT)]:
                self._tasks.remove(old)
        return task

    def get(self, task_id: str) -> Optional[BackgroundTask]:
        with self._lock:
            return next((t for t in self._tasks if t.id == task_id), None)

    def running(self, background_only: bool = False) -> List[BackgroundTask]:
        with self._lock:
            return [t for t in self._tasks if not t.finished and (t.background or not background_only)]

    def snapshot(self) -> List[Dict[str, Any]]:
        """Background tasks only (newest first): foreground requests already show as normal turns."""
        with self._lock:
            return [t.to_dict() for t in reversed(self._tasks) if t.background]

    def emit(self, event: str, task: BackgroundTask):
        if not task.background or not self.listener:
            return
        try:
            self.listener(event, task.to_dict())
        except Exception as err:
            print(f"[TaskBoard Warning] Listener failed: {err}", flush=True)

    def cancel(self, task_id: Optional[str] = None) -> Optional[BackgroundTask]:
        """Cancel one task, or the newest running background task."""
        targets = [self.get(task_id)] if task_id else list(reversed(self.running(background_only=True)))
        for task in targets:
            if task and not task.finished:
                task.cancel_event.set()
                return task
        return None
