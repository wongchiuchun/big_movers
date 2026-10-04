"""Human account, order intentions, fixed protective stops and trade records."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math
import numpy as np
from abides_markets.agents import TradingAgent
from abides_markets.orders import Side, MarketOrder
from .market import SYMBOL, TapeMsg, DoneMsg, CommandMsg

TERMINAL = {"filled", "cancelled", "expired"}


def cents(value, label="price", allow_zero=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (number == 0 and not allow_zero) or number > Decimal("100000000"):
            raise ValueError(f"{label} must be a {'nonnegative' if allow_zero else 'positive'} finite number.")
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
        self.stop, self.last, self.lod, self.hod = None, None, None, None
        self.stop_levels = []
        self.stop_counter = 0
        self.exit_remaining = None
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

    @property
    def direction(self):
        if self.active_trade:
            return 1 if self.active_trade["plan"].get("direction","long") == "long" else -1
        return -1 if self.shares < 0 else 1

    def entries(self):
        return [r for r in self.active() if r["role"] in {"entry","add"}]

    def exits(self):
        return [r for r in self.active() if r["role"] == "exit"]

    def available_cash(self):
        restricted = 2*sum(l["price"]*l["quantity"] for l in self.lots) if self.shares < 0 else 0
        return max(0,self.cash-restricted-self.reserved_cash())

    def active(self, side=None):
        return [r for r in self.records.values() if r["status"] not in TERMINAL
                and (side is None or r["side"] == side)]

    def reserved_cash(self):
        return sum((r["quantity"] - r["filled"]) * r["estimate"] for r in self.entries())

    def reserved_shares(self):
        return sum(r["quantity"] - r["filled"] for r in self.exits())

    def size(self, body, entry, stop, estimate):
        mode = body.get("size_mode","risk")
        value = body.get("size_value",body.get("budget",100))
        if mode == "shares":
            requested = integer(value,"shares")
        elif mode == "dollars":
            requested = cents(value,"notional")//entry
        elif mode == "risk":
            requested = cents(value,"risk budget")//max(1,abs(entry-stop))
        else:
            raise ValueError("Size using shares, dollars or risk.")
        cap = self.available_cash()//max(1,estimate)
        if mode != "risk" and requested > cap:
            raise ValueError("Requested size exceeds available buying power/collateral.")
        quantity = min(requested,cap,1_000_000)
        if quantity < 1:
            raise ValueError("Size or buying power is too small for one share.")
        return int(quantity),mode,quantity<requested

    def event(self, kind, **values):
        item = {"time": int(self.current_time // 1_000_000_000), "kind": kind, **values}
        self.events.append(item)
        if self.active_trade:
            self.active_trade["events"].append(deepcopy(item))

    def prepare_entry(self, body, time, ask):
        if self.shares or self.active() or self.exit_intent:
            raise ValueError("Close the current trade first, or use Add for the same direction.")
        kind = body.get("order_type", "market")
        if kind not in {"market", "limit"}:
            raise ValueError("Use a market or limit entry.")
        if self.lod is None:
            raise ValueError("Wait for the first executed trade before planning against LOD.")
        entry = cents(body.get("entry"), "planned entry")
        stop = cents(body.get("stop"), "stop")
        target = cents(body["target"],"target") if body.get("target") not in (None,"") else None
        direction = body.get("direction","long")
        if direction not in {"long","short"}:
            raise ValueError("Direction must be long or short.")
        sign = 1 if direction == "long" else -1
        budget = cents(body.get("budget",100), "risk budget")
        buffer = cents(body.get("buffer", .01), "Stop buffer", allow_zero=True)
        if sign*(entry-stop) <= 0 or (target is not None and sign*(target-entry) <= 0):
            raise ValueError("Long: stop below entry and target above. Short: stop above entry and target below.")
        preference = float(body.get("minimum_r", 2))
        if not math.isfinite(preference) or not 0 < preference <= 100:
            raise ValueError("Preferred minimum R must be between 0 and 100.")
        estimate = max(entry, ask or entry) if kind == "market" else entry
        quantity,mode,capped = self.size(body,entry,stop,estimate)
        plan = {"time": int(time // 1_000_000_000), "observed_lod": self.lod,
                "observed_hod":self.hod,"direction":direction,"size_mode":mode,
                "buffer": buffer, "entry": entry, "stop": stop, "target": target,
                "budget": budget, "preferred_minimum_r": preference,
                "planned_rr": sign*(target-entry)/abs(entry-stop) if target is not None else None,
                "quantity": int(quantity),"cash_capped": capped,
                "planned_risk": int(quantity*abs(entry-stop)),
                "rationale": str(body.get("rationale", ""))[:1000]}
        trade = {"id": len(self.trades)+1, "plan": plan, "status": "pending",
                 "entry_quantity": 0, "entry_value": 0, "initial_risk": 0,
                 "invalid_risk": False, "realized": 0, "exit_quantity": 0,
                 "events": [], "fills": [], "mfe": 0, "mae": 0, "stop_edits": [],
                 "original_quantity":0,"add_plans":[]}
        self.trades.append(trade)
        self.active_trade, self.stop = trade, stop
        self.stop_levels=[]
        self.add_level(stop,100,initial=True,strategy=body.get("stop_strategy","manual"),
                       parameter=body.get("stop_parameter",0),period=body.get("ema_period",10))
        return self.make_record("buy" if sign==1 else "sell",kind,quantity,estimate,
                                plan=deepcopy(plan),role="entry")

    def prepare_add(self,body,time,reference):
        if not self.shares or self.entries() or self.exits() or self.exit_intent:
            raise ValueError("Wait for working orders to settle before adding to the open position.")
        kind=body.get("order_type","market")
        if kind not in {"market","limit"}:
            raise ValueError("Use market or limit.")
        entry=cents(body.get("entry"),"add price")
        if self.stop is None or self.direction*(entry-self.stop)<=0:
            raise ValueError("Add price must be on the protected side of the current stop.")
        estimate=max(entry,reference or entry) if kind=="market" else entry
        qty,mode,capped=self.size(body,entry,self.stop,estimate)
        plan={"time":int(time//1_000_000_000),"entry":entry,"stop":self.stop,"quantity":qty,
              "size_mode":mode,"cash_capped":capped,"direction":"long" if self.direction==1 else "short"}
        self.active_trade["add_plans"].append(deepcopy(plan))
        return self.make_record("buy" if self.direction==1 else "sell",kind,qty,estimate,plan=plan,role="add")

    def make_record(self, side, kind, quantity, estimate, plan=None, protective=False,role="exit"):
        oid = 1_000_000_000 + len(self.records)
        record = {"id": oid, "side": side, "type": kind, "quantity": quantity,
                  "filled": 0, "status": "queued", "estimate": int(estimate),
                  "limit": int(estimate) if kind == "limit" else None,
                  "plan": plan, "protective": protective,
                  "role":role,"direction":"long" if self.direction==1 else "short",
                  "trade_id": self.active_trade["id"] if self.active_trade else None}
        self.records[oid] = record
        return {"action": "submit", "order_id": oid}

    def prepare_exit(self, body):
        if self.exit_intent:
            raise ValueError("An exit is already protecting/flattening the position.")
        if body.get("all") is True:
            if not self.shares and not self.entries():
                raise ValueError("No position or working entry to close.")
            return {"action": "flatten"}
        if self.entries():
            raise ValueError("Cancel the remaining entry first, or use Close all.")
        qty = integer(body.get("quantity"), "exit shares")
        if qty > abs(self.shares)-self.reserved_shares():
            raise ValueError("Exit exceeds unreserved shares.")
        kind = body.get("order_type", "market")
        if kind not in {"market", "limit"}:
            raise ValueError("Use market or limit for an exit.")
        estimate = cents(body.get("price"), "exit limit") if kind == "limit" else (self.last or 1)
        return self.make_record("sell" if self.direction==1 else "buy",kind,qty,estimate)

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
        mode=body.get("mode","replace")
        if mode not in {"replace","add","edit"}:
            raise ValueError("Choose replace, add or edit stop.")
        percent=integer(body.get("percent",100),"stop percent",100)
        level_id=body.get("stop_id")
        if mode=="edit" and not any(s["id"]==level_id and not s["fired"] for s in self.stop_levels):
            raise ValueError("Stop is no longer editable.")
        return {"action":"stop","price":cents(body.get("price"),"new stop"),"mode":mode,
                "percent":percent,"stop_id":level_id,"strategy":body.get("strategy","manual"),
                "parameter":body.get("parameter",0),"period":body.get("ema_period",10)}

    def prepare_delete_stop(self,body):
        level=next((s for s in self.stop_levels if s["id"]==body.get("stop_id")),None)
        if not level or level["initial"] or level["fired"]:
            raise ValueError("Only an unfired additional stop can be deleted.")
        return {"action":"delete_stop","stop_id":level["id"]}

    def add_level(self,price,percent,initial=False,strategy="manual",parameter=0,period=10):
        self.stop_counter+=1
        level={"id":self.stop_counter,"price":int(price),"percent":int(percent),"initial":initial,
               "fired":False,"strategy":strategy,"parameter":parameter,"period":period}
        self.stop_levels.append(level)
        return level

    def stop_hit(self,price,stop):
        return self.direction*(price-stop)<=0

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
            self.exit_remaining = None
            self.event("flatten_requested")
            self._protect()
        elif action == "stop":
            if self.active_trade and self.shares and not self.exit_intent:
                mode=command["mode"]
                if mode=="add":
                    old=None
                    level=self.add_level(command["price"],command["percent"],strategy=command["strategy"],
                                         parameter=command["parameter"],period=command["period"])
                else:
                    level=next((s for s in self.stop_levels if (s["initial"] if mode=="replace" else s["id"]==command["stop_id"]) and not s["fired"]),None)
                    if level is None:
                        return
                    old=level["price"]
                    level.update(price=command["price"],percent=100 if level["initial"] else command["percent"],
                                 strategy=command["strategy"],parameter=command["parameter"],period=command["period"])
                if level["initial"]:
                    self.stop=level["price"]
                edit = {"time": int(self.current_time//1_000_000_000), "old": old,
                        "new":level["price"],"shares":abs(self.shares),"stop_id":level["id"],
                        "percent":level["percent"],"widened":old is not None and self.direction*(level["price"]-old)<0}
                self.active_trade["stop_edits"].append(edit)
                self.event("stop_changed", **{k:v for k,v in edit.items() if k != "time"})
                if self.last is not None:
                    self.check_stops(self.last)
        elif action == "delete_stop":
            self.stop_levels=[s for s in self.stop_levels if s["id"]!=command["stop_id"]]
            self.event("stop_deleted",stop_id=command["stop_id"])

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
        self.exit_intent, self.exit_remaining = "stop", None
        self.event("stop_triggered", trigger_price=price, stop=self.stop)
        self._protect()

    def check_stops(self,price):
        if self.finishing or not self.shares:
            return
        hit=sorted([s for s in self.stop_levels if not s["fired"] and self.stop_hit(price,s["price"])],
                   key=lambda s:-self.direction*s["price"])
        for level in hit:
            level["fired"]=True
            full=level["percent"]==100
            qty=abs(self.shares) if full else min(abs(self.shares),self.active_trade["original_quantity"]*level["percent"]//100)
            self.event("stop_triggered",trigger_price=price,stop=level["price"],stop_id=level["id"],percent=level["percent"],quantity=qty)
            if full:
                self.exit_intent,self.exit_remaining="stop",None
            elif qty and not (self.exit_intent and self.exit_remaining is None):
                self.exit_remaining=min(abs(self.shares),(self.exit_remaining or 0)+qty)
                self.exit_intent="partial stop"
        if hit:
            self._protect()

    def _protect(self):
        if self.finishing or not self.exit_intent:
            return
        for r in self.active():
            if not r["protective"] and r["status"] != "cancel_pending":
                self._cancel(r["id"])
        # Await sell cancel/fill confirmations; concurrent exits must not short.
        if self.exits():
            return
        quantity=abs(self.shares) if self.exit_remaining is None else min(abs(self.shares),self.exit_remaining)
        if quantity > 0:
            command = self.make_record("sell" if self.direction==1 else "buy", "market",quantity,
                                       self.last or 1, protective=True)
            self.dispatch(command)
        else:
            if self.exit_remaining==0 and not self.entries():
                self.exit_intent,self.exit_remaining=None,None
            self._close_if_flat()

    def _close_if_flat(self):
        if self.shares or self.active():
            return
        if self.active_trade:
            self.active_trade["status"] = "closed" if self.active_trade["entry_quantity"] else "unfilled"
        self.active_trade, self.stop, self.exit_intent = None, None, None
        self.stop_levels=[]
        self.exit_remaining=None

    def receive_message(self, current_time, sender_id, message):
        if isinstance(message, CommandMsg):
            self.current_time = current_time
            self.dispatch(message.command)
            return
        if isinstance(message, TapeMsg):
            self.current_time = current_time
            self.last = message.price
            self.lod = message.price if self.lod is None else min(self.lod, message.price)
            self.hod = message.price if self.hod is None else max(self.hod,message.price)
            self.on_print(message)
            if self.active_trade and self.shares:
                t = self.active_trade
                floating = self.direction*sum((message.price-lot["price"])*lot["quantity"] for lot in self.lots)
                excursion = t["realized"] + floating
                t["mfe"], t["mae"] = max(t["mfe"], excursion), min(t["mae"], excursion)
            self.check_stops(message.price)
            if self.exit_intent:
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
                "protective": r["protective"],"role":r["role"],"direction":r["direction"]}
        self.fills.append(fill)
        t["fills"].append(deepcopy(fill))
        sign=1 if r["direction"]=="long" else -1
        if r["role"] in {"entry","add"}:
            t["status"] = "open"
            t["entry_quantity"] += q
            t["entry_value"] += q * price
            if r["role"]=="entry":
                t["original_quantity"]+=q
            risk = sign*(price-t["plan"]["stop"])
            if risk <= 0:
                t["invalid_risk"] = True
                self.event("invalidated_on_arrival", order_id=r["id"], price=price)
            else:
                t["initial_risk"] += risk*q
            self.lots.append({"quantity": q, "price": price})
            if self.stop is not None and (self.stop_hit(price,self.stop) or (self.last is not None and self.stop_hit(self.last,self.stop))):
                self._trigger_stop(price)
            elif self.exit_intent:
                self._protect()
        else:
            left = q
            while left and self.lots:
                lot = self.lots[0]
                taken = min(left, lot["quantity"])
                t["realized"] += sign*taken*(price-lot["price"])
                lot["quantity"] -= taken
                left -= taken
                if lot["quantity"] == 0:
                    self.lots.pop(0)
            if left or sign*self.shares<0:
                raise RuntimeError("Account invariant violated; session halted.")
            t["exit_quantity"] += q
            if r["protective"] and self.exit_remaining is not None:
                self.exit_remaining=max(0,self.exit_remaining-q)
        self.event("fill", **{k:v for k,v in fill.items() if k != "time"})
        # Include the exit execution itself in excursions, even when it closes
        # the trade before its public-tape message arrives (e.g. stop slippage).
        excursion = t["realized"] + sign*sum((price-lot["price"])*lot["quantity"] for lot in self.lots)
        t["mfe"], t["mae"] = max(t["mfe"],excursion), min(t["mae"],excursion)
        self._close_if_flat()

    def account(self):
        cost = sum(l["price"]*l["quantity"] for l in self.lots)
        mark = self.last
        unrealized = None if mark is None and self.shares else self.direction*((mark or 0)*abs(self.shares)-cost)
        equity = None if unrealized is None else self.cash + (mark or 0)*self.shares
        return {"cash": self.cash/100, "reserved_cash": self.reserved_cash()/100,
                "buying_power":self.available_cash()/100,
                "shares": self.shares, "reserved_shares": self.reserved_shares(),
                "quantity":abs(self.shares),"direction":"short" if self.direction==-1 else "long",
                "average_entry": cost/abs(self.shares)/100 if self.shares else None,
                "realized": sum(t["realized"] for t in self.trades)/100,
                "unrealized": None if unrealized is None else unrealized/100,
                "equity": None if equity is None else equity/100,
                "stop": None if self.stop is None else self.stop/100,
                "remaining_risk": (sum(max(0,self.direction*(l["price"]-self.stop))*l["quantity"] for l in self.lots)/100
                                   if self.stop is not None else None),
                "exit_intent": self.exit_intent,
                "protection_waiting": bool(self.exit_intent and self.shares and not self.exits()),
                "short_collateral":cost/100 if self.shares<0 else 0,
                "restricted_proceeds":cost/100 if self.shares<0 else 0}

    def review_trades(self):
        result = []
        for t in self.trades:
            row = deepcopy(t)
            row["average_entry"] = t["entry_value"]/t["entry_quantity"] if t["entry_quantity"] else None
            valid = not t["invalid_risk"] and t["initial_risk"] > 0
            row["actual_initial_risk"] = t["initial_risk"] if valid else None
            row["realized_r"] = t["realized"]/t["initial_risk"] if valid else None
            sign=1 if t["plan"].get("direction","long")=="long" else -1
            row["actual_rr"] = (sign*(t["plan"]["target"]*t["entry_quantity"]-t["entry_value"])/t["initial_risk"]
                                if valid and t["plan"]["target"] is not None else None)
            row["slippage_per_share"] = (row["average_entry"]-t["plan"]["entry"]
                                          if row["average_entry"] is not None else None)
            result.append(row)
        return result
