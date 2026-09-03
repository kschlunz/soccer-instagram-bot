import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.fixtures import normalise

SAMPLE = json.loads((Path(__file__).parent / "sample_matches.json").read_text())


def test_filters_to_local_day_in_utc():
    matches = normalise(SAMPLE, date(2026, 9, 5), ZoneInfo("UTC"), [])
    # The 01:00Z Santos match is on 6 Sept in UTC and must be excluded.
    assert len(matches) == 8
    assert all(m.kickoff.date() == date(2026, 9, 5) for m in matches)


def test_local_day_shifts_with_timezone():
    matches = normalise(SAMPLE, date(2026, 9, 5), ZoneInfo("America/New_York"), [])
    # In New York the 01:00Z match is still 5 Sept at 21:00, so all nine count.
    assert len(matches) == 9
    santos = next(m for m in matches if m.home == "Santos")
    assert santos.time_label() == "9:00 PM"
    assert santos.time_label(twelve_hour=False) == "21:00"
    assert santos.tv == "Fanatiz & TV Globo Internacional"


def test_competition_filter_and_labels():
    matches = normalise(SAMPLE, date(2026, 9, 5), ZoneInfo("Europe/London"), ["PL"])
    assert {m.competition_code for m in matches} == {"PL"}
    labels = {m.home: m.time_label(twelve_hour=False) for m in matches}
    assert labels["Arsenal"] == "12:30"  # BST
    assert labels["Everton"] == "PPD"


def test_ordering_groups_competitions_by_first_kickoff():
    matches = normalise(SAMPLE, date(2026, 9, 5), ZoneInfo("UTC"), [])
    comps = [m.competition for m in matches]
    # Premier League (11:30) first, then Primera Division (16:15), Bundesliga (17:30), Brasileiro
    assert comps == sorted(comps, key=comps.index)
    assert comps[0] == "Premier League"
    assert comps[-1] == "Brasileirão"
    tbd = next(m for m in matches if m.status == "SCHEDULED")
    assert tbd.time_label() == "TBD"


def test_every_free_tier_competition_has_a_us_broadcaster():
    from bot.fixtures import load_broadcasters

    tv = load_broadcasters()
    for code in ["PL", "ELC", "PD", "BL1", "SA", "FL1", "DED", "PPL", "CL", "EC", "WC", "BSA", "CLI"]:
        assert tv.get(code), code


def test_tz_label_and_time_format_config(monkeypatch):
    from bot.config import Config

    monkeypatch.setenv("TIMEZONE", "America/New_York")
    cfg = Config.from_env(require_secrets=False)
    assert cfg.tz_label(date(2026, 9, 5)) == "ET"
    assert cfg.twelve_hour is True

    monkeypatch.setenv("TIMEZONE", "Europe/London")
    monkeypatch.setenv("TIME_FORMAT", "24h")
    cfg = Config.from_env(require_secrets=False)
    assert cfg.tz_label(date(2026, 9, 5)) == "BST"
    assert cfg.tz_label(date(2026, 1, 5)) == "GMT"
    assert cfg.twelve_hour is False

    monkeypatch.setenv("TZ_LABEL", "EST")
    assert Config.from_env(require_secrets=False).tz_label(date(2026, 9, 5)) == "EST"


class _FakeResponse:
    def __init__(self, status, headers=None, payload=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload or {"matches": []}
        self.text = "rate limited" if status == 429 else ""

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers, params))
        return self.responses.pop(0)


def test_fetch_sends_auth_header_and_retries_after_429(monkeypatch):
    from bot import fixtures

    sleeps = []
    monkeypatch.setattr(fixtures.time, "sleep", lambda s: sleeps.append(s))
    session = _FakeSession([
        _FakeResponse(429, {"X-Requests-Available-Minute": "0", "X-RequestCounter-Reset": "7"}),
        _FakeResponse(200, {"X-Requests-Available-Minute": "9"}, SAMPLE),
    ])
    matches = fixtures.fetch_matches("tok", date(2026, 9, 5), ZoneInfo("UTC"), ["PL"], session=session)

    assert len(matches) == 4
    assert sleeps == [8]  # reset seconds + 1
    assert session.calls[0][1] == {"X-Auth-Token": "tok"}
    assert session.calls[0][2]["competitions"] == "PL"
    assert session.calls[0][2]["dateFrom"] == "2026-09-04"
    assert session.calls[0][2]["dateTo"] == "2026-09-06"


def test_fetch_raises_on_persistent_error():
    from bot import fixtures

    session = _FakeSession([_FakeResponse(403)])
    try:
        fixtures.fetch_matches("tok", date(2026, 9, 5), ZoneInfo("UTC"), session=session)
    except RuntimeError as err:
        assert "403" in str(err)
    else:
        raise AssertionError("expected RuntimeError")
