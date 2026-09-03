import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from bot import spotlight, tennis
from bot.caption import build_spotlight_caption
from bot.fixtures import BROADCASTERS_FILE, Match, load_broadcasters
from bot.marquee import tag_marquee
from bot.render import render_spotlight

NY = ZoneInfo("America/New_York")
BC = load_broadcasters(BROADCASTERS_FILE.with_name("us_broadcasters_womens.json"))


def _m(**kw) -> Match:
    base = dict(competition="US Open · Women's Singles", competition_code="WTA", home="(1) A. Sabalenka",
                away="(3) C. Gauff", kickoff=datetime(2026, 9, 12, 16, tzinfo=NY), status="TIMED",
                sport="tennis", tv="ESPN & ESPN+ (final on ABC)")
    base.update(kw)
    return Match(**base)


def test_levels_and_pick():
    final = tag_marquee([_m(stage="Final")])[0]
    semi = tag_marquee([_m(stage="Semifinals", home="I. Swiatek", away="N. Osaka")])[0]
    derby = tag_marquee([_m(competition_code="PD", competition="La Liga", home="Real Madrid", away="Barcelona",
                            sport="soccer", stage="REGULAR_SEASON")])[0]
    plain = _m(stage="Round 2")
    assert spotlight.level(final) == 3 and spotlight.level(semi) == 2 and spotlight.level(derby) == 1
    assert spotlight.level(plain) == 0

    assert spotlight.pick([plain, semi, derby]) is None                 # default: finals only
    assert spotlight.pick([plain, semi, derby], "semifinal") is semi
    assert spotlight.pick([plain, derby], "any") is derby
    assert spotlight.pick([final, semi]) is final
    assert spotlight.pick([tag_marquee([_m(stage="Final", home="TBD")])[0]]) is None   # finalists unknown yet
    assert spotlight.pick([tag_marquee([_m(stage="Final", status="FINISHED")])[0]]) is None
    assert spotlight.heading(final) == "THE FINAL" and spotlight.heading(semi) == "SEMIFINAL"
    assert spotlight.heading(derby) == "GAME OF THE DAY"


def test_wnba_finals_headline_counts_as_final():
    m = tag_marquee([_m(competition="WNBA", competition_code="WNBA", sport="basketball", home="Liberty",
                        away="Aces", stage="WNBA Finals - Game 3", tv="ESPN")])[0]
    assert spotlight.level(m) == 3


def test_render_and_caption(tmp_path):
    final = tag_marquee([_m(stage="Final", channel="ABC")])[0]
    paths = render_spotlight(final, date(2026, 9, 12), "ET", tmp_path, "2026-09-12-spotlight", "THE FINAL",
                             handle="@wgameday", theme="purple", tagline="What's on, when it's on")
    assert [p.name for p in paths] == ["2026-09-12-spotlight-1.jpg"]
    with Image.open(paths[0]) as img:
        assert img.size == (1080, 1350)
    caption = build_spotlight_caption(final, "ET", "#tennis")
    assert caption.splitlines()[0] == "🏆 US Open · Women's Singles — Final"
    assert "(1) A. Sabalenka vs (3) C. Gauff" in caption
    assert "🕒 Saturday, 12 September · 4:00 PM ET" in caption
    assert "📺 ABC" in caption and caption.endswith("#tennis")


def test_spotlight_mode_skips_quiet_days_and_posts_finals(monkeypatch, tmp_path):
    from bot import main as bot_main

    monkeypatch.setenv("PROFILE", "womens")
    monkeypatch.setenv("TIMEZONE", "America/New_York")
    quiet = tag_marquee([_m(stage="Round 2")])
    monkeypatch.setattr(bot_main, "fetch_day", lambda cfg, day, bc, sample: quiet)
    assert bot_main.run(["--mode", "spotlight", "--dry-run", "--date", "2026-09-12", "--out", str(tmp_path / "q")]) == 0
    assert not (tmp_path / "q").exists()

    final_day = tag_marquee([_m(stage="Final")])
    monkeypatch.setattr(bot_main, "fetch_day", lambda cfg, day, bc, sample: final_day)
    assert bot_main.run(["--mode", "spotlight", "--dry-run", "--date", "2026-09-12", "--out", str(tmp_path / "f")]) == 0
    names = sorted(p.name for p in (tmp_path / "f").iterdir())
    assert names == ["2026-09-12-spotlight-1-story.jpg", "2026-09-12-spotlight-1.jpg", "2026-09-12-spotlight-caption.txt"]
