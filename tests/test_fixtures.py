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
    assert santos.time_label == "21:00"


def test_competition_filter_and_labels():
    matches = normalise(SAMPLE, date(2026, 9, 5), ZoneInfo("Europe/London"), ["PL"])
    assert {m.competition_code for m in matches} == {"PL"}
    labels = {m.home: m.time_label for m in matches}
    assert labels["Arsenal"] == "12:30"  # BST
    assert labels["Everton"] == "PPD"


def test_ordering_groups_competitions_by_first_kickoff():
    matches = normalise(SAMPLE, date(2026, 9, 5), ZoneInfo("UTC"), [])
    comps = [m.competition for m in matches]
    # Premier League (11:30) first, then Primera Division (16:15), Bundesliga (17:30), Brasileiro
    assert comps == sorted(comps, key=comps.index)
    assert comps[0] == "Premier League"
    assert comps[-1].startswith("Campeonato")
    tbd = next(m for m in matches if m.status == "SCHEDULED")
    assert tbd.time_label == "TBD"
