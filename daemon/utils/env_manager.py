"""
Environment Key & .env File Persistence Manager
Allows adding, updating, and saving API keys (Gemini, OpenAI, Anthropic, ElevenLabs, AWS)
directly from the GUI application into the project root .env file and os.environ.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional

ENV_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class EnvManager:
    def __init__(self, env_path: Optional[Path] = None):
        self.env_path = env_path or ENV_FILE_PATH

    def get_key(self, key_name: str, default: str = "") -> str:
        """
        Retrieves API key value from os.environ or .env file.
        """
        return os.environ.get(key_name, default)

    def load_env_dict(self) -> Dict[str, str]:
        """
        Parses current .env file into a dictionary and populates os.environ.
        """
        env_dict = {}
        if not self.env_path.exists():
            return env_dict

        try:
            with open(self.env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        # Strip surrounding quotes if present
                        v_clean = v.strip().strip("'\"")
                        k_clean = k.strip()
                        env_dict[k_clean] = v_clean
                        if k_clean not in os.environ or not os.environ[k_clean]:
                            os.environ[k_clean] = v_clean
        except Exception as e:
            print(f"[EnvManager Error] Failed to read .env file: {e}", flush=True)

        return env_dict

    def save_key(self, key_name: str, key_value: str) -> bool:
        """
        Saves a single key-value pair to .env file and updates os.environ.
        """
        return self.save_keys({key_name: key_value})

    def save_keys(self, keys_dict: Dict[str, str]) -> bool:
        """
        Updates multiple key-value pairs in the .env file and updates os.environ in memory.
        """
        try:
            # 1. Update live os.environ memory immediately
            for k, v in keys_dict.items():
                if v is not None:
                    os.environ[k] = str(v)

            # 2. Read existing lines from .env
            lines = []
            existing_keys = set()
            if self.env_path.exists():
                with open(self.env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in keys_dict:
                        existing_keys.add(k)
                        val = keys_dict[k]
                        new_lines.append(f'{k}="{val}"\n')
                        continue
                new_lines.append(line)

            # Append any new keys that were not already in .env
            for k, v in keys_dict.items():
                if k not in existing_keys and v:
                    new_lines.append(f'{k}="{v}"\n')

            # Write updated lines back to .env
            os.makedirs(self.env_path.parent, exist_ok=True)
            with open(self.env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            print(f"[EnvManager] Successfully saved {len(keys_dict)} keys to {self.env_path}", flush=True)
            return True

        except Exception as e:
            print(f"[EnvManager Error] Failed to write to .env: {e}", flush=True)
            return False


# Singleton instance
_global_env_manager: Optional[EnvManager] = None

def get_env_manager() -> EnvManager:
    global _global_env_manager
    if _global_env_manager is None:
        _global_env_manager = EnvManager()
    return _global_env_manager
