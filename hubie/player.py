"""Plays House originals in DEMO mode via Playwright. Selectors in config.yaml are placeholders: tune them."""
import asyncio, logging, random, re

log = logging.getLogger("player")
FORBIDDEN = re.compile(r"deposit|cashier|wallet|withdraw|buy crypto|sign ?up|register|log ?in|real ?money", re.I)
BLOCK_MARKERS = ("just a moment", "verify you are human", "security check")
FORBIDDEN_URL = re.compile(r"cashier|wallet|deposit|withdraw|account|login|register", re.I)


class Blocked(Exception):
    """Game page is behind a bot/security check. We never try to bypass it."""


class GamePlayer:
    def __init__(self, cfg: dict, emit):
        self.cfg, self.games, self.emit = cfg, cfg["games"], emit
        self.last = None

    async def _safe_click(self, page, selector: str, timeout=4000) -> bool:
        loc = page.locator(selector).first
        try:
            label = (await loc.inner_text(timeout=timeout)) or ""
        except Exception:
            return False
        if FORBIDDEN.search(label):
            log.warning("refusing to click '%s'", label)
            return False
        await loc.click(timeout=timeout)
        return True

    async def _is_blocked(self, page) -> bool:
        try:
            title = (await page.title()).lower()
            body = (await page.inner_text("body", timeout=2000)).lower()[:3000]
        except Exception:
            return False
        return any(m in title or m in body for m in BLOCK_MARKERS)

    async def _play(self, page, g: dict):
        await page.goto(g["url"], wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(8)                      # let a normal page settle / a passive check finish
        if await self._is_blocked(page):
            raise Blocked(g["url"])
        for sel in g.get("demo_selectors", []):
            if await self._safe_click(page, sel):
                break
        self.emit("segment", g["name"])
        for i in range(g.get("rounds", 10)):
            if FORBIDDEN_URL.search(page.url):          # never wander into wallet/login pages
                log.error("navigated to %s, aborting segment", page.url)
                return
            if not await self._safe_click(page, g["play_selector"]):
                log.warning("play button not found for %s", g["name"])
                await asyncio.sleep(3)
                continue
            await asyncio.sleep(g.get("round_delay_sec", 6))
            result = f"round {i + 1} of {g['name']} just finished"
            if g.get("result_selector"):
                try:
                    result += ": " + (await page.locator(g["result_selector"]).first.inner_text(timeout=2000))
                except Exception:
                    pass
            self.emit("game", result)

    async def run(self):
        from playwright.async_api import async_playwright
        profile = self.cfg.get("browser_profile", ".browser-profile")
        vp = {"width": 1280, "height": 720}
        async with async_playwright() as p:
            try:   # real Chrome with a persistent profile (a human can pass any check once, during setup)
                ctx = await p.chromium.launch_persistent_context(profile, channel="chrome", headless=False, viewport=vp)
            except Exception as e:
                log.warning("Chrome not found (%s), using bundled Chromium", e)
                ctx = await p.chromium.launch_persistent_context(profile, headless=False, viewport=vp)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            while True:
                choices = [g for g in self.games if g["name"] != self.last] or self.games
                g = random.choice(choices)
                self.last = g["name"]
                try:
                    await self._play(page, g)
                except Blocked:
                    wait = self.cfg.get("blocked_retry_sec", 600)
                    log.warning("game page is behind a security check; talk-only mode, retry in %ss", wait)
                    self.emit("game", "the game page is behind a security check right now, so I'm just hanging out and chatting")
                    await asyncio.sleep(wait)       # Hubie keeps talking (idle/chat) meanwhile
                except Exception as e:
                    log.warning("segment %s failed: %s", g["name"], e)
                    await asyncio.sleep(5)
