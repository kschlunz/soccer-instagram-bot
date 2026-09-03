"""Build the Instagram caption for a day's fixtures."""
from __future__ import annotations

from datetime import date
from typing import Sequence

from .fixtures import Match

MAX_CAPTION = 2200  # Instagram limit


def build_caption(
    matches: Sequence[Match], day: date, tz_label: str, hashtags: str = "", twelve_hour: bool = True
) -> str:
    title = day.strftime("%A, %d %B %Y").replace(" 0", " ")
    lines = [f"⚽ Today's matches — {title}", f"🕒 All times {tz_label}", ""]

    if not matches:
        lines.append("No matches scheduled today. Rest day!")
    else:
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
            middle = m.score_label or "vs"
            row = f"{m.time_label(twelve_hour)}  {m.home} {middle} {m.away}"
            if m.channel:
                row += f" · {m.channel}"
            lines.append(row)

    body = "\n".join(lines).rstrip()
    footer = f"\n\n{hashtags.strip()}" if hashtags.strip() else ""

    if len(body) + len(footer) > MAX_CAPTION:
        note = "\n… (more matches than fit in the caption)"
        budget = MAX_CAPTION - len(footer) - len(note)
        body = body[:budget].rsplit("\n", 1)[0] + note
    return body + footer
