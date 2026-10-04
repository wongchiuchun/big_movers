"""ABIDES exchange matching, public tape, and seeded lightweight participants."""
from dataclasses import dataclass
from copy import deepcopy
import math
import numpy as np
from abides_core import Agent, Message
from abides_markets.agents import ExchangeAgent, TradingAgent
from abides_markets.order_book import OrderBook
from abides_markets.orders import Side, MarketOrder
from abides_markets.messages.order import MarketOrderMsg, CancelOrderMsg

SECOND = 1_000_000_000
SYMBOL = "SIM"


@dataclass
class TapeMsg(Message):
    timestamp: int
    price: int
    quantity: int


@dataclass
class DoneMsg(Message):
    order_id: int
    reason: str


@dataclass
class CommandMsg(Message):
    command: dict


class RecordedBook(OrderBook):
    def execute_order(self, order):
        opposite = self.asks if order.side.is_bid() else self.bids
        if opposite:
            passive = opposite[0].peek()[0]
            price = passive.limit_price
            if order.agent_id == 1:
                available = self.owner.allowed_quantity(order,price)
                order.quantity = min(order.quantity, max(0, int(available)))
                if order.quantity <= 0:
                    return None
            if passive.agent_id == 1:
                available = self.owner.allowed_quantity(passive,price)
                if passive.quantity > available:
                    self.cancel_order(deepcopy(passive))
                    return self.execute_order(order)
        matched = super().execute_order(order)
        if matched is not None:
            q, price = int(matched.quantity), int(matched.fill_price)
            for agent_id, side in ((order.agent_id, order.side), (matched.agent_id, matched.side)):
                if agent_id == 1:
                    sign = 1 if side.is_bid() else -1
                    self.owner.broker_cash -= sign * q * price
                    self.owner.broker_shares += sign * q
                    record=self.owner.records[order.order_id if agent_id==order.agent_id else matched.order_id]
                    if record["role"] in {"entry","add"}:
                        self.owner.broker_lots.append({"price":price,"quantity":q})
                    else:
                        left=q
                        while left and self.owner.broker_lots:
                            lot=self.owner.broker_lots[0]
                            taken=min(left,lot["quantity"])
                            left-=taken
                            lot["quantity"]-=taken
                            if not lot["quantity"]:
                                self.owner.broker_lots.pop(0)
            self.owner.send_message(1, TapeMsg(int(self.owner.current_time), price, q))
        return matched


class LabExchange(ExchangeAgent):
    def __init__(self, opening, closing, cash, seed):
        super().__init__(0, opening, closing, [SYMBOL], name="Lab exchange",
                         random_state=np.random.RandomState(seed), book_logging=False,
                         pipeline_delay=0, computation_delay=1, log_orders=False)
        self.order_books[SYMBOL] = RecordedBook(self, SYMBOL)
        self.broker_cash, self.broker_shares = cash, 0
        self.records={}
        self.broker_lots=[]
        self.log_events = self.log_to_file = False
        self.enabled = True

    def allowed_quantity(self,order,price):
        record=self.records.get(order.order_id)
        if not record:
            return 0
        sign=1 if record["direction"]=="long" else -1
        if record["role"]=="exit":
            return max(0,sign*self.broker_shares)
        if sign*self.broker_shares<0:
            return 0
        restricted=2*sum(l["price"]*l["quantity"] for l in self.broker_lots) if sign==-1 else 0
        return max(0,(self.broker_cash-restricted)//max(1,price))

    def receive_message(self, current_time, sender_id, message):
        if not self.enabled and sender_id != 1:
            return
        super().receive_message(current_time, sender_id, message)
        if isinstance(message, MarketOrderMsg):
            self.send_message(sender_id, DoneMsg(message.order.order_id, "market remainder expired"))
        elif isinstance(message, CancelOrderMsg):
            self.send_message(sender_id, DoneMsg(message.order.order_id, "cancel settled"))

    def kernel_terminating(self):
        pass


class Clock(Agent):
    def __init__(self, id):
        super().__init__(id, log_events=False)
        self.target = None

    def wakeup(self, current_time):
        super().wakeup(current_time)
        if self.target is not None and current_time >= self.target:
            self.target = None
            return {"clock": int(current_time)}
        return None


class Fundamental:
    """Hidden seeded background state; never returned in live responses."""
    OPTIONS = {"regime": ("trend_up", "trend_down", "range", "reversal"),
               "volatility": ("low", "normal", "high"),
               "liquidity": ("deep", "normal", "thin")}

    def __init__(self, seed, selections=None, duration=23400):
        selections = selections or {}
        self.selections = {}
        for key, choices in self.OPTIONS.items():
            value = selections.get(key) or "random"
            if value not in ("random", *choices):
                raise ValueError(f"Invalid {key}; choose random or {', '.join(choices)}.")
            self.selections[key] = value
        rng = np.random.RandomState(seed)
        self.base = int(rng.choice([2500, 5000, 7500, 10000]))
        chosen = {key: str(rng.choice(choices)) if self.selections[key] == "random" else self.selections[key]
                  for key, choices in self.OPTIONS.items()}
        self.regime = chosen["regime"]
        self.volatility = chosen["volatility"]
        self.liquidity_mode = chosen["liquidity"]
        lo, hi = {"low": (.00008, .00014), "normal": (.00014, .00030),
                  "high": (.00030, .00052)}[self.volatility]
        self.volatility_rate = float(rng.uniform(lo, hi))
        self.vol = self.base * self.volatility_rate  # cents per square-root second
        self.drift = self.base * float(rng.uniform(.000005, .000009))
        self.liquidity = {"deep": 500, "normal": 120, "thin": 60}[self.liquidity_mode]
        self.duration = duration
        self.reversal_sign = int(rng.choice([-1, 1]))
        self.rng = np.random.RandomState(seed ^ 0x51A7)
        self.last_second, self.value = 0, float(self.base)

    def bias(self, seconds):
        if self.regime == "trend_up":
            return self.drift
        if self.regime == "trend_down":
            return -self.drift
        if self.regime == "reversal":
            return -self.reversal_sign * self.drift * math.tanh((seconds-self.duration*.45)/600)
        return (self.base-self.value)*.001  # range: pull back toward the opening anchor

    def get_daily_open_price(self, symbol, time):
        return self.base

    def price(self, seconds):
        end = int(seconds)
        while self.last_second < end:
            t = self.last_second
            intraday = 1.0 + 0.8 * math.exp(-t / 1800) + 0.3 * max(0, (t - 21000) / 2400)
            drift = self.bias(t) + self.base * .000005 * math.sin(t / 1100)
            self.value = max(500, self.value + drift + self.rng.normal(0, self.vol * intraday))
            self.last_second += 1
        return int(round(self.value))


class Participant(TradingAgent):
    def __init__(self, id, opening, closing, fundamental, seed, maker=False):
        super().__init__(id, starting_cash=10**12, random_state=np.random.RandomState(seed),
                         log_orders=False, name=f"{'Maker' if maker else 'Trader'} {id}")
        self.log_events = self.log_to_file = False
        self.opening, self.closing, self.fundamental = opening, closing, fundamental
        self.maker, self.enabled = maker, True

    def get_wake_frequency(self):
        return SECOND

    def wakeup(self, current_time):
        super().wakeup(current_time)
        if not self.enabled or current_time >= self.closing:
            return None
        if current_time < self.opening + SECOND:
            return None
        if self.exchange_id is not None:
            value = self.fundamental.price((current_time - self.opening) / SECOND)
            if self.maker:
                for order in list(self.orders.values()):
                    self.cancel_order(order)
                offset = int(self.random_state.randint(-3, 4))
                spread = int(self.random_state.randint(1, 5))
                for depth in range(3):
                    qty = int(self.fundamental.liquidity * self.random_state.uniform(.6, 1.5))
                    self.place_limit_order(SYMBOL, qty, Side.BID, max(1, value+offset-spread-depth*3))
                    self.place_limit_order(SYMBOL, qty, Side.ASK, value+offset+spread+depth*3)
                interval = self.random_state.uniform(3, 6)
            else:
                for order in list(self.orders.values()):
                    if not isinstance(order, MarketOrder):
                        self.cancel_order(order)
                bias = self.fundamental.bias((current_time-self.opening)/SECOND)
                buy_probability = min(.65, max(.35, .5 + bias/self.fundamental.base*10000))
                side = Side.BID if self.random_state.rand() < buy_probability else Side.ASK
                qty = int(self.random_state.randint(10, self.fundamental.liquidity + 30))
                if self.random_state.rand() < .75:
                    self.place_market_order(SYMBOL, qty, side)
                else:
                    self.place_limit_order(SYMBOL, qty, side, max(1, value + int(self.random_state.normal(0, 8))))
                interval = self.random_state.uniform(2, 12)
            self.set_wakeup(current_time + int(interval * SECOND))
        return None

    def receive_message(self, current_time, sender_id, message):
        if isinstance(message, DoneMsg):
            self.orders.pop(message.order_id, None)
            return
        super().receive_message(current_time, sender_id, message)
