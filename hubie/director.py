"""Central loop: decides what Hubie says next, speaks it, keeps the show alive.

Latency design (so chat replies come right after the chat message):
  * pipelined: the next line (LLM + TTS) is prepared WHILE the current line is being spoken
  * chat first: a waiting chat reply replaces a prepared game/idle line that has not started yet
  * fresh only: chat messages older than chat_stale_sec are skipped, and at most chat_backlog chats wait (newest kept)
  * every reply logs how long it took from the chat message to the start of speech
"""
import asyncio, heapq, itertools, logging, random, time

log = logging.getLogger("director")
P_DISCLAIMER, P_CHAT, P_GAME, P_IDLE = 0, 1, 2, 3
P_SCORE = 1                                                         # the score call is spoken the moment the die lands


def score_call(i: dict) -> str:
    """Short spoken call for the roll that is on screen right now (built from the same numbers the overlay shows)."""
    n, t, over, win, d, bal = i["roll"], i["target"], i["mode"] == "over", i["win"], abs(i["delta"]), i["balance"]
    side = f"{'Over' if over else 'Under'} {t}"
    if win:
        return random.choice([f"{n}! {side}, that's a win. Plus {d:g} credits.",
                              f"Rolled {n}. {side}, winner!",
                              f"{n}, nice one! That clears the target. Balance is {bal:g}."])
    return random.choice([f"{n}. Not {side.lower()}, no luck this round.",
                          f"Rolled {n}, that misses the target. Next roll is coming up.",
                          f"{n}... not this time. Minus {d:g} credits."])


class Director:
    def __init__(self, cfg, brain, tts, server, mod):
        self.cfg, self.brain, self.tts, self.server, self.mod = cfg, brain, tts, server, mod
        self.q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.ready: asyncio.Queue = asyncio.Queue(maxsize=1)      # one fully prepared line (text + audio)
        self.n = itertools.count()
        self.last_disclaimer = time.time()
        self.max_q = cfg.get("max_queue", 8)
        self.chat_stale = float(cfg.get("chat_stale_sec", 45))
        self.chat_backlog = int(cfg.get("chat_backlog", 4))
        self.spoken = 0
        self.speaking = False
        self.preparing_chat = False
        self.preparing = False
        self.round_waiting = False

    # ---------- queue helpers ----------
    def _pending(self):
        return [t for t in self.q._queue if t[3] in ("chat", "score")]

    def _chats_waiting(self):
        return [t for t in self.q._queue if t[3] == "chat"]

    def push(self, prio: int, kind: str, ctx: dict):
        if self.q.qsize() >= self.max_q and prio >= P_GAME:
            return  # drop low-priority events when busy
        if kind == "idle" and (self._chats_waiting() or self.preparing_chat or not self.ready.empty()):
            return                                                   # idle chatter never blocks real events
        # Every game result is kept. The stream must react to each roll, not only the latest one.
        if kind == "chat":
            waiting = self._chats_waiting()
            while len(waiting) >= self.chat_backlog:                 # keep only the newest chats
                oldest = min(waiting, key=lambda t: t[1])
                self.q._queue.remove(oldest); heapq.heapify(self.q._queue); waiting.remove(oldest)
            try:                                                     # only replace prepared idle chatter, never a game result
                item = self.ready.get_nowait()
                if item[0] != "idle":
                    self.ready.put_nowait(item)
            except asyncio.QueueEmpty:
                pass
        self.q.put_nowait((prio, next(self.n), time.time(), kind, ctx))

    async def quiet(self, max_wait: float = 10.0, for_round: bool = False):
        """Wait until Hubie is completely free (nothing queued, preparing or being spoken).
        The dice round waits with for_round=True and goes first; the simulated audience yields to a waiting round, so both get their turn."""
        if for_round:
            self.round_waiting = True
        t0 = time.time()
        try:
            while time.time() - t0 < max_wait:
                free = not self.speaking and not self.preparing and self.q.empty() and self.ready.empty()
                if free and (for_round or not self.round_waiting):
                    return
                await asyncio.sleep(0.3)
        finally:
            if for_round:
                self.round_waiting = False

    # ---------- callbacks for other components ----------
    def on_chat(self, user: str, text: str, defer_show: bool = False):
        clean = self.mod.check_chat(user, text)
        if clean:
            self.push(P_CHAT, "chat", {"user": user, "text": clean, "show": defer_show})
            if defer_show:
                return                                               # shown later, when Hubie starts replying to it
            try:
                asyncio.get_running_loop().create_task(
                    self.server.broadcast({"type": "chat", "user": user[:20], "text": clean[:90]}))
            except RuntimeError:
                pass
        else:
            # Keep the public chat feed clean: filtered content is counted, never displayed.
            try:
                asyncio.get_running_loop().create_task(self.server.broadcast({"type": "mod"}))
            except RuntimeError:
                pass

    def on_game(self, kind: str, text: str):
        self.push(P_GAME, kind, {"text": text})
        state = "excited" if "WIN" in text.upper() or kind == "segment" else "reacting"
        try:
            asyncio.get_running_loop().create_task(
                self.server.broadcast({"type": "avatar", "state": state, "event": kind}))
        except RuntimeError:
            pass

    async def make_score_audio(self, info: dict):
        """Pre-render the spoken score (text + audio) before the round starts, so TTS speed never delays the voice."""
        text = self.mod.check_output(score_call(info))
        return text, await self.tts.speak(text)

    def on_ambient(self, user: str, text: str):
        """Background viewer chatter (simulated audience only): moderated and shown at once, Hubie does not reply to each one."""
        clean = self.mod.check_chat(user, text)
        try:
            msg = {"type": "chat", "user": user[:20], "text": clean[:90]} if clean else {"type": "mod"}
            asyncio.get_running_loop().create_task(self.server.broadcast(msg))
        except RuntimeError:
            pass

    def queue_score(self, info: dict, not_before: float, pre=None):
        """Queue the spoken score synchronously (so no chat can slip in front of it); returns a future that resolves when it has been spoken."""
        done = asyncio.get_running_loop().create_future()
        self.push(P_SCORE, "score", {"info": info, "done": done, "not_before": not_before, "pre": pre})
        return done

    async def announce_score(self, info: dict, not_before: float, timeout: float = 20.0):
        done = self.queue_score(info, not_before)
        await self.wait_spoken(done, info, timeout)

    async def wait_spoken(self, done, info: dict, timeout: float = 20.0):
        try:
            await self.server.broadcast({"type": "avatar", "state": "excited" if info["win"] else "reacting", "event": "score"})
        except Exception:
            pass
        try:
            await asyncio.wait_for(done, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("score call timed out; continuing")

    async def on_game_and_wait(self, kind: str, text: str, timeout: float = 15.0):
        """Queue a result and wait until its spoken reaction finishes."""
        done = asyncio.get_running_loop().create_future()
        self.push(P_GAME, kind, {"text": text, "done": done})
        state = "excited" if "WIN" in text.upper() or kind == "segment" else "reacting"
        try:
            await self.server.broadcast({"type": "avatar", "state": state, "event": kind})
        except Exception:
            pass
        try:
            await asyncio.wait_for(done, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("game reaction timed out; continuing")

    # ---------- main loops ----------
    async def _next_event(self):
        idle_after = self.cfg.get("idle_after_sec", 12)
        while True:
            if time.time() - self.last_disclaimer > self.cfg.get("disclaimer_every_sec", 600):
                self.last_disclaimer = time.time()
                self.push(P_DISCLAIMER, "disclaimer", {})
            try:
                prio, _, ts, kind, ctx = await asyncio.wait_for(self.q.get(), timeout=idle_after)
            except asyncio.TimeoutError:
                if self.speaking or not self.ready.empty():
                    continue                                          # still busy: not idle yet
                return "idle", {}, time.time()
            age = time.time() - ts
            if kind == "score" and age > 12:
                d = ctx.get("done")
                if d is not None and not d.done():
                    d.set_result(True)
                continue                                              # a score nobody heard in time is not announced late
            if kind in ("game", "roll") and age > 25:
                continue                                              # stale game reaction
            if kind == "chat" and age > self.chat_stale:
                log.info("[skip] stale chat from %s (%.0fs old)", ctx.get("user"), age)
                continue
            return kind, ctx, ts

    async def _prepare(self):
        while True:
            kind, ctx, ts = await self._next_event()
            self.preparing_chat = kind == "chat"
            self.preparing = True
            try:
                if kind == "score" and ctx.get("pre"):
                    raw, audio = ctx["pre"]                                  # already rendered before the roll
                elif kind == "score":
                    raw = score_call(ctx["info"])                           # instant, always matches the visible roll
                elif kind == "game":
                    # Keep dice commentary tied to the exact visible roll. Network
                    # LLM latency here can make Hubie describe an older score.
                    from .brain import game_fallback
                    raw = game_fallback(str(ctx.get("text", "")))
                else:
                    raw = await self.brain.say(kind, ctx)
                text = self.mod.check_output(raw)
                if not (kind == "score" and ctx.get("pre")):
                    audio = await self.tts.speak(text)
            finally:
                self.preparing_chat = False
                self.preparing = False
            if kind == "idle" and self._chats_waiting():
                continue                                             # real events always beat idle chatter
            await self.ready.put((kind, ctx, text, audio, ts))

    async def _speak(self):
        while True:
            kind, ctx, text, audio, ts = await self.ready.get()
            self.speaking = True
            nb = ctx.get("not_before") if isinstance(ctx, dict) else None
            if nb:
                await asyncio.sleep(max(0.0, nb - time.time()))          # hold the score call until the die has landed
            if kind == "chat" and ctx.get("show"):
                try:                                                     # the viewer message appears exactly as Hubie starts answering it
                    await self.server.broadcast({"type": "chat", "user": ctx["user"][:20], "text": ctx["text"][:90]})
                except Exception:
                    pass
            try:
                await self.server.broadcast({"type": "avatar", "state": "talking", "event": kind})
            except Exception:
                pass
            log.info("[%s] %s", kind, text)
            if kind == "chat":
                log.info("[latency] chat from %s -> Hubie starts speaking after %.1fs", ctx.get("user"), time.time() - ts)
            try:
                await self.server.say(text, audio, kind)
            finally:
                done = ctx.get("done") if isinstance(ctx, dict) else None
                if done is not None and not done.done():
                    done.set_result(True)
                self.speaking = False
            try:
                await self.server.broadcast({"type": "avatar", "state": "idle", "event": kind})
            except Exception:
                pass
            self.spoken += 1

    async def run(self):
        self.push(P_CHAT, "startup", {})
        await asyncio.gather(self._prepare(), self._speak())
