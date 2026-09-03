"""Per-match US broadcaster lookup via ESPN's public scoreboard feed.

ESPN's site API is free and needs no key, but it is undocumented, so every call
here is best effort: any failure just means a match keeps the competition-level
"where to watch" line instead of an exact channel.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable

import requests

from .fixtures import Match

log = logging.getLogger("soccer-bot.espn")

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"

# football-data.org competition code -> ESPN league slug
ESPN_LEAGUES = {
    "PL": "eng.1",
    "ELC": "eng.2",
    "PD": "esp.1",
    "BL1": "ger.1",
    "SA": "ita.1",
    "FL1": "fra.1",
    "DED": "ned.1",
    "PPL": "por.1",
    "CL": "uefa.champions",
    "EC": "uefa.euro",
    "WC": "fifa.world",
    "BSA": "bra.1",
    "CLI": "conmebol.libertadores",
}

# ESPN's short network names -> how we want them printed
NETWORK_NAMES = {
    "USA Net": "USA Network",
    "USA": "USA Network",
    "CBSSN": "CBS Sports Network",
    "beIN SPORTS": "beIN Sports",
    "beIN Sports": "beIN Sports",
    "ESPN Unlmtd": "ESPN Unlimited",
    "CBSSN": "CBS Sports Network",
    "ESPN Deportes": None,  # Spanish-language feeds are skipped
    "Telemundo": None,
    "Universo": None,
    "UniMás": None,
    "TUDN": None,
    "ViX": None,
}

# Spanish-language US networks sometimes come through tagged as English; drop them by prefix.
SPANISH_PREFIXES = ("tele", "univ", "tudn", "vix", "fox deportes", "espn deportes", "galavis", "unimas", "unimás")

# Linear/major networks that count as "on national TV". ESPN also tags conference streams
# (ESPN+, SECN+, ACCNX, BTN+, school YouTube channels...) as national, which would list
# every college game in the country; those are filtered out for national-TV-only leagues.
MAJOR_NETWORKS = {
    "ESPN", "ESPN2", "ESPNU", "ESPNEWS", "ABC",
    "FOX", "FS1", "FS2",
    "CBS", "CBS Sports Network",
    "NBC", "Peacock", "USA Network",
    "Big Ten Network", "BTN", "SEC Network", "ACC Network", "Big 12 Network",
    "Prime Video", "TNT", "TBS", "truTV", "ION", "NBA TV", "Paramount+", "Disney+",
}




def major_networks_only(channel: str | None) -> str | None:
    """Keep only major national networks from a ' / '-joined channel string."""
    if not channel:
        return None
    kept = [c for c in (part.strip() for part in channel.split("/")) if c in MAJOR_NETWORKS]
    return " / ".join(kept) if kept else None


KICKOFF_TOLERANCE = timedelta(minutes=10)


def fetch_events(
    sport: str,
    league: str,
    day: date,
    session: requests.Session | None = None,
    params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Raw ESPN events for one league across the UTC day before/after `day`. Raises on failure."""
    http = session or requests.Session()
    span = f"{(day - timedelta(days=1)):%Y%m%d}-{(day + timedelta(days=1)):%Y%m%d}"
    query = {"dates": span, "limit": 300, **(params or {})}
    response = http.get(SCOREBOARD_URL.format(sport=sport, league=league), params=query, timeout=20)
    response.raise_for_status()
    events = response.json().get("events") or []
    log.info("ESPN %s/%s: %d events", sport, league, len(events))
    return events


def fetch_broadcasts(
    codes: Iterable[str], day: date, session: requests.Session | None = None
) -> list[dict[str, Any]]:
    """Return ESPN soccer events for the given football-data.org competitions around `day`."""
    events: list[dict[str, Any]] = []
    for code in sorted(set(codes)):
        league = ESPN_LEAGUES.get(code)
        if not league:
            continue
        try:
            events.extend(fetch_events("soccer", league, day, session))
        except (requests.RequestException, ValueError) as err:
            log.warning("ESPN lookup failed for %s (%s): %s", code, league, err)
    return events


def enrich(matches: list[Match], session: requests.Session | None = None) -> list[Match]:
    """Attach a per-match US broadcaster where ESPN lists one. Never raises."""
    if not matches:
        return matches
    try:
        day = matches[0].kickoff.date()
        events = fetch_broadcasts({m.competition_code for m in matches}, day, session)
        return apply_broadcasts(matches, events)
    except Exception as err:  # noqa: BLE001 - enrichment must never break the post
        log.warning("ESPN enrichment skipped: %s", err)
        return matches


def apply_broadcasts(matches: list[Match], events: list[dict[str, Any]]) -> list[Match]:
    parsed = [e for e in (_parse_event(ev) for ev in events) if e]
    out: list[Match] = []
    hits = 0
    for m in matches:
        channel = _find_channel(m, parsed)
        if channel:
            hits += 1
            out.append(replace(m, channel=channel))
        else:
            out.append(m)
    log.info("ESPN: found a US broadcaster for %d of %d matches", hits, len(matches))
    return out


# -- helpers ---------------------------------------------------------------

def channels_for(comp: dict[str, Any]) -> str | None:
    """Public alias: national English-language US broadcaster(s) listed for a competition."""
    return _channels(comp)


def _parse_event(event: dict[str, Any]) -> dict[str, Any] | None:
    try:
        comp = (event.get("competitions") or [{}])[0]
        raw_date = comp.get("date") or event.get("date")
        kickoff = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        home = away = ""
        for c in comp.get("competitors") or []:
            team = c.get("team") or {}
            name = team.get("displayName") or team.get("shortDisplayName") or team.get("name") or ""
            if c.get("homeAway") == "home":
                home = name
            elif c.get("homeAway") == "away":
                away = name
        return {"kickoff": kickoff, "home": home, "away": away, "channel": _channels(comp)}
    except (KeyError, IndexError, AttributeError, ValueError, TypeError):
        return None


def _channels(comp: dict[str, Any]) -> str | None:
    names: list[str] = []
    for gb in comp.get("geoBroadcasts") or []:
        if (gb.get("region") or "us").lower() != "us":
            continue
        if (gb.get("lang") or "en").lower() != "en":
            continue
        if ((gb.get("market") or {}).get("type") or "National").lower() != "national":
            continue
        names.append(((gb.get("media") or {}).get("shortName") or "").strip())
    if not names:
        for b in comp.get("broadcasts") or []:
            if (b.get("market") or "national").lower() == "national":
                names.extend(n.strip() for n in b.get("names") or [])
    cleaned: list[str] = []
    for n in names:
        if not n or n.lower().startswith(SPANISH_PREFIXES):
            continue
        mapped = NETWORK_NAMES.get(n, n)
        if mapped and mapped not in cleaned:
            cleaned.append(mapped)
    return " / ".join(cleaned[:2]) if cleaned else None


def _norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    stop = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "sd", "rcd", "club", "de", "the", "1", "04", "05", "09", "96"}
    return " ".join(t for t in name.split() if t not in stop)


def _similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _find_channel(m: Match, events: list[dict[str, Any]]) -> str | None:
    best, best_score = None, 0.0
    for ev in events:
        if not ev["channel"]:
            continue
        if abs(ev["kickoff"] - m.kickoff) > KICKOFF_TOLERANCE:
            continue
        score = _similar(m.home, ev["home"]) + _similar(m.away, ev["away"])
        if score > best_score:
            best, best_score = ev, score
    # Same kickoff plus one clearly matching side (or two plausible sides) is enough.
    if best and best_score >= 1.2:
        return best["channel"]
    return None
