"""Minimal Instagram Graph API client for publishing image and carousel posts."""
from __future__ import annotations

import time
from typing import Any, Sequence

import requests


class InstagramError(RuntimeError):
    pass


class InstagramClient:
    def __init__(
        self,
        access_token: str,
        user_id: str,
        api_base: str = "https://graph.facebook.com/v21.0",
        session: requests.Session | None = None,
    ) -> None:
        self.token = access_token
        self.user_id = user_id
        self.base = api_base.rstrip("/")
        self.http = session or requests.Session()

    # -- low level -----------------------------------------------------------
    def _request(self, method: str, path: str, **params: Any) -> dict[str, Any]:
        params["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        response = self.http.request(method, url, params=params if method == "GET" else None,
                                     data=None if method == "GET" else params, timeout=60)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400 or "error" in payload:
            err = payload.get("error", payload)
            raise InstagramError(f"{method} {path} failed ({response.status_code}): {err}")
        return payload

    # -- containers ----------------------------------------------------------
    def create_image_container(self, image_url: str, caption: str | None = None,
                               is_carousel_item: bool = False) -> str:
        params: dict[str, Any] = {"image_url": image_url}
        if is_carousel_item:
            params["is_carousel_item"] = "true"
        elif caption:
            params["caption"] = caption
        return self._request("POST", f"{self.user_id}/media", **params)["id"]

    def create_carousel_container(self, children: Sequence[str], caption: str) -> str:
        return self._request(
            "POST", f"{self.user_id}/media",
            media_type="CAROUSEL", children=",".join(children), caption=caption,
        )["id"]

    def wait_until_ready(self, container_id: str, timeout: float = 180, interval: float = 3) -> None:
        """Poll the container until Instagram has finished downloading/processing the media."""
        deadline = time.monotonic() + timeout
        while True:
            info = self._request("GET", container_id, fields="status_code,status")
            status = info.get("status_code")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramError(f"Container {container_id} {status}: {info.get('status')}")
            if time.monotonic() > deadline:
                raise InstagramError(f"Container {container_id} still {status} after {timeout}s")
            time.sleep(interval)

    def publish(self, creation_id: str) -> str:
        return self._request("POST", f"{self.user_id}/media_publish", creation_id=creation_id)["id"]

    # -- high level ----------------------------------------------------------
    def post_images(self, image_urls: Sequence[str], caption: str) -> str:
        """Publish one image, or a carousel when several URLs are given. Returns the media id."""
        if not image_urls:
            raise ValueError("No images to post")
        if len(image_urls) > 10:
            raise ValueError("Instagram carousels support at most 10 items")

        if len(image_urls) == 1:
            container = self.create_image_container(image_urls[0], caption=caption)
            self.wait_until_ready(container)
            return self.publish(container)

        children = []
        for url in image_urls:
            child = self.create_image_container(url, is_carousel_item=True)
            self.wait_until_ready(child)
            children.append(child)
        carousel = self.create_carousel_container(children, caption)
        self.wait_until_ready(carousel)
        return self.publish(carousel)
