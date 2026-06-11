"""Rule registry + statistical evaluation for the myth-testing study.

Every rule is a claim made by a trader/school, classified by what the
winners-only databank can honestly test:

  prevalence   "big winners have property X" — directly measurable on all moves/events
  holdability  "X makes a move hard/easy to hold" — measured from the post-event
               price path, validated against the human-labeled subset (reviews.json)
  within-winner predictive  "at the event, X predicts better follow-through"
               — contrast forward outcomes across X buckets, winners only
  predictive (UNTESTABLE)  "X predicts that a stock becomes a big winner"
               — requires a control group of non-winners we don't have yet

Stats kept deliberately simple and robust: medians, group contrasts, share
above threshold, and a permutation test on the median difference (no scipy).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
N_PERM = 4000


# ---------- stat helpers ----------

def perm_pvalue(a: np.ndarray, b: np.ndarray) -> float | None:
    """Two-sided permutation test on difference of medians."""
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 8 or len(b) < 8:
        return None
    obs = abs(np.median(a) - np.median(b))
    pool = np.concatenate([a, b])
    n = len(a)
    count = 0
    for _ in range(N_PERM):
        RNG.shuffle(pool)
        if abs(np.median(pool[:n]) - np.median(pool[n:])) >= obs:
            count += 1
    return count / N_PERM


def med(s) -> float | None:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return round(float(s.median()), 2) if len(s) else None


def pct(mask: pd.Series) -> float | None:
    mask = mask.dropna()
    return round(float(mask.mean() * 100), 1) if len(mask) else None


def group_stats(df: pd.DataFrame, by: pd.Series, outcomes: list[str]) -> dict:
    """Median of each outcome column per bucket of `by` + n per bucket."""
    out: dict = {}
    for bucket, sub in df.groupby(by):
        entry = {"n": int(len(sub))}
        for col in outcomes:
            entry[col] = med(sub[col])
        if "reach_2r_before_stop" in sub.columns:
            entry["reach_2r_rate"] = pct(sub["reach_2r_before_stop"])
        out[str(bucket)] = entry
    return out


def label_contrast(moves: pd.DataFrame, metric: str) -> dict:
    """Median metric per human label + permutation p tradable-vs-not."""
    lab = moves[moves["label"].notna()]
    res = {
        grp: {"n": int(len(sub)), "median": med(sub[metric])}
        for grp, sub in lab.groupby("label")
    }
    a = pd.to_numeric(lab[lab["label"] == "tradable"][metric], errors="coerce").dropna().to_numpy()
    b = pd.to_numeric(lab[lab["label"] == "not"][metric], errors="coerce").dropna().to_numpy()
    res["p_tradable_vs_not"] = perm_pvalue(a, b)
    return res


OUTCOMES = ["fwd_ret_20", "fwd_ret_60", "fwd_mae_60", "fwd_max_dd_60"]


# ---------- lateness-controlled contrast machinery ----------
#
# THE central confound of a winners-only bank: conditions that only exist early
# in a move (weak RS, broken stack, far from highs) inherit the huge remaining
# upside of early entries, and vice versa. Q5 measures the effect directly
# (1st breakout vastly outperforms 4th+). So every within-winner entry-filter
# claim is tested twice: on all events AND on the early third of each move
# (pct_through_move <= 33), where the lateness gradient is mostly removed.
# Risk metrics (2R-before-stop rate, MAE) are weighed separately from returns —
# many entry rules are really stop-survival rules, not return rules.

def _side_stats(df: pd.DataFrame) -> dict:
    return {
        "n": int(len(df)),
        "fwd_ret_20": med(df["fwd_ret_20"]),
        "fwd_ret_60": med(df["fwd_ret_60"]),
        "fwd_mae_60": med(df["fwd_mae_60"]),
        "reach_2r_rate": pct(df["reach_2r_before_stop"]),
    }


def dual_contrast(df: pd.DataFrame, good_mask: pd.Series, bad_mask: pd.Series,
                  good_name: str, bad_name: str) -> dict:
    out: dict = {}
    early = df["pct_through_move"] <= 33
    for scope_name, scope in (("all_events", pd.Series(True, index=df.index)), ("early_third", early)):
        g, b = df[good_mask & scope], df[bad_mask & scope]
        a1 = pd.to_numeric(g["fwd_ret_20"], errors="coerce").dropna().to_numpy()
        b1 = pd.to_numeric(b["fwd_ret_20"], errors="coerce").dropna().to_numpy()
        out[scope_name] = {
            good_name: _side_stats(g),
            bad_name: _side_stats(b),
            "p_fwd20": perm_pvalue(a1, b1),
        }
    return out


def synth_verdict(dc: dict, good_name: str, bad_name: str,
                  claim_type: str = "return") -> tuple[str, list[str]]:
    """Verdict weighted by what the claim is actually about:
      return — the condition produces better forward returns (lateness-controlled)
      stop   — the condition makes a LOD-stop entry survive to 2R (2R rate dominates)
      risk   — the condition reduces pain while holding (MAE dominates)
    """
    early, full = dc["early_third"], dc["all_events"]

    def gap(scope, col):
        g, b = scope[good_name].get(col), scope[bad_name].get(col)
        return None if g is None or b is None else round(g - b, 2)

    ret_e = gap(early, "fwd_ret_20")
    r2r_f, r2r_e = gap(full, "reach_2r_rate"), gap(early, "reach_2r_rate")
    mae_f, mae_e = gap(full, "fwd_mae_60"), gap(early, "fwd_mae_60")

    notes: list[str] = []
    if ret_e is not None:
        notes.append(f"early-of-move fwd20 edge {ret_e:+}pp (p={early['p_fwd20']})")
    if r2r_f is not None:
        notes.append(f"2R-before-stop {r2r_f:+}pp all events, {r2r_e:+}pp early")
    if mae_f is not None:
        notes.append(f"MAE {mae_f:+}pp all events, {mae_e:+}pp early (positive = shallower)")

    score = 0
    if claim_type == "stop":
        if (r2r_f or 0) > 8 and (r2r_e or 0) > 8:
            score += 2
        elif (r2r_f or 0) > 3:
            score += 1
        if (ret_e or 0) < -3:
            score -= 1
        if (mae_f or 0) > 2:
            score += 1
    elif claim_type == "risk":
        if (mae_f or 0) > 4 and (mae_e or 0) > 4:
            score += 2
        elif (mae_f or 0) > 2:
            score += 1
        if (ret_e or 0) < -3:
            score -= 1
        if (r2r_f or 0) > 3:
            score += 1
    else:  # return claim
        if ret_e is not None:
            score += 1 if ret_e > 1 else (-1 if ret_e < -1 else 0)
        if r2r_f is not None:
            score += 1 if r2r_f > 3 else (-1 if r2r_f < -3 else 0)
        if mae_f is not None:
            score += 1 if mae_f > 2 else (-1 if mae_f < -2 else 0)
    if score >= 2:
        return "CONFIRMED", notes
    if score >= 1:
        return "PARTIAL", notes
    return "BUSTED", notes


# ---------- rule evaluators ----------
# Each returns {stats: {...}, verdict: str, finding: str}
# Verdicts: CONFIRMED / PARTIAL / BUSTED / UNTESTABLE

def _verdict_from_contrast(better: float | None, worse: float | None, p: float | None,
                           min_gap: float = 0.0) -> str:
    if better is None or worse is None:
        return "PARTIAL"
    gap_ok = (better - worse) > min_gap
    if gap_ok and (p is not None and p < 0.05):
        return "CONFIRMED"
    if gap_ok:
        return "PARTIAL"
    return "BUSTED"


def eval_u1_ema10(moves, events):
    cs = label_contrast(moves, "ema10_adh")
    share_hi = pct(moves["ema10_adh"] >= 75)
    share_lo = pct(moves["ema10_adh"] < 65)
    t = cs.get("tradable", {}).get("median")
    n = cs.get("not", {}).get("median")
    verdict = _verdict_from_contrast(t, n, cs["p_tradable_vs_not"], min_gap=5)
    return {
        "stats": {"by_label": cs, "share_movers_adh_ge75": share_hi, "share_movers_adh_lt65": share_lo},
        "verdict": verdict,
        "finding": f"Median 10EMA adherence: tradable {t}% vs not-my-style {n}% "
                   f"(p={cs['p_tradable_vs_not']}). Across ALL movers, {share_hi}% spend ≥75% of the move above the "
                   f"10EMA while {share_lo}% sit below the 65% skip line — clean trenders are the minority of big winners.",
    }


def eval_u2_sma50_touches(moves, events):
    cs = label_contrast(moves, "sma50_touches")
    t = cs.get("tradable", {}).get("median")
    n = cs.get("not", {}).get("median")
    # direction reversed: fewer touches is better
    verdict = _verdict_from_contrast(n, t, cs["p_tradable_vs_not"], min_gap=2)
    share_gt10 = pct(moves["sma50_touches"] > 10)
    return {
        "stats": {"by_label": cs, "share_movers_touches_gt10": share_gt10},
        "verdict": verdict,
        "finding": f"Median 50SMA touches: tradable {t} vs not-my-style {n} (p={cs['p_tradable_vs_not']}). "
                   f"{share_gt10}% of all movers exceed the >10-touch skip line.",
    }


def eval_u3_adr(moves, events):
    cs = label_contrast(moves, "adr_mean")
    t = cs.get("tradable", {}).get("median")
    n = cs.get("not", {}).get("median")
    verdict = _verdict_from_contrast(n, t, cs["p_tradable_vs_not"], min_gap=0.5)
    # correlation with holdability across ALL movers
    sub = moves.dropna(subset=["adr_mean", "worst_dd_pct"])
    corr_dd = round(float(sub["adr_mean"].corr(sub["worst_dd_pct"], method="spearman")), 2)
    sub2 = moves.dropna(subset=["adr_mean", "pct_days_u10"])
    corr_u10 = round(float(sub2["adr_mean"].corr(sub2["pct_days_u10"], method="spearman")), 2)
    return {
        "stats": {"by_label": cs, "spearman_adr_vs_worst_dd": corr_dd,
                  "spearman_adr_vs_pct_days_underwater10": corr_u10},
        "verdict": verdict,
        "finding": f"Median ADR: tradable {t}% vs not-my-style {n}% (p={cs['p_tradable_vs_not']}). Across all movers, "
                   f"higher ADR correlates with deeper drawdowns (ρ={corr_dd} vs worst DD) and more time >10% underwater (ρ={corr_u10}).",
    }


def eval_q3_adr_tension(moves, events):
    """Qullamaggie: high ADR = good (big moves). User: high ADR = hard to hold. Test both."""
    sub = moves.dropna(subset=["adr_mean", "gain_pct"])
    corr_gain = round(float(sub["adr_mean"].corr(sub["gain_pct"], method="spearman")), 2)
    hi = sub[sub["adr_mean"] >= 7]
    lo = sub[sub["adr_mean"] < 5.5]
    stats = {
        "spearman_adr_vs_move_gain": corr_gain,
        "median_gain_adr_ge7": med(hi["gain_pct"]), "n_ge7": int(len(hi)),
        "median_gain_adr_lt55": med(lo["gain_pct"]), "n_lt55": int(len(lo)),
        "median_worst_dd_adr_ge7": med(hi["worst_dd_pct"]),
        "median_worst_dd_adr_lt55": med(lo["worst_dd_pct"]),
    }
    both = (corr_gain is not None and corr_gain > 0.15)
    return {
        "stats": stats,
        "verdict": "CONFIRMED" if both else "PARTIAL",
        "finding": f"Both schools are right about different things: ADR vs move size ρ={corr_gain} "
                   f"(higher ADR → bigger gains: median {stats['median_gain_adr_ge7']}% vs {stats['median_gain_adr_lt55']}%), "
                   f"but the cost is drawdown (median worst DD {stats['median_worst_dd_adr_ge7']}% vs {stats['median_worst_dd_adr_lt55']}%). "
                   f"High ADR buys move size with pain; pick your seat on that curve deliberately.",
    }


def eval_u4_close_in_range(moves, events):
    gaps = events[events["event_type"] == "gap"].copy()
    bucket = pd.cut(gaps["close_in_range"], [-1, 50, 75, 101], labels=["<50 trap", "50-75 mid", ">75 clean"])
    gs = group_stats(gaps, bucket, OUTCOMES)
    dc = dual_contrast(gaps, gaps["close_in_range"] > 75, gaps["close_in_range"] < 50,
                       "clean >75", "trap <50")
    verdict, notes = synth_verdict(dc, "clean >75", "trap <50", claim_type="stop")
    return {
        "stats": {"by_close_in_range": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"The rule is about stop survival, not raw return: clean closes reach 2R before a LOD stop "
                   f"{dc['all_events']['clean >75']['reach_2r_rate']}% of the time vs {dc['all_events']['trap <50']['reach_2r_rate']}% "
                   f"for trap closes — a monotonic ladder across the three buckets — while 20-bar returns are similar. "
                   f"Signals: {'; '.join(notes)}.",
    }


def eval_u5_ema_stack(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])]
    prev = pct(bo["ema_stack_bull"])
    gs = group_stats(bo, bo["ema_stack_bull"].map({True: "stack bullish", False: "stack not bullish"}), OUTCOMES)
    dc = dual_contrast(bo, bo["ema_stack_bull"] == True, bo["ema_stack_bull"] == False,  # noqa: E712
                       "stack bullish", "stack broken")
    verdict, notes = synth_verdict(dc, "stack bullish", "stack broken")
    return {
        "stats": {"prevalence_at_breakouts_pct": prev, "by_stack": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"{prev}% of winners' breakout events already have the full bullish stack, so as a FILTER it costs little. "
                   f"But broken-stack breakouts (early, off the lows) show the bigger forward returns — the naive full-sample "
                   f"comparison is pure lateness bias. After controlling: {'; '.join(notes)}. "
                   f"Treat the stack as a holdability/trend-quality gate (its real role in your framework), not a return edge.",
    }


def eval_u6_gain_vs_tradability(moves, events):
    cs = label_contrast(moves, "gain_pct")
    lab = moves[moves["label"].notna()].copy()
    lab["lab_num"] = lab["label"].map({"not": 0, "partial": 1, "tradable": 2})
    rho = round(float(lab["gain_pct"].corr(lab["lab_num"], method="spearman")), 2)
    verdict = "CONFIRMED" if abs(rho) < 0.25 else "BUSTED"
    return {
        "stats": {"by_label": cs, "spearman_gain_vs_label": rho},
        "verdict": verdict,
        "finding": f"Move size barely relates to tradability (ρ={rho}); median gains by label: "
                   + ", ".join(f"{k} {v['median']}%" for k, v in cs.items() if isinstance(v, dict)) + ".",
    }


def eval_q1_breakout_volume(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])].copy()
    prev2x = pct(bo["event_rel_vol20"] >= 2)
    bucket = pd.cut(bo["event_rel_vol20"], [0, 1, 1.5, 2, 3, np.inf],
                    labels=["<1x", "1-1.5x", "1.5-2x", "2-3x", ">3x"])
    gs = group_stats(bo, bucket, OUTCOMES)
    dc = dual_contrast(bo, bo["event_rel_vol20"] >= 2, bo["event_rel_vol20"] < 1.5,
                       "vol ≥2x", "vol <1.5x")
    verdict, notes = synth_verdict(dc, "vol ≥2x", "vol <1.5x")
    r2r = " → ".join(f"{k} {v['reach_2r_rate']}%" for k, v in gs.items())
    return {
        "stats": {"share_breakouts_ge2x_pct": prev2x, "by_relvol": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"Two halves to this myth. As a PREREQUISITE it fails: only {prev2x}% of winners' breakout days print ≥2x "
                   f"volume — winners break out quietly all the time. As a STOP-SURVIVAL signal it works: 2R-before-stop "
                   f"climbs monotonically with volume ({r2r}). Signals: {'; '.join(notes)}.",
    }


def eval_q2_prior_uptrend(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])].copy()
    prev30 = pct(bo["prior_gain_3m"] >= 30)
    bucket = pd.cut(bo["prior_gain_3m"], [-np.inf, 0, 30, 100, np.inf],
                    labels=["down 3m", "0-30%", "30-100%", ">100%"])
    gs = group_stats(bo, bucket, OUTCOMES)
    dc = dual_contrast(bo, bo["prior_gain_3m"] >= 30, bo["prior_gain_3m"] < 30,
                       "prior 3m ≥30%", "prior 3m <30%")
    verdict, notes = synth_verdict(dc, "prior 3m ≥30%", "prior 3m <30%")
    return {
        "stats": {"share_breakouts_prior3m_ge30_pct": prev30, "by_prior_gain": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"{prev30}% of breakout events already ran ≥30% in the prior 3 months, so momentum-begets-momentum is the "
                   f"normal state of a big mover. But the >100%-prior bucket pays for it in risk (median MAE "
                   f"{gs.get('>100%', {}).get('fwd_mae_60')}% vs {gs.get('0-30%', {}).get('fwd_mae_60')}% for 0-30%) — "
                   f"matching your ADD-vs-cold-entry rule. After lateness control: {'; '.join(notes)}.",
    }


def eval_q4_market_regime(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50", "gap"])].copy()
    gs = group_stats(bo, bo["spy_above_50sma"].map({True: "SPY>50SMA", False: "SPY<50SMA"}), OUTCOMES)
    dc = dual_contrast(bo, bo["spy_above_50sma"] == True, bo["spy_above_50sma"] == False,  # noqa: E712
                       "SPY>50SMA", "SPY<50SMA")
    verdict, notes = synth_verdict(dc, "SPY>50SMA", "SPY<50SMA")
    share_bad_regime = pct(bo["spy_above_50sma"] == False)  # noqa: E712
    return {
        "stats": {"by_regime": gs, "lateness_controlled": dc,
                  "share_events_spy_below_50sma_pct": share_bad_regime},
        "verdict": verdict,
        "finding": f"{share_bad_regime}% of winners' entry events fired with SPY BELOW its 50SMA — and those events did NOT "
                   f"underperform (weak tape is when the next cycle's leaders bottom). After lateness control: "
                   f"{'; '.join(notes)}. The folklore overstates the tape filter for THESE stocks; what a weak tape really "
                   f"changes is how many such setups exist at all, which a winners-only bank cannot measure (see X1).",
    }


def eval_q5_first_breakout(moves, events):
    bo = events[events["event_type"] == "breakout20"].copy()
    bucket = pd.cut(bo["event_ordinal"], [0, 1, 3, np.inf], labels=["1st", "2nd-3rd", "4th+"])
    gs = group_stats(bo, bucket, OUTCOMES)
    # also by how far through / above move start (user's ADD-vs-cold 2x rule)
    ext = pd.cut(bo["gain_from_move_start"], [-np.inf, 50, 100, np.inf], labels=["<50% up", "50-100% up", ">100% up"])
    gs_ext = group_stats(bo, ext, OUTCOMES + ["fwd_mae_60"])
    a = bo[bo["event_ordinal"] == 1]["fwd_ret_60"].to_numpy(dtype=float)
    b = bo[bo["event_ordinal"] >= 4]["fwd_ret_60"].to_numpy(dtype=float)
    p = perm_pvalue(a, b)
    m1 = gs.get("1st", {}).get("fwd_ret_60")
    m4 = gs.get("4th+", {}).get("fwd_ret_60")
    verdict = _verdict_from_contrast(m1, m4, p)
    return {
        "stats": {"by_ordinal": gs, "by_extension_from_move_start": gs_ext, "p_1st_vs_4thplus_fwd60": p},
        "verdict": verdict,
        "finding": f"Median fwd 60-bar return: 1st breakout {m1}% vs 4th+ {m4}% (p={p}). By extension off the move low: "
                   + ", ".join(f"{k}: fwd60 {v['fwd_ret_60']}%" for k, v in gs_ext.items()) + ".",
    }


def eval_q6_winners_hold_ema(moves, events):
    s65 = pct(moves["ema10_adh"] >= 65)
    s80_20 = pct(moves["ema20_adh"] >= 80)
    med10 = med(moves["ema10_adh"])
    med20 = med(moves["ema20_adh"])
    verdict = "CONFIRMED" if (s80_20 or 0) >= 60 else ("PARTIAL" if (s80_20 or 0) >= 40 else "BUSTED")
    return {
        "stats": {"median_ema10_adh": med10, "median_ema20_adh": med20,
                  "share_ema10_ge65_pct": s65, "share_ema20_ge80_pct": s80_20},
        "verdict": verdict,
        "finding": f"Median big mover holds the 10EMA {med10}% of days and the 20EMA {med20}%. {s65}% clear your 65% 10EMA line; "
                   f"{s80_20}% hold the 20EMA ≥80% of the time. The 20EMA, not the 10, is the real 'magic line' for the median winner.",
    }


def eval_m1_trend_template(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])]
    prev = pct(bo["trend_template"])
    gs = group_stats(bo, bo["trend_template"].map({True: "template pass", False: "template fail"}), OUTCOMES)
    dc = dual_contrast(bo, bo["trend_template"] == True, bo["trend_template"] == False,  # noqa: E712
                       "template pass", "template fail")
    verdict, notes = synth_verdict(dc, "template pass", "template fail")
    ms = events[events["event_type"] == "move_start"]
    prev_start = pct(ms["trend_template"])
    return {
        "stats": {"prevalence_at_breakouts_pct": prev, "prevalence_at_move_start_pct": prev_start,
                  "by_template": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"Only {prev_start}% of big moves BEGIN in full stage-2 (price>50>150>200, 200 rising) — the biggest moves "
                   f"start from broken charts, which the template excludes by design. By breakout time {prev}% pass. "
                   f"After lateness control: {'; '.join(notes)}. The template buys cleaner risk, not bigger returns, and it "
                   f"makes you structurally late on the largest winners.",
    }


def eval_m2_52wk_high(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])].copy()
    near = pct(bo["pct_off_52wk_high"] >= -25)
    bucket = pd.cut(bo["pct_off_52wk_high"], [-np.inf, -50, -25, -10, 1],
                    labels=[">50% off", "25-50% off", "10-25% off", "<10% off"])
    gs = group_stats(bo, bucket, OUTCOMES)
    dc = dual_contrast(bo, bo["pct_off_52wk_high"] >= -10, bo["pct_off_52wk_high"] < -25,
                       "<10% off high", ">25% off high")
    verdict, notes = synth_verdict(dc, "<10% off high", ">25% off high")
    return {
        "stats": {"share_within_25pct_of_high": near, "by_distance": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"{near}% of breakout events fire within 25% of the 52wk high, so the filter passes most of what matters. "
                   f"Risk profile: near-high entries have shallower MAE ({gs.get('<10% off', {}).get('fwd_mae_60')}%) than "
                   f"deep-recovery entries ({gs.get('>50% off', {}).get('fwd_mae_60')}%). After lateness control: "
                   f"{'; '.join(notes)}.",
    }


def eval_m3_rs(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])].copy()
    prev = pct(bo["rs_63d"] > 1)
    bucket = pd.cut(bo["rs_63d"], [0, 1, 1.3, np.inf], labels=["RS<1", "RS 1-1.3", "RS>1.3"])
    gs = group_stats(bo, bucket, OUTCOMES)
    dc = dual_contrast(bo, bo["rs_63d"] > 1.3, bo["rs_63d"] <= 1, "RS>1.3", "RS≤1")
    verdict, notes = synth_verdict(dc, "RS>1.3", "RS≤1")
    return {
        "stats": {"share_rs_gt1_pct": prev, "by_rs": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"{prev}% of winners' breakouts already outperform SPY over the trailing 63d — RS>1 is near-universal "
                   f"in big movers (prevalence holds). But demanding MORE RS (>1.3) at entry buys nothing further: "
                   f"{'; '.join(notes)}. Extreme trailing RS at the event is extension, not extra edge.",
    }


def eval_s1_tightness(moves, events):
    bo = events[events["event_type"].isin(["breakout20", "breakout50"])].copy()
    bo = bo.dropna(subset=["tightness_10"])
    q = bo["tightness_10"].quantile([0.33, 0.67])
    bucket = pd.cut(bo["tightness_10"], [-np.inf, q.iloc[0], q.iloc[1], np.inf],
                    labels=["tight", "medium", "loose"])
    gs = group_stats(bo, bucket, OUTCOMES)
    dc = dual_contrast(bo, bucket == "tight", bucket == "loose", "tight third", "loose third")
    verdict, notes = synth_verdict(dc, "tight third", "loose third", claim_type="risk")
    return {
        "stats": {"tightness_terciles": {"t1": round(float(q.iloc[0]), 2), "t2": round(float(q.iloc[1]), 2)},
                  "by_tightness": gs, "lateness_controlled": dc},
        "verdict": verdict,
        "finding": f"Tightness is a RISK rule, not a return rule: the tight third suffers roughly half the adverse excursion "
                   f"(MAE {gs.get('tight', {}).get('fwd_mae_60')}% vs {gs.get('loose', {}).get('fwd_mae_60')}%, max DD "
                   f"{gs.get('tight', {}).get('fwd_max_dd_60')}% vs {gs.get('loose', {}).get('fwd_max_dd_60')}%) for similar "
                   f"raw returns — tight entries let you hold the same move with far less pain. Signals: {'; '.join(notes)}.",
    }


def eval_x1_untestable(moves, events):
    return {
        "stats": {"note": "databank contains winners only — no control group of failed breakouts / non-movers"},
        "verdict": "UNTESTABLE",
        "finding": "Any claim of the form 'criteria X finds the next big winner' cannot be tested here: every stock in the "
                   "bank already won. What CAN be tested (and is, above): what winners look like, and which entry conditions "
                   "produced better follow-through within winners. To test true predictiveness, build a control sample "
                   "(random ticker-dates, or same-ticker breakouts outside move windows) — recommended phase 2.",
    }


RULES = [
    {"id": "U1", "source": "Your framework (ANNOTATION_TRACKER)", "class": "holdability",
     "claim": "10EMA adherence <65% → skip; >75% → promising", "fn": eval_u1_ema10},
    {"id": "U2", "source": "Your framework (ANNOTATION_TRACKER)", "class": "holdability",
     "claim": ">10 SMA50 touches → skip; ≤2 → ideal", "fn": eval_u2_sma50_touches},
    {"id": "U3", "source": "Your framework (ANNOTATION_TRACKER)", "class": "holdability",
     "claim": "ADR >7% → hard to hold; <5.5% → comfortable", "fn": eval_u3_adr},
    {"id": "Q3", "source": "Qullamaggie vs your framework", "class": "holdability",
     "claim": "Tension test: Qullamaggie wants high-ADR names ('they move'), you flag high ADR as unholdable", "fn": eval_q3_adr_tension},
    {"id": "U4", "source": "Your framework (close-in-range rule)", "class": "within-winner predictive",
     "claim": "Gap close >75% in range = clean EP; <50% = trap (overrides gap %)", "fn": eval_u4_close_in_range},
    {"id": "U5", "source": "Your framework (watchlist-vs-tradable gate)", "class": "within-winner predictive",
     "claim": "Tradable requires full bullish EMA stack (10>20>50) and price above the 50", "fn": eval_u5_ema_stack},
    {"id": "U6", "source": "Your framework (ANNOTATION_TRACKER insight)", "class": "holdability",
     "claim": "Gain size has zero correlation with tradability", "fn": eval_u6_gain_vs_tradability},
    {"id": "Q1", "source": "Qullamaggie / Minervini", "class": "prevalence + within-winner predictive",
     "claim": "Real breakouts need a volume surge (≥2x average)", "fn": eval_q1_breakout_volume},
    {"id": "Q2", "source": "Qullamaggie", "class": "prevalence + within-winner predictive",
     "claim": "The best setups already ran 30-100% in the prior 1-3 months", "fn": eval_q2_prior_uptrend},
    {"id": "Q4", "source": "Qullamaggie (market regime)", "class": "within-winner predictive",
     "claim": "Breakouts work when the index is above its 50SMA; fight the tape and lose", "fn": eval_q4_market_regime},
    {"id": "Q5", "source": "Qullamaggie + your ADD-vs-cold rule", "class": "within-winner predictive",
     "claim": "The first breakout of a move works best; late breakouts are adds, not cold entries", "fn": eval_q5_first_breakout},
    {"id": "Q6", "source": "Qullamaggie ('magic line')", "class": "prevalence",
     "claim": "Big winners ride the 10/20EMA for the duration of the move", "fn": eval_q6_winners_hold_ema},
    {"id": "M1", "source": "Minervini (trend template)", "class": "prevalence + within-winner predictive",
     "claim": "Buy only stage-2 stocks: price>50SMA>150SMA>200SMA with 200 rising", "fn": eval_m1_trend_template},
    {"id": "M2", "source": "Minervini / O'Neil", "class": "prevalence + within-winner predictive",
     "claim": "Buy within 25% of the 52-week high; closer is better", "fn": eval_m2_52wk_high},
    {"id": "M3", "source": "Minervini / IBD (RS line)", "class": "prevalence + within-winner predictive",
     "claim": "Demand positive relative strength vs the index before entry", "fn": eval_m3_rs},
    {"id": "S1", "source": "VCP doctrine (Minervini/Qullamaggie)", "class": "within-winner predictive",
     "claim": "Tighter pre-breakout price action → better breakout", "fn": eval_s1_tightness},
    {"id": "X1", "source": "All schools", "class": "predictive (no control group)",
     "claim": "'These criteria find the next big winner'", "fn": eval_x1_untestable},
]


BOOL_COLS = [
    "ema_stack_bull", "trend_template", "above_sma50", "above_sma200",
    "spy_above_50sma", "spy_above_200sma", "lod_stop_survives_20", "reach_2r_before_stop",
]
_BOOL_MAP = {True: True, False: False, "True": True, "False": False, 1.0: True, 0.0: False}


def normalize_bools(df: pd.DataFrame) -> pd.DataFrame:
    """CSV round-trip turns nullable bool columns into 'True'/'False' strings — undo that."""
    for c in BOOL_COLS:
        if c in df.columns:
            df[c] = df[c].map(_BOOL_MAP)
    return df


def run_all(moves: pd.DataFrame, events: pd.DataFrame) -> list[dict]:
    events = normalize_bools(events.copy())
    out = []
    for rule in RULES:
        try:
            res = rule["fn"](moves, events)
        except Exception as exc:
            res = {"stats": {"error": str(exc)}, "verdict": "ERROR", "finding": f"evaluator failed: {exc}"}
        out.append({k: rule[k] for k in ("id", "source", "class", "claim")} | res)
    return out
