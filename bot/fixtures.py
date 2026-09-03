"""Fetch and normalise fixtures from football-data.org (v4)."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

API_URL = "https://api.football-data.org/v4/matches"
log = logging.getLogger("soccer-bot.fixtures")
BROADCASTERS_FILE = Path(__file__).parent / "data" / "us_broadcasters.json"

# football-data.org's official names are long or unfamiliar to US fans; show these instead.
DISPLAY_NAMES = {
    "PD": "La Liga",
    "BSA": "Brasileirão",
    "ELC": "Championship",
    "CLI": "Copa Libertadores",
    "EC": "European Championship",
    "WC": "World Cup",
}

# Statuses where the kickoff time is meaningful.
TIMED_STATUSES = {"TIMED", "IN_PLAY", "PAUSED", "FINISHED"}


@dataclass(frozen=True)
class Match:
    competition: str
    competition_code: str
    home: str
    away: str
    kickoff: datetime  # timezone-aware, already in the display timezone
    status: str
    home_score: int | None = None
    away_score: int | None = None
    stage: str | None = None
    tv: str | None = None  # where to watch (US broadcaster), if known

    def time_label(self, twelve_hour: bool = True) -> str:
        """Short label for the time column: kickoff time, or the state of the match."""
        if self.status == "TIMED":
            if twelve_hour:
                return self.kickoff.strftime("%I:%M %p").lstrip("0")
            return self.kickoff.strftime("%H:%M")
        if self.status in {"IN_PLAY", "PAUSED"}:
            return "LIVE"
        if self.status == "FINISHED":
            return "FT"
        if self.status == "POSTPONED":
            return "PPD"
        if self.status == "CANCELLED":
            return "CANC"
        if self.status == "SUSPENDED":
            return "SUSP"
        return "TBD"  # SCHEDULED: date known, kickoff time not yet confirmed

    @property
    def score_label(self) -> str | None:
        if self.home_score is None or self.away_score is None:
            return None
        return f"{self.home_score}-{self.away_score}"


def load_broadcasters(path: Path = BROADCASTERS_FILE) -> dict[str, str]:
    """Competition code -> where to watch in the USA."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {code.upper(): name for code, name in data.items() if not code.startswith("_")}


def fetch_matches(
    token: str,
    day: date,
    tz: ZoneInfo,
    competitions: Iterable[str] | None = None,
    session: requests.Session | None = None,
    broadcasters: dict[str, str] | None = None,
) -> list[Match]:
    """Return all matches that kick off on `day` in timezone `tz`.

    The API filters by UTC date, so we ask for a three-day window and filter
    locally; that keeps late-evening kickoffs on the right local day.
    """
    params: dict[str, str] = {
        "dateFrom": (day - timedelta(days=1)).isoformat(),
        "dateTo": (day + timedelta(days=1)).isoformat(),
    }
    comps = [c.upper() for c in (competitions or [])]
    if comps:
        params["competitions"] = ",".join(comps)

    http = session or requests.Session()
    response = _get_with_throttle(http, token, params)
    return normalise(response.json(), day, tz, comps, broadcasters)


def _get_with_throttle(http: requests.Session, token: str, params: dict[str, str],
                       max_attempts: int = 3) -> requests.Response:
    """GET honouring football-data.org's throttling headers.

    Every response carries X-Requests-Available-Minute (calls left this minute) and
    X-RequestCounter-Reset (seconds until the counter resets). A 429 means the
    quota is spent; wait for the reset and retry instead of hammering the API.
    """
    for attempt in range(1, max_attempts + 1):
        response = http.get(API_URL, headers={"X-Auth-Token": token}, params=params, timeout=30)
        available = response.headers.get("X-Requests-Available-Minute")
        reset = response.headers.get("X-RequestCounter-Reset")
        if available is not None:
            log.info("football-data.org quota: %s request(s) left this minute, resets in %ss", available, reset)

        if response.status_code == 429 and attempt < max_attempts:
            wait = min(_to_int(reset, default=60) + 1, 90)
            log.warning("Rate limited by football-data.org; waiting %ss before retry %d/%d",
                        wait, attempt + 1, max_attempts)
            time.sleep(wait)
            continue
        if response.status_code != 200:
            raise RuntimeError(
                f"football-data.org returned {response.status_code}: {response.text[:300]}"
            )
        return response
    raise AssertionError("unreachable")


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def normalise(
    payload: dict[str, Any],
    day: date,
    tz: ZoneInfo,
    competitions: list[str],
    broadcasters: dict[str, str] | None = None,
) -> list[Match]:
    if broadcasters is None:
        broadcasters = load_broadcasters()
    matches: list[Match] = []
    for raw in payload.get("matches", []):
        comp = raw.get("competition") or {}
        code = (comp.get("code") or "").upper()
        if competitions and code not in competitions:
            continue

        utc = datetime.fromisoformat(raw["utcDate"].replace("Z", "+00:00"))
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=timezone.utc)
        local = utc.astimezone(tz)
        if local.date() != day:
            continue

        score = (raw.get("score") or {}).get("fullTime") or {}
        matches.append(
            Match(
                competition=DISPLAY_NAMES.get(code) or comp.get("name") or code or "Unknown competition",
                competition_code=code,
                home=_team_name(raw.get("homeTeam")),
                away=_team_name(raw.get("awayTeam")),
                kickoff=local,
                status=raw.get("status") or "SCHEDULED",
                home_score=score.get("home"),
                away_score=score.get("away"),
                stage=raw.get("stage"),
                tv=broadcasters.get(code),
            )
        )

    # Group competitions together, earliest kickoff within each competition first,
    # competitions ordered by their earliest kickoff.
    first_kick: dict[str, datetime] = {}
    for m in matches:
        first_kick[m.competition] = min(first_kick.get(m.competition, m.kickoff), m.kickoff)
    matches.sort(key=lambda m: (first_kick[m.competition], m.competition, m.kickoff, m.home))
    return matches


def _team_name(team: dict[str, Any] | None) -> str:
    team = team or {}
    return team.get("shortName") or team.get("name") or team.get("tla") or "TBD"
