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
                available = (self.owner.broker_cash // max(1, price)
                             if order.side.is_bid() else self.owner.broker_shares)
                order.quantity = min(order.quantity, max(0, int(available)))
                if order.quantity <= 0:
                    return None
            if passive.agent_id == 1:
                available = (self.owner.broker_cash // max(1, price)
                             if passive.side.is_bid() else self.owner.broker_shares)
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
            self.owner.send_message(1, TapeMsg(int(self.owner.current_time), price, q))
        return matched


class LabExchange(ExchangeAgent):
    def __init__(self, opening, closing, cash, seed):
        super().__init__(0, opening, closing, [SYMBOL], name="Lab exchange",
                         random_state=np.random.RandomState(seed), book_logging=False,
                         pipeline_delay=0, computation_delay=1, log_orders=False)
        self.order_books[SYMBOL] = RecordedBook(self, SYMBOL)
        self.broker_cash, self.broker_shares = cash, 0
        self.log_events = self.log_to_file = False
        self.enabled = True

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
    def __init__(self, seed):
        rng = np.random.RandomState(seed)
        self.base = int(rng.choice([2500, 5000, 7500, 10000]))
        self.vol = float(rng.uniform(0.7, 2.6))
        self.drift = float(rng.uniform(-0.035, 0.045))
        self.liquidity = int(rng.choice([60, 120, 250, 500]))
        self.regime = int(rng.choice([-1, 0, 1]))
        self.rng = np.random.RandomState(seed ^ 0x51A7)
        self.last_second, self.value = 0, float(self.base)

    def get_daily_open_price(self, symbol, time):
        return self.base

    def price(self, seconds):
        end = int(seconds)
        while self.last_second < end:
            t = self.last_second
            intraday = 1.0 + 0.8 * math.exp(-t / 1800) + 0.3 * max(0, (t - 21000) / 2400)
            drift = self.drift + self.regime * .025 * math.sin(t / 1100)
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
                side = Side.BID if self.random_state.rand() > .5 - self.fundamental.drift * 2 else Side.ASK
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
