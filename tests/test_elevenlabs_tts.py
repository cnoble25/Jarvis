"""
Test file for ElevenLabs TTS Provider to check if audio output works properly.
Includes step-by-step logging and diagnostic error reporting.
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is in sys.path and load .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

# Configure basic logging for test output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ElevenLabsTest")


def run_elevenlabs_test():
    logger.info("=== Starting ElevenLabs TTS Output Test ===")
    
    # 1. Check API Key configuration
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if api_key:
        logger.info(f"ELEVENLABS_API_KEY found ({api_key[:6]}...).")
    else:
        logger.warning("ELEVENLABS_API_KEY is not set in environment or .env file.")

    # 2. Test Importing Provider Module
    logger.info("Attempting to import ElevenLabsTTSProvider...")
    try:
        from daemon.providers.tts.elevenlabs_tts_provider import ElevenLabsTTSProvider
        logger.info("Successfully imported ElevenLabsTTSProvider.")
    except Exception as e:
        logger.error(f"Failed to import ElevenLabsTTSProvider: {e}", exc_info=True)
        logger.error("=== Test Result: FAIL (Import Error) ===")
        return False

    # 3. Instantiate Provider
    logger.info("Instantiating ElevenLabsTTSProvider...")
    try:
        provider = ElevenLabsTTSProvider()
        info = provider.get_provider_info()
        logger.info(f"Provider info: {info}")
    except Exception as e:
        logger.error(f"Failed to instantiate ElevenLabsTTSProvider: {e}", exc_info=True)
        logger.error("=== Test Result: FAIL (Instantiation Error) ===")
        return False

    # 4. Synthesize Audio
    sample_text = "Testing ElevenLabs text-to-speech output."
    logger.info(f"Attempting to synthesize audio for text: '{sample_text}'")

    try:
        samples, sample_rate = provider._synthesize_audio(sample_text, voice="", speed=1.0)
        
        if samples is not None and len(samples) > 0:
            logger.info("Successfully generated audio output!")
            logger.info(f"Audio details: {len(samples)} samples at {sample_rate} Hz.")
            logger.info("=== Test Result: SUCCESS ===")
            return True
        else:
            logger.error("Synthesis returned empty or invalid audio samples.")
            logger.error("=== Test Result: FAIL (Empty Audio Output) ===")
            return False
            
    except Exception as e:
        logger.error(f"Error during audio synthesis: {e}", exc_info=True)
        logger.error("=== Test Result: FAIL (Synthesis Error) ===")
        return False


if __name__ == "__main__":
    success = run_elevenlabs_test()
    sys.exit(0 if success else 1)
