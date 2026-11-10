"""One-time SETUP (before going live): open the persistent browser profile so YOU can pass any
security check / look at the game pages by hand. Run:  python -m hubie.setup_browser
Close it when done. Setup before going live is allowed by the contest; never touch it during the run."""
import asyncio, yaml


async def main():
    from playwright.async_api import async_playwright
    cfg = yaml.safe_load(open("config.yaml"))
    profile = cfg.get("browser_profile", ".browser-profile")
    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(profile, channel="chrome", headless=False,
                                                             viewport={"width": 1280, "height": 720})
        except Exception:
            ctx = await p.chromium.launch_persistent_context(profile, headless=False,
                                                             viewport={"width": 1280, "height": 720})
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(cfg["games"][0]["url"])
        input("Pass the security check by hand if shown, open the game in DEMO mode, then press Enter here...")
        await ctx.close()

asyncio.run(main())
