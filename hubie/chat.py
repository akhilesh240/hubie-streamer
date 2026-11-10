"""Read-only chat readers. Hubie answers by voice, so no chat-write credentials are needed."""
import asyncio, json, logging, random, re
import websockets

log = logging.getLogger("chat")


async def twitch_reader(channel: str, on_chat):
    pat = re.compile(r"^:(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.*)$")
    async with websockets.connect("wss://irc-ws.chat.twitch.tv:443", ping_interval=None) as ws:
        await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
        await ws.send(f"JOIN #{channel.lower()}")
        log.info("twitch chat connected: %s", channel)
        async for raw in ws:
            for line in raw.split("\r\n"):
                if line.startswith("PING"):
                    await ws.send("PONG :tmi.twitch.tv")
                elif m := pat.match(line):
                    on_chat(m.group(1), m.group(2))


async def kick_reader(chatroom_id: int, on_chat):
    """Kick moved off its public Pusher feed (Oct 2026), so the old unofficial reader no longer connects.
    Reading Kick chat now needs the official Kick API (OAuth app + webhooks via a public tunnel).
    Until that is added, chat is disabled here: log once and idle, so the rest of Hubie keeps running."""
    log.warning("Kick chat feed unavailable (unofficial feed removed by Kick). Chat disabled; Hubie keeps talking.")
    while True:
        await asyncio.sleep(3600)

async def demo_chat_reader(on_chat, brain=None, min_delay=8, max_delay=16, quiet=None):
    """AI-driven simulated audience for demo streams.

    One of 30 viewer identities is selected for each turn. DeepSeek generates a
    fresh question/comment when available, with a safe local fallback if the AI
    is unavailable. Hubie's normal moderation and reply pipeline handles every
    generated message, so the chat feed contains only viewers and Hubie replies.
    """
    users = [
    "GamerRohit", "Aarav95", "PriyaK", "CryptoVibe", "Neha_S",
    "Lucky_07", "RdxOfficial", "RahulPlays", "AnanyaLive", "TradeKing",
    "SkyFan", "TechVibe", "RajGaming", "MayaStreams", "CryptoArjun",
    "NightOwl", "KingPlayz", "SanaLive", "GameMaster", "VibeCheck",
    "AlphaPlayer", "LuckyStar", "RohanGaming", "SimranX", "ProViewer",
    "CyberFan", "RockyLive", "DreamPlayer", "FastFingers", "LiveWatcher"
]
    fallback_topics = [
        "How does the multiplier work?",
        "Can you explain the rules?",
        "What does Under 70 mean?",
        "Can I change the target before the next roll?",
        "What are play credits used for?",
        "This stream setup looks great!",
        "Is there a simple way to understand win chance?",
        "Does a lower target change the multiplier?",
        "Hubie, what are you watching for on this round?",
        "That was a close one!",
        "Can you explain the target slider?",
        "How do you decide the win chance?",
        "Nice vibes in here tonight!",
        "Is this a demo stream?",
        "What happens when the roll is above the target?",
        "Can the target be adjusted between rounds?",
        "Hubie, how are you enjoying the stream?",
        "I like the water effects in the studio!",
        "What does Over 65 mean?",
        "Why is the multiplier higher on Under 35?",
        "Is Over 50 the same chance as Under 50?",
        "Does the last roll affect the next one?",
        "Which target has the best win chance?",
        "Hubie, which target would you pick next?",
        "Why does a bigger multiplier mean a lower chance?",
        "How is the multiplier worked out from the win chance?",
        "What does Under 45 need to win?",
        "Does a bigger bet change the win chance?",
        "Are the rolls random?",
        "Hubie, what is your favourite target?",
    ]
    recent_users, recent_messages = [], []
    # Give the stream a little breathing room before the first viewer appears.
    await asyncio.sleep(random.uniform(3, 6))
    while True:
        # Keep the same viewer from dominating the conversation.
        choices = [u for u in users if u not in recent_users[-4:]] or [u for u in users if u != recent_users[-1]] or users
        user = random.choice(choices)
        text = ""
        if brain:
            try:
                text = await asyncio.wait_for(brain.demo_viewer_message(recent_messages), timeout=6.0)
            except asyncio.TimeoutError:
                text = ""
        if not text:
            choices = [m for m in fallback_topics if m not in recent_messages[-8:]] or fallback_topics
            text = random.choice(choices)
        text = " ".join(text.split())[:180]
        # Keep the audience active. Do not wait for all voice commentary to finish;
        # the Director handles reply order and backpressure.
        if text:
            if quiet:
                await quiet(8)                                           # short pause so replies do not pile up, but chat never stalls
            on_chat(user, text, defer_show=True)                         # appears on screen exactly when Hubie starts replying
            recent_users.append(user)
            recent_messages.append(text)
            del recent_users[:-6]
            del recent_messages[:-12]
        # Keep enough activity on screen to make the 30-person demo audience feel alive.
        base_gap = random.uniform(min_delay, max_delay)
        if random.random() < 0.12:
            base_gap += random.uniform(6, 12)
        await asyncio.sleep(base_gap)


async def demo_ambient_reader(on_ambient, lo=5, hi=9):
    """Simulated background chatter (shown at once, Hubie does not answer each one). Only runs together with the labelled simulated audience."""
    users = ["GamerRohit", "Aarav95", "PriyaK", "CryptoVibe", "Neha_S", "Lucky_07", "RdxOfficial", "RahulPlays", "AnanyaLive",
             "TradeKing", "SkyFan", "TechVibe", "RajGaming", "MayaStreams", "NightOwl", "KingPlayz", "SanaLive", "VibeCheck"]
    lines = ["Let's go Hubie!", "Nice roll!", "So close!", "GG", "Good vibes tonight", "Another one!", "Hubie is on fire",
             "That was quick", "Love this stream", "Roll it again!", "Responsible gaming always", "Play credits only, nice demo",
             "Who else is up late?", "Studio looks amazing", "Hello from India!", "Big roll incoming", "This is fun to watch"]
    last = ""
    await asyncio.sleep(random.uniform(2, 4))
    while True:
        u, t = random.choice(users), random.choice([x for x in lines if x != last])
        last = t
        on_ambient(u, t)
        await asyncio.sleep(random.uniform(lo, hi))
