"""Restart-on-crash with backoff + heartbeat file for the external health check (the 35-point part)."""
import asyncio, logging, time
from pathlib import Path

log = logging.getLogger("supervisor")
HEARTBEAT = Path("heartbeat.txt")


async def supervise(name: str, factory):
    delay = 2
    while True:
        started = time.time()
        try:
            await factory()
            log.warning("%s exited, restarting", name)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("%s crashed: %s", name, e)
        delay = 2 if time.time() - started > 120 else min(delay * 2, 60)  # healthy run resets backoff
        await asyncio.sleep(delay)


async def heartbeat(director):
    while True:
        HEARTBEAT.write_text(f"{time.time()} {director.spoken}")
        await asyncio.sleep(15)
