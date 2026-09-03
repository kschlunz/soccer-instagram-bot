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
STORY_WIDTH, STORY_HEIGHT = 1080, 1920  # Instagram Stories are 9:16
MARGIN = 72
HEADER_HEIGHT = 250
FOOTER_HEIGHT = 110
SECTION_HEADER_H = 74
ROW_H = 66
ROW_H_WITH_CHANNEL = 92  # two lines: teams, then the exact US channel underneath
MAX_PAGES = 10  # Instagram carousel limit

def _hex(code: str) -> tuple[int, int, int]:
    code = code.lstrip("#")
    return int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16)


@dataclass(frozen=True)
class Theme:
    bg: tuple[int, int, int]
    stripe: tuple[int, int, int]      # alternating row background
    accent: tuple[int, int, int]      # brand colour: title bar, section headers, tagline
    text: tuple[int, int, int]        # team names
    muted: tuple[int, int, int]       # date, "vs", footer, competition TV line
    time_bg: tuple[int, int, int]     # kickoff chip background
    time_text: tuple[int, int, int]   # kickoff chip text
    rule: tuple[int, int, int]        # section divider line
    highlight: tuple[int, int, int]   # per-match channel line
    live_bg: tuple[int, int, int]     # kickoff chip background while a game is in progress


THEMES = {
    # Soccer: deep navy with pitch green
    "green": Theme(
        bg=(11, 29, 42), stripe=(14, 38, 54), accent=(34, 197, 94), text=(245, 247, 250),
        muted=(150, 165, 180), time_bg=(18, 52, 72), time_text=(34, 197, 94),
        rule=(34, 197, 94), highlight=(150, 165, 180), live_bg=(18, 52, 72),
    ),
    # W GAMEDAY brand: #8048B8 purple, #7038A0 darker states, #9858D0 highlights only,
    # near-black background, white primary text.
    "purple": Theme(
        bg=(8, 8, 12), stripe=(18, 14, 26), accent=_hex("#8048B8"), text=(255, 255, 255),
        muted=(178, 170, 196), time_bg=_hex("#7038A0"), time_text=(255, 255, 255),
        rule=_hex("#7038A0"), highlight=_hex("#9858D0"), live_bg=_hex("#9858D0"),
    ),
}
DEFAULT_THEME = THEMES["green"]

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
    tv: str | None = None


def paginate(matches: Sequence[Match], max_pages: int = MAX_PAGES) -> list[list[_Line]]:
    """Split matches into pages, repeating a competition header when it is cut."""
    usable = HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT
    pages: list[list[_Line]] = []
    current: list[_Line] = []
    used = 0
    current_comp: str | None = None
    fully_covered = {
        comp for comp in {m.competition for m in matches}
        if all(m.channel for m in matches if m.competition == comp)
    }

    for index, match in enumerate(matches):
        needs_header = match.competition != current_comp
        row_h = _row_h(match)
        needed = row_h + (SECTION_HEADER_H if needs_header else 0)
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
            needed = row_h + SECTION_HEADER_H
            label = f"{match.competition} (cont.)" if match.competition == current_comp else match.competition
        else:
            label = match.competition
        if needs_header:
            current.append(_Line("section", label, tv=None if match.competition in fully_covered else match.tv))
            current_comp = match.competition
        current.append(_Line("match", match=match))
        used += needed
    if current:
        pages.append(current)
    return pages


def _row_h(match: Match) -> int:
    return ROW_H_WITH_CHANNEL if match.channel else ROW_H


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _draw_header(
    draw: ImageDraw.ImageDraw,
    day: date,
    page: int,
    total: int,
    title: str = "TODAY'S MATCHES",
    th: Theme = DEFAULT_THEME,
    tagline: str | None = None,
    date_text: str | None = None,
) -> None:
    sub_font = _font(False, 34)
    draw.rectangle([0, 0, WIDTH, HEADER_HEIGHT], fill=th.bg)
    draw.rectangle([MARGIN, 84, MARGIN + 14, 84 + 130], fill=th.accent)
    # Shrink long titles until they clear the page indicator on the right.
    max_w = WIDTH - (MARGIN + 40) - MARGIN - (110 if total > 1 else 0)
    size = 64
    title_font = _font(True, size)
    while size > 36 and draw.textlength(title, font=title_font) > max_w:
        size -= 2
        title_font = _font(True, size)
    draw.text((MARGIN + 40, 78 + (64 - size) // 2), title, font=title_font, fill=th.text)
    if not date_text:
        date_text = day.strftime("%A, %-d %B %Y") if os.name != "nt" else day.strftime("%A, %d %B %Y")
    draw.text((MARGIN + 40, 160), date_text, font=sub_font, fill=th.muted)
    if tagline:
        tag_font = _font(True, 22)
        draw.text((MARGIN + 40, 212), tagline.upper(), font=tag_font, fill=th.accent)
    if total > 1:
        pf = _font(True, 30)
        label = f"{page}/{total}"
        w = draw.textlength(label, font=pf)
        draw.text((WIDTH - MARGIN - w, 92), label, font=pf, fill=th.accent)


def _draw_footer(draw: ImageDraw.ImageDraw, tz_label: str, handle: str | None, th: Theme = DEFAULT_THEME) -> None:
    font = _font(False, 28)
    y = HEIGHT - FOOTER_HEIGHT + 30
    draw.line([MARGIN, y - 22, WIDTH - MARGIN, y - 22], fill=th.stripe, width=2)
    draw.text((MARGIN, y), f"All times {tz_label}", font=font, fill=th.muted)
    if handle:
        w = draw.textlength(handle, font=font)
        draw.text((WIDTH - MARGIN - w, y), handle, font=font, fill=th.muted)


def render_page(
    lines: Sequence[_Line],
    day: date,
    page: int,
    total: int,
    tz_label: str,
    handle: str | None,
    twelve_hour: bool = True,
    title: str = "TODAY'S MATCHES",
    th: Theme = DEFAULT_THEME,
    tagline: str | None = None,
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), th.bg)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, day, page, total, title, th, tagline)

    section_font = _font(True, 30)
    tv_font = _font(False, 22)
    time_font = _font(True, 28)
    team_font = _font(False, 32)
    vs_font = _font(False, 24)
    channel_font = _font(False, 22)
    more_font = _font(False, 30)

    y = HEADER_HEIGHT
    time_col_w = 190 if twelve_hour else 150
    text_x = MARGIN + time_col_w + 28
    text_w = WIDTH - MARGIN - text_x
    stripe = False

    for line in lines:
        if line.kind == "section":
            y += 18
            name_max_w = WIDTH - 2 * MARGIN
            if line.tv:
                tv_text = _ellipsize(draw, f"TV: {line.tv}", tv_font, (WIDTH - 2 * MARGIN) // 2)
                tv_w = draw.textlength(tv_text, font=tv_font)
                draw.text((WIDTH - MARGIN - tv_w, y + 14), tv_text, font=tv_font, fill=th.muted)
                name_max_w -= int(tv_w) + 24
            name = _ellipsize(draw, line.text.upper(), section_font, name_max_w)
            draw.text((MARGIN, y + 6), name, font=section_font, fill=th.accent)
            draw.line([MARGIN, y + SECTION_HEADER_H - 22, WIDTH - MARGIN, y + SECTION_HEADER_H - 22], fill=th.rule, width=2)
            y += SECTION_HEADER_H - 18
            stripe = False
        elif line.kind == "match":
            m = line.match
            assert m is not None
            row_h = _row_h(m)
            if stripe:
                draw.rectangle([MARGIN - 16, y, WIDTH - MARGIN + 16, y + row_h], fill=th.stripe)
            stripe = not stripe
            # Time pill (kept at the standard height, vertically aligned with the team line)
            label = m.time_label(twelve_hour)
            pill_top, pill_bottom = y + 12, y + ROW_H - 12
            draw.rounded_rectangle([MARGIN, pill_top, MARGIN + time_col_w, pill_bottom], radius=10,
                                   fill=th.live_bg if label == "LIVE" else th.time_bg)
            tw = draw.textlength(label, font=time_font)
            draw.text((MARGIN + (time_col_w - tw) / 2, pill_top + 6), label, font=time_font, fill=th.time_text)
            # Teams: "Home vs Away" for soccer, "Away at Home" for US sports
            left_name, vs, right_name = m.display_pair()
            if m.marquee:
                left_name = f"\u2605 {left_name}"
            vs_w = draw.textlength(f"  {vs}  ", font=vs_font)
            side_w = (text_w - vs_w) / 2
            left = _ellipsize(draw, left_name, team_font, int(side_w))
            right = _ellipsize(draw, right_name, team_font, int(side_w))
            lw = draw.textlength(left, font=team_font)
            text_y = y + 14
            draw.text((text_x + side_w - lw, text_y), left, font=team_font, fill=th.text)
            draw.text((text_x + side_w + (vs_w - draw.textlength(vs, font=vs_font)) / 2, text_y + 6), vs, font=vs_font, fill=th.muted)
            draw.text((text_x + side_w + vs_w, text_y), right, font=team_font, fill=th.text)
            if m.channel:
                ch = _ellipsize(draw, m.channel, channel_font, text_w)
                cw = draw.textlength(ch, font=channel_font)
                draw.text((text_x + (text_w - cw) / 2, y + ROW_H - 10), ch, font=channel_font, fill=th.highlight)
            y += row_h
        elif line.kind == "more":
            y += 18
            draw.text((MARGIN, y), line.text, font=more_font, fill=th.muted)
            y += ROW_H

    _draw_footer(draw, tz_label, handle, th)
    return img


def render_empty(
    day: date,
    tz_label: str,
    handle: str | None,
    title: str = "TODAY'S MATCHES",
    th: Theme = DEFAULT_THEME,
    tagline: str | None = None,
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), th.bg)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, day, 1, 1, title, th, tagline)
    font = _font(True, 44)
    msg = "Nothing scheduled today"
    w = draw.textlength(msg, font=font)
    draw.text(((WIDTH - w) / 2, HEIGHT / 2 - 40), msg, font=font, fill=th.text)
    sub = _font(False, 30)
    msg2 = "Rest day. Back tomorrow."
    w2 = draw.textlength(msg2, font=sub)
    draw.text(((WIDTH - w2) / 2, HEIGHT / 2 + 30), msg2, font=sub, fill=th.muted)
    _draw_footer(draw, tz_label, handle, th)
    return img


def _fit_font(draw: ImageDraw.ImageDraw, text: str, bold: bool, size: int, max_w: int, min_size: int = 30):
    font = _font(bold, size)
    while size > min_size and draw.textlength(text, font=font) > max_w:
        size -= 2
        font = _font(bold, size)
    return font


def render_featured(
    games: Sequence[Match],
    day: date,
    tz_label: str,
    handle: str | None,
    twelve_hour: bool,
    th: Theme,
    tagline: str | None,
    page: int,
    total: int,
    show_day: bool = False,
    date_text: str | None = None,
) -> Image.Image:
    """Big-type slide for up to three marquee games."""
    img = Image.new("RGB", (WIDTH, HEIGHT), th.bg)
    draw = ImageDraw.Draw(img)
    heading = "GAME OF THE DAY" if len(games) == 1 else "GAMES OF THE DAY"
    if show_day:
        heading = "MARQUEE MATCHUPS" if len(games) > 1 else "MARQUEE MATCHUP"
    _draw_header(draw, day, page, total, heading, th, tagline, date_text)

    usable_top, usable_bottom = HEADER_HEIGHT + 20, HEIGHT - FOOTER_HEIGHT - 20
    block_h = (usable_bottom - usable_top) // max(len(games), 1)
    comp_font = _font(True, 26)
    reason_font = _font(True, 30)
    info_font = _font(False, 32)
    vs_font = _font(False, 34)
    max_w = WIDTH - 2 * MARGIN

    for i, m in enumerate(games):
        top = usable_top + i * block_h
        centre_y = top + block_h / 2
        if i > 0:
            draw.line([MARGIN, top, WIDTH - MARGIN, top], fill=th.stripe, width=2)

        left, mid, right = m.display_pair()
        if block_h >= 700:      # single game: stack the two names
            name_font = _fit_font(draw, max(left, right, key=len), True, 84, max_w, 44)
            lines = [(left, name_font, th.text), (mid, vs_font, th.muted), (right, name_font, th.text)]
        else:                   # two or three games: one line each
            one_line = f"{left}  {mid}  {right}"
            name_font = _fit_font(draw, one_line, True, 60, max_w, 32)
            lines = [(one_line, name_font, th.text)]

        # Measure the whole block so it can be vertically centred
        heights = [26 + 14, *(f.size + 10 for _, f, _ in lines), 30 + 12, 32]
        y = centre_y - sum(heights) / 2
        comp = m.competition.upper()
        draw.text(((WIDTH - draw.textlength(comp, font=comp_font)) / 2, y), comp, font=comp_font, fill=th.accent)
        y += heights[0]
        for text, font, colour in lines:
            draw.text(((WIDTH - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=colour)
            y += font.size + 10
        reason = (m.marquee or "").upper()
        draw.text(((WIDTH - draw.textlength(reason, font=reason_font)) / 2, y), reason, font=reason_font, fill=th.highlight)
        y += 30 + 12
        when = m.time_label(twelve_hour)
        if show_day and m.status == "TIMED":
            when = f"{m.kickoff.strftime('%a')} {when}"
        info = f"{when}  ·  {m.channel or m.tv}" if (m.channel or m.tv) else when
        draw.text(((WIDTH - draw.textlength(info, font=info_font)) / 2, y), info, font=info_font, fill=th.muted)

    _draw_footer(draw, tz_label, handle, th)
    return img


def render_spotlight(
    m: Match,
    day: date,
    tz_label: str,
    out_dir: Path,
    stamp: str,
    heading: str,
    handle: str | None = None,
    twelve_hour: bool = True,
    theme: str = "green",
    tagline: str | None = None,
) -> list[Path]:
    """One big slide for a single game: competition, the two sides, the round, time and channel."""
    out_dir.mkdir(parents=True, exist_ok=True)
    th = THEMES.get(theme, DEFAULT_THEME)
    img = Image.new("RGB", (WIDTH, HEIGHT), th.bg)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, day, 1, 1, heading, th, tagline)

    max_w = WIDTH - 2 * MARGIN
    left, mid, right = m.display_pair()
    comp_font = _font(True, 34)
    name_font = _fit_font(draw, max(left, right, key=len), True, 104, max_w, 48)
    vs_font = _font(False, 44)
    stage_font = _font(True, 34)
    when_font = _font(True, 40)
    tv_font = _font(False, 36)

    stage = (m.marquee or m.stage or "").upper()
    when = m.time_label(twelve_hour)
    if m.status == "TIMED":
        when = f"{m.kickoff.strftime('%A')} \u00b7 {when} {tz_label}"
    where = m.channel or m.tv

    blocks = [
        (m.competition.upper(), comp_font, th.accent, 24),
        (left, name_font, th.text, 8),
        (mid, vs_font, th.muted, 8),
        (right, name_font, th.text, 40),
        (stage, stage_font, th.highlight, 36),
        (when, when_font, th.text, 16),
    ]
    if where:
        blocks.append((f"TV: {where}", tv_font, th.muted, 0))
    total_h = sum(f.size + gap for _, f, _, gap in blocks)
    y = HEADER_HEIGHT + (HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT - total_h) / 2
    for text, font, colour, gap in blocks:
        text = _ellipsize(draw, text, font, max_w)
        draw.text(((WIDTH - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=colour)
        y += font.size + gap
    # accent rules above and below the names block for a poster feel
    draw.line([MARGIN, HEADER_HEIGHT + 10, WIDTH - MARGIN, HEADER_HEIGHT + 10], fill=th.rule, width=3)
    _draw_footer(draw, tz_label, handle, th)

    path = out_dir / f"{stamp}-1.jpg"
    img.save(path, "JPEG", quality=92, optimize=True)
    return [path]


def render_days(
    day_matches: Sequence[tuple[date, Sequence[Match]]],
    tz_label: str,
    out_dir: Path,
    stamp: str,
    handle: str | None = None,
    twelve_hour: bool = True,
    title: str = "TODAY'S MATCHES",
    theme: str = "green",
    tagline: str | None = None,
    featured_games: Sequence[Match] = (),
) -> list[Path]:
    """Render a carousel covering one or more days, optionally led by a featured slide."""
    out_dir.mkdir(parents=True, exist_ok=True)
    th = THEMES.get(theme, DEFAULT_THEME)
    multi_day = len(day_matches) > 1
    budget = MAX_PAGES - (1 if featured_games else 0)

    # Paginate each day, then trim to the carousel budget.
    pages: list[tuple[date, list[_Line]]] = []
    for day, matches in day_matches:
        for lines in (paginate(matches, max_pages=budget) if matches else []):
            pages.append((day, lines))
    if len(pages) > budget:
        dropped = sum(1 for _, lines in pages[budget:] for l in lines if l.kind == "match")
        pages = pages[:budget]
        last = pages[-1][1]
        if last and last[-1].kind == "match":
            last.pop()
            dropped += 1
        last.append(_Line("more", f"+{dropped} more \u2014 full list in the caption"))

    total = len(pages) + (1 if featured_games else 0) if pages or featured_games else 1
    images: list[Image.Image] = []
    first_day = day_matches[0][0]
    if featured_games:
        span = None
        if multi_day:
            last_day = day_matches[-1][0]
            span = f"{first_day.strftime('%a %d')} \u2013 {last_day.strftime('%a %d %B %Y')}".replace(" 0", " ")
        images.append(render_featured(featured_games, first_day, tz_label, handle, twelve_hour, th, tagline,
                                      1, total, show_day=multi_day, date_text=span))
    for i, (day, lines) in enumerate(pages):
        images.append(render_page(lines, day, len(images) + 1, total, tz_label, handle, twelve_hour, title, th, tagline))
    if not images:
        images.append(render_empty(first_day, tz_label, handle, title, th, tagline))

    paths: list[Path] = []
    for i, img in enumerate(images, start=1):
        path = out_dir / f"{stamp}-{i}.jpg"
        img.save(path, "JPEG", quality=92, optimize=True)  # Instagram only accepts JPEG
        paths.append(path)
    return paths


def render_all(
    matches: Sequence[Match],
    day: date,
    tz_label: str,
    out_dir: Path,
    handle: str | None = None,
    twelve_hour: bool = True,
    title: str = "TODAY'S MATCHES",
    theme: str = "green",
    tagline: str | None = None,
    featured_games: Sequence[Match] = (),
) -> list[Path]:
    """Render every page for `day` into `out_dir` and return the JPEG paths in order."""
    return render_days([(day, matches)], tz_label, out_dir, day.isoformat(), handle, twelve_hour,
                       title, theme, tagline, featured_games)


def make_story_images(paths: Sequence[Path], theme: str = "green", limit: int = 3) -> list[Path]:
    """Place carousel slides on a 9:16 canvas for Stories, keeping them inside the safe zone."""
    th = THEMES.get(theme, DEFAULT_THEME)
    out: list[Path] = []
    for path in list(paths)[:limit]:
        with Image.open(path) as slide:
            canvas = Image.new("RGB", (STORY_WIDTH, STORY_HEIGHT), th.bg)
            canvas.paste(slide, (0, (STORY_HEIGHT - slide.height) // 2))
        story_path = path.with_name(f"{path.stem}-story.jpg")
        canvas.save(story_path, "JPEG", quality=92, optimize=True)
        out.append(story_path)
    return out
