import asyncio
import logging
import uuid
from pathlib import Path

import edge_tts

log = logging.getLogger("tts")


class TTS:
    def __init__(self, cfg: dict, cache_dir: str = "cache"):
        self.voice = cfg.get("voice", "en-US-GuyNeural")
        self.rate = cfg.get("voice_rate", "+0%")
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)

    async def speak(self, text: str):
        try:
            path = self.cache / f"{uuid.uuid4().hex}.mp3"

            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate
            )

            await asyncio.wait_for(
                communicate.save(str(path)),
                timeout=30
            )

            return path

        except Exception as e:
            log.error("TTS failed: %s", e)
            return None