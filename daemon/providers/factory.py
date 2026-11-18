"""
Provider Factory & Settings Persistence (Story 3.1)
Manages dynamic provider instantiation and live configuration hot-swapping.
"""

import os
import json
import importlib
import pkgutil
from pathlib import Path
from typing import Dict, Any, Optional
from daemon.providers.base import BaseSTTProvider, BaseLLMProvider, BaseTTSProvider

SETTINGS_FILE = Path(os.path.expanduser("~/.config/jarvis/settings.json"))

DEFAULT_SETTINGS = {
    "stt_provider": "faster_whisper",
    "stt_model": "large-v3-turbo",
    "llm_provider": "ollama",
    "llm_model": "qwen3.5:9b",
    "memory_llm_provider": "inherit",
    "memory_llm_model": "inherit",
    "tts_provider": "kokoro",
    "tts_voice": "af_kore",
    "gemini_api_key": "",
    "anthropic_api_key": ""
}


class ProviderRegistry:
    _stt_registry: Dict[str, type] = {}
    _tts_registry: Dict[str, type] = {}
    _llm_registry: Dict[str, type] = {}
    _discovered: bool = False

    @classmethod
    def register_stt(cls, provider_id: str):
        def decorator(subclass):
            if provider_id in cls._stt_registry and cls._stt_registry[provider_id] != subclass:
                print(f"[ProviderRegistry Warning] Overwriting STT provider '{provider_id}'", flush=True)
            cls._stt_registry[provider_id] = subclass
            return subclass
        return decorator

    @classmethod
    def register_tts(cls, provider_id: str):
        def decorator(subclass):
            if provider_id in cls._tts_registry and cls._tts_registry[provider_id] != subclass:
                print(f"[ProviderRegistry Warning] Overwriting TTS provider '{provider_id}'", flush=True)
            cls._tts_registry[provider_id] = subclass
            return subclass
        return decorator

    @classmethod
    def register_llm(cls, provider_id: str):
        def decorator(subclass):
            if provider_id in cls._llm_registry and cls._llm_registry[provider_id] != subclass:
                print(f"[ProviderRegistry Warning] Overwriting LLM provider '{provider_id}'", flush=True)
            cls._llm_registry[provider_id] = subclass
            return subclass
        return decorator

    @classmethod
    def discover_providers(cls):
        if cls._discovered:
            return
        cls._discovered = True
        base_dir = Path(__file__).parent
        for category in ["stt", "tts", "llm"]:
            cat_dir = base_dir / category
            if cat_dir.exists():
                for mod_info in pkgutil.iter_modules([str(cat_dir)]):
                    if not mod_info.name.startswith("_"):
                        try:
                            importlib.import_module(f"daemon.providers.{category}.{mod_info.name}")
                        except Exception as e:
                            print(f"[ProviderRegistry Error] Failed to auto-discover daemon.providers.{category}.{mod_info.name}: {e}", flush=True)

    @classmethod
    def get_stt_provider_class(cls, provider_id: str) -> Optional[type]:
        cls.discover_providers()
        return cls._stt_registry.get(provider_id)

    @classmethod
    def get_tts_provider_class(cls, provider_id: str) -> Optional[type]:
        cls.discover_providers()
        return cls._tts_registry.get(provider_id)

    @classmethod
    def get_llm_provider_class(cls, provider_id: str) -> Optional[type]:
        cls.discover_providers()
        return cls._llm_registry.get(provider_id)

    @staticmethod
    def _canonical_ids(registry: Dict[str, type]) -> Dict[str, type]:
        """
        A provider class may register under several aliases (e.g. 'ElevenLabs', 'elevenlabs_tts', 'elevenlabs').
        Listings show each class once, under its plainest alias: lowercase first, then shortest.
        """
        by_class: Dict[type, list] = {}
        for pid, pcls in registry.items():
            by_class.setdefault(pcls, []).append(pid)
        return {min(pids, key=lambda p: (not p.islower(), len(p))): pcls for pcls, pids in by_class.items()}

    @classmethod
    def list_stt_providers(cls) -> list[dict[str, Any]]:
        cls.discover_providers()
        res = []
        for pid, pcls in cls._canonical_ids(cls._stt_registry).items():
            try:
                inst = pcls.__new__(pcls)
                info = dict(inst.get_provider_info()) if hasattr(inst, "get_provider_info") else {"id": pid, "name": pid}
            except Exception:
                info = {"id": pid, "name": pid, "type": "local"}
            info["id"] = pid
            res.append(info)
        return res

    @classmethod
    def list_tts_providers(cls) -> list[dict[str, Any]]:
        cls.discover_providers()
        res = []
        for pid, pcls in cls._canonical_ids(cls._tts_registry).items():
            try:
                inst = pcls.__new__(pcls)
                info = dict(inst.get_provider_info()) if hasattr(inst, "get_provider_info") else {"id": pid, "name": pid}
            except Exception:
                info = {"id": pid, "name": pid, "type": "local"}
            info["id"] = pid
            res.append(info)
        return res

    @classmethod
    def list_llm_providers(cls) -> list[dict[str, Any]]:
        cls.discover_providers()
        res = []
        seen = set()
        for pid, pcls in cls._llm_registry.items():
            if pcls in seen:
                continue
            seen.add(pcls)
            try:
                inst = pcls.__new__(pcls)
                info = dict(inst.get_provider_info()) if hasattr(inst, "get_provider_info") else {"id": pid, "name": pid}
            except Exception:
                info = {"id": pid, "name": pid, "type": "cloud"}
            if "id" not in info:
                info["id"] = pid
            if "models" not in info or not info["models"]:
                if hasattr(pcls, "get_available_models"):
                    try:
                        inst_m = pcls.__new__(pcls)
                        info["models"] = inst_m.get_available_models()
                    except Exception:
                        info["models"] = []
            res.append(info)
        return res


class ProviderFactory:
    def __init__(self, settings_path: Optional[Path] = None):
        self.settings_path = settings_path or SETTINGS_FILE
        self.settings: Dict[str, Any] = {}
        self.load_settings()

        self.stt_provider: Optional[BaseSTTProvider] = None
        self.llm_provider: Optional[BaseLLMProvider] = None
        self.memory_llm_provider: Optional[BaseLLMProvider] = None
        self.tts_provider: Optional[BaseTTSProvider] = None

        self.reload_active_providers()

    def get_available_stt_providers(self) -> list[dict[str, Any]]:
        return ProviderRegistry.list_stt_providers()

    def get_available_tts_providers(self) -> list[dict[str, Any]]:
        return ProviderRegistry.list_tts_providers()

    def get_available_llm_providers(self) -> list[dict[str, Any]]:
        return ProviderRegistry.list_llm_providers()

    def get_voices_for_provider(self, tts_id: str) -> list[str]:
        if self.tts_provider and getattr(self, "_tts_id", None) == tts_id:
            return self.tts_provider.get_available_voices()
        tts_cls = ProviderRegistry.get_tts_provider_class(tts_id)
        if tts_cls:
            try:
                inst = tts_cls()
                return inst.get_available_voices()
            except Exception as e:
                print(f"[ProviderFactory Warning] Failed to inspect voices for TTS provider '{tts_id}': {e}", flush=True)
        return []

    def load_settings(self) -> Dict[str, Any]:
        """
        Loads settings from disk, creating default settings if missing.
        """
        if self.settings_path.exists():
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except Exception as e:
                print(f"[ProviderFactory Warning] Failed to load settings: {e}", flush=True)
                self.settings = dict(DEFAULT_SETTINGS)
        else:
            self.settings = dict(DEFAULT_SETTINGS)
            self.save_settings()

        return self.settings

    def save_settings(self):
        """
        Saves current settings dictionary to disk.
        """
        try:
            os.makedirs(self.settings_path.parent, exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
            print(f"[ProviderFactory] Saved settings to {self.settings_path}", flush=True)
        except Exception as e:
            print(f"[ProviderFactory Error] Failed to save settings: {e}", flush=True)

    def _instantiate_llm_provider(self, raw_llm_id: str, default_model: Optional[str] = None) -> BaseLLMProvider:
        if ":" in raw_llm_id:
            llm_id, submodel = raw_llm_id.split(":", 1)
        else:
            llm_id = raw_llm_id
            submodel = default_model or ("gemini-3.6-flash" if llm_id == "gemini_llm" else "qwen3.5:9b")

        llm_cls = ProviderRegistry.get_llm_provider_class(llm_id)
        if llm_cls:
            if llm_id == "anthropic_llm":
                api_key = self.settings.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
                return llm_cls(api_key=api_key, model_name=submodel)
            elif llm_id == "gemini_llm":
                api_key = self.settings.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                return llm_cls(api_key=api_key, model_name=submodel)
            else:
                return llm_cls(model_name=submodel)
        else:
            print(f"[ProviderFactory Warning] LLM provider '{llm_id}' not registered. Falling back to OllamaLLMProvider.", flush=True)
            from daemon.providers.llm.ollama_llm_provider import OllamaLLMProvider
            return OllamaLLMProvider(model_name=submodel)

    def reload_active_providers(self):
        """
        Instantiates active STT, LLM, Memory LLM, and TTS providers based on current settings.
        """
        print("[ProviderFactory] Instantiating active AI engine providers...", flush=True)
        
        # 1. STT Provider (only re-instantiate if STT provider or model changed)
        stt_id = self.settings.get("stt_provider", "faster_whisper")
        stt_model = self.settings.get("stt_model", "large-v3-turbo")
        curr_stt_id = getattr(self, "_stt_id", None)
        curr_stt_model = getattr(self, "_stt_model", None)

        if self.stt_provider is None or curr_stt_id != stt_id or curr_stt_model != stt_model:
            stt_cls = ProviderRegistry.get_stt_provider_class(stt_id)
            if stt_cls:
                if stt_id == "gemini_stt":
                    api_key = self.settings.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                    self.stt_provider = stt_cls(api_key=api_key)
                else:
                    self.stt_provider = stt_cls(model_size=stt_model)
            else:
                print(f"[ProviderFactory Warning] STT provider '{stt_id}' not registered. Falling back to faster_whisper.", flush=True)
                from daemon.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider
                self.stt_provider = FasterWhisperSTTProvider(model_size=stt_model)
            self._stt_id = stt_id
            self._stt_model = stt_model

        # 2. Main LLM Provider
        raw_llm_id = self.settings.get("llm_provider", "ollama")
        self.llm_provider = self._instantiate_llm_provider(raw_llm_id, self.settings.get("llm_model"))
        if ":" in raw_llm_id:
            self.settings["llm_provider"] = raw_llm_id.split(":", 1)[0]
            self.settings["llm_model"] = raw_llm_id.split(":", 1)[1]

        # 2b. Memory & Fast-Path Agent LLM Provider
        raw_mem_id = self.settings.get("memory_llm_provider", "inherit")
        if raw_mem_id in ("inherit", "", None):
            self.memory_llm_provider = self.llm_provider
            self.settings["memory_llm_provider"] = "inherit"
        else:
            self.memory_llm_provider = self._instantiate_llm_provider(raw_mem_id, self.settings.get("memory_llm_model"))
            if ":" in raw_mem_id:
                self.settings["memory_llm_provider"] = raw_mem_id.split(":", 1)[0]
                self.settings["memory_llm_model"] = raw_mem_id.split(":", 1)[1]

        # 3. TTS Provider (only re-instantiate if TTS provider or voice changed)
        tts_id = self.settings.get("tts_provider", "kokoro")
        voice = self.settings.get("tts_voice", "af_kore")
        tts_model = self.settings.get("elevenlabs_model")  # only ElevenLabs takes a model
        curr_tts_id = getattr(self, "_tts_id", None)
        curr_tts_voice = getattr(self, "_tts_voice", None)

        if (self.tts_provider is None or curr_tts_id != tts_id or curr_tts_voice != voice
                or getattr(self, "_tts_model", None) != tts_model):
            tts_cls = ProviderRegistry.get_tts_provider_class(tts_id)
            if tts_cls:
                try:
                    self.tts_provider = tts_cls(voice=voice, model=tts_model)
                except TypeError:
                    self.tts_provider = tts_cls(voice=voice)
            else:
                print(f"[ProviderFactory Warning] TTS provider '{tts_id}' not registered. Falling back to kokoro.", flush=True)
                from daemon.providers.tts.kokoro_tts_provider import KokoroTTSProvider
                self.tts_provider = KokoroTTSProvider(voice=voice)
            self._tts_id = tts_id
            self._tts_voice = voice
            self._tts_model = tts_model

        print(f"[ProviderFactory] Active STT: {self.stt_provider.get_provider_info()['name']}", flush=True)
        print(f"[ProviderFactory] Active Main LLM: {self.llm_provider.get_provider_info()['name']}", flush=True)
        print(f"[ProviderFactory] Active Memory LLM: {self.memory_llm_provider.get_provider_info()['name']}", flush=True)
        print(f"[ProviderFactory] Active TTS: {self.tts_provider.get_provider_info()['name']}", flush=True)

    def update_settings(self, new_settings: Dict[str, Any]):
        """
        Updates settings dictionary, persists API keys to .env and os.environ, and hot-swaps active engine instances.
        """
        from daemon.utils.env_manager import get_env_manager
        env_mgr = get_env_manager()

        # Save any API key entries directly to .env file & os.environ
        env_updates = {}
        if "gemini_api_key" in new_settings and new_settings["gemini_api_key"]:
            env_updates["GEMINI_API_KEY"] = new_settings["gemini_api_key"]
        if "openai_api_key" in new_settings and new_settings["openai_api_key"]:
            env_updates["OPENAI_API_KEY"] = new_settings["openai_api_key"]
        if "anthropic_api_key" in new_settings and new_settings["anthropic_api_key"]:
            env_updates["ANTHROPIC_API_KEY"] = new_settings["anthropic_api_key"]
        if "elevenlabs_api_key" in new_settings and new_settings["elevenlabs_api_key"]:
            env_updates["ELEVENLABS_API_KEY"] = new_settings["elevenlabs_api_key"]

        if "s3_sync_enabled" in new_settings:
            env_updates["JARVIS_S3_SYNC_ENABLED"] = "true" if new_settings["s3_sync_enabled"] else "false"
        if "s3_bucket_arn" in new_settings and new_settings["s3_bucket_arn"]:
            env_updates["JARVIS_S3_BUCKET_ARN"] = new_settings["s3_bucket_arn"]
        if "aws_region" in new_settings and new_settings["aws_region"]:
            env_updates["AWS_REGION"] = new_settings["aws_region"]
        if "aws_access_key_id" in new_settings and new_settings["aws_access_key_id"]:
            env_updates["AWS_ACCESS_KEY_ID"] = new_settings["aws_access_key_id"]
        if "aws_secret_access_key" in new_settings and new_settings["aws_secret_access_key"]:
            env_updates["AWS_SECRET_ACCESS_KEY"] = new_settings["aws_secret_access_key"]

        if env_updates:
            env_mgr.save_keys(env_updates)

        self.settings.update(new_settings)
        self.save_settings()
        self.reload_active_providers()


# Global singleton instance
_global_factory: Optional[ProviderFactory] = None

def get_provider_factory() -> ProviderFactory:
    global _global_factory
    if _global_factory is None:
        _global_factory = ProviderFactory()
    return _global_factory

