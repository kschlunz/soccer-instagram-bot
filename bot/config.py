from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


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
    timezone: str = "UTC"
    competitions: list[str] = field(default_factory=list)
    post_when_empty: bool = False
    images_branch: str = "soccer-bot-images"
    hashtags: str = "#soccer #football #matchday #fixtures"
    keep_days: int = 30

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_env(cls, require_secrets: bool = True) -> "Config":
        cfg = cls(
            football_token=os.environ.get("FOOTBALL_DATA_TOKEN", ""),
            ig_user_id=os.environ.get("IG_USER_ID", ""),
            ig_access_token=os.environ.get("IG_ACCESS_TOKEN", ""),
            ig_api_base=os.environ.get("IG_API_BASE") or cls.ig_api_base,
            timezone=os.environ.get("TIMEZONE") or "UTC",
            competitions=_csv(os.environ.get("COMPETITIONS")),
            post_when_empty=_bool(os.environ.get("POST_WHEN_EMPTY"), False),
            images_branch=os.environ.get("IMAGES_BRANCH") or "soccer-bot-images",
            hashtags=os.environ.get("HASHTAGS", cls.hashtags),
            keep_days=int(os.environ.get("IMAGES_KEEP_DAYS") or 30),
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
