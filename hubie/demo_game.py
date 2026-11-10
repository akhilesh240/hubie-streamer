"""Self-hosted DEMO dice game. Play credits only (no real money, no wallet, no external site).
It runs inside Hubie, so there is no browser automation and no bot check involved.
Every round is pushed to the overlay (type "game") and reported to the director so Hubie can react."""
import asyncio, logging, random, time

log = logging.getLogger("demo")


class DemoDice:
    def __init__(self, cfg: dict, emit, server, wait_emit=None, score=None, quiet=None):
        self.cfg, self.emit, self.server, self.wait_emit = cfg, emit, server, wait_emit
        self.score, self.quiet = score, quiet
        d = cfg.get("demo_game", {}) or {}
        self.start_bal = float(d.get("start_credits", 1000))
        self.delay = float(d.get("round_delay_sec", 9))
        self.rounds = int(d.get("rounds_per_segment", 12))
        self.balance = self.start_bal
        self.land = float(d.get("score_voice_delay_sec", 1.6))         # seconds after the roll starts when the voice begins
        self.targets = [int(x) for x in d.get("targets", [35, 45, 50, 65, 70])]   # whole-number targets only (keeps the voice clean)
        self.roll_decimals = int(d.get("roll_decimals", 0))            # 0 = whole-number rolls (clean voice), 2 = rolls like 34.57
        self.comment_chance = float(d.get("commentary_chance", 0.7))   # chance Hubie adds extra commentary after a roll
        self.streak = 0                                                 # +n = n wins in a row, -n = n losses in a row
        self.plan = None
        self.n = 0
        self.segment = 0
        self.segment_styles = [
            "Chill rolls and rule talk", "Multiplier focus", "Target challenge",
            "Night-owl Q and A", "Quick reaction round"
        ]

    def _pick_roll(self, target):
        """Fair roll, so the win chance shown on screen is the true chance.
        Whole-number mode: one of 0..100 except the target itself, so Over T wins on 100-T numbers and Under T on T numbers
        (exactly the stated chance, and the voice only ever says a whole number)."""
        if self.roll_decimals <= 0:
            return random.choice([n for n in range(0, 101) if n != target])
        scale = 10 ** self.roll_decimals
        return random.randint(0, 100 * scale - 1) / scale

    def _plan(self):
        """Decide the next roll in advance (nothing is applied yet) and start rendering its spoken score right away."""
        bet = min(float(random.choice([5, 10, 20, 25, 50])), self.balance)
        mode = random.choice(["over", "under"])
        target = random.choice(self.targets)
        chance = (100 - target) if mode == "over" else target          # % chance to win
        mult = round(99 / chance, 4)                                    # real Housebets dice: 99 / win chance (1% edge)
        roll = self._pick_roll(target)
        win = roll > target if mode == "over" else roll < target
        delta = round(bet * (mult - 1), 2) if win else -bet
        plan = {"bet": bet, "mode": mode, "target": target, "mult": mult, "roll": roll, "win": win, "delta": delta,
                "balance": round(self.balance + delta, 2)}
        plan["audio"] = None
        make = getattr(getattr(self.score, "__self__", None), "make_score_audio", None)
        if make:
            plan["audio"] = asyncio.ensure_future(make({k: plan[k] for k in ("roll", "mode", "target", "win", "delta", "balance")}))
        return plan

    async def _round(self):
        if self.plan is None:
            self.plan = self._plan()
        if self.quiet:
            await self.quiet(60, for_round=True)                         # start the roll only when Hubie is free, so the voice lands with the die
        p, self.plan = self.plan, None
        self.balance = p["balance"]
        self.n += 1
        ev = {"type": "game", "game": "Demo Dice", "round": self.n, "bet": p["bet"], "mode": p["mode"], "target": p["target"],
              "mult": p["mult"], "roll": p["roll"], "win": p["win"], "delta": p["delta"], "balance": self.balance}
        info = {k: p[k] for k in ("roll", "mode", "target", "win", "delta", "balance")}
        t_land = time.time() + self.land                                # the voice starts as the die settles
        owner = getattr(self.score, "__self__", None)
        pre = None
        if p["audio"] is not None:
            try:
                pre = await asyncio.wait_for(p["audio"], timeout=4)     # normally already finished long ago
            except Exception:
                pre = None
        spoken = owner.queue_score(info, t_land, pre) if owner else None   # queued BEFORE the broadcast: nothing can slip in front of it
        await self.server.broadcast(ev)
        if spoken is not None:
            await owner.wait_spoken(spoken, info)
        else:
            await asyncio.sleep(1.9)
            line = (f"Demo Dice round {self.n}: bet {p['bet']:g} play credits on roll {p['mode']} {p['target']} "
                    f"(pays x{p['mult']}). Rolled {p['roll']}: {'WIN' if p['win'] else 'LOSS'}, balance is now {self.balance:g} play credits.")
            if self.wait_emit:
                await self.wait_emit("game", line)
            else:
                self.emit("game", line)
        self.streak = (max(self.streak, 0) + 1) if p["win"] else (min(self.streak, 0) - 1)
        if spoken is not None and random.random() < self.comment_chance:
            chance = (100 - p["target"]) if p["mode"] == "over" else p["target"]
            note = f" Streak: {abs(self.streak)} {'wins' if self.streak > 0 else 'losses'} in a row." if abs(self.streak) >= 2 else ""
            self.emit("roll", f"Round {self.n}: bet {p['bet']:g} play credits on Roll {p['mode']} {p['target']} "
                              f"({chance:g} percent win chance, pays x{p['mult']:.2f}). Rolled {p['roll']}: "
                              f"{'WIN' if p['win'] else 'LOSS'}. Balance {self.balance:g}.{note}")   # extra commentary, spoken when Hubie has a free moment
        if self.balance < 1:
            self.balance = self.start_bal
            self.emit("game", f"Demo balance hit zero, so it was reset to {self.start_bal:g} free play credits.")
        self.plan = self._plan()                                        # pre-render the next score while this one settles

    async def run(self):
        while True:
            self.segment += 1
            style = self.segment_styles[(self.segment - 1) % len(self.segment_styles)]
            self.emit("segment", f"Demo Dice segment {self.segment}: {style}. Play credits only, no real money")
            for _ in range(self.rounds):
                await self._round()
                await asyncio.sleep(self.delay)
