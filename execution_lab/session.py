"""Authoritative simulation session and durable completed reviews."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import uuid
import numpy as np
from abides_core import Kernel
from abides_core.message import Message
from abides_markets.orders import Order
from .session_calendar import schedule
from .market import LabExchange, Clock, Fundamental, Participant, CommandMsg, SECOND, SYMBOL
from .broker import Human, cents, integer, TERMINAL

DATA_DIR = Path(__file__).resolve().parent / "data"
ENGINE_REVISION = "f9cbe51342b7dedd9587e4e069040d68a5c6477f"
RULES = ("Synthetic, uncalibrated stock · long-only cash · whole shares · $0.01 grid · zero fees. "
         "ABIDES single-venue matching; no auctions, halts, margin, shorting or settlement rules. "
         "Stops use executed trades and can slip. Targets are planning markers, not exit orders. "
         "Market remainders expire; entry fills are capped to actual cash. Pause orders run on resume.")


class Session:
    def __init__(self, body):
        self.schedule = schedule(body.get("date") or None)
        self.seed = integer(body["seed"], "seed", 2**32-1) if body.get("seed") not in (None, "") else secrets.randbelow(2**32-1)+1
        cash = cents(body.get("cash", 100000), "starting cash")
        self.id = uuid.uuid4().hex
        self.revision, self.ended, self.failed = 0, False, False
        self.bars, self.curve, self.commands = {}, [], []
        self.opening, self.closing = self.schedule["open_ns"], self.schedule["close_ns"]
        self.fundamental = Fundamental(self.seed)
        # Reset upstream global IDs for reproducibility across repeated sessions.
        Order._order_id_counter = 0
        Message._Message__message_id_counter = 1
        self.human = Human(cash, self.seed ^ 13, self.record_print)
        self.exchange = LabExchange(self.opening, self.closing, cash, self.seed ^ 7)
        self.clock = Clock(2)
        self.background = [Participant(i, self.opening, self.closing, self.fundamental,
                                      (self.seed+i*101) % (2**32), maker=i < 6)
                           for i in range(3, 14)]
        agents = [self.exchange, self.human, self.clock, *self.background]
        self.kernel = Kernel(agents, start_time=self.opening, stop_time=self.closing+SECOND,
                             default_computation_delay=1, default_latency=1_000_000,
                             random_state=np.random.RandomState(self.seed), skip_log=True,
                             custom_properties={"oracle": self.fundamental})
        self.kernel.initialize()
        self.advance(60)  # One observed minute supplies context; history starts at open.

    @property
    def now(self):
        return int(self.kernel.current_time)

    def record_print(self, message):
        minute = int(message.timestamp // (60*SECOND) * 60)
        p = message.price/100
        bar = self.bars.get(minute)
        if bar is None:
            self.bars[minute] = {"time": minute, "open": p, "high": p, "low": p,
                                 "close": p, "volume": int(message.quantity)}
        else:
            bar["high"], bar["low"] = max(bar["high"],p), min(bar["low"],p)
            bar["close"], bar["volume"] = p, bar["volume"]+int(message.quantity)

    def run_until(self, target):
        self.clock.target = int(target)
        self.kernel.set_wakeup(self.clock.id, int(target))
        self.kernel.runner()

    def sample_equity(self):
        account = self.human.account()
        if account["equity"] is not None:
            row = {"time": int(self.now//SECOND), "value": account["equity"]}
            if self.curve and self.curve[-1]["time"] == row["time"]:
                self.curve[-1] = row
            else:
                self.curve.append(row)

    def advance(self, seconds):
        if self.ended:
            raise ValueError("Session has ended. Start a new session.")
        n = integer(seconds, "advance seconds", 60)
        target = min(self.closing, self.now+n*SECOND)
        self.run_until(target)
        self.revision += 1
        self.sample_equity()
        if self.now >= self.closing:
            self.finish("regular session close")

    def command(self, action, body):
        if self.ended or self.failed:
            raise ValueError("Session is not accepting trading commands.")
        book = self.exchange.order_books[SYMBOL]
        ask = book.get_l1_ask_data()
        if action == "entry":
            command = self.human.prepare_entry(body, self.now, ask[0] if ask else None)
        elif action == "exit":
            command = self.human.prepare_exit(body)
        elif action == "cancel":
            command = self.human.prepare_cancel(body)
        elif action == "stop":
            command = self.human.prepare_stop(body)
        else:
            raise ValueError("Unsupported trading action.")
        self.kernel.send_message(1, 1, CommandMsg(command))
        self.revision += 1

    def state(self):
        book = self.exchange.order_books[SYMBOL]
        bid, ask = book.get_l1_bid_data(), book.get_l1_ask_data()
        return {"session_id": self.id, "revision": self.revision, "ended": self.ended,
                "failed": self.failed, "time": int(self.now//SECOND),
                "session_date": self.schedule["date"], "open_time": int(self.opening//SECOND),
                "close_time": int(self.closing//SECOND), "hours": f'{self.schedule["open_label"]}–{self.schedule["close_label"]} ET',
                "symbol": "SIM · Synthetic", "rules": RULES,
                "last": self.human.last/100 if self.human.last is not None else None,
                "lod": self.human.lod/100 if self.human.lod is not None else None,
                "bid": bid[0]/100 if bid else None, "ask": ask[0]/100 if ask else None,
                "bid_size": bid[1] if bid else 0, "ask_size": ask[1] if ask else 0,
                "bars": list(self.bars.values()), "account": self.human.account(),
                "orders": [{k: deepcopy(v) for k,v in r.items() if k != "plan"}
                           for r in self.human.records.values()],
                "plan": deepcopy(self.human.active_trade["plan"]) if self.human.active_trade else None,
                "fills": deepcopy(self.human.fills[-100:]),
                "events": deepcopy(self.human.events[-40:]),
                "review_id": self.id if self.ended else None}

    def finish(self, reason="ended by learner"):
        if self.ended:
            return
        self.human.finishing = True
        self.human.event("session_finished", reason=reason, stop_cancelled=self.human.stop)
        self.exchange.enabled = False
        for agent in self.background:
            agent.enabled = False
        # Settle already queued human requests and confirmations in a bounded
        # interval with no fresh background orders. No synthetic liquidation.
        for record in self.human.active():
            if record["type"] == "limit":
                self.human._cancel(record["id"])
        self.run_until(min(self.now + SECOND//10, self.closing+SECOND//2))
        for record in self.human.active():
            record["status"], record["terminal_reason"] = "expired", "session ended"
        self.human.orders.clear()
        if self.human.active_trade:
            self.human.active_trade["status"] = "open at finish" if self.human.shares else (
                "closed" if self.human.active_trade["entry_quantity"] else "unfilled")
        self.human.stop, self.human.exit_intent = None, None
        self.ended = True
        self.revision += 1
        self.sample_equity()
        peak, drawdown = self.human.starting_cash/100, 0
        for item in self.curve:
            peak = max(peak,item["value"])
            drawdown = max(drawdown,peak-item["value"])
        review = {"id": self.id, "saved_at": datetime.now(timezone.utc).isoformat(),
                  "reason": reason, "seed": self.seed, "engine_revision": ENGINE_REVISION,
                  "configuration": {"date": self.schedule["date"], "cash": self.human.starting_cash/100,
                                    "profile": {"initial_price": self.fundamental.base/100,
                                                "volatility": self.fundamental.vol,
                                                "drift": self.fundamental.drift,
                                                "liquidity": self.fundamental.liquidity,
                                                "regime": self.fundamental.regime}},
                  "state": self.state(), "trades": self.human.review_trades(),
                  "commands": deepcopy(self.commands), "events": deepcopy(self.human.events),
                  "equity_curve": deepcopy(self.curve), "sampled_max_drawdown": drawdown,
                  "notes": "Drawdown sampled at advance boundaries. MFE/MAE are observed trade P&L excursions in dollars, including realized partial exits; no outcome-based trade grade."}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        target = DATA_DIR / f"{self.id}.json"
        temporary = target.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as f:
            json.dump(review, f, allow_nan=False)
        os.replace(temporary,target)
