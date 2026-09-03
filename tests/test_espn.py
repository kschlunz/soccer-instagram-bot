import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from bot import espn
from bot.caption import build_caption
from bot.fixtures import normalise
from bot.render import paginate

HERE = Path(__file__).parent
SAMPLE = json.loads((HERE / "sample_matches.json").read_text())
ESPN = json.loads((HERE / "sample_espn.json").read_text())
DAY = date(2026, 9, 5)


def _matches():
    return normalise(SAMPLE, DAY, ZoneInfo("America/New_York"), [])


def test_apply_broadcasts_matches_by_kickoff_and_team_names():
    enriched = espn.apply_broadcasts(_matches(), ESPN["events"])
    by_home = {m.home: m for m in enriched}
    assert by_home["Arsenal"].channel == "USA Network / Peacock"      # simulcast, Spanish feed dropped
    assert by_home["Wolverhampton"].channel == "Peacock"               # short vs long name still matches
    assert by_home["Man City"].channel == "NBC"
    assert by_home["Real Madrid"].channel is None                      # no broadcasts listed, decoy ignored
    assert by_home["Sevilla"].channel is None                          # not in ESPN feed at all
    assert by_home["Everton"].channel is None


def test_enrich_never_raises_on_network_failure():
    class BrokenSession:
        def get(self, *a, **k):
            raise espn.requests.ConnectionError("offline")

    matches = _matches()
    assert espn.enrich(matches, session=BrokenSession()) == matches


def test_channels_appear_in_caption_and_hide_redundant_competition_line():
    enriched = espn.apply_broadcasts(_matches(), ESPN["events"])
    caption = build_caption(enriched, DAY, "ET", "")
    assert "7:30 AM  Arsenal vs Chelsea · USA Network / Peacock" in caption
    # Premier League still has a match without a channel (Everton PPD), so the fallback line stays.
    assert "📺 NBC, USA Network & Peacock" in caption
    # La Liga has an unmatched game too, so its fallback line stays.
    assert "📺 ESPN+ (select games on ESPN/ABC)" in caption

    only_covered = [m for m in enriched if m.channel]
    caption2 = build_caption(only_covered, DAY, "ET", "")
    assert "📺" not in caption2
    pages = paginate(only_covered)
    assert all(line.tv is None for page in pages for line in page if line.kind == "section")


def test_league_map_covers_free_tier():
    for code in ["PL", "ELC", "PD", "BL1", "SA", "FL1", "DED", "PPL", "CL", "BSA", "CLI"]:
        assert code in espn.ESPN_LEAGUES


def test_spanish_networks_are_dropped_even_when_tagged_english():
    comp = {"geoBroadcasts": [
        {"market": {"type": "National"}, "media": {"shortName": "USA Net"}, "lang": "en", "region": "us"},
        {"market": {"type": "National"}, "media": {"shortName": "Tele"}, "lang": "en", "region": "us"},
        {"market": {"type": "National"}, "media": {"shortName": "Universo"}, "lang": "en", "region": "us"},
    ]}
    assert espn.channels_for(comp) == "USA Network"
