"""Focused essentials; deliberately not the full deferred verification suite."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB / "vendor"))
sys.path.insert(0,str(LAB.parent))
from execution_lab import session as session_module
from execution_lab.session import Session
from execution_lab.broker import Human, TERMINAL
from execution_lab.session_calendar import schedule
from execution_lab.market import Fundamental


class EssentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.object(session_module,"DATA_DIR",Path(self.directory.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def new_session(self):
        return Session({"seed":17,"date":"2026-10-02","cash":100000})

    def entry(self,session):
        state=session.state()
        entry=state["ask"]
        stop=round(state["lod"]-.05,2)
        if stop>=entry:
            stop=round(entry-.05,2)
        return {"entry":entry,"stop":stop,"target":round(entry+3*(entry-stop),2),
                "budget":10,"buffer":.05,"order_type":"market","rationale":"essential test", "immediate":False}

    def test_direct_short_entry_and_cover_without_playback(self):
        session=self.new_session()
        state=session.state()
        session.command("entry",{"direction":"short","entry":state["bid"],
            "stop":round(max(b["high"] for b in state["bars"])+.1,2),
            "size_mode":"shares","size_value":20,"order_type":"market"})
        self.assertEqual(session.human.shares,-20)
        self.assertEqual(session.human.active_trade["plan"]["direction"],"short")
        self.assertIsNone(session.human.active_trade["plan"]["planned_rr"])
        session.command("exit",{"quantity":10})
        self.assertEqual(session.human.shares,-10)
        session.command("exit",{"all":True})
        self.assertEqual(session.human.shares,0)
        self.assertEqual(session.human.cash,session.exchange.broker_cash)

    def test_add_and_partial_stop_keep_initial_risk_reference(self):
        session=self.new_session()
        body=self.entry(session)
        body.update(immediate=True,size_mode="shares",size_value=20)
        session.command("entry",body)
        self.assertEqual(session.human.shares,20)
        initial_stop=session.human.active_trade["plan"]["stop"]
        session.command("add",{"entry":session.state()["ask"],"order_type":"market",
                               "size_mode":"shares","size_value":10})
        self.assertEqual(session.human.shares,30)
        session.command("stop",{"mode":"add","percent":50,"price":round(session.state()["last"]+1,2)})
        self.assertEqual(session.human.shares,20,"50% stop uses original 20 shares, not the 30 after adding")
        self.assertEqual(session.human.active_trade["plan"]["stop"],initial_stop)
        self.assertEqual(session.human.cash,session.exchange.broker_cash)
        session.command("exit",{"all":True})
        self.assertEqual(session.human.shares,0)

    def test_direct_limit_can_rest_and_cancel(self):
        session=self.new_session()
        entry=round(session.state()["lod"]-1,2)
        session.command("entry",{"direction":"long","order_type":"limit", "entry":entry,
            "stop":round(entry-.2,2),"size_mode":"dollars","size_value":500})
        record=list(session.human.records.values())[-1]
        self.assertEqual(record["status"],"working")
        self.assertEqual(session.human.shares,0)
        session.command("cancel",{"order_id":record["id"]})
        self.assertEqual(record["status"],"cancelled")

    def test_short_collateral_and_direct_hod_stop(self):
        session=self.new_session()
        state=session.state()
        body={"direction":"short","order_type":"market","entry":state["bid"],
              "size_mode":"shares","size_value":1_000_000,"stop_strategy":"lod",
              "stop_parameter":0,"buffer":0}
        with self.assertRaisesRegex(ValueError,"buying power/collateral"):
            session.command("entry",body)
        self.assertFalse(session.human.records)
        body["size_value"]=20
        session.command("entry",body)
        self.assertEqual(session.human.shares,-20)
        self.assertEqual(session.human.stop,round(state["hod"]*100))
        initial_risk=session.human.active_trade["initial_risk"]
        self.assertGreater(initial_risk,0)
        with self.assertRaises(ValueError):
            session.command("exit",{"quantity":21})
        session.command("stop",{"price":round(session.state()["last"]-1,2)})
        self.assertEqual(session.human.shares,0)
        self.assertEqual(session.human.trades[-1]["initial_risk"],initial_risk)
        self.assertTrue(any(f["protective"] and f["side"]=="buy" for f in session.human.fills))
        self.assertEqual(session.human.cash,session.exchange.broker_cash)

    def test_calendar_early_close_and_weekend(self):
        self.assertEqual(schedule("2026-11-27")["close_label"],"13:00")
        with self.assertRaises(ValueError):
            schedule("2026-10-04")

    def test_regime_random_defaults_and_reproducibility(self):
        default=Fundamental(17)
        blank=Fundamental(17,{"regime":"","volatility":None,"liquidity":""})
        explicit=Fundamental(17,{key:"random" for key in Fundamental.OPTIONS})
        self.assertEqual(default.selections,{key:"random" for key in Fundamental.OPTIONS})
        self.assertEqual(default.price(60),blank.price(60))
        self.assertEqual(default.price(60),explicit.price(60))
        with self.assertRaises(ValueError):
            Fundamental(17,{"regime":"invalid"})
        session=self.new_session()
        self.assertEqual(session.state()["selections"],default.selections)
        self.assertNotIn("profile",session.state())
        session.finish()
        review=json.loads((Path(self.directory.name)/f"{session.id}.json").read_text())
        self.assertEqual(review["configuration"]["selections"],default.selections)
        self.assertEqual(review["configuration"]["profile"]["regime"],default.regime)

    def test_selected_regimes_and_volatility_scaling(self):
        for regime in Fundamental.OPTIONS["regime"]:
            market=Fundamental(17,{"regime":regime,"volatility":"low","liquidity":"thin"},duration=3600)
            self.assertEqual(market.regime,regime)
            self.assertEqual(market.liquidity,60)
            self.assertAlmostEqual(market.vol/market.base,market.volatility_rate)
            if regime=="trend_up":self.assertGreater(market.bias(0),0)
            if regime=="trend_down":self.assertLess(market.bias(0),0)
            if regime=="reversal":self.assertLess(market.bias(0)*market.bias(3600),0)
            if regime=="range":
                market.value=market.base+100
                self.assertLess(market.bias(0),0)
                market.value=market.base-100
                self.assertGreater(market.bias(0),0)
        high=Fundamental(17,{"volatility":"high","liquidity":"deep"})
        low=Fundamental(17,{"volatility":"low"})
        self.assertGreater(high.volatility_rate,low.volatility_rate)
        self.assertEqual(high.liquidity,500)

    def test_risk_sizing_example_and_invalid_plan(self):
        human=Human(10_000_000,17,lambda p:None)
        human.lod=4960
        cmd=human.prepare_entry({"entry":50,"stop":49.55,"target":51.35,
                                 "budget":100,"buffer":.05},0,5000)
        record=human.records[cmd["order_id"]]
        self.assertEqual(record["quantity"],222)
        self.assertAlmostEqual(record["plan"]["planned_rr"],3)
        other=Human(10_000_000,18,lambda p:None)
        other.lod=4960
        with self.assertRaises(ValueError):
            other.prepare_entry({"entry":50,"stop":50,"target":51,"budget":100},0,5000)

    def test_real_session_has_prints_and_hides_profile(self):
        session=self.new_session()
        state=session.state()
        self.assertEqual(state["time"]-state["open_time"],60)
        self.assertTrue(state["bars"])
        self.assertIsNotNone(state["lod"])
        self.assertNotIn("seed",state)
        self.assertNotIn("profile",state)
        self.assertEqual(state["lod"],min(b["low"] for b in state["bars"]))

    def test_actual_market_fill_stop_exit_and_saved_review(self):
        session=self.new_session()
        body=self.entry(session)
        session.command("entry",body)
        self.assertEqual(session.human.shares,0,"Paused submission must not fill")
        session.advance(1)
        self.assertGreater(session.human.shares,0)
        self.assertEqual(session.human.stop,round(body["stop"]*100))
        initial_risk=session.human.active_trade["initial_risk"]
        self.assertGreater(initial_risk,0)
        session.advance(1)
        self.assertEqual(session.human.stop,round(body["stop"]*100),"LOD updates must not widen the stop")
        session.command("stop",{"price":round(session.state()["last"]+1,2)})
        session.advance(1)
        self.assertEqual(session.human.shares,0,"Stop replacement above price must exit on resume")
        self.assertEqual(session.human.trades[0]["initial_risk"],initial_risk)
        self.assertTrue(any(f["protective"] for f in session.human.fills))
        self.assertEqual(session.human.cash,session.exchange.broker_cash)
        self.assertEqual(session.human.shares,session.exchange.broker_shares)
        session.finish()
        review=json.loads((Path(self.directory.name)/f"{session.id}.json").read_text())
        self.assertEqual(review["seed"],17)
        self.assertAlmostEqual(review["trades"][0]["realized_r"],
                               review["trades"][0]["realized"]/initial_risk)

    def test_queued_cancel_and_partial_manual_exit(self):
        session=self.new_session()
        body=self.entry(session)
        session.command("entry",body)
        record=list(session.human.records.values())[-1]
        session.command("cancel",{"order_id":record["id"]})
        session.advance(1)
        self.assertEqual(record["status"],"cancelled")
        self.assertEqual(session.human.shares,0)
        session.command("entry",self.entry(session))
        session.advance(1)
        shares=session.human.shares
        self.assertGreater(shares,1)
        quantity=max(1,shares//2)
        session.command("exit",{"quantity":quantity})
        session.advance(1)
        self.assertEqual(session.human.shares,shares-quantity)
        session.command("exit",{"all":True})
        session.advance(1)
        self.assertEqual(session.human.shares,0)
        self.assertEqual(session.human.cash,session.exchange.broker_cash)

    def test_worker_protocol_idempotency_and_stale_session(self):
        process=subprocess.Popen([sys.executable,"-u",str(LAB/"worker.py")],
                                  stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,text=True)
        def call(body):
            process.stdin.write(json.dumps(body)+"\n")
            process.stdin.flush()
            line=process.stdout.readline()
            self.assertTrue(line,"Worker exited before responding")
            return json.loads(line)
        try:
            create=call({"action":"create","command_id":"create-test","seed":17,"date":"2026-10-02"})
            self.assertTrue(create["ok"],create.get("error"))
            sid=create["state"]["session_id"]
            command={"action":"advance","command_id":"advance-test","session_id":sid,"seconds":1}
            advanced=call(command)
            repeated=call(command)
            self.assertEqual(repeated["state"]["time"],advanced["state"]["time"])
            stale=call({"action":"advance","command_id":"stale-test","session_id":"wrong","seconds":1})
            self.assertFalse(stale["ok"])
        finally:
            process.terminate()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
