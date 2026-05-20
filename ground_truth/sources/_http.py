"""Shared HTTP fetching with file-level caching and per-domain rate limits.

Every Phase 2 scraper goes through `fetch_text` so that:
  - re-runs are free (we keep the raw HTML/JSON on disk)
  - we never violate a host's politeness policy
  - cache files double as audit artifacts (the exact bytes we parsed)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from .. import config

log = logging.getLogger(__name__)


def fetch_text(
    url: str,
    cache_path: Path,
    delay: float,
    headers: dict[str, str] | None = None,
    timeout: int = config.DEFAULT_TIMEOUT,
    force: bool = False,
) -> str:
    """Return body of `url`, reading from `cache_path` if present.

    `delay` is the *pre-request* sleep, so back-to-back calls all wait
    the appropriate gap regardless of how the caller orders them.
    """
    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8")

    h = {"User-Agent": config.USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)

    log.info("GET %s (sleeping %.1fs first)", url, delay)
    time.sleep(delay)
    r = requests.get(url, headers=h, timeout=timeout)
    r.raise_for_status()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(r.text, encoding="utf-8")
    return r.text


def fetch_json(
    url: str,
    cache_path: Path,
    delay: float,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    timeout: int = config.DEFAULT_TIMEOUT,
    force: bool = False,
):
    """Like fetch_text but parses JSON and the cache stores parsed JSON."""
    import json

    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    h = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    if headers:
        h.update(headers)

    log.info("GET %s (sleeping %.1fs first)", url, delay)
    time.sleep(delay)
    r = requests.get(url, headers=h, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
