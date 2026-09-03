"""CLI entry point: fetch today's fixtures, render images, publish to Instagram."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from .caption import build_caption
from .config import Config
from .espn import enrich
from .espn_fixtures import WOMENS_LEAGUES, build_matches
from .fixtures import BROADCASTERS_FILE, fetch_matches, load_broadcasters, normalise
from .hosting import publish_images, wait_until_public
from .instagram import InstagramClient
from .render import render_all

log = logging.getLogger("soccer-bot")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post today's soccer fixtures to Instagram.")
    parser.add_argument("--date", help="Day to post, YYYY-MM-DD (default: today in TIMEZONE)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render images and caption locally, do not push or post")
    parser.add_argument("--out", default="out", help="Output directory for images (default: out)")
    parser.add_argument("--sample", help="Use a saved football-data.org JSON response instead of the API")
    parser.add_argument("--handle", help="Instagram handle to print in the image footer, e.g. @dailykickoffs")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    cfg = Config.from_env(require_secrets=not args.dry_run)
    tz = cfg.tz
    day = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    tz_label = cfg.tz_label(day)

    broadcasters = load_broadcasters(BROADCASTERS_FILE.with_name(cfg.settings["broadcasters_file"]))
    if args.sample:
        payload = json.loads(Path(args.sample).read_text())
        matches = normalise(payload, day, tz, cfg.competitions, broadcasters)
    elif cfg.profile == "womens":
        leagues = [l for l in WOMENS_LEAGUES if not cfg.competitions or l.code in cfg.competitions]
        matches = build_matches(leagues, day, tz, broadcasters)
    else:
        matches = fetch_matches(cfg.football_token, day, tz, cfg.competitions, broadcasters=broadcasters)
    log.info("[%s] %d matches on %s (%s)", cfg.profile, len(matches), day, cfg.timezone)
    if matches and cfg.espn_enrich and cfg.profile == "soccer" and not args.sample:
        matches = enrich(matches)

    if not matches and not cfg.post_when_empty:
        log.info("No matches today and POST_WHEN_EMPTY is off; nothing to post.")
        return 0

    out_dir = Path(args.out)
    paths = render_all(matches, day, tz_label, out_dir, handle=args.handle, twelve_hour=cfg.twelve_hour,
                       title=cfg.settings["title"], theme=cfg.settings.get("theme", "green"),
                       tagline=cfg.settings.get("tagline") or None)
    caption = build_caption(matches, day, tz_label, cfg.hashtags, twelve_hour=cfg.twelve_hour,
                            title=cfg.settings["caption_title"])
    (out_dir / f"{day.isoformat()}-caption.txt").write_text(caption, encoding="utf-8")
    log.info("Rendered %d image(s) to %s", len(paths), out_dir)

    if args.dry_run:
        log.info("Dry run: skipping upload and Instagram publish.\n\n%s", caption)
        return 0

    urls = publish_images(paths, cfg.images_branch, keep_days=cfg.keep_days, subdir=cfg.settings["images_subdir"])
    log.info("Hosted images:\n  %s", "\n  ".join(urls))
    wait_until_public(urls)

    client = InstagramClient(cfg.ig_access_token, cfg.ig_user_id, cfg.ig_api_base)
    media_id = client.post_images(urls, caption)
    log.info("Published Instagram media %s", media_id)
    return 0


if __name__ == "__main__":
    sys.exit(run())
