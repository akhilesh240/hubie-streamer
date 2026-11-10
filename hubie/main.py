import asyncio, logging, os, sys, yaml
from .brain import Brain
from .chat import kick_reader, twitch_reader, demo_chat_reader, demo_ambient_reader
from .director import Director
from .moderation import Moderator
from .demo_game import DemoDice
from .player import GamePlayer
from .server import OverlayServer
from .supervisor import heartbeat, supervise
from .tts import TTS


def load_env(path=".env"):
    """Tiny .env loader (no extra dependency). Existing environment variables win."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def idle_chat():
    while True:                                     # no chat feed configured: wait quietly (no fake viewers)
        await asyncio.sleep(3600)


async def amain():
    load_env()
    cfg = yaml.safe_load(open(os.getenv("HUBIE_CONFIG", "config.yaml")))
    mod = Moderator(cfg.get("chat_cooldown_per_user_sec", 20))
    server = OverlayServer(cfg.get("overlay_port", 8000))
    director = Director(cfg, Brain(cfg), TTS(cfg), server, mod)
    server.on_chat = lambda u, t: (mod.last_by_user.pop(u, None), director.on_chat(u, t))   # operator input: no cooldown, still moderated
    if cfg.get("game_mode", "demo") == "demo":      # self-hosted play-credit game (no external site, no bot check)
        player = DemoDice(cfg, director.on_game, server, director.on_game_and_wait, score=director.announce_score, quiet=director.quiet)
    else:                                           # play a real site's demo mode through Playwright
        player = GamePlayer(cfg, director.on_game)

    if cfg.get("platform") == "twitch":
        chat = lambda: twitch_reader(cfg["twitch_channel"], director.on_chat)
    elif int(cfg.get("kick_chatroom_id", 0) or 0) > 0:
        chat = lambda: kick_reader(cfg["kick_chatroom_id"], director.on_chat)
    else:
        server.simulated = bool(cfg.get("simulated_chat", False))      # real chat (Kick/Twitch) always wins over the simulation
        async def sim_audience():
            tasks = [demo_chat_reader(director.on_chat, director.brain, cfg.get("demo_chat_min_delay_sec", 8), cfg.get("demo_chat_max_delay_sec", 25), director.quiet)]
            if cfg.get("demo_chat_ambient", True):                       # extra background chatter so the room feels alive (still labelled simulated)
                tasks.append(demo_ambient_reader(director.on_ambient, cfg.get("demo_chat_ambient_min_sec", 5), cfg.get("demo_chat_ambient_max_sec", 9)))
            await asyncio.gather(*tasks)
        chat = sim_audience if server.simulated else idle_chat

    await asyncio.gather(
        supervise("overlay", server.start),
        supervise("director", director.run),
        supervise("chat", chat),
        supervise("player", player.run),
        heartbeat(director),
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    asyncio.run(amain())


if __name__ == "__main__":
    main()
