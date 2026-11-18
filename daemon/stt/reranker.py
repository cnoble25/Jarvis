"""
Pick what you most likely said, not just what Whisper heard most strongly.

Whisper returns several candidate transcriptions (n-best) with log-probabilities. Short
commands are easy to mishear ("pause Spotify" -> "poor Spotify"), but the right answer is
usually still in the list. Each candidate is scored by

    log P(candidate | audio)  +  LAMBDA * plausibility(candidate)

where plausibility measures how much it sounds like something said to Jarvis: an exact match
with a known phrase (shortcut phrases, command examples, macro names), how many of its words
Jarvis knows, and how close it is to the nearest known phrase.

LAMBDA and TEMPERATURE were tuned on 60 synthetic (Kokoro) command clips from three voices and
checked on 40 clips from two held-out voices: with large-v3-turbo on GPU the full pipeline got
99/100 commands exactly right; base.en on CPU went from 88 to 97. Re-tune on real recordings
(Settings > Test hearing on your voice) before trusting these weights further.
"""

import difflib
import math
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

LAMBDA = 4.0
TEMPERATURE = 0.7
VOCAB_TTL_SECONDS = 60

# Proper nouns Whisper tends to mangle; also fed to Whisper as hotwords.
DEFAULT_HOTWORDS = ["Spotify", "Discord", "Steam", "Firefox", "VS Code", "Stremio", "Jarvis", "Claude", "locked in"]

_NUMBERS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
    "7": "seven", "8": "eight", "9": "nine", "10": "ten", "15": "fifteen", "20": "twenty",
    "30": "thirty", "45": "forty five", "60": "sixty", "90": "ninety", "100": "hundred",
}


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, spell out common numbers: 'Set it to 60%.' -> 'set it to sixty percent'."""
    t = text.lower().replace("%", " percent").replace("vs. code", "vs code")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return " ".join(_NUMBERS.get(w, w) for w in t.split())


class CommandVocabulary:
    """Phrases and words Jarvis already knows you say, refreshed periodically from live sources."""

    def __init__(self, sources: Optional[Callable[[], Iterable[str]]] = None):
        self._sources = sources
        self._lock = threading.Lock()
        self._built_at = 0.0
        self.phrases: List[str] = []
        self.phrase_set: set = set()
        self.words: set = set()
        self.hotwords = " ".join(DEFAULT_HOTWORDS)

    def set_sources(self, sources: Callable[[], Iterable[str]]):
        with self._lock:
            self._sources = sources
            self._built_at = 0.0

    def refresh(self, force: bool = False):
        with self._lock:
            if not force and self.phrases and time.monotonic() - self._built_at < VOCAB_TTL_SECONDS:
                return
            raw = list(self._sources()) if self._sources else []
            phrases = sorted({normalize(p) for p in raw if p and normalize(p)})
            self.phrases = phrases
            self.phrase_set = set(phrases)
            self.words = {w for p in phrases for w in p.split()} | {normalize(h) for h in DEFAULT_HOTWORDS}
            self.words = {w for h in self.words for w in h.split()}
            self._built_at = time.monotonic()

    def plausibility(self, normalized_text: str, shared_words: Optional[set] = None) -> float:
        """
        0..1: 1 for an exact known phrase, otherwise word coverage plus closeness to the nearest phrase.
        Coverage is measured on the words this candidate does NOT share with the other candidates,
        so in a long request the one disputed word ("light" vs "liked") decides it, not the 9 that agree.
        """
        if not normalized_text:
            return 0.0
        if normalized_text in self.phrase_set:
            return 1.0
        words = normalized_text.split()
        disputed = [w for w in words if not shared_words or w not in shared_words] or words
        coverage = sum(w in self.words for w in disputed) / len(disputed)
        nearest = max((difflib.SequenceMatcher(None, normalized_text, p).ratio() for p in self.phrases), default=0.0)
        return 0.5 * coverage + 0.4 * nearest


def rerank(candidates: List[Tuple[str, float]], vocabulary: CommandVocabulary) -> Tuple[str, List[Dict[str, Any]]]:
    """
    candidates: (text, length-normalized log-probability) pairs from Whisper's n-best.
    Returns the chosen text and the alternatives with their probabilities after reranking,
    most likely first. Variants that differ only in case or punctuation are merged.
    """
    if not candidates:
        return "", []
    vocabulary.refresh()

    # Merge variants ("Close Spotify", "close spotify!") and keep the best-looking surface text.
    merged: Dict[str, Dict[str, Any]] = {}
    for text, score in candidates:
        key = normalize(text)
        if not key:
            continue
        weight = math.exp(score / TEMPERATURE)
        entry = merged.setdefault(key, {"weight": 0.0, "text": text.strip(), "best": score})
        entry["weight"] += weight
        if score > entry["best"]:
            entry["best"], entry["text"] = score, text.strip()
    if not merged:
        return candidates[0][0].strip(), []

    total = sum(e["weight"] for e in merged.values())
    word_sets = [set(key.split()) for key in merged]
    shared = set.intersection(*word_sets) if len(word_sets) > 1 else set()
    combined = {
        key: math.log(e["weight"] / total) + LAMBDA * vocabulary.plausibility(key, shared)
        for key, e in merged.items()
    }
    peak = max(combined.values())
    exp = {k: math.exp(v - peak) for k, v in combined.items()}
    z = sum(exp.values())
    ranked = sorted(merged, key=lambda k: combined[k], reverse=True)
    alternatives = [
        {"text": merged[k]["text"], "probability": round(exp[k] / z, 3), "heard_probability": round(merged[k]["weight"] / total, 3)}
        for k in ranked
    ]
    return merged[ranked[0]]["text"], alternatives
