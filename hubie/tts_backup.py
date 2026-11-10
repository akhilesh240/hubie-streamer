"""TTS with fallback chain: ElevenLabs (if key) -> edge-tts (free). Returns an mp3 path."""
import asyncio, logging, os, time, uuid
from pathlib import Path

log = logging.getLogger("tts")


class TTS:
    def __init__(self, cfg: dict, cache_dir: str = "cache"):
        self.voice = cfg.get("voice", "en-GB-RyanNeural")
        self.rate = cfg.get("voice_rate", "-8%")
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)
        self.eleven_key = os.getenv("ELEVENLABS_API_KEY")
        self.eleven_voice = os.getenv("ELEVENLABS_VOICE_ID")

    def _cleanup(self):
        cutoff = time.time() - 900
        for p in self.cache.glob("*.mp3"):
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)

    async def speak(self, text: str) -> Path | None:
        self._cleanup()
        path = self.cache / f"{uuid.uuid4().hex}.mp3"
        if self.eleven_key and self.eleven_voice:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=20) as c:
                    r = await c.post(
                        f"https://api.elevenlabs.io/v1/text-to-speech/{self.eleven_voice}",
                        headers={"xi-api-key": self.eleven_key},
                        json={"text": text, "model_id": "eleven_turbo_v2_5"})
                    r.raise_for_status()
                    path.write_bytes(r.content)
                    return path
            except Exception as e:
                log.warning("ElevenLabs failed (%s) -> edge-tts", e)
        try:
            import edge_tts
            await asyncio.wait_for(edge_tts.Communicate(text, self.voice, rate=self.rate).save(str(path)), timeout=20)
            return path
        except Exception as e:
            log.error("edge-tts failed: %s", e)
            return None
