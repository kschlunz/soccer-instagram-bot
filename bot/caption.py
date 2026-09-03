"""Build the Instagram caption for a day's fixtures."""
from __future__ import annotations

from datetime import date
from typing import Sequence

from .fixtures import Match

MAX_CAPTION = 2200  # Instagram limit


def _match_lines(matches: Sequence[Match], twelve_hour: bool) -> list[str]:
    lines: list[str] = []
    # Show the competition-level "where to watch" only when some match lacks its own channel.
    fully_covered = {
        comp for comp in {m.competition for m in matches}
        if all(m.channel for m in matches if m.competition == comp)
    }
    current = None
    for m in matches:
        if m.competition != current:
            if current is not None:
                lines.append("")
            lines.append(f"🏆 {m.competition}")
            if m.tv and m.competition not in fully_covered:
                lines.append(f"📺 {m.tv}")
            current = m.competition
        left, middle, right = m.display_pair()
        row = f"{'⭐ ' if m.marquee else ''}{m.time_label(twelve_hour)}  {left} {middle} {right}"
        if m.channel:
            row += f" · {m.channel}"
        lines.append(row)
    return lines


def _featured_lines(games: Sequence[Match], twelve_hour: bool, show_day: bool) -> list[str]:
    if not games:
        return []
    lines = ["⭐ Game of the day" if len(games) == 1 else "⭐ Games of the day"]
    for m in games:
        left, middle, right = m.display_pair()
        when = m.time_label(twelve_hour)
        if show_day and m.status == "TIMED":
            when = f"{m.kickoff.strftime('%a')} {when}"
        where = f" · {m.channel or m.tv}" if (m.channel or m.tv) else ""
        lines.append(f"{left} {middle} {right} — {m.marquee} · {when}{where}")
    lines.append("")
    return lines


def build_caption(
    matches: Sequence[Match],
    day: date,
    tz_label: str,
    hashtags: str = "",
    twelve_hour: bool = True,
    title: str = "⚽ Today's matches",
    featured_games: Sequence[Match] = (),
) -> str:
    date_text = day.strftime("%A, %d %B %Y").replace(" 0", " ")
    lines = [f"{title} — {date_text}", f"🕒 All times {tz_label}", ""]
    lines += _featured_lines(featured_games, twelve_hour, show_day=False)
    if not matches:
        lines.append("Nothing scheduled today. Rest day!")
    else:
        lines += _match_lines(matches, twelve_hour)
    return _finish(lines, hashtags)


def build_weekend_caption(
    day_matches: Sequence[tuple[date, Sequence[Match]]],
    tz_label: str,
    hashtags: str = "",
    twelve_hour: bool = True,
    title: str = "📅 Weekend preview",
    featured_games: Sequence[Match] = (),
) -> str:
    first, last = day_matches[0][0], day_matches[-1][0]
    span = f"{first.strftime('%a %d')}–{last.strftime('%a %d %B')}".replace(" 0", " ")
    lines = [f"{title} — {span}", f"🕒 All times {tz_label}", ""]
    lines += _featured_lines(featured_games, twelve_hour, show_day=True)
    any_games = False
    for day, matches in day_matches:
        lines.append(f"📅 {day.strftime('%A, %d %B').replace(' 0', ' ')}")
        if matches:
            any_games = True
            lines += _match_lines(matches, twelve_hour)
        else:
            lines.append("Nothing scheduled.")
        lines.append("")
    if not any_games:
        lines.append("Quiet weekend. Back next week!")
    return _finish(lines, hashtags)


def _finish(lines: list[str], hashtags: str) -> str:
    body = "\n".join(lines).rstrip()
    footer = f"\n\n{hashtags.strip()}" if hashtags.strip() else ""

    if len(body) + len(footer) > MAX_CAPTION:
        note = "\n… (more matches than fit in the caption)"
        budget = MAX_CAPTION - len(footer) - len(note)
        body = body[:budget].rsplit("\n", 1)[0] + note
    return body + footer
