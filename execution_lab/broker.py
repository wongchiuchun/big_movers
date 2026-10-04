"""Human account, order intentions, fixed protective stops and trade records."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math
import numpy as np
from abides_markets.agents import TradingAgent
from abides_markets.orders import Side, MarketOrder
from .market import SYMBOL, TapeMsg, DoneMsg, CommandMsg

TERMINAL = {"filled", "cancelled", "expired"}


def cents(value, label="price"):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > Decimal("100000000"):
            raise ValueError(f"{label} must be a positive finite number.")
        scaled = number * 100
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{label} must use whole cents.")
        return int(scaled)
    except (InvalidOperation, TypeError):
        raise ValueError(f"Invalid {label}.") from None


def integer(value, label, maximum=1_000_000):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n != n.to_integral_value() or not 1 <= n <= maximum:
            raise ValueError(f"{label} must be a whole number from 1 to {maximum}.")
        return int(n)
    except InvalidOperation:
        raise ValueError(f"Invalid {label}.") from None


class Human(TradingAgent):
    def __init__(self, cash, seed, on_print):
        super().__init__(1, starting_cash=cash, random_state=np.random.RandomState(seed),
                         name="You", log_orders=False)
        self.log_events = self.log_to_file = False
        self.records, self.trades, self.events, self.fills = {}, [], [], []
        self.lots = []
        self.active_trade = None
        self.stop, self.last, self.lod = None, None, None
        self.exit_intent = None
        self.on_print = on_print
        self.finishing = False

    def get_wake_frequency(self):
        return 1_000_000_000

    def wakeup(self, current_time):
        super().wakeup(current_time)
        return None  # Only the clock agent may interrupt Kernel.runner().

    @property
    def shares(self):
        return int(self.holdings.get(SYMBOL, 0))

    @property
    def cash(self):
        return int(self.holdings["CASH"])

    def active(self, side=None):
        return [r for r in self.records.values() if r["status"] not in TERMINAL
                and (side is None or r["side"] == side)]

    def reserved_cash(self):
        return sum((r["quantity"] - r["filled"]) * r["estimate"] for r in self.active("buy"))

    def reserved_shares(self):
        return sum(r["quantity"] - r["filled"] for r in self.active("sell"))

    def event(self, kind, **values):
        item = {"time": int(self.current_time // 1_000_000_000), "kind": kind, **values}
        self.events.append(item)
        if self.active_trade:
            self.active_trade["events"].append(deepcopy(item))

    def prepare_entry(self, body, time, ask):
        if self.shares or self.active() or self.exit_intent:
            raise ValueError("Finish the current position and working entry before a new entry. Scale-ins are disabled.")
        kind = body.get("order_type", "market")
        if kind not in {"market", "limit"}:
            raise ValueError("Use a market or limit entry.")
        if self.lod is None:
            raise ValueError("Wait for the first executed trade before planning against LOD.")
        entry = cents(body.get("entry"), "planned entry")
        stop = cents(body.get("stop"), "stop")
        target = cents(body.get("target"), "target")
        budget = cents(body.get("budget"), "risk budget")
        buffer = cents(body.get("buffer", .01), "LOD buffer")
        if not stop < entry < target:
            raise ValueError("Plan requires stop < entry < target.")
        preference = float(body.get("minimum_r", 2))
        if not math.isfinite(preference) or not 0 < preference <= 100:
            raise ValueError("Preferred minimum R must be between 0 and 100.")
        available = self.cash - self.reserved_cash()
        estimate = max(entry, ask or entry) if kind == "market" else entry
        sized = budget // (entry - stop)
        quantity = min(sized, available // estimate, 1_000_000)
        if quantity < 1:
            raise ValueError("Risk budget or available cash is too small for one share.")
        plan = {"time": int(time // 1_000_000_000), "observed_lod": self.lod,
                "buffer": buffer, "entry": entry, "stop": stop, "target": target,
                "budget": budget, "preferred_minimum_r": preference,
                "planned_rr": (target-entry)/(entry-stop), "quantity": int(quantity),
                "cash_capped": quantity < sized, "planned_risk": int(quantity*(entry-stop)),
                "rationale": str(body.get("rationale", ""))[:1000]}
        trade = {"id": len(self.trades)+1, "plan": plan, "status": "pending",
                 "entry_quantity": 0, "entry_value": 0, "initial_risk": 0,
                 "invalid_risk": False, "realized": 0, "exit_quantity": 0,
                 "events": [], "fills": [], "mfe": 0, "mae": 0, "stop_edits": []}
        self.trades.append(trade)
        self.active_trade, self.stop = trade, stop
        return self.make_record("buy", kind, int(quantity), estimate, plan=deepcopy(plan))

    def make_record(self, side, kind, quantity, estimate, plan=None, protective=False):
        oid = 1_000_000_000 + len(self.records)
        record = {"id": oid, "side": side, "type": kind, "quantity": quantity,
                  "filled": 0, "status": "queued", "estimate": int(estimate),
                  "limit": int(estimate) if kind == "limit" else None,
                  "plan": plan, "protective": protective,
                  "trade_id": self.active_trade["id"] if self.active_trade else None}
        self.records[oid] = record
        return {"action": "submit", "order_id": oid}

    def prepare_exit(self, body):
        if self.exit_intent:
            raise ValueError("An exit is already protecting/flattening the position.")
        if body.get("all") is True:
            if not self.shares and not self.active("buy"):
                raise ValueError("No position or working entry to close.")
            return {"action": "flatten"}
        if self.active("buy"):
            raise ValueError("Cancel the remaining entry first, or use Close all.")
        qty = integer(body.get("quantity"), "exit shares")
        if qty > self.shares-self.reserved_shares():
            raise ValueError("Exit exceeds unreserved shares.")
        kind = body.get("order_type", "market")
        if kind not in {"market", "limit"}:
            raise ValueError("Use market or limit for an exit.")
        estimate = cents(body.get("price"), "exit limit") if kind == "limit" else (self.last or 1)
        return self.make_record("sell", kind, qty, estimate)

    def prepare_cancel(self, body):
        oid = integer(body.get("order_id"), "order ID", 2_000_000_000)
        record = self.records.get(oid)
        if record is None or record["status"] in TERMINAL:
            raise ValueError("Order is no longer working.")
        if record["type"] == "market" and record["status"] != "queued":
            raise ValueError("A dispatched market order cannot be canceled.")
        record["status"] = "cancel_pending"
        return {"action": "cancel", "order_id": oid}

    def prepare_stop(self, body):
        if not self.shares or not self.active_trade or self.exit_intent:
            raise ValueError("A stop can be changed only for an open, non-exiting position.")
        return {"action": "stop", "price": cents(body.get("price"), "new stop")}

    def dispatch(self, command):
        action = command["action"]
        if action == "submit":
            r = self.records[command["order_id"]]
            if r["status"] in TERMINAL:
                return
            # A cancellation queued before resuming wins over an undispatched order.
            if r["status"] == "cancel_pending":
                r["status"] = "cancelled"
                self._close_if_flat()
                return
            r["status"] = "submitted"
            side = Side.BID if r["side"] == "buy" else Side.ASK
            if r["type"] == "limit":
                self.place_limit_order(SYMBOL, r["quantity"], side, r["limit"], order_id=r["id"])
            else:
                self.place_market_order(SYMBOL, r["quantity"], side, order_id=r["id"])
            self.event("submitted", order_id=r["id"], side=r["side"], quantity=r["quantity"])
        elif action == "cancel":
            self._cancel(command["order_id"])
        elif action == "flatten":
            self.exit_intent = "manual close"
            self.event("flatten_requested")
            self._protect()
        elif action == "stop":
            if self.active_trade and self.shares and not self.exit_intent:
                old, self.stop = self.stop, command["price"]
                edit = {"time": int(self.current_time//1_000_000_000), "old": old,
                        "new": self.stop, "shares": self.shares, "widened": self.stop < old}
                self.active_trade["stop_edits"].append(edit)
                self.event("stop_changed", **{k:v for k,v in edit.items() if k != "time"})
                if self.last is not None and self.last <= self.stop:
                    self._trigger_stop(self.last)

    def _cancel(self, oid):
        r = self.records.get(oid)
        if not r or r["status"] in TERMINAL:
            return
        order = self.orders.get(oid)
        if order is None:
            r["status"] = "cancelled"
            self._close_if_flat()
        elif not isinstance(order, MarketOrder):
            r["status"] = "cancel_pending"
            self.cancel_order(order)

    def _trigger_stop(self, price):
        if not self.exit_intent:
            self.exit_intent = "stop"
            self.event("stop_triggered", trigger_price=price, stop=self.stop)
        self._protect()

    def _protect(self):
        if self.finishing or not self.exit_intent:
            return
        for r in self.active():
            if not r["protective"] and r["status"] != "cancel_pending":
                self._cancel(r["id"])
        # Await sell cancel/fill confirmations; concurrent exits must not short.
        if self.active("sell"):
            return
        if self.shares > 0:
            command = self.make_record("sell", "market", self.shares,
                                       self.last or 1, protective=True)
            self.dispatch(command)
        else:
            self._close_if_flat()

    def _close_if_flat(self):
        if self.shares or self.active():
            return
        if self.active_trade:
            self.active_trade["status"] = "closed" if self.active_trade["entry_quantity"] else "unfilled"
        self.active_trade, self.stop, self.exit_intent = None, None, None

    def receive_message(self, current_time, sender_id, message):
        if isinstance(message, CommandMsg):
            self.current_time = current_time
            self.dispatch(message.command)
            return
        if isinstance(message, TapeMsg):
            self.current_time = current_time
            self.last = message.price
            self.lod = message.price if self.lod is None else min(self.lod, message.price)
            self.on_print(message)
            if self.active_trade and self.shares:
                t = self.active_trade
                floating = sum((message.price-lot["price"])*lot["quantity"] for lot in self.lots)
                excursion = t["realized"] + floating
                t["mfe"], t["mae"] = max(t["mfe"], excursion), min(t["mae"], excursion)
            if self.shares and self.stop is not None and message.price <= self.stop:
                self._trigger_stop(message.price)
            elif self.exit_intent:
                self._protect()
            return
        if isinstance(message, DoneMsg):
            self.current_time = current_time
            self.orders.pop(message.order_id, None)
            r = self.records.get(message.order_id)
            if r and r["status"] not in TERMINAL:
                r["status"] = "filled" if r["filled"] >= r["quantity"] else (
                    "cancelled" if message.reason == "cancel settled" else "expired")
                r["terminal_reason"] = message.reason
                self.event("order_terminal", order_id=r["id"], status=r["status"], unfilled=r["quantity"]-r["filled"])
            # Do not immediately retry an unfilled protective market order: wait
            # for fresh liquidity on another print to avoid infinite queue loops.
            if r and not r["protective"]:
                self._protect()
            self._close_if_flat()
            return
        super().receive_message(current_time, sender_id, message)

    def order_accepted(self, order):
        super().order_accepted(order)
        r = self.records.get(order.order_id)
        if r and r["status"] != "cancel_pending":
            r["status"] = "partial" if r["filled"] else "working"

    def order_cancelled(self, order):
        super().order_cancelled(order)
        r = self.records.get(order.order_id)
        if r:
            r["status"] = "cancelled"
            self.event("cancel_confirmed", order_id=r["id"])
        self._protect()
        self._close_if_flat()

    def order_executed(self, order):
        super().order_executed(order)
        r = self.records.get(order.order_id)
        if not r:
            raise RuntimeError("Unknown human execution; account stopped.")
        q, price = int(order.quantity), int(order.fill_price)
        r["filled"] += q
        r["status"] = "filled" if r["filled"] >= r["quantity"] else (
            "cancel_pending" if r["status"] == "cancel_pending" else "partial")
        t = next(t for t in self.trades if t["id"] == r["trade_id"])
        fill = {"time": int(self.current_time//1_000_000_000), "order_id": r["id"],
                "side": r["side"], "quantity": q, "price": price,
                "protective": r["protective"]}
        self.fills.append(fill)
        t["fills"].append(deepcopy(fill))
        if r["side"] == "buy":
            t["status"] = "open"
            t["entry_quantity"] += q
            t["entry_value"] += q * price
            risk = price-t["plan"]["stop"]
            if risk <= 0:
                t["invalid_risk"] = True
                self.event("invalidated_on_arrival", order_id=r["id"], price=price)
            else:
                t["initial_risk"] += risk*q
            self.lots.append({"quantity": q, "price": price})
            if self.stop is not None and (price <= self.stop or (self.last is not None and self.last <= self.stop)):
                self._trigger_stop(price)
            elif self.exit_intent:
                self._protect()
        else:
            left = q
            while left and self.lots:
                lot = self.lots[0]
                taken = min(left, lot["quantity"])
                t["realized"] += taken*(price-lot["price"])
                lot["quantity"] -= taken
                left -= taken
                if lot["quantity"] == 0:
                    self.lots.pop(0)
            if left or self.shares < 0 or self.cash < 0:
                raise RuntimeError("Account invariant violated; session halted.")
            t["exit_quantity"] += q
        self.event("fill", **{k:v for k,v in fill.items() if k != "time"})
        # Include the exit execution itself in excursions, even when it closes
        # the trade before its public-tape message arrives (e.g. stop slippage).
        excursion = t["realized"] + sum((price-lot["price"])*lot["quantity"] for lot in self.lots)
        t["mfe"], t["mae"] = max(t["mfe"],excursion), min(t["mae"],excursion)
        self._close_if_flat()

    def account(self):
        cost = sum(l["price"]*l["quantity"] for l in self.lots)
        mark = self.last
        unrealized = None if mark is None and self.shares else ((mark or 0)*self.shares-cost)
        equity = None if unrealized is None else self.cash + (mark or 0)*self.shares
        return {"cash": self.cash/100, "reserved_cash": self.reserved_cash()/100,
                "buying_power": max(0,self.cash-self.reserved_cash())/100,
                "shares": self.shares, "reserved_shares": self.reserved_shares(),
                "average_entry": cost/self.shares/100 if self.shares else None,
                "realized": sum(t["realized"] for t in self.trades)/100,
                "unrealized": None if unrealized is None else unrealized/100,
                "equity": None if equity is None else equity/100,
                "stop": None if self.stop is None else self.stop/100,
                "remaining_risk": (sum(max(0,l["price"]-self.stop)*l["quantity"] for l in self.lots)/100
                                   if self.stop is not None else None),
                "exit_intent": self.exit_intent,
                "protection_waiting": bool(self.exit_intent and self.shares and not self.active("sell"))}

    def review_trades(self):
        result = []
        for t in self.trades:
            row = deepcopy(t)
            row["average_entry"] = t["entry_value"]/t["entry_quantity"] if t["entry_quantity"] else None
            valid = not t["invalid_risk"] and t["initial_risk"] > 0
            row["actual_initial_risk"] = t["initial_risk"] if valid else None
            row["realized_r"] = t["realized"]/t["initial_risk"] if valid else None
            row["actual_rr"] = ((t["plan"]["target"]*t["entry_quantity"]-t["entry_value"])/t["initial_risk"]
                                if valid else None)
            row["slippage_per_share"] = (row["average_entry"]-t["plan"]["entry"]
                                          if row["average_entry"] is not None else None)
            result.append(row)
        return result
