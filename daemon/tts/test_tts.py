"""
Test Script for Task 1.3: Local Text-to-Speech (TTS) Engine
Synthesizes a test voice response using Kokoro-ONNX and plays audio through speakers.
"""

from daemon.tts.tts_engine import TTSEngine


def run_tts_test():
    print("==================================================")
    print("     Jarvis Task 1.3 Text-to-Speech (TTS) Test    ")
    print("==================================================")
    
    tts = TTSEngine()
    
    test_phrase = "Hello Carson, Jarvis local voice synthesis is fully operational."
    
    print(f"\n[Test] Available Voices: {tts.get_available_voices()[:6]}")
    print(f"[Test] Synthesizing & playing spoken response...")
    
    # Speak test response
    tts.speak(test_phrase, voice="af_kore", speed=1.0, block=True)
    
    print("\n✅ SUCCESS: TTS playback completed cleanly.")
    print("==================================================")


if __name__ == "__main__":
    run_tts_test()
