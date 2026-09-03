import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from bot.caption import MAX_CAPTION, build_caption
from bot.fixtures import Match, normalise
from bot.render import HEIGHT, MAX_PAGES, WIDTH, paginate, render_all

SAMPLE = json.loads((Path(__file__).parent / "sample_matches.json").read_text())
DAY = date(2026, 9, 5)


def _many_matches(n: int, per_league: int = 6) -> list[Match]:
    base = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    return [
        Match(competition=f"League {i // per_league}", competition_code=f"L{i // per_league}", home=f"Home {i}",
              away=f"Away {i}", kickoff=base + timedelta(minutes=15 * i), status="TIMED")
        for i in range(n)
    ]


def test_render_sample_single_page(tmp_path):
    matches = normalise(SAMPLE, DAY, ZoneInfo("UTC"), [])
    paths = render_all(matches, DAY, "UTC", tmp_path)
    assert [p.name for p in paths] == ["2026-09-05-1.jpg"]
    with Image.open(paths[0]) as img:
        assert img.format == "JPEG"
        assert img.size == (WIDTH, HEIGHT)


def test_render_empty_day(tmp_path):
    paths = render_all([], DAY, "UTC", tmp_path)
    assert len(paths) == 1 and paths[0].exists()


def test_pagination_repeats_header_and_caps_pages():
    pages = paginate(_many_matches(40))
    assert len(pages) > 1
    assert all(page[0].kind == "section" for page in pages)
    assert sum(1 for page in pages for line in page if line.kind == "match") == 40

    # One league with more matches than fit on a page is cut and gets a "(cont.)" header.
    pages = paginate(_many_matches(20, per_league=20))
    assert len(pages) == 2
    assert pages[1][0].kind == "section" and pages[1][0].text == "League 0 (cont.)"

    pages = paginate(_many_matches(400))
    assert len(pages) == MAX_PAGES
    assert pages[-1][-1].kind == "more"


def test_caption_lists_matches_and_respects_limit():
    matches = normalise(SAMPLE, DAY, ZoneInfo("UTC"), [])
    caption = build_caption(matches, DAY, "UTC", "#soccer")
    assert "Premier League" in caption
    assert "12:30  Arsenal vs Chelsea" not in caption  # UTC, not BST
    assert "11:30  Arsenal vs Chelsea" in caption
    assert caption.endswith("#soccer")

    long_caption = build_caption(_many_matches(300), DAY, "UTC", "#soccer #football")
    assert len(long_caption) <= MAX_CAPTION
    assert long_caption.endswith("#soccer #football")
