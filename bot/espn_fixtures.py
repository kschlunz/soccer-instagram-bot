"""Build the day's schedule from ESPN scoreboards (used by the women's sports profile).

football-data.org has no women's competitions, so this profile uses ESPN's public
scoreboard feed as the source of fixtures as well as channels. Leagues whose slug
ESPN does not recognise are logged and skipped, so a bad entry never kills a post.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

from .espn import channels_for, fetch_events
from .fixtures import Match, sort_matches

log = logging.getLogger("soccer-bot.espn_fixtures")


# Linear/major networks that count as "on national TV". ESPN also tags conference streams
# (ESPN+, SECN+, ACCNX, BTN+, school YouTube channels...) as national, which would list
# every college game in the country; those are filtered out for national_tv_only leagues.
MAJOR_NETWORKS = {
    "ESPN", "ESPN2", "ESPNU", "ESPNEWS", "ABC",
    "FOX", "FS1", "FS2",
    "CBS", "CBS Sports Network",
    "NBC", "Peacock", "USA Network",
    "Big Ten Network", "BTN", "SEC Network", "ACC Network", "Big 12 Network",
    "Prime Video", "TNT", "TBS", "truTV", "ION", "NBA TV", "Paramount+", "Disney+",
}


@dataclass(frozen=True)
class League:
    code: str
    sport: str
    slug: str
    name: str
    national_tv_only: bool = False  # college sports: only list games on a major national network
    params: dict[str, str] = field(default_factory=dict)


WOMENS_LEAGUES: list[League] = [
    League("NWSL", "soccer", "usa.nwsl", "NWSL"),
    League("WSL", "soccer", "eng.w.1", "Women's Super League"),
    League("UWCL", "soccer", "uefa.wchampions", "Women's Champions League"),
    League("WWC", "soccer", "fifa.wwc", "Women's World Cup"),
    League("WEURO", "soccer", "uefa.weuro", "Women's Euro"),
    League("WINTL", "soccer", "fifa.friendly.w", "Women's Internationals"),
    League("LIGAF", "soccer", "esp.w.1", "Liga F"),
    League("WNBA", "basketball", "wnba", "WNBA"),
    League("NCAAWBB", "basketball", "womens-college-basketball", "Women's College Basketball",
           national_tv_only=True, params={"groups": "50"}),
    League("NCAAWVB", "volleyball", "womens-college-volleyball", "Women's College Volleyball",
           national_tv_only=True),
    League("NCAAWSB", "baseball", "college-softball", "College Softball", national_tv_only=True),
    League("NCAAWH", "hockey", "womens-college-hockey", "Women's College Hockey", national_tv_only=True),
    League("NCAAWLAX", "lacrosse", "womens-college-lacrosse", "Women's College Lacrosse",
           national_tv_only=True),
    # Not on ESPN's feed (400 Bad Request): Frauen-Bundesliga (ger.w.1), PWHL (pwhl).
]


def build_matches(
    leagues: Iterable[League],
    day: date,
    tz: ZoneInfo,
    broadcasters: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> list[Match]:
    """Fetch every league and return the matches that fall on `day` in `tz`, sorted."""
    broadcasters = broadcasters or {}
    http = session or requests.Session()
    matches: list[Match] = []
    for league in leagues:
        try:
            events = fetch_events(league.sport, league.slug, day, http, league.params)
        except (requests.RequestException, ValueError) as err:
            log.warning("Skipping %s (%s/%s): %s", league.name, league.sport, league.slug, err)
            continue
        matches.extend(events_to_matches(events, league, day, tz, broadcasters.get(league.code)))
    return sort_matches(matches)


def events_to_matches(
    events: list[dict[str, Any]], league: League, day: date, tz: ZoneInfo, tv: str | None
) -> list[Match]:
    out: list[Match] = []
    for event in events:
        try:
            comp = (event.get("competitions") or [{}])[0]
            raw_date = comp.get("date") or event.get("date")
            utc = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if utc.tzinfo is None:
                utc = utc.replace(tzinfo=timezone.utc)
            local = utc.astimezone(tz)
            if local.date() != day:
                continue

            home = away = None
            for c in comp.get("competitors") or []:
                if c.get("homeAway") == "home":
                    home = c
                elif c.get("homeAway") == "away":
                    away = c
            if not home or not away:
                continue

            channel = channels_for(comp)
            if league.national_tv_only:
                channel = major_networks_only(channel)
                if not channel:
                    continue

            status = _status(comp, event)
            finished = status == "FINISHED"
            out.append(
                Match(
                    competition=league.name,
                    competition_code=league.code,
                    home=_team_name(home),
                    away=_team_name(away),
                    kickoff=local,
                    status=status,
                    home_score=_score(home) if finished else None,
                    away_score=_score(away) if finished else None,
                    tv=tv,
                    channel=channel,
                    sport=league.sport,
                )
            )
        except (KeyError, IndexError, AttributeError, ValueError, TypeError) as err:
            log.warning("Skipping malformed ESPN event in %s: %s", league.name, err)
    return out


def major_networks_only(channel: str | None) -> str | None:
    """Keep only major national networks from a ' / '-joined channel string."""
    if not channel:
        return None
    kept = [c for c in (part.strip() for part in channel.split("/")) if c in MAJOR_NETWORKS]
    return " / ".join(kept) if kept else None


def _status(comp: dict[str, Any], event: dict[str, Any]) -> str:
    status_type = ((comp.get("status") or event.get("status") or {}).get("type") or {})
    name = (status_type.get("name") or "").upper()
    state = (status_type.get("state") or "").lower()
    if "POSTPONED" in name:
        return "POSTPONED"
    if "CANCEL" in name:
        return "CANCELLED"
    if "SUSPEND" in name:
        return "SUSPENDED"
    if state == "in":
        return "IN_PLAY"
    if state == "post":
        return "FINISHED"
    if comp.get("timeValid") is False or "TBD" in (status_type.get("detail") or "").upper():
        return "SCHEDULED"  # date known, kickoff not confirmed
    return "TIMED"


def _team_name(competitor: dict[str, Any]) -> str:
    team = competitor.get("team") or {}
    name = team.get("shortDisplayName") or team.get("displayName") or team.get("name") or "TBD"
    rank = (competitor.get("curatedRank") or {}).get("current")
    if isinstance(rank, int) and 1 <= rank <= 25:
        return f"#{rank} {name}"
    return name


def _score(competitor: dict[str, Any]) -> int | None:
    try:
        return int(float(competitor.get("score")))
    except (TypeError, ValueError):
        return None
