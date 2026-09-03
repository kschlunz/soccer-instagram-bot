"""Build the Instagram caption for a day's fixtures."""
from __future__ import annotations

from datetime import date
from typing import Sequence

from .fixtures import Match

MAX_CAPTION = 2200  # Instagram limit


def build_caption(matches: Sequence[Match], day: date, tz_label: str, hashtags: str = "") -> str:
    title = day.strftime("%A, %d %B %Y").replace(" 0", " ")
    lines = [f"⚽ Today's matches — {title}", f"🕒 All times {tz_label}", ""]

    if not matches:
        lines.append("No matches scheduled today. Rest day!")
    else:
        current = None
        for m in matches:
            if m.competition != current:
                if current is not None:
                    lines.append("")
                lines.append(f"🏆 {m.competition}")
                current = m.competition
            middle = m.score_label or "vs"
            lines.append(f"{m.time_label}  {m.home} {middle} {m.away}")

    body = "\n".join(lines).rstrip()
    footer = f"\n\n{hashtags.strip()}" if hashtags.strip() else ""

    if len(body) + len(footer) > MAX_CAPTION:
        note = "\n… (more matches than fit in the caption)"
        budget = MAX_CAPTION - len(footer) - len(note)
        body = body[:budget].rsplit("\n", 1)[0] + note
    return body + footer
