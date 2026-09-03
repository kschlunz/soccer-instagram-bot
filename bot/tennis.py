"""WTA matches from ESPN's tennis scoreboard.

ESPN's tennis feed differs from team sports: each *event* is a tournament, and the
matches live under event["groupings"][i]["competitions"] (grouped by draw: women's
singles, women's doubles...). Only singles are used. To keep a Grand Slam's first
week from flooding the post, only the later rounds are shown (see MIN_ROUND).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .espn import channels_for, major_networks_only
from .fixtures import Match

log = logging.getLogger("soccer-bot.tennis")

GRAND_SLAMS = ("us open", "wimbledon", "australian open", "french open", "roland garros")

# Round names -> importance. Matches below MIN_ROUND (or with an unknown round) are skipped.
ROUND_ORDER = {
    "round of 128": 0, "first round": 0, "1st round": 0,
    "round of 64": 0, "second round": 0, "2nd round": 0,
    "round of 32": 0, "third round": 0, "3rd round": 0,
    "round of 16": 1, "fourth round": 1, "4th round": 1,
    "quarterfinal": 2, "quarterfinals": 2, "quarter-final": 2, "quarter-finals": 2,
    "semifinal": 3, "semifinals": 3, "semi-final": 3, "semi-finals": 3,
    "final": 4, "finals": 4, "championship": 4,
}
MIN_ROUND_SLAM = 1    # Grand Slams: round of 16 onward is always shown
MIN_ROUND_OTHER = 2   # other WTA events: quarterfinals onward is always shown
# Earlier rounds are shown only when ESPN lists the match on a major national network
# (the show-court schedule), capped per tournament per day.
EARLY_ROUND_CAP = 8
SINGLES_SLUGS = ("womens-singles", "women's singles", "womens singles", "singles")


def events_to_matches(
    events: Iterable[dict[str, Any]],
    day: date,
    tz: ZoneInfo,
    broadcasters: dict[str, str],
    code: str = "WTA",
) -> list[Match]:
    out: list[Match] = []
    seen: set[str] = set()
    events = list(events)
    if events:
        first = events[0]
        comps = list(_competitions(first))
        draws = {draw: sum(1 for _, d in comps if d == draw) for _, draw in comps}
        log.info("ESPN tennis: %d tournament(s); first=%r; draws=%s",
                 len(events), first.get("shortName") or first.get("name"), draws)
        if comps:
            c = comps[0][0]
            comp0 = (c.get("competitors") or [{}])[0]
            log.info("ESPN tennis sample: round=%r status=%r timeValid=%r date=%r competitor keys=%s athlete=%s",
                     c.get("round"), (c.get("status") or {}).get("type", {}).get("name"), c.get("timeValid"),
                     c.get("date"), sorted(comp0.keys())[:12],
                     {k: v for k, v in (comp0.get("athlete") or {}).items() if k in ("displayName", "shortName")})
    for event in events:
        tournament = (event.get("shortName") or event.get("name") or "WTA").strip()
        is_slam = any(s in tournament.lower() for s in GRAND_SLAMS)
        min_round = MIN_ROUND_SLAM if is_slam else MIN_ROUND_OTHER
        tv = broadcasters.get(f"{code}:{tournament}") or _slam_tv(tournament, broadcasters) or broadcasters.get(code)
        competition_name = f"{tournament} · Women's Singles"

        kept_early = 0
        for comp, draw in _competitions(event):
            key = str(comp.get("id") or comp.get("uid") or id(comp))
            if key in seen:
                continue
            seen.add(key)
            if not _is_singles(draw, comp):
                continue
            try:
                m, early = _match(comp, competition_name, code, day, tz, tv, min_round)
            except (KeyError, IndexError, AttributeError, ValueError, TypeError) as err:
                log.warning("Skipping malformed tennis match in %s: %s", tournament, err)
                continue
            if not m:
                continue
            if early:
                if kept_early >= EARLY_ROUND_CAP:
                    continue
                kept_early += 1
            out.append(m)
        log.info("ESPN tennis %s: kept %d women's singles match(es) for %s", tournament,
                 sum(1 for m in out if m.competition == competition_name), day)
    return out


def _competitions(event: dict[str, Any]):
    """Yield (competition, draw name) for every match in the tournament."""
    groupings = event.get("groupings")
    if groupings:
        for g in groupings:
            info = g.get("grouping") or g
            draw = (info.get("slug") or info.get("displayName") or info.get("name") or "").lower()
            for comp in g.get("competitions") or []:
                yield comp, draw
    else:
        for comp in event.get("competitions") or []:
            draw = ((comp.get("type") or {}).get("text") or comp.get("description") or "singles").lower()
            yield comp, draw


def _is_singles(draw: str, comp: dict[str, Any] | None = None) -> bool:
    if "doubles" in draw or "mixed" in draw:
        return False
    if any(s in draw for s in SINGLES_SLUGS):
        return True
    # No usable draw label: singles if both competitors are individual athletes.
    competitors = (comp or {}).get("competitors") or []
    return len(competitors) == 2 and all(c.get("athlete") and not c.get("roster") for c in competitors)


def _match(comp, competition_name, code, day, tz, tv, min_round) -> tuple[Match | None, bool]:
    """Return (match, is_early_round). Early-round matches are kept only when on national TV."""
    raw_date = comp.get("date")
    if not raw_date:
        return None, False
    utc = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)
    local = utc.astimezone(tz)
    if local.date() != day:
        return None, False

    round_name = _round_name(comp)
    importance = _importance(round_name)
    if importance is None or "qualifying" in (round_name or "").lower():
        return None, False
    channel = channels_for(comp)
    early = importance < min_round
    if early:
        channel = major_networks_only(channel)
        if not channel:
            return None, True

    players = [c for c in comp.get("competitors") or [] if c.get("athlete") or c.get("team")]
    if len(players) < 2:
        return None, early
    a, b = players[0], players[1]
    status = _status(comp)
    finished = status == "FINISHED"
    return Match(
        competition=competition_name,
        competition_code=code,
        home=_player(a),
        away=_player(b),
        kickoff=local,
        status=status,
        home_score=_sets_won(a) if finished else None,
        away_score=_sets_won(b) if finished else None,
        stage=round_name,
        tv=tv,
        channel=channel,
        sport="tennis",
    ), early


def _importance(round_name: str | None) -> int | None:
    if not round_name:
        return None
    low = round_name.lower()
    exact = ROUND_ORDER.get(low.strip())
    if exact is not None:
        return exact
    for key, value in sorted(ROUND_ORDER.items(), key=lambda kv: -len(kv[0])):
        if key in low:
            return value
    return None


def _round_name(comp: dict[str, Any]) -> str | None:
    rnd = comp.get("round")
    if isinstance(rnd, dict):
        return rnd.get("displayName") or rnd.get("name")
    if isinstance(rnd, str):
        return rnd
    for note in comp.get("notes") or []:
        text = note.get("headline") or ""
        if text:
            return text
    return (comp.get("type") or {}).get("text")


def _player(competitor: dict[str, Any]) -> str:
    athlete = competitor.get("athlete") or competitor.get("team") or {}
    name = (athlete.get("shortName") or athlete.get("displayName") or "TBD").strip()
    seed = competitor.get("seed")
    try:
        seed = int(seed) if seed not in (None, "") else None
    except (TypeError, ValueError):
        seed = None
    return f"({seed}) {name}" if seed else name


def _sets_won(competitor: dict[str, Any]) -> int | None:
    scores = competitor.get("linescores") or []
    if not scores:
        return None
    # ESPN gives per-set games; count sets this player won when both sides are present.
    return None if not competitor.get("winner") and competitor.get("winner") is not False else (
        len([s for s in scores if s.get("winner")]) or None
    )


def _status(comp: dict[str, Any]) -> str:
    status_type = ((comp.get("status") or {}).get("type") or {})
    name = (status_type.get("name") or "").upper()
    state = (status_type.get("state") or "").lower()
    if "POSTPONED" in name:
        return "POSTPONED"
    if "CANCEL" in name:
        return "CANCELLED"
    if "SUSPEND" in name or "DELAY" in name or "RAIN" in name:
        return "SUSPENDED"
    if state == "in":
        return "IN_PLAY"
    if state == "post":
        return "FINISHED"
    if comp.get("timeValid") is False:
        return "SCHEDULED"
    return "TIMED"


def _slam_tv(tournament: str, broadcasters: dict[str, str]) -> str | None:
    low = tournament.lower()
    for key, value in broadcasters.items():
        if ":" in key and key.split(":", 1)[1].lower() in low:
            return value
    return None
