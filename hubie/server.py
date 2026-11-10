"""Serves the overlay (avatar + audio + subtitles) to an OBS Browser Source and pushes speech to it."""
import asyncio, json, logging, time
from pathlib import Path
from aiohttp import web, WSMsgType

log = logging.getLogger("server")


class OverlayServer:
    def __init__(self, port: int, cache_dir="cache", overlay_dir="overlay"):
        self.port, self.cache, self.overlay = port, Path(cache_dir), Path(overlay_dir)
        self.clients: set[web.WebSocketResponse] = set()
        self.simulated = False                           # True while a simulated audience is running (shown on screen)
        self.on_chat = None                              # set by main: (user, text) -> moderated chat pipeline
        self._done = asyncio.Event()
        self.run_started = self._run_start()

    @staticmethod
    def _run_start() -> float:
        """Start time of the current unattended run. Kept across quick restarts (heartbeat still fresh)."""
        f, hb = Path("run_start.txt"), Path("heartbeat.txt")
        try:
            if f.exists() and hb.exists() and time.time() - hb.stat().st_mtime < 180:
                return float(f.read_text())
        except Exception:
            pass
        t = time.time()
        f.write_text(str(t))
        return t

    async def broadcast(self, obj: dict):
        msg = json.dumps(obj)
        for ws in [w for w in self.clients if not w.closed]:
            try:
                await ws.send_str(msg)
            except Exception:
                pass

    async def _ws(self, req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        self.clients.add(ws)
        await ws.send_str(json.dumps({"type": "hello", "start": self.run_started, "sim": self.simulated}))
        local = req.remote in ("127.0.0.1", "::1", None)
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                d = json.loads(m.data)
            except Exception:
                continue
            if d.get("type") == "done":
                self._done.set()
            elif d.get("type") == "chat" and local and self.on_chat:       # typed in the overlay's input bar
                user, text = str(d.get("user") or "You")[:20], str(d.get("text") or "")[:200]
                if text.strip():
                    self.on_chat(user, text)
        self.clients.discard(ws)
        return ws

    async def start(self):
        app = web.Application()
        app.add_routes([
            web.get("/", lambda r: web.FileResponse(self.overlay / "index.html")),
            web.get("/ws", self._ws),
            web.static("/audio", self.cache),
            web.static("/avatar", self.overlay / "avatar"),
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", self.port).start()
        log.info("overlay on http://localhost:%s  (add as OBS Browser Source)", self.port)
        while True:
            await asyncio.sleep(3600)

    async def say(self, text: str, audio: Path | None, kind: str | None = None):
        self._done.clear()
        msg = json.dumps({"type": "say", "text": text, "kind": kind, "audio": f"/audio/{audio.name}" if audio else None})
        live = [ws for ws in self.clients if not ws.closed]
        for ws in live:
            await ws.send_str(msg)
        if not live or not audio:                       # nobody listening / no audio: simulate duration
            await asyncio.sleep(min(12, 1.5 + len(text) * 0.06))
            return
        try:
            await asyncio.wait_for(self._done.wait(), timeout=45)
        except asyncio.TimeoutError:
            log.warning("overlay never reported done")
