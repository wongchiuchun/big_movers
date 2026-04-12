"""Setup scoring and tiebreaker resolution (§7 of the reference)."""
from __future__ import annotations

from classifier.setups import DetectorResult

# (winner, loser) — if both match, winner wins even if loser has higher score
TIEBREAKERS: list[tuple[str, str]] = [
    ("HTF", "VCP"),
    ("HTF", "Cup with Handle"),
    ("Cup with Handle", "VCP"),
    ("Flat Base", "VCP"),
    # EP vs Gap & Go: determined by entry day. If the gap day IS the pivot -> Gap & Go.
    # If pivot is 2+ days later -> EP. For scoring purposes, EP wins if both match
    # because it's a more structured entry.
    ("Episodic Pivot", "Gap & Go"),
    # Pocket Pivot is almost always secondary — demote it unless it's the only match
]

PRIMARY_DEMOTE: set[str] = {"Pocket Pivot", "Gap & Go"}


def resolve_primary_setup(results: list[DetectorResult]) -> str | None:
    matched = [r for r in results if r.matched]
    if not matched:
        return None
    matched.sort(key=lambda r: r.score, reverse=True)
    matched_names = {r.setup for r in matched}

    # Apply tiebreakers
    for winner, loser in TIEBREAKERS:
        if winner in matched_names and loser in matched_names:
            matched_names.discard(loser)

    # Demote Pocket Pivot unless it's the only match
    base_matches = matched_names - PRIMARY_DEMOTE
    if base_matches:
        matched_names = base_matches

    for r in matched:
        if r.setup in matched_names:
            return r.setup
    return matched[0].setup
