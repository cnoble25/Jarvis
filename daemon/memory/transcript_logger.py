"""
Transcript Logger & S3 Backup Syncer (Sub-Task 3.1)
Logs voice conversation turns locally as daily JSONL files and optionally syncs un-uploaded records
to an AWS S3 bucket configured via .env (JARVIS_S3_BUCKET_ARN).
"""

import os
import json
import uuid
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Load environment variables from project root .env
load_dotenv()


def parse_bucket_name(arn_or_name: str) -> str:
    """
    Parses S3 Bucket Name from an S3 ARN (e.g. 'arn:aws:s3:::my-jarvis-transcripts-bucket')
    or returns plain bucket name.
    """
    if not arn_or_name:
        return ""
    cleaned = arn_or_name.strip()
    if cleaned.startswith("arn:aws:s3:::"):
        cleaned = cleaned.replace("arn:aws:s3:::", "")
    elif "arn:aws:s3:" in cleaned:
        cleaned = cleaned.split(":")[-1]
    return cleaned.split("/")[0]


class TranscriptLogger:
    def __init__(self, log_dir: Optional[str] = None, max_local_turns: int = 50, max_s3_turns: int = 300):
        """
        Initialize TranscriptLogger.
        
        :param log_dir: Custom directory for transcripts. Defaults to ~/.local/share/jarvis/transcripts/
        :param max_local_turns: Maximum number of local transcript turns saved (default 50).
        :param max_s3_turns: Maximum number of transcript records stored in S3 bucket (default 300).
        """
        if log_dir is None:
            home = Path.home()
            self.log_dir = home / ".local" / "share" / "jarvis" / "transcripts"
        else:
            self.log_dir = Path(log_dir)
            
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_local_turns = max_local_turns
        # Extra fields for the next logged turn (e.g. the transcription alternatives), set by the daemon.
        self._next_turn_meta: Dict[str, Any] = {}
        self._write_lock = threading.RLock()
        self.max_s3_turns = max_s3_turns

        # S3 Configuration from environment
        self.s3_arn = os.getenv("JARVIS_S3_BUCKET_ARN", "")
        self.bucket_name = parse_bucket_name(self.s3_arn)
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
        self.aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        
        # Toggle S3 sync (True if enabled in .env and bucket name is present)
        s3_enabled_env = os.getenv("JARVIS_S3_SYNC_ENABLED", "false").lower() in ("true", "1", "yes")
        self.s3_sync_enabled = s3_enabled_env and bool(self.bucket_name)

        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Enforce max 50 local turns cap on initialization
        self.prune_local_logs()

        # Trigger auto-sync on application startup if S3 sync enabled
        if self.s3_sync_enabled:
            threading.Thread(target=self.sync_unuploaded_to_s3, daemon=True, name="JarvisStartupS3SyncThread").start()

    def prune_local_logs(self):
        """
        Enforces maximum local transcript limit (50 turns).
        Deletes older local JSONL records/files exceeding max_local_turns.
        """
        all_records = self.read_all_transcripts()
        if len(all_records) <= self.max_local_turns:
            return

        print(f"[TranscriptLogger] Pruning local transcript logs ({len(all_records)} records -> max {self.max_local_turns})...", flush=True)
        keep_records = all_records[-self.max_local_turns:]
        keep_ids = set(r.get("record_id") for r in keep_records)

        for log_file in sorted(self.log_dir.glob("*.jsonl")):
            kept_lines = []
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        rec = json.loads(line_str)
                        if rec.get("record_id") in keep_ids:
                            kept_lines.append(line_str)
                    except Exception:
                        pass

            if kept_lines:
                with open(log_file, "w", encoding="utf-8") as f:
                    for kl in kept_lines:
                        f.write(kl + "\n")
            else:
                try:
                    os.remove(log_file)
                except OSError:
                    pass

    def prune_s3_bucket(self):
        """
        Enforces maximum S3 bucket transcript limit (300 records).
        Deletes oldest S3 transcript objects exceeding max_s3_turns.
        """
        if not self.s3_sync_enabled or not self.bucket_name:
            return

        try:
            import boto3
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=self.aws_access_key or None,
                aws_secret_access_key=self.aws_secret_key or None,
                region_name=self.aws_region or None
            )

            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix="transcripts/")
            
            s3_objects = []
            for page in pages:
                for obj in page.get('Contents', []):
                    s3_objects.append(obj)

            if len(s3_objects) > self.max_s3_turns:
                s3_objects.sort(key=lambda x: x['LastModified'])
                to_delete_count = len(s3_objects) - self.max_s3_turns
                objects_to_delete = [{'Key': obj['Key']} for obj in s3_objects[:to_delete_count]]

                print(f"[TranscriptLogger S3 Prune] Pruning S3 bucket ({len(s3_objects)} records -> deleting {to_delete_count} oldest to cap at {self.max_s3_turns})...", flush=True)
                s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={'Objects': objects_to_delete}
                )
        except Exception as e:
            print(f"[TranscriptLogger S3 Warning] Failed to prune S3 bucket: {e}", flush=True)

    def get_todays_log_file(self) -> Path:
        """
        Returns Path object for today's JSONL log file (e.g. 2026-07-25.jsonl).
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{today_str}.jsonl"

    def log_turn(
        self,
        session_id: str,
        user_query: str,
        tool_executed: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        execution_stdout: str = "",
        execution_stderr: str = "",
        spoken_response: str = "",
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Logs a completed interaction packet to local JSONL transcript.
        
        :return: The written record dict.
        """
        record = {
            "record_id": str(uuid.uuid4()),
            "session_id": session_id,
            "timestamp": datetime.now().astimezone().isoformat(),
            "user_query": user_query,
            "tool_executed": tool_executed or "none",
            "tool_args": tool_args or {},
            "execution_stdout": execution_stdout,
            "execution_stderr": execution_stderr,
            "spoken_response": spoken_response,
            "synced_to_s3": False
        }
        # Explicit meta belongs to this turn (a background task carries its own); otherwise use the pending one.
        if meta is not None:
            record.update(meta)
        elif self._next_turn_meta:
            record.update(self.pop_next_turn_meta())

        log_path = self.get_todays_log_file()
        try:
            with self._write_lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
                print(f"[TranscriptLogger] Turn logged to {log_path.name} (ID: {record['record_id'][:8]})", flush=True)
                self.prune_local_logs()
        except Exception as e:
            print(f"[TranscriptLogger Error] Failed to write transcript log: {e}", flush=True)

        return record

    def set_next_turn_meta(self, meta: Dict[str, Any]):
        """Attach extra fields to the next turn this logger writes."""
        self._next_turn_meta = dict(meta or {})

    def update_next_turn_meta(self, meta: Dict[str, Any]):
        """Add fields to the pending metadata without dropping what's already there."""
        self._next_turn_meta.update(meta or {})

    def peek_next_turn_meta(self) -> Dict[str, Any]:
        return dict(self._next_turn_meta)

    def pop_next_turn_meta(self) -> Dict[str, Any]:
        """Take the pending metadata for the turn being processed, so a later turn can't pick it up."""
        meta, self._next_turn_meta = self._next_turn_meta, {}
        return dict(meta)

    def read_all_transcripts(self) -> List[Dict[str, Any]]:
        """
        Reads and parses all JSONL transcript records stored locally.
        """
        records = []
        for log_file in sorted(self.log_dir.glob("*.jsonl")):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
            except Exception as e:
                print(f"[TranscriptLogger Warning] Error reading {log_file.name}: {e}", flush=True)
        return records

    def sync_unuploaded_to_s3(self) -> Dict[str, Any]:
        """
        Uploads un-synced transcript logs to AWS S3 bucket specified by JARVIS_S3_BUCKET_ARN.
        Updates 'synced_to_s3' flag in local files upon successful upload.
        """
        if not self.s3_sync_enabled:
            return {"success": False, "reason": "S3 sync disabled or JARVIS_S3_BUCKET_ARN not configured"}

        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError:
            return {"success": False, "reason": "boto3 library not installed"}

        if not self.bucket_name:
            return {"success": False, "reason": "Invalid or missing S3 bucket name from ARN"}

        try:
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=self.aws_access_key or None,
                aws_secret_access_key=self.aws_secret_key or None,
                region_name=self.aws_region or None
            )

            total_uploaded = 0
            for log_file in sorted(self.log_dir.glob("*.jsonl")):
                updated_lines = []
                file_modified = False

                with open(log_file, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip()]

                for line in lines:
                    record = json.loads(line)
                    if not record.get("synced_to_s3", False):
                        date_parts = record["timestamp"].split("T")[0].split("-")
                        s3_key = f"transcripts/{date_parts[0]}/{date_parts[1]}/{date_parts[2]}/{record['record_id']}.json"

                        s3_client.put_object(
                            Bucket=self.bucket_name,
                            Key=s3_key,
                            Body=json.dumps(record, indent=2).encode("utf-8"),
                            ContentType="application/json"
                        )

                        record["synced_to_s3"] = True
                        file_modified = True
                        total_uploaded += 1

                    updated_lines.append(json.dumps(record))

                if file_modified:
                    with open(log_file, "w", encoding="utf-8") as f:
                        for ul in updated_lines:
                            f.write(ul + "\n")

            # Enforce 300 S3 record cap
            self.prune_s3_bucket()

            msg = f"Successfully synced {total_uploaded} records to s3://{self.bucket_name}"
            print(f"[TranscriptLogger S3 Sync] {msg}", flush=True)
            return {"success": True, "uploaded_count": total_uploaded, "bucket": self.bucket_name}

        except Exception as e:
            err_msg = f"S3 Sync failed: {e}"
            print(f"[TranscriptLogger S3 Error] {err_msg}", flush=True)
            return {"success": False, "error": str(e)}

    def start_background_s3_sync(self, interval_sec: int = 300):
        """
        Starts a background daemon thread that periodically syncs logs to S3.
        """
        if not self.s3_sync_enabled:
            print("[TranscriptLogger] S3 sync disabled in .env (JARVIS_S3_SYNC_ENABLED=false). Background sync thread not started.", flush=True)
            return

        def _worker():
            # Initial startup sync
            self.sync_unuploaded_to_s3()
            while not self._stop_event.is_set():
                self._stop_event.wait(interval_sec)
                if not self._stop_event.is_set():
                    self.sync_unuploaded_to_s3()

        self._stop_event.clear()
        self._sync_thread = threading.Thread(target=_worker, daemon=True, name="JarvisS3SyncThread")
        self._sync_thread.start()
        print(f"[TranscriptLogger] Background S3 Sync thread started (Interval: {interval_sec}s, Target: {self.bucket_name})", flush=True)

    def stop_background_s3_sync(self):
        """
        Stops the background S3 sync thread.
        """
        if self._sync_thread and self._sync_thread.is_alive():
            self._stop_event.set()
            self._sync_thread.join(timeout=3.0)
            print("[TranscriptLogger] Background S3 Sync thread stopped.", flush=True)
