"""Refresh the long-lived Instagram access token.

Instagram-login tokens last 60 days and can be refreshed any time after they
are 24 hours old, which resets the clock to another 60 days. This prints the
refreshed token to a file so the workflow can store it back as a secret; it
never prints the token to stdout.
"""
from __future__ import annotations

import argparse
import os
import sys

import requests


def refresh(token: str, api_base: str) -> tuple[str, int]:
    if "graph.instagram.com" not in api_base:
        raise SystemExit(
            "Automatic refresh only supports tokens from 'Instagram API with Instagram Login' "
            "(IG_API_BASE on graph.instagram.com). Facebook-login tokens must be refreshed by hand."
        )
    host = api_base.split("/v")[0]  # strip the version segment
    response = requests.get(
        f"{host}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=30,
    )
    payload = response.json()
    if response.status_code != 200 or "access_token" not in payload:
        raise SystemExit(f"Refresh failed ({response.status_code}): {payload.get('error', payload)}")
    return payload["access_token"], int(payload.get("expires_in", 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the Instagram access token.")
    parser.add_argument("--out", required=True, help="File to write the refreshed token to")
    args = parser.parse_args(argv)

    token = os.environ.get("IG_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("IG_ACCESS_TOKEN is not set")
    api_base = os.environ.get("IG_API_BASE") or "https://graph.facebook.com/v21.0"

    new_token, expires_in = refresh(token, api_base)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(new_token)
    print(f"Token refreshed; new token valid for about {expires_in // 86400} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
