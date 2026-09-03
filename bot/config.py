from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

# Friendly labels for common US zones; these cover both standard and daylight time.
TZ_LABELS = {
    "America/New_York": "ET",
    "America/Chicago": "CT",
    "America/Denver": "MT",
    "America/Phoenix": "MT",
    "America/Los_Angeles": "PT",
}


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip().upper() for part in value.split(",") if part.strip()]


@dataclass
class Config:
    football_token: str
    ig_user_id: str
    ig_access_token: str
    ig_api_base: str = "https://graph.facebook.com/v21.0"
    timezone: str = "America/New_York"
    tz_label_override: str | None = None
    twelve_hour: bool = True
    competitions: list[str] = field(default_factory=list)
    post_when_empty: bool = False
    images_branch: str = "soccer-bot-images"
    hashtags: str = "#soccer #football #matchday #fixtures"
    keep_days: int = 30
    espn_enrich: bool = True

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def tz_label(self, day: date) -> str:
        """Label shown next to times, e.g. 'ET'. Falls back to the zone abbreviation for `day`."""
        if self.tz_label_override:
            return self.tz_label_override
        if self.timezone in TZ_LABELS:
            return TZ_LABELS[self.timezone]
        return datetime.combine(day, time(12), tzinfo=self.tz).strftime("%Z") or self.timezone

    @classmethod
    def from_env(cls, require_secrets: bool = True) -> "Config":
        cfg = cls(
            football_token=os.environ.get("FOOTBALL_DATA_TOKEN", ""),
            ig_user_id=os.environ.get("IG_USER_ID", ""),
            ig_access_token=os.environ.get("IG_ACCESS_TOKEN", ""),
            ig_api_base=os.environ.get("IG_API_BASE") or cls.ig_api_base,
            timezone=os.environ.get("TIMEZONE") or cls.timezone,
            tz_label_override=os.environ.get("TZ_LABEL") or None,
            twelve_hour=(os.environ.get("TIME_FORMAT") or "12h").strip().lower() != "24h",
            competitions=_csv(os.environ.get("COMPETITIONS")),
            post_when_empty=_bool(os.environ.get("POST_WHEN_EMPTY"), False),
            images_branch=os.environ.get("IMAGES_BRANCH") or "soccer-bot-images",
            hashtags=os.environ.get("HASHTAGS", cls.hashtags),
            keep_days=int(os.environ.get("IMAGES_KEEP_DAYS") or 30),
            espn_enrich=_bool(os.environ.get("ESPN_ENRICH"), True),
        )
        if require_secrets:
            missing = [
                name
                for name, value in (
                    ("FOOTBALL_DATA_TOKEN", cfg.football_token),
                    ("IG_USER_ID", cfg.ig_user_id),
                    ("IG_ACCESS_TOKEN", cfg.ig_access_token),
                )
                if not value
            ]
            if missing:
                raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
        # Validate the timezone early so a typo fails loudly.
        cfg.tz
        return cfg
