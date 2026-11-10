"""Input filter (chat -> LLM) and output filter (LLM -> speech). Keeps the 15 'stays safe' points."""
import re, time

LINK = re.compile(r"(https?://|www\.|\b\w+\.(com|gg|io|net|xyz|ru|tv|me)\b)", re.I)
SCAM = re.compile(r"(promo ?code|free (money|crypto|bonus)|dm me|telegram|whatsapp|cashapp|send (btc|eth|usdt)|"
                  r"guaranteed|sure ?win|giveaway link|click (here|link)|deposit (now|bonus))", re.I)
JAILBREAK = re.compile(r"(ignore (all |your |previous )|system prompt|you are now|new instructions|"
                       r"pretend (to be|you)|developer mode|jailbreak)", re.I)
BAD_WORDS = re.compile(r"\b(nigg\w*|fag\w*|retard\w*|kys|kill yourself|suicide|cp\b|rape)\b", re.I)

# Things Hubie must never SAY
OUT_BLOCK = re.compile(r"(guarantee\w*|sure ?win|can't lose|cannot lose|you will win|i promise.*win|"
                       r"deposit|promo ?code|bonus code|real money|https?://|www\.|financial advice)", re.I)
SAFE_FALLBACK = "Remember, this is demo play only, no real money. 18 plus, and gamble responsibly."


class Moderator:
    def __init__(self, cooldown_sec: int = 20):
        self.cooldown = cooldown_sec
        self.last_by_user: dict[str, float] = {}
        self.banned: set[str] = set()

    def check_chat(self, user: str, text: str):
        """Return cleaned text or None if the message must be ignored."""
        text = " ".join(text.split())[:200]
        if not text or user.lower() in self.banned:
            return None
        if BAD_WORDS.search(text):
            self.banned.add(user.lower())
            return None
        if LINK.search(text) or SCAM.search(text) or JAILBREAK.search(text):
            return None
        now = time.time()
        if now - self.last_by_user.get(user, 0) < self.cooldown:
            return None
        self.last_by_user[user] = now
        if len(self.last_by_user) > 5000:
            self.last_by_user.clear()
        return text

    def check_output(self, text: str) -> str:
        text = text.replace("*", "").replace("#", "").strip()
        if not text or OUT_BLOCK.search(text) or BAD_WORDS.search(text):
            return SAFE_FALLBACK
        return text[:300]
