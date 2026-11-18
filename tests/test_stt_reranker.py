"""Tests for picking the most sensible transcription from Whisper's n-best candidates."""
import unittest

from daemon.stt.reranker import CommandVocabulary, normalize, rerank

KNOWN = ["pause spotify", "play music", "close spotify", "set a timer for 10 minutes", "start movie mode"]


def vocab():
    v = CommandVocabulary(lambda: KNOWN)
    v.refresh(force=True)
    return v


class TestNormalize(unittest.TestCase):
    def test_punctuation_case_and_numbers(self):
        self.assertEqual(normalize("Set the volume to 60%."), "set the volume to sixty percent")
        self.assertEqual(normalize("Pause Spotify!"), "pause spotify")


class TestRerank(unittest.TestCase):
    def test_known_phrase_beats_a_more_probable_mishearing(self):
        # Real n-best from base.en: Whisper preferred "Poor Spotify" ~7:1 over "Pause Spotify".
        candidates = [("Poor Spotify", -0.20), ("poor Spotify", -0.85), ("Pause Spotify", -0.88), ("Poor Spotify.", -0.98)]
        text, alts = rerank(candidates, vocab())
        self.assertEqual(normalize(text), "pause spotify")
        self.assertEqual(normalize(alts[0]["text"]), "pause spotify")
        self.assertAlmostEqual(sum(a["probability"] for a in alts), 1.0, places=2)

    def test_variants_are_merged(self):
        candidates = [("Close Spotify.", -0.3), ("close spotify", -0.4), ("Close Spotify!", -0.5)]
        _, alts = rerank(candidates, vocab())
        self.assertEqual(len(alts), 1)

    def test_clear_unknown_speech_is_not_overridden(self):
        # Free-form questions aren't known phrases; a confident transcription must survive.
        candidates = [("What's the weather like tomorrow?", -0.05), ("What's the weather like tomorrow", -0.9), ("Watch the weather like tomorrow", -2.5)]
        text, _ = rerank(candidates, vocab())
        self.assertEqual(normalize(text), "what's the weather like tomorrow")

    def test_empty(self):
        self.assertEqual(rerank([], vocab()), ("", []))


if __name__ == "__main__":
    unittest.main()


class TestDisputedWords(unittest.TestCase):
    def test_one_disputed_word_in_a_long_request(self):
        # Real n-best from a live request: Whisper preferred "light" ~8:1 over "liked".
        v = CommandVocabulary(lambda: ["play my liked songs", "shuffle my liked songs", "play my classics playlist"])
        v.refresh(force=True)
        candidates = [("Hey Claude, can you play my light songs playlist on Spotify?", -0.10),
                      ("Hey Claude, can you play my liked songs playlist on Spotify?", -0.80)]
        text, _ = rerank(candidates, v)
        self.assertIn("liked songs", normalize(text))
