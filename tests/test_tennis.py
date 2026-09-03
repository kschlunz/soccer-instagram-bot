import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from bot import tennis
from bot.caption import build_caption
from bot.fixtures import BROADCASTERS_FILE, load_broadcasters
from bot.marquee import tag_marquee

EVENTS = json.loads((Path(__file__).parent / "sample_espn_wta.json").read_text())["events"]
NY = ZoneInfo("America/New_York")
BC = load_broadcasters(BROADCASTERS_FILE.with_name("us_broadcasters_womens.json"))


def test_us_open_semis_kept_early_rounds_and_doubles_dropped():
    ms = tennis.events_to_matches(EVENTS, date(2026, 9, 3), NY, BC)
    names = [(m.competition, m.home, m.away, m.time_label()) for m in ms]
    assert ("US Open · Women's Singles", "(1) A. Sabalenka", "(3) C. Gauff", "7:00 PM") in names
    assert ("US Open · Women's Singles", "(2) I. Swiatek", "N. Osaka", "8:30 PM") in names
    assert not any("P. A" in n for n in names)            # round of 32 at a Slam: skipped
    assert not any("Team X" in n for n in names)          # doubles: skipped
    assert not any("P. C" in n for n in names)            # round of 16 at a non-Slam: skipped
    assert any("(4) P. E" in n for n in names)            # quarterfinal at a non-Slam: kept
    us_open = [m for m in ms if m.competition.startswith("US Open")]
    assert all(m.tv == "ESPN & ESPN+ (final on ABC)" for m in us_open)
    assert all(m.sport == "tennis" and m.display_pair()[1] == "vs" for m in ms)
    other = [m for m in ms if m.competition.startswith("Guadalajara")]
    assert other[0].tv == "Tennis Channel"


def test_semifinals_are_marquee_and_caption_reads_well():
    ms = tag_marquee(tennis.events_to_matches(EVENTS, date(2026, 9, 3), NY, BC))
    semis = [m for m in ms if m.stage == "Semifinals"]
    assert len(semis) == 2 and all(m.marquee == "Semifinals" for m in semis)
    caption = build_caption(ms, date(2026, 9, 3), "ET", "", True, "🏟️ Today in women's sports")
    assert "🏆 US Open · Women's Singles" in caption
    assert "⭐ 7:00 PM  (1) A. Sabalenka vs (3) C. Gauff" in caption
