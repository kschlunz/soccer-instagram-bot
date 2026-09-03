"""Pick the one game worth a dedicated post: a final, or (if configured) a semifinal or any marquee game."""
from __future__ import annotations

from typing import Iterable

from .fixtures import Match

LEVELS = {"any": 1, "semifinal": 2, "final": 3}


def level(match: Match) -> int:
    """3 = final/championship, 2 = semifinal, 1 = other marquee, 0 = not marquee."""
    reason = (match.marquee or "").lower()
    stage = (match.stage or "").lower()
    text = f"{reason} {stage}"
    if not match.marquee:
        return 0
    if ("final" in text or "championship" in text or "title game" in text) and "semi" not in text and "quarter" not in text:
        return 3
    if "semi" in text:
        return 2
    return 1


def pick(matches: Iterable[Match], minimum: str = "final") -> Match | None:
    """Best candidate at or above `minimum` ('final', 'semifinal', 'any'), earliest kickoff on ties."""
    threshold = LEVELS.get(minimum, 3)
    candidates = [
        m for m in matches
        if level(m) >= threshold
        and m.status in {"TIMED", "SCHEDULED", "IN_PLAY"}
        and "tbd" not in m.home.lower() and "tbd" not in m.away.lower()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: (-level(m), m.kickoff))
    return candidates[0]


def heading(match: Match) -> str:
    lvl = level(match)
    if lvl == 3:
        return "THE FINAL"
    if lvl == 2:
        return "SEMIFINAL"
    return "GAME OF THE DAY"
