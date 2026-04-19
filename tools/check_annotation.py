#!/usr/bin/env python3
"""Structural validator for drawings.json annotations.

Enforces Hard Rules 5-8 from .claude/commands/annotate.md mechanically
so the "PI_2025 April 2026 failure" class of annotation (one omnibus
essay-note instead of 6-10 atomic decision-moment notes) cannot ship.

Rules enforced:
  Rule 5  DENSITY  count(drawings) >= 6 per move key
  Rule 6  SPAN     fail if note p1->p2 span > 42 days AND text > 300 chars
                   (essay detection — wide rectangles with short anchored
                   text are fine because users drag notes for visual layout;
                   only flag long-text AND wide-span, which is the
                   "omnibus essay" failure mode)
  Rule 7  QUANT    note text must not contain aggregate-metric labels
                   (e.g. "54% 10EMA", "5x 50SMA touches", "DD -16%",
                   "Q2", "UNTRADABLE")
  Rule 8  COLOR    note color == "#000000"

Usage:
    python3 tools/check_annotation.py              # audit all move keys
    python3 tools/check_annotation.py PI_2025      # audit one move key
    python3 tools/check_annotation.py PI_2025 PL_2025  # audit several

Exit code 0 iff every audited move key passes.
"""
import json
import os
import re
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAWINGS_FILE = os.path.join(BASE, "drawings.json")

# Rule 7 — aggregate-metric patterns banned inside note text.
# These are the exact anti-patterns called out in Step 9b of the skill:
# quant labels that describe a multi-week window rather than a single
# decision moment.
QUANT_PATTERNS = [
    ("% 10EMA",        re.compile(r"\d+\s*%\s*10\s*EMA",      re.IGNORECASE)),
    ("% 20EMA",        re.compile(r"\d+\s*%\s*20\s*EMA",      re.IGNORECASE)),
    ("50SMA touches",  re.compile(r"\d+\s*[x×]?\s*50\s*SMA\s*touches?", re.IGNORECASE)),
    ("DD -N%",         re.compile(r"\bDD\s*-?\d+\s*%",        re.IGNORECASE)),
    ("Q1/Q2/Q3/Q4",    re.compile(r"\bQ[1-4]\b")),
    ("bucket label",   re.compile(r"\b(?:UNTRADABLE|PARTIALLY\s+TRADABLE|NOT\s+TRADABLE|TRADABLE)\b")),
]


def parse_time(tp):
    """Turn a {'day':D,'month':M,'year':Y} dict into a date, or None."""
    if not isinstance(tp, dict):
        return None
    try:
        return date(int(tp["year"]), int(tp["month"]), int(tp["day"]))
    except (KeyError, ValueError, TypeError):
        return None


def audit_move(move_key, drawings):
    """Return a list of (code, message) violations for this move key."""
    violations = []

    # Rule 5 — density floor
    n = len(drawings) if isinstance(drawings, list) else 0
    if n < 6:
        violations.append(("DENSITY", f"{n} drawings < 6 minimum (see Step 5.5)"))

    for d in drawings or []:
        if not isinstance(d, dict):
            continue
        if d.get("type") != "note":
            continue

        did = d.get("id", "?")
        txt = d.get("text", "") or ""

        # Rule 8 — note color
        color = (d.get("color") or "").strip().lower()
        if color != "#000000":
            violations.append(("COLOR",
                f"note id={did} color={color or '<empty>'!r} != #000000"))

        # Rule 6 — span (essay detection: wide rectangle + long text)
        # Wide visual placement alone is fine (hand-dragged notes stretch
        # naturally); flag only when a long body rides a wide span, which
        # is the omnibus-essay signature we want to catch.
        p1 = parse_time((d.get("p1") or {}).get("time"))
        p2 = parse_time((d.get("p2") or {}).get("time"))
        if p1 and p2:
            span = abs((p2 - p1).days)
            if span > 42 and len(txt) > 300:
                violations.append(("SPAN",
                    f"note id={did} spans {span}d with {len(txt)}ch text "
                    f"(>42d AND >300ch — omnibus essay)"))

        # Rule 7 — aggregate-metric ban
        hits = [label for label, pat in QUANT_PATTERNS if pat.search(txt)]
        if hits:
            snippet = txt.replace("\n", " ")[:80]
            violations.append(("QUANT",
                f"note id={did} matches {hits}: {snippet!r}"))

    return violations


def main():
    if not os.path.isfile(DRAWINGS_FILE):
        print(f"drawings.json not found at {DRAWINGS_FILE}", file=sys.stderr)
        sys.exit(2)

    with open(DRAWINGS_FILE) as f:
        all_drawings = json.load(f)

    keys = sys.argv[1:] if len(sys.argv) > 1 else sorted(all_drawings.keys())

    any_fail = False
    for k in keys:
        if k not in all_drawings:
            print(f"[SKIP] {k}: not in drawings.json")
            continue
        arr = all_drawings[k] or []
        viols = audit_move(k, arr)
        if viols:
            any_fail = True
            print(f"[FAIL] {k}: {len(arr)} drawings, {len(viols)} violation(s)")
            for code, msg in viols:
                print(f"   {code:8s} {msg}")
        else:
            print(f"[OK]   {k}: {len(arr)} drawings")

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
