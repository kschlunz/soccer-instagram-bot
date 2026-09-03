"""Render fixture lists to Instagram-ready JPEG images (1080x1350, 4:5)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .fixtures import Match

WIDTH, HEIGHT = 1080, 1350
MARGIN = 72
HEADER_HEIGHT = 250
FOOTER_HEIGHT = 110
SECTION_HEADER_H = 74
ROW_H = 66
MAX_PAGES = 10  # Instagram carousel limit

BG = (11, 29, 42)
BG_STRIPE = (14, 38, 54)
ACCENT = (34, 197, 94)
TEXT = (245, 247, 250)
MUTED = (150, 165, 180)
TIME_BG = (18, 52, 72)

FONT_DIRS = [
    os.environ.get("FONT_DIR", ""),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    "/usr/local/share/fonts",
    "/Library/Fonts",
    "C:/Windows/Fonts",
]


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"] if bold else [
        "DejaVuSans.ttf",
        "Arial.ttf",
        "arial.ttf",
    ]
    for directory in FONT_DIRS:
        if not directory:
            continue
        for name in names:
            path = Path(directory) / name
            if path.exists():
                return ImageFont.truetype(str(path), size)
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


@dataclass
class _Line:
    kind: str  # "section" | "match" | "more"
    text: str = ""
    match: Match | None = None


def paginate(matches: Sequence[Match], max_pages: int = MAX_PAGES) -> list[list[_Line]]:
    """Split matches into pages, repeating a competition header when it is cut."""
    usable = HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT
    pages: list[list[_Line]] = []
    current: list[_Line] = []
    used = 0
    current_comp: str | None = None

    for index, match in enumerate(matches):
        needs_header = match.competition != current_comp
        needed = ROW_H + (SECTION_HEADER_H if needs_header else 0)
        if used + needed > usable:
            pages.append(current)
            if len(pages) == max_pages:
                remaining = len(matches) - index
                last = pages[-1]
                if last and last[-1].kind == "match":
                    last.pop()  # make room for the overflow note
                    remaining += 1
                last.append(_Line("more", f"+{remaining} more \u2014 full list in the caption"))
                return pages
            current, used = [], 0
            needs_header = True
            needed = ROW_H + SECTION_HEADER_H
            label = f"{match.competition} (cont.)" if match.competition == current_comp else match.competition
        else:
            label = match.competition
        if needs_header:
            current.append(_Line("section", label))
            current_comp = match.competition
        current.append(_Line("match", match=match))
        used += needed
    if current:
        pages.append(current)
    return pages


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _draw_header(draw: ImageDraw.ImageDraw, day: date, page: int, total: int) -> None:
    title_font = _font(True, 64)
    sub_font = _font(False, 34)
    draw.rectangle([0, 0, WIDTH, HEADER_HEIGHT], fill=BG)
    draw.rectangle([MARGIN, 84, MARGIN + 14, 84 + 130], fill=ACCENT)
    draw.text((MARGIN + 40, 78), "TODAY'S MATCHES", font=title_font, fill=TEXT)
    date_text = day.strftime("%A, %-d %B %Y") if os.name != "nt" else day.strftime("%A, %d %B %Y")
    draw.text((MARGIN + 40, 160), date_text, font=sub_font, fill=MUTED)
    if total > 1:
        pf = _font(True, 30)
        label = f"{page}/{total}"
        w = draw.textlength(label, font=pf)
        draw.text((WIDTH - MARGIN - w, 92), label, font=pf, fill=ACCENT)


def _draw_footer(draw: ImageDraw.ImageDraw, tz_label: str, handle: str | None) -> None:
    font = _font(False, 28)
    y = HEIGHT - FOOTER_HEIGHT + 30
    draw.line([MARGIN, y - 22, WIDTH - MARGIN, y - 22], fill=BG_STRIPE, width=2)
    draw.text((MARGIN, y), f"All times {tz_label}", font=font, fill=MUTED)
    if handle:
        w = draw.textlength(handle, font=font)
        draw.text((WIDTH - MARGIN - w, y), handle, font=font, fill=MUTED)


def render_page(
    lines: Sequence[_Line], day: date, page: int, total: int, tz_label: str, handle: str | None
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, day, page, total)

    section_font = _font(True, 30)
    time_font = _font(True, 30)
    team_font = _font(False, 32)
    vs_font = _font(False, 24)
    more_font = _font(False, 30)

    y = HEADER_HEIGHT
    time_col_w = 150
    text_x = MARGIN + time_col_w + 28
    text_w = WIDTH - MARGIN - text_x
    stripe = False

    for line in lines:
        if line.kind == "section":
            y += 18
            draw.text((MARGIN, y + 6), line.text.upper(), font=section_font, fill=ACCENT)
            draw.line([MARGIN, y + SECTION_HEADER_H - 22, WIDTH - MARGIN, y + SECTION_HEADER_H - 22], fill=ACCENT, width=2)
            y += SECTION_HEADER_H - 18
            stripe = False
        elif line.kind == "match":
            m = line.match
            assert m is not None
            if stripe:
                draw.rectangle([MARGIN - 16, y, WIDTH - MARGIN + 16, y + ROW_H], fill=BG_STRIPE)
            stripe = not stripe
            # Time pill
            label = m.time_label
            pill_top, pill_bottom = y + 12, y + ROW_H - 12
            draw.rounded_rectangle([MARGIN, pill_top, MARGIN + time_col_w, pill_bottom], radius=10, fill=TIME_BG)
            tw = draw.textlength(label, font=time_font)
            draw.text((MARGIN + (time_col_w - tw) / 2, pill_top + 6), label, font=time_font, fill=ACCENT if label != "TBD" else MUTED)
            # Teams
            vs = m.score_label or "vs"
            vs_w = draw.textlength(f"  {vs}  ", font=vs_font)
            side_w = (text_w - vs_w) / 2
            home = _ellipsize(draw, m.home, team_font, int(side_w))
            away = _ellipsize(draw, m.away, team_font, int(side_w))
            hw = draw.textlength(home, font=team_font)
            text_y = y + 14
            draw.text((text_x + side_w - hw, text_y), home, font=team_font, fill=TEXT)
            draw.text((text_x + side_w + (vs_w - draw.textlength(vs, font=vs_font)) / 2, text_y + 6), vs, font=vs_font, fill=MUTED)
            draw.text((text_x + side_w + vs_w, text_y), away, font=team_font, fill=TEXT)
            y += ROW_H
        elif line.kind == "more":
            y += 18
            draw.text((MARGIN, y), line.text, font=more_font, fill=MUTED)
            y += ROW_H

    _draw_footer(draw, tz_label, handle)
    return img


def render_empty(day: date, tz_label: str, handle: str | None) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, day, 1, 1)
    font = _font(True, 44)
    msg = "No matches scheduled today"
    w = draw.textlength(msg, font=font)
    draw.text(((WIDTH - w) / 2, HEIGHT / 2 - 40), msg, font=font, fill=TEXT)
    sub = _font(False, 30)
    msg2 = "Rest day. Back tomorrow."
    w2 = draw.textlength(msg2, font=sub)
    draw.text(((WIDTH - w2) / 2, HEIGHT / 2 + 30), msg2, font=sub, fill=MUTED)
    _draw_footer(draw, tz_label, handle)
    return img


def render_all(
    matches: Sequence[Match], day: date, tz_label: str, out_dir: Path, handle: str | None = None
) -> list[Path]:
    """Render every page for `day` into `out_dir` and return the JPEG paths in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = day.isoformat()
    pages = paginate(matches) if matches else []
    images = (
        [render_page(lines, day, i + 1, len(pages), tz_label, handle) for i, lines in enumerate(pages)]
        if pages
        else [render_empty(day, tz_label, handle)]
    )
    paths: list[Path] = []
    for i, img in enumerate(images, start=1):
        path = out_dir / f"{stamp}-{i}.jpg"
        # Instagram's publishing API only accepts JPEG.
        img.save(path, "JPEG", quality=92, optimize=True)
        paths.append(path)
    return paths
