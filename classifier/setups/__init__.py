"""Setup detectors — shared types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectorResult:
    setup: str
    matched: bool
    score: int = 0
    criteria_met: list[str] = field(default_factory=list)
    criteria_failed: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "setup": self.setup,
            "matched": self.matched,
            "score": self.score,
            "criteria_met": self.criteria_met,
            "criteria_failed": self.criteria_failed,
            "extra": self.extra,
        }
