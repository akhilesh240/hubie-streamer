"""LLM brain. Always returns something (canned fallback) so the stream never goes silent."""
import asyncio, logging, os, random
from collections import deque
from pathlib import Path

log = logging.getLogger("brain")

FALLBACKS = [
    "Another round, let's see what happens. Demo play only, no real money here.",
    "Chat, drop a hello! I read every message I can.",
    "Vibes are good tonight. Remember, 18 plus, and gamble responsibly.",
    "Okay okay, the animations in this game are so satisfying.",
    "If you're up at this hour with me, you're officially part of the night crew.",
]

IDLE_TOPICS = [
    "Tell a short, clean joke about being a sloth who surfs.",
    "Share one fun, harmless fact (science, space, animals or the ocean) and react to it.",
    "Ask chat an easy question (favourite snack, 3am playlist, best surf spot) and invite answers.",
    "Do a calm 3am check-in: tell night-owl viewers they're welcome and say what you're up to.",
    "Tell a tiny two-sentence story about a day at the beach, in your sloth style.",
    "Offer a gentle 'go with the flow' thought of the moment.",
    "Remind chat they can say hi and you'll answer by name; keep it playful.",
    "Make a light observation about the screen or the waves around you.",
    "Do a quick would-you-rather for chat (clean and silly).",
]

PROMPTS = {
    "viewer": """You are simulating ONE friendly viewer in a live Housebets demo chat.
Write only one short, natural viewer message, 4 to 18 words. Do not include a username, prefix, quotation marks, system text, dice results, or moderation notes.
Choose a fresh topic or follow-up related to demo dice rules, targets, win chance, multipliers, play credits, the stream, Hubie, or a friendly reaction.
Avoid repeating questions from recent chat. This is demo play only, so never ask about deposits, bonuses, real-money betting, or links.""",
    "idle": "Nothing is happening. Say something fun and short to keep viewers company (a joke, a comment on the current game, or a question to chat).",
    "chat": 'Viewer {user} in chat said: "{text}"\nRead the actual message carefully. Start with {user}\'s exact name, then answer the specific question or react specifically to their comment. Do not give a generic welcome unless they are actually greeting you. Keep it to 1-2 short sentences.',
    "game": "Game event on screen: {text}\nReact specifically to the result. Mention the roll or outcome when useful, never promise wins, and keep it short.",
    "segment": "You are switching to a new demo segment: {text}\nIntroduce it with fresh energy and avoid repeating previous wording.",
    "disclaimer": "Give a quick, natural reminder: demo play only, no real money, 18 plus, gamble responsibly. Keep it fun.",
    "startup": "You just went live. Greet chat and say what you're doing today.",
    "roll": "A dice roll just finished and its score was already called out loud. Details: {text}\nAdd ONE short extra comment (1-2 sentences) that does NOT just repeat the score: explain what the win chance or multiplier means for this roll, react to a streak if there is one, or tease the next roll. Never promise wins, never talk about real money.",
}

ROLL_FALLBACKS = [
    "Remember, the win chance on screen is the true chance in this demo. A bigger multiplier always means a smaller chance.",
    "Every roll is random, so the last result tells us nothing about the next one.",
    "Over and Under just flip which side of the target wins. The win chance and multiplier follow from that.",
    "A lower win chance pays a higher multiplier. A higher chance pays less. That's the whole trade-off.",
    "Play credits only here, so it's all just for fun and for learning how the dice works.",
    "Chat, ask me anything about targets, win chance or multipliers, I'm happy to explain.",
]


def game_fallback(text: str) -> str:
    """Instant local reaction to a game event (no LLM wait), so it can never describe an older result."""
    t = (text or "").upper()
    if "RESET" in t:
        return "The demo balance hit zero, so it was topped up with fresh play credits. Same fun, no real money."
    if "WIN" in t:
        return random.choice(["That's a win! Play credits only, but still a nice one.",
                              "Winner! Demo play only, no real money here."])
    if "LOSS" in t:
        return random.choice(["No luck that round, but it's all play credits. On to the next one.",
                              "That one missed. Good thing it's just a demo."])
    return random.choice(FALLBACKS)

def chat_fallback(user: str, message: str) -> str:
    """Question-aware local replies when the LLM/API is unavailable."""
    t = message.lower().strip()
    name = user or "there"
    if any(x in t for x in ("multiplier", "multipl")):
        return f"{name}, the multiplier shows the potential return on a winning roll. Lower win chances usually come with a higher multiplier."
    if "win chance" in t or "chance" in t:
        return f"{name}, win chance is simply how likely your selected target is to hit. Higher chances usually mean a lower multiplier."
    if "demo" in t or "real money" in t:
        return f"Yep, {name}! This is a demo using play credits only, with no real money involved."
    if any(x in t for x in ("rule", "how to play", "how does this work")):
        return f"{name}, pick a target and make a roll. If the result lands on the winning side of your target, that round wins."
    if "under" in t or "over" in t or "target" in t or "slider" in t:
        return f"{name}, the target sets the winning range. A wider range gives a better win chance, while a tighter range can raise the multiplier."
    if "play credit" in t or "credits" in t:
        return f"{name}, play credits are just for this demo experience. They are not real money."
    if "adjust" in t or "change" in t:
        return f"{name}, yes, the target can be adjusted for the next round in this demo."
    if any(x in t for x in ("hello", "hi ", "hey", "good evening", "what's up")):
        return f"Hey {name}, good to see you! Glad you're hanging out with us tonight."
    if any(x in t for x in ("nice", "great", "love", "looks", "vibes")):
        return f"Thanks, {name}! Glad you're enjoying the stream. The water effects are doing their best to steal the show."
    return f"{name}, good question! I caught your message. This is a play-credit demo, and I’m happy to explain the dice setup as we go."


class Brain:
    def __init__(self, cfg: dict):
        self.provider = cfg.get("llm_provider", "deepseek")        # deepseek | anthropic
        self.model = cfg.get("llm_model", "deepseek-flash" if self.provider == "deepseek" else "claude-sonnet-5-5")
        self.ds_key = os.getenv("DEEPSEEK_API_KEY")
        self.system = Path(cfg.get("persona_file", "persona.md")).read_text()
        self.recent: deque[str] = deque(maxlen=8)
        self.client = None
        if self.provider == "anthropic":
            try:
                import anthropic
                self.client = anthropic.AsyncAnthropic()
            except Exception as e:  # missing key/package -> canned lines only
                log.warning("LLM disabled: %s", e)
        elif not self.ds_key:
            log.warning("DEEPSEEK_API_KEY missing -> canned lines only")

    async def _deepseek(self, prompt: str) -> str:
        import httpx
        body = {"model": self.model, "max_tokens": 120, "temperature": 1.0,
                "messages": [{"role": "system", "content": self.system},
                             {"role": "user", "content": prompt}],
                "thinking": {"type": "disabled"}}      # short spoken lines: no slow reasoning
        headers = {"Authorization": f"Bearer {self.ds_key}"}
        async with httpx.AsyncClient(timeout=25) as c:
            r = await c.post("https://api.deepseek.com/chat/completions", json=body, headers=headers)
            if r.status_code == 400 and "thinking" in r.text.lower():   # field not accepted -> retry without
                body.pop("thinking")
                r = await c.post("https://api.deepseek.com/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            return (r.json()["choices"][0]["message"].get("content") or "").strip()

    async def demo_viewer_message(self, recent_messages: list[str] | None = None) -> str:
        """Generate one natural simulated viewer message using the configured AI brain."""
        history = recent_messages[-10:] if recent_messages else []
        prompt = PROMPTS["viewer"]
        if history:
            prompt += "\n\nRecent viewer messages. Do not repeat these topics or wording:\n- " + "\n- ".join(history)
        text = ""
        try:
            if self.provider == "deepseek" and self.ds_key:
                text = await self._deepseek(prompt)
            elif self.provider == "anthropic" and self.client:
                r = await asyncio.wait_for(self.client.messages.create(
                    model=self.model, max_tokens=70, system=self.system,
                    messages=[{"role": "user", "content": prompt}]), timeout=20)
                text = r.content[0].text.strip()
        except Exception as e:
            log.warning("demo viewer generation failed: %s", e)
        text = " ".join((text or "").split()).strip(' "\'')
        return text[:180]

    async def say(self, kind: str, ctx: dict) -> str:
        prompt = PROMPTS.get(kind, PROMPTS["idle"]).format(user=ctx.get("user", ""), text=ctx.get("text", ""))
        if kind == "idle":   # rotate topics so the stream never loops, even without any game on screen
            prompt = "Nothing is happening. " + random.choice(IDLE_TOPICS)
        if self.recent:
            prompt += "\n\nYour last lines (do NOT repeat them):\n- " + "\n- ".join(self.recent)
        text = ""
        try:
            if self.provider == "anthropic" and self.client:
                r = await asyncio.wait_for(self.client.messages.create(
                    model=self.model, max_tokens=120, system=self.system,
                    messages=[{"role": "user", "content": prompt}]), timeout=20)
                text = r.content[0].text.strip()
            elif self.provider == "deepseek" and self.ds_key:
                text = await self._deepseek(prompt)
        except Exception as e:
            log.warning("LLM call failed (%s) -> fallback line", e)
        # Guard against generic LLM replies to actual viewer questions.
        # If the model returns a canned welcome, use the question-aware local answer instead.
        if kind == "chat" and text:
            low = text.lower()
            generic_markers = ("thanks for dropping", "welcome to the stream", "glad you are here", "reading you loud and clear")
            if any(marker in low for marker in generic_markers):
                text = ""
        if not text:
            u = ctx.get("user", "")
            if kind == "chat" and u:
                # Never use a generic welcome for a real question. This keeps the
                # demo chat useful even if DeepSeek is offline, out of credits, or slow.
                text = chat_fallback(u, str(ctx.get("text", "")))
            elif kind == "roll":
                text = random.choice([x for x in ROLL_FALLBACKS if x not in self.recent] or ROLL_FALLBACKS)
            else:
                text = random.choice(FALLBACKS)
        self.recent.append(text)
        return text
