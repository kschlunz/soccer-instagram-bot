"""Pick out marquee games: rivalries, ranked matchups, and knockout rounds."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .fixtures import Match

RIVALRIES_FILE = Path(__file__).parent / "data" / "rivalries.json"

# football-data.org stage names that count as marquee, with a display label
KNOCKOUT_STAGES = {
    "FINAL": "Final",
    "SEMI_FINALS": "Semifinal",
    "QUARTER_FINALS": "Quarterfinal",
    "THIRD_PLACE": "Third-place match",
    "PLAYOFFS": "Playoff",
}
# words in an ESPN headline/stage that count as marquee
KNOCKOUT_WORDS = ("final", "semifinal", "semi-final", "championship", "playoff", "title game")

RANK_RE = re.compile(r"^#(\d{1,2})\s+")
MAX_FEATURED = 3


def load_rivalries(path: Path = RIVALRIES_FILE) -> dict[str, list[list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k.upper(): v for k, v in data.items() if not k.startswith("_")}


def _norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _mentions(team: str, name: str) -> bool:
    """`team` may list aliases separated by '|', e.g. 'Barcelona|Barça'."""
    target = _norm(name)
    return any(_norm(alias) and _norm(alias) in target for alias in team.split("|"))


def _rank(name: str) -> int | None:
    m = RANK_RE.match(name)
    return int(m.group(1)) if m else None


def reason_for(match: Match, rivalries: dict[str, list[list[str]]]) -> str | None:
    """Return why this match is marquee, or None."""
    # 1. Knockout round / final
    stage = (match.stage or "").strip()
    if stage.upper() in KNOCKOUT_STAGES:
        return KNOCKOUT_STAGES[stage.upper()]
    low = stage.lower()
    if stage and any(w in low for w in KNOCKOUT_WORDS) and "round of" not in low and "quarter" not in low:
        return stage

    # 2. Rivalry
    for a, b, label in rivalries.get(match.competition_code, []):
        if (_mentions(a, match.home) and _mentions(b, match.away)) or (
            _mentions(b, match.home) and _mentions(a, match.away)
        ):
            return label

    # 3. Ranked matchup (college): both teams ranked
    rh, ra = _rank(match.home), _rank(match.away)
    if rh and ra:
        return f"Ranked matchup: #{min(rh, ra)} vs #{max(rh, ra)}"
    return None


def tag_marquee(matches: Iterable[Match], rivalries: dict[str, list[list[str]]] | None = None) -> list[Match]:
    """Return the matches with `marquee` set where a reason applies."""
    rivalries = rivalries if rivalries is not None else load_rivalries()
    out = []
    for m in matches:
        reason = reason_for(m, rivalries)
        out.append(replace(m, marquee=reason) if reason else m)
    return out


def featured(matches: Iterable[Match], limit: int = MAX_FEATURED) -> list[Match]:
    """Marquee games to put on the featured slide, earliest first, skipping postponed ones."""
    picks = [m for m in matches if m.marquee and m.status not in {"POSTPONED", "CANCELLED", "SUSPENDED"}]
    picks.sort(key=lambda m: m.kickoff)
    return picks[:limit]
