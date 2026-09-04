"""CLI entry point: fetch fixtures, render images, publish to Instagram (feed + Stories)."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from .caption import build_caption, build_spotlight_caption, build_weekend_caption
from .config import Config
from .espn import enrich
from .espn_fixtures import WOMENS_LEAGUES, build_matches
from .fixtures import BROADCASTERS_FILE, Match, fetch_matches, load_broadcasters, normalise
from .hosting import already_published, publish_images, record_published, wait_until_public
from .instagram import InstagramClient, InstagramError
from .marquee import featured, tag_marquee
from .render import make_story_images, render_days, render_spotlight
from .spotlight import heading as spotlight_heading, pick as pick_spotlight

log = logging.getLogger("soccer-bot")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post today's fixtures to Instagram.")
    parser.add_argument("--date", help="Day to post, YYYY-MM-DD (default: today in TIMEZONE)")
    parser.add_argument("--mode", choices=["daily", "weekend", "spotlight"], default="daily",
                        help="daily: one day. weekend: preview of the coming Saturday and Sunday. "
                             "spotlight: one dedicated slide for today's final (see SPOTLIGHT_LEVEL)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render images and caption locally, do not push or post")
    parser.add_argument("--stories-only", action="store_true",
                        help="Skip the feed post and publish only the Stories")
    parser.add_argument("--force", action="store_true",
                        help="Post even if a post for this day/mode was already published")
    parser.add_argument("--out", default="out", help="Output directory for images (default: out)")
    parser.add_argument("--sample", help="Use a saved football-data.org JSON response instead of the API")
    parser.add_argument("--handle", help="Instagram handle to print in the image footer, e.g. @dailykickoffs")
    return parser.parse_args(argv)


def weekend_days(today: date) -> list[date]:
    """The coming Saturday and Sunday (today if it is already Saturday/Sunday)."""
    saturday = today + timedelta(days=(5 - today.weekday()) % 7)
    if today.weekday() == 6:  # Sunday: just today
        return [today]
    return [saturday, saturday + timedelta(days=1)]


def fetch_day(cfg: Config, day: date, broadcasters: dict[str, str], sample: str | None) -> list[Match]:
    tz = cfg.tz
    if sample:
        payload = json.loads(Path(sample).read_text())
        matches = normalise(payload, day, tz, cfg.competitions, broadcasters)
    elif cfg.profile == "womens":
        leagues = [l for l in WOMENS_LEAGUES if not cfg.competitions or l.code in cfg.competitions]
        matches = build_matches(leagues, day, tz, broadcasters)
    else:
        matches = fetch_matches(cfg.football_token, day, tz, cfg.competitions, broadcasters=broadcasters)
    if matches and cfg.espn_enrich and cfg.profile == "soccer" and not sample:
        matches = enrich(matches)
    return tag_marquee(matches)


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    cfg = Config.from_env(require_secrets=not args.dry_run)
    tz = cfg.tz
    today = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    days = weekend_days(today) if args.mode == "weekend" else [today]
    tz_label = cfg.tz_label(days[0])
    settings = cfg.settings

    broadcasters = load_broadcasters(BROADCASTERS_FILE.with_name(settings["broadcasters_file"]))
    day_matches = [(day, fetch_day(cfg, day, broadcasters, args.sample)) for day in days]
    total = sum(len(m) for _, m in day_matches)
    log.info("[%s/%s] %d matches across %s", cfg.profile, args.mode, total, ", ".join(d.isoformat() for d in days))

    if args.mode == "spotlight":
        game = pick_spotlight(day_matches[0][1], cfg.spotlight_level)
        if not game:
            log.info("No %s-level game today; no spotlight post.", cfg.spotlight_level)
            return 0
        log.info("Spotlight: %s v %s (%s)", game.home, game.away, game.marquee)
        out_dir = Path(args.out)
        stamp = f"{days[0].isoformat()}-spotlight"
        paths = render_spotlight(game, days[0], tz_label, out_dir, stamp, spotlight_heading(game), handle=args.handle,
                                 twelve_hour=cfg.twelve_hour, theme=settings.get("theme", "green"),
                                 tagline=settings.get("tagline") or None)
        caption = build_spotlight_caption(game, tz_label, cfg.hashtags, cfg.twelve_hour)
        (out_dir / f"{stamp}-caption.txt").write_text(caption, encoding="utf-8")
        story_paths = make_story_images(paths, settings.get("theme", "green"), 1) if cfg.post_stories else []
        return publish(cfg, settings, args, paths, story_paths, caption)

    if total == 0 and not cfg.post_when_empty:
        log.info("Nothing scheduled and POST_WHEN_EMPTY is off; nothing to post.")
        return 0

    # A one- or two-game day does not need a "Game of the day" slide.
    stars = featured([m for _, ms in day_matches for m in ms]) if total >= cfg.featured_min_games else []
    if stars:
        log.info("Marquee: %s", "; ".join(f"{m.home} v {m.away} ({m.marquee})" for m in stars))

    out_dir = Path(args.out)
    stamp = days[0].isoformat() + ("-weekend" if args.mode == "weekend" else "")
    title = settings["weekend_title"] if args.mode == "weekend" else settings["title"]
    paths = render_days(day_matches, tz_label, out_dir, stamp, handle=args.handle, twelve_hour=cfg.twelve_hour,
                        title=title, theme=settings.get("theme", "green"), tagline=settings.get("tagline") or None,
                        featured_games=stars)
    if args.mode == "weekend":
        caption = build_weekend_caption(day_matches, tz_label, cfg.hashtags, cfg.twelve_hour,
                                        settings["weekend_caption_title"], stars)
    else:
        caption = build_caption(day_matches[0][1], days[0], tz_label, cfg.hashtags, cfg.twelve_hour,
                                settings["caption_title"], stars)
    (out_dir / f"{stamp}-caption.txt").write_text(caption, encoding="utf-8")
    story_paths = make_story_images(paths, settings.get("theme", "green"), cfg.story_max) if cfg.post_stories else []
    return publish(cfg, settings, args, paths, story_paths, caption)


def publish(cfg: Config, settings: dict, args: argparse.Namespace, paths: list[Path],
            story_paths: list[Path], caption: str) -> int:
    """Host the images, publish the feed post (unless --stories-only) and the Stories."""
    log.info("Rendered %d slide(s) and %d story image(s) to %s", len(paths), len(story_paths), paths[0].parent)
    if args.dry_run:
        log.info("Dry run: skipping upload and Instagram publish.\n\n%s", caption)
        return 0

    stamp = paths[0].stem.rsplit("-", 1)[0]  # e.g. 2026-09-04, 2026-09-05-weekend, 2026-09-12-spotlight
    if not args.stories_only and not args.force and already_published(cfg.images_branch, settings["images_subdir"], stamp):
        log.info("A post for %s already went out (backup schedule or re-run); nothing to do. Use --force to repost.", stamp)
        return 0

    urls = publish_images(paths + story_paths, cfg.images_branch, keep_days=cfg.keep_days,
                          subdir=settings["images_subdir"])
    log.info("Hosted images:\n  %s", "\n  ".join(urls))
    wait_until_public(urls)
    feed_urls, story_urls = urls[: len(paths)], urls[len(paths):]

    client = InstagramClient(cfg.ig_access_token, cfg.ig_user_id, cfg.ig_api_base)
    if not args.stories_only:
        media_id = client.post_images(feed_urls, caption)
        log.info("Published Instagram feed post %s", media_id)
        record_published(cfg.images_branch, settings["images_subdir"], stamp, f"media {media_id}")

    failures = 0
    for url in story_urls:
        try:
            log.info("Published Story %s", client.post_story(url))
        except InstagramError as err:
            failures += 1
            log.error("Story failed: %s", err)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
