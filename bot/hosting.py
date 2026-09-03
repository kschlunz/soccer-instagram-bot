"""Publish rendered images to a git branch so Instagram can fetch them over HTTPS.

Instagram's API only accepts a public image URL, it will not accept an upload.
For a public GitHub repository, files on any branch are served from
raw.githubusercontent.com, so we commit the JPEGs to a dedicated branch using
git plumbing (no checkout needed) and hand those URLs to Instagram.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import requests

IMAGE_DIR = "posts"


def _git(*args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repo_slug() -> str:
    """owner/repo, from GITHUB_REPOSITORY (Actions) or the origin remote."""
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug:
        return slug
    url = _git("remote", "get-url", "origin")
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise RuntimeError(f"Cannot determine GitHub repo from remote URL {url!r}")
    return f"{match.group(1)}/{match.group(2)}"


def publish_images(
    paths: Sequence[Path],
    branch: str,
    keep_days: int = 30,
    remote: str = "origin",
    subdir: str = IMAGE_DIR,
    attempts: int = 3,
) -> list[str]:
    """Commit `paths` under `subdir/` on `branch` (creating it if needed) and return raw URLs.

    Two profiles may post around the same time, so a rejected (non-fast-forward)
    push is retried against the freshly fetched branch tip.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _publish_once(paths, branch, keep_days, remote, subdir)
        except RuntimeError as err:
            last_error = err
            if "push" not in str(err) or attempt == attempts:
                raise
            time.sleep(3 * attempt)
    raise RuntimeError(f"push failed after {attempts} attempts: {last_error}")


def _publish_once(paths: Sequence[Path], branch: str, keep_days: int, remote: str, subdir: str) -> list[str]:
    slug = repo_slug()
    _git("fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", check=False)
    parent = _git("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}", check=False) or None

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        env.setdefault("GIT_AUTHOR_NAME", "soccer-bot")
        env.setdefault("GIT_AUTHOR_EMAIL", "soccer-bot@users.noreply.github.com")
        env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
        env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])

        if parent:
            _git("read-tree", parent, env=env)
            _prune_old(parent, keep_days, env, subdir)
        else:
            readme = _hash_stdin("Generated images for the soccer Instagram bot.\n", env)
            _git("update-index", "--add", "--cacheinfo", f"100644,{readme},README.md", env=env)

        rel_paths = []
        for path in paths:
            blob = _git("hash-object", "-w", str(path), env=env)
            rel = f"{subdir}/{path.name}"
            _git("update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
            rel_paths.append(rel)

        tree = _git("write-tree", env=env)
        message = f"Add {subdir} images for {paths[0].stem.rsplit('-', 1)[0] if paths else date.today()}"
        commit_args = ["commit-tree", tree, "-m", message]
        if parent:
            commit_args += ["-p", parent]
        commit = _git(*commit_args, env=env)
        _git("push", remote, f"{commit}:refs/heads/{branch}")

    return [f"https://raw.githubusercontent.com/{slug}/{branch}/{rel}" for rel in rel_paths]


def _hash_stdin(content: str, env: dict[str, str]) -> str:
    result = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=content,
                            capture_output=True, text=True, env=env, check=True)
    return result.stdout.strip()


def _prune_old(parent: str, keep_days: int, env: dict[str, str], subdir: str = IMAGE_DIR) -> None:
    """Drop <subdir>/YYYY-MM-DD-*.jpg entries older than keep_days from the index."""
    if keep_days <= 0:
        return
    cutoff = date.today() - timedelta(days=keep_days)
    for entry in _git("ls-tree", "-r", "--name-only", parent, env=env).splitlines():
        match = re.match(rf"{re.escape(subdir)}/(\d{{4}}-\d{{2}}-\d{{2}})-\d+\.jpg$", entry)
        if match and date.fromisoformat(match.group(1)) < cutoff:
            _git("update-index", "--force-remove", entry, env=env)


def wait_until_public(urls: Sequence[str], timeout: float = 120, interval: float = 5) -> None:
    """raw.githubusercontent.com can lag a push by a few seconds; wait for every URL to serve."""
    deadline = time.monotonic() + timeout
    pending = list(urls)
    while pending:
        still = []
        for url in pending:
            try:
                ok = requests.head(url, timeout=20, allow_redirects=True).status_code == 200
            except requests.RequestException:
                ok = False
            if not ok:
                still.append(url)
        pending = still
        if pending:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Images never became public: {pending}")
            time.sleep(interval)
