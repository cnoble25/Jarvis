"""
Jarvis LLM JSON Payload Parser Utility
Extracts clean, valid JSON object dictionaries from raw LLM text outputs,
handling markdown codeblocks, thinking tags, and multi-block conversational text.
"""

import re
import json
from typing import Dict, Any, Optional


def extract_json_payload(raw_text: str, fallback_spoken: str = "") -> Dict[str, Any]:
    """
    Parses LLM output text and extracts the target JSON response object dictionary.
    
    :param raw_text: Raw string returned by LLM provider.
    :param fallback_spoken: Spoken text to use if no valid JSON dictionary can be extracted.
    :return: Dictionary matching Jarvis response schema {"tool": ..., "args": ..., "spoken_summary": ...}.
    """
    if not raw_text or not isinstance(raw_text, str):
        return {"tool": "none", "args": {}, "status": "complete", "spoken_summary": fallback_spoken or "Done."}

    text = raw_text.strip()

    # 1. Clean thinking tags (<think>...</think>)
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>")[-1].strip()

    # 2. Try direct json.loads
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return _normalize_payload(parsed)
    except Exception:
        pass

    # 3. Look for markdown ```json ... ``` code blocks
    code_block_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for block in reversed(code_block_matches):
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict) and ("tool" in parsed or "spoken_summary" in parsed):
                return _normalize_payload(parsed)
        except Exception:
            pass

    # 4. Search for individual JSON object candidates { ... }
    json_candidates = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    for cand in reversed(json_candidates):
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict) and ("tool" in parsed or "spoken_summary" in parsed):
                return _normalize_payload(parsed)
        except Exception:
            pass

    # 5. Fallback slice between first '{' and last '}'
    if "{" in text and "}" in text:
        start_idx = text.find("{")
        end_idx = text.rfind("}") + 1
        sub_str = text[start_idx:end_idx]
        try:
            parsed = json.loads(sub_str)
            if isinstance(parsed, dict):
                return _normalize_payload(parsed)
        except Exception:
            pass

    # Fallback if no valid JSON structure could be extracted
    clean_fallback = re.sub(r"```.*```", "", text, flags=re.DOTALL).strip()
    return {
        "tool": "none",
        "args": {},
        "status": "complete",
        "spoken_summary": fallback_spoken or (clean_fallback if len(clean_fallback) < 150 else "Processed query.")
    }


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensures required fields exist in the parsed payload dictionary.
    """
    if "tool" not in payload:
        payload["tool"] = "none"
    if "args" not in payload:
        payload["args"] = {}
    if "status" not in payload:
        payload["status"] = "complete"
    return payload
