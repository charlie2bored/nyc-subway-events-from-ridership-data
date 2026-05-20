"""Thin Socrata SODA 2.1 client.

We don't use `sodapy` because it's quietly stalled upstream and adds an
abstraction we don't need. A few hundred lines of `requests` with retry,
pagination, and a small SoQL builder cover everything Phase 1 requires.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests

from .config import (
    BACKOFF_BASE,
    MAX_RETRIES,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    SOCRATA_BASE,
    SODA_APP_TOKEN,
)

log = logging.getLogger(__name__)


class SocrataError(RuntimeError):
    pass


@dataclass
class SoQL:
    """Tiny SoQL query builder. Order of clauses follows SODA 2.1 spec."""
    select: str | None = None
    where: str | None = None
    group: str | None = None
    order: str | None = None
    limit: int | None = None
    offset: int | None = None

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.select:
            params["$select"] = self.select
        if self.where:
            params["$where"] = self.where
        if self.group:
            params["$group"] = self.group
        if self.order:
            params["$order"] = self.order
        if self.limit is not None:
            params["$limit"] = str(self.limit)
        if self.offset is not None:
            params["$offset"] = str(self.offset)
        return params


class SocrataClient:
    def __init__(
        self,
        dataset_id: str,
        app_token: str | None = SODA_APP_TOKEN,
        base: str = SOCRATA_BASE,
    ) -> None:
        self.dataset_id = dataset_id
        self.url = f"{base}/{dataset_id}.json"
        self.session = requests.Session()
        if app_token:
            self.session.headers["X-App-Token"] = app_token
            self._has_token = True
        else:
            self._has_token = False
            log.warning(
                "No SODA_APP_TOKEN set; pulls will use the shared anonymous "
                "rate-limit pool. This works but is slower."
            )

    # -- single request -----------------------------------------------------

    def _request(self, params: dict[str, str]) -> list[dict[str, Any]]:
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(self.url, params=params, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                last_err = e
                self._sleep(attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 502, 503, 504):
                last_err = SocrataError(f"HTTP {r.status_code}: {r.text[:200]}")
                self._sleep(attempt)
                continue
            raise SocrataError(
                f"HTTP {r.status_code} from Socrata: {r.text[:500]}\n"
                f"URL: {r.url}"
            )
        raise SocrataError(f"Exhausted {MAX_RETRIES} retries; last error: {last_err}")

    @staticmethod
    def _sleep(attempt: int) -> None:
        delay = BACKOFF_BASE ** (attempt + 1)
        log.info("Backing off %.1fs before retry %d", delay, attempt + 1)
        time.sleep(delay)

    # -- public helpers -----------------------------------------------------

    def query(self, q: SoQL) -> list[dict[str, Any]]:
        """One-shot query. Caller is responsible for $limit/$offset."""
        return self._request(q.to_params())

    def paginate(self, q: SoQL, page_size: int = PAGE_SIZE) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of rows for a query, advancing $offset automatically.

        Stops when a page returns fewer than `page_size` rows.
        """
        if q.order is None:
            # Stable ordering is required for correct pagination on Socrata.
            raise SocrataError("paginate(): SoQL must specify $order for stable pagination")
        offset = 0
        while True:
            page_q = SoQL(
                select=q.select,
                where=q.where,
                group=q.group,
                order=q.order,
                limit=page_size,
                offset=offset,
            )
            page = self._request(page_q.to_params())
            if not page:
                return
            yield page
            if len(page) < page_size:
                return
            offset += page_size

    # -- convenience for resolver ------------------------------------------

    def distinct_stations(self, probe_timestamp: str = "2024-06-12T18:00:00.000") -> list[dict[str, Any]]:
        """Return distinct (station_complex_id, station_complex, borough) tuples.

        A full-dataset GROUP BY on the hourly ridership table times out on
        Socrata's free tier. Instead we pull all rows from a single busy
        weekday hour (Wednesday 6pm) — that hour exercises virtually every
        station complex in the system — and dedupe client-side.
        """
        q = SoQL(
            select="station_complex_id, station_complex, borough",
            where=f"transit_timestamp = '{probe_timestamp}'",
            order="station_complex_id",
            limit=PAGE_SIZE,
        )
        rows = self._request(q.to_params())
        seen: set[tuple[str, str, str]] = set()
        out: list[dict[str, Any]] = []
        for r in rows:
            key = (r.get("station_complex_id"), r.get("station_complex"), r.get("borough"))
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out
