import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from bot import espn_fixtures as ef
from bot.caption import build_caption
from bot.config import Config
from bot.fixtures import Match, sort_matches
from bot.render import render_all

HERE = Path(__file__).parent
EVENTS = json.loads((HERE / "sample_espn_womens.json").read_text())["events"]
DAY = date(2026, 9, 5)
NY = ZoneInfo("America/New_York")


def test_events_to_matches_wnba_uses_away_at_home_and_channel():
    wnba = ef.League("WNBA", "basketball", "wnba", "WNBA")
    ms = ef.events_to_matches(EVENTS[:1], wnba, DAY, NY, tv="ESPN & friends")
    assert len(ms) == 1
    m = ms[0]
    assert m.display_pair() == ("Aces", "at", "Liberty")
    assert m.time_label() == "7:00 PM"
    assert m.channel == "ABC" and m.tv == "ESPN & friends" and m.sport == "basketball"


def test_nwsl_late_utc_kickoff_lands_on_local_day_and_reads_home_vs_away():
    nwsl = ef.League("NWSL", "soccer", "usa.nwsl", "NWSL")
    ms = ef.events_to_matches(EVENTS[1:2], nwsl, DAY, NY, tv=None)
    assert len(ms) == 1
    assert ms[0].display_pair() == ("Angel City", "vs", "Portland Thorns")
    assert ms[0].time_label() == "8:30 PM"
    # In London that game is on 6 Sept, so it must drop out.
    assert ef.events_to_matches(EVENTS[1:2], nwsl, DAY, ZoneInfo("Europe/London"), None) == []


def test_college_filters_to_national_tv_and_shows_ranks_and_final_scores():
    ncaa = ef.League("NCAAWVB", "volleyball", "womens-college-volleyball", "Volleyball", national_tv_only=True)
    ms = ef.events_to_matches(EVENTS[2:5], ncaa, DAY, NY, tv=None)
    assert len(ms) == 1  # no broadcast -> dropped; ESPN+ only -> dropped; ESPN2 -> kept
    m = ms[0]
    assert m.home == "#5 Stanford" and m.away == "#1 Texas"
    assert m.status == "FINISHED" and m.time_label() == "FT"
    assert m.display_pair() == ("#1 Texas", "1-3", "#5 Stanford")


def test_major_networks_only():
    assert ef.major_networks_only("ESPN+") is None
    assert ef.major_networks_only("SECN+") is None
    assert ef.major_networks_only("FS1") == "FS1"
    assert ef.major_networks_only("ESPN+ / ESPN2") == "ESPN2"
    assert ef.major_networks_only(None) is None


def test_tbd_and_previous_day_handling():
    wsl = ef.League("WSL", "soccer", "eng.w.1", "WSL")
    ms = ef.events_to_matches(EVENTS[5:7], wsl, DAY, NY, tv=None)
    assert [m.status for m in ms] == ["SCHEDULED"]
    assert ms[0].time_label() == "TBD"


def test_build_matches_skips_unknown_leagues(monkeypatch):
    calls = []

    def fake_fetch(sport, league, day, session=None, params=None):
        calls.append(league)
        if league == "bogus":
            raise ef.requests.HTTPError("404")
        return EVENTS[:2]

    monkeypatch.setattr(ef, "fetch_events", fake_fetch)
    leagues = [ef.League("X", "basketball", "bogus", "Bogus"), ef.League("WNBA", "basketball", "wnba", "WNBA")]
    ms = ef.build_matches(leagues, DAY, NY, {"WNBA": "ESPN"})
    assert calls == ["bogus", "wnba"]
    assert len(ms) == 2 and all(m.competition == "WNBA" for m in ms)


def test_womens_profile_config_and_render(monkeypatch, tmp_path):
    monkeypatch.setenv("PROFILE", "womens")
    monkeypatch.delenv("HASHTAGS", raising=False)
    cfg = Config.from_env(require_secrets=False)
    assert cfg.settings["title"] == "TODAY IN WOMEN'S SPORTS"
    assert cfg.hashtags.startswith("#womenssports")
    assert cfg.settings["broadcasters_file"] == "us_broadcasters_womens.json"

    wnba = ef.League("WNBA", "basketball", "wnba", "WNBA")
    nwsl = ef.League("NWSL", "soccer", "usa.nwsl", "NWSL")
    ms = sort_matches(ef.events_to_matches(EVENTS[:1], wnba, DAY, NY, "ESPN") + ef.events_to_matches(EVENTS[1:2], nwsl, DAY, NY, "CBS"))
    paths = render_all(ms, DAY, "ET", tmp_path, title=cfg.settings["title"])
    assert len(paths) == 1
    caption = build_caption(ms, DAY, "ET", cfg.hashtags, title=cfg.settings["caption_title"])
    assert caption.startswith("🏟️ Today in women's sports — Saturday, 5 September 2026")
    assert "7:00 PM  Aces at Liberty · ABC" in caption
    assert "8:30 PM  Angel City vs Portland Thorns · Paramount+" in caption


def test_soccer_profile_still_requires_football_token(monkeypatch):
    monkeypatch.setenv("PROFILE", "soccer")
    monkeypatch.setenv("IG_USER_ID", "1"); monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.delenv("FOOTBALL_DATA_TOKEN", raising=False)
    try:
        Config.from_env()
    except SystemExit as err:
        assert "FOOTBALL_DATA_TOKEN" in str(err)
    else:
        raise AssertionError("expected SystemExit")
    monkeypatch.setenv("PROFILE", "womens")
    assert Config.from_env().profile == "womens"  # no football token needed
