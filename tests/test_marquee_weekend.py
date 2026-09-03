import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from bot import espn_fixtures as ef
from bot.caption import build_caption, build_weekend_caption
from bot.fixtures import Match, normalise
from bot.main import weekend_days
from bot.marquee import featured, reason_for, tag_marquee
from bot.render import MAX_PAGES, STORY_HEIGHT, STORY_WIDTH, make_story_images, render_days

HERE = Path(__file__).parent
SAMPLE = json.loads((HERE / "sample_matches.json").read_text())
WOMENS = json.loads((HERE / "sample_espn_womens.json").read_text())["events"]
DAY = date(2026, 9, 5)
NY = ZoneInfo("America/New_York")


def _m(**kw) -> Match:
    base = dict(competition="X", competition_code="PL", home="A", away="B",
                kickoff=datetime(2026, 9, 5, 12, tzinfo=timezone.utc), status="TIMED")
    base.update(kw)
    return Match(**base)


def test_rivalries_rankings_and_knockouts_are_marquee():
    tagged = {m.home: m for m in tag_marquee(normalise(SAMPLE, DAY, NY, []))}
    assert tagged["Real Madrid"].marquee == "El Clásico"
    assert tagged["Sevilla"].marquee == "Seville Derby"
    assert tagged["Bayern"].marquee == "Der Klassiker"
    assert tagged["Everton"].marquee == "Merseyside Derby"
    assert tagged["Arsenal"].marquee == "London Derby"
    assert tagged["Wolverhampton"].marquee is None

    riv = {}
    assert reason_for(_m(home="#3 Nebraska", away="#12 Iowa", competition_code="NCAAWVB"), riv) == "Ranked matchup: #3 vs #12"
    assert reason_for(_m(home="#2 Texas", away="Rice", competition_code="NCAAWVB"), riv) is None  # one ranked side is not enough
    assert reason_for(_m(home="#20 Baylor", away="Rice", competition_code="NCAAWVB"), riv) is None
    assert reason_for(_m(stage="SEMI_FINALS", competition_code="CL"), riv) == "Semifinal"
    assert reason_for(_m(stage="NWSL Playoffs - Semifinal", competition_code="NWSL"), riv) == "NWSL Playoffs - Semifinal"
    assert reason_for(_m(stage="Round of 16", competition_code="CL"), riv) is None
    assert reason_for(_m(stage="REGULAR_SEASON"), riv) is None


def test_featured_skips_postponed_and_caps_at_three():
    ms = tag_marquee(normalise(SAMPLE, DAY, NY, []))
    picks = featured(ms)
    assert len(picks) == 3
    assert all(m.status != "POSTPONED" for m in picks)  # Everton v Liverpool (PPD) excluded
    assert [m.kickoff for m in picks] == sorted(m.kickoff for m in picks)


def test_espn_headline_becomes_stage():
    ev = json.loads(json.dumps(WOMENS[0]))
    ev["competitions"][0]["notes"] = [{"type": "event", "headline": "WNBA Finals - Game 3"}]
    wnba = ef.League("WNBA", "basketball", "wnba", "WNBA")
    m = ef.events_to_matches([ev], wnba, DAY, NY, None)[0]
    assert m.stage == "WNBA Finals - Game 3"
    assert tag_marquee([m])[0].marquee == "WNBA Finals - Game 3"


def test_render_days_with_featured_slide_and_stories(tmp_path):
    ms = tag_marquee(normalise(SAMPLE, DAY, NY, []))
    stars = featured(ms)
    paths = render_days([(DAY, ms)], "ET", tmp_path, "2026-09-05", handle="@x", featured_games=stars, theme="purple")
    assert [p.name for p in paths] == ["2026-09-05-1.jpg", "2026-09-05-2.jpg"]  # featured + one schedule page

    stories = make_story_images(paths, "purple", limit=3)
    assert [p.name for p in stories] == ["2026-09-05-1-story.jpg", "2026-09-05-2-story.jpg"]
    with Image.open(stories[0]) as img:
        assert img.size == (STORY_WIDTH, STORY_HEIGHT)

    # single featured game uses the stacked layout without error
    one = render_days([(DAY, ms)], "ET", tmp_path, "solo", featured_games=stars[:1])
    assert len(one) == 2


def test_weekend_carousel_numbers_pages_across_days_and_caps(tmp_path):
    sat = normalise(SAMPLE, DAY, NY, [])
    sun = [Match(competition="League", competition_code="L", home=f"H{i}", away=f"A{i}",
                 kickoff=datetime(2026, 9, 6, 15, tzinfo=NY) + timedelta(minutes=i), status="TIMED") for i in range(200)]
    paths = render_days([(DAY, sat), (DAY + timedelta(days=1), sun)], "ET", tmp_path, "2026-09-05-weekend",
                        featured_games=featured(tag_marquee(sat)))
    assert len(paths) == MAX_PAGES  # never more than Instagram's carousel limit

    caption = build_weekend_caption([(DAY, sat), (DAY + timedelta(days=1), sun[:2])], "ET", "#x", True,
                                    "📅 Weekend preview", featured(tag_marquee(sat)))
    assert caption.startswith("📅 Weekend preview — Sat 5–Sun 6 September")
    assert "📅 Saturday, 5 September" in caption and "📅 Sunday, 6 September" in caption
    assert "⭐ Games of the day" in caption
    assert "Sat 7:30 AM" in caption  # weekday shown on featured lines for multi-day previews
    assert len(caption) <= 2200


def test_daily_caption_marks_marquee_rows():
    ms = tag_marquee(normalise(SAMPLE, DAY, NY, []))
    caption = build_caption(ms, DAY, "ET", "", True, "⚽ Today's matches", featured(ms))
    assert "⭐ Games of the day" in caption
    assert "Arsenal vs Chelsea — London Derby · 7:30 AM" in caption
    assert "⭐ 3:00 PM  Real Madrid vs Barça" in caption  # marquee but not in the top three by kickoff


def test_weekend_days():
    assert weekend_days(date(2026, 9, 3)) == [date(2026, 9, 5), date(2026, 9, 6)]   # Thursday
    assert weekend_days(date(2026, 9, 4)) == [date(2026, 9, 5), date(2026, 9, 6)]   # Friday
    assert weekend_days(date(2026, 9, 5)) == [date(2026, 9, 5), date(2026, 9, 6)]   # Saturday
    assert weekend_days(date(2026, 9, 6)) == [date(2026, 9, 6)]                      # Sunday


def test_featured_slide_needs_enough_games(monkeypatch, tmp_path):
    """With fewer than FEATURED_MIN_GAMES games the run renders no featured slide."""
    from bot import main as bot_main

    monkeypatch.setenv("PROFILE", "soccer")
    monkeypatch.setenv("TIMEZONE", "UTC")
    few = [_m(home="Real Madrid", away="Barcelona", competition_code="PD", competition="La Liga")]
    many = few + [_m(home=f"H{i}", away=f"A{i}") for i in range(3)]

    monkeypatch.setattr(bot_main, "fetch_day", lambda cfg, day, bc, sample: tag_marquee(few))
    assert bot_main.run(["--dry-run", "--date", "2026-09-05", "--out", str(tmp_path / "few")]) == 0
    assert sorted(p.name for p in (tmp_path / "few").glob("*.jpg")) == ["2026-09-05-1-story.jpg", "2026-09-05-1.jpg"]

    monkeypatch.setattr(bot_main, "fetch_day", lambda cfg, day, bc, sample: tag_marquee(many))
    assert bot_main.run(["--dry-run", "--date", "2026-09-05", "--out", str(tmp_path / "many")]) == 0
    assert "2026-09-05-2.jpg" in {p.name for p in (tmp_path / "many").glob("*.jpg")}  # featured + schedule
