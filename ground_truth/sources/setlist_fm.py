"""Concerts at MSG and Barclays from the setlist.fm API.

Setlist.fm publishes user-submitted setlists keyed by venue. We use the
free-tier REST API (~1440 req/day, 2 req/s; we pace at 1 req/s).

Quirks:
  - `eventDate` is delivered as "DD-MM-YYYY" (day-first, European style).
  - Pagination returns 20 items per page in date-descending order; we
    walk back until we cross from 2024 into 2023.
  - Setlist.fm records support acts as separate setlists on the same
    date. We dedup by (date, venue) keeping the headliner heuristically
    (the entry with no `tour` referenced as a "support" string in
    `info`; in practice the first one returned is the headliner).
  - Times are not in the API response. Default to 20:00 with a note.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from .. import config
from ..schema import Event
from ._http import fetch_json

log = logging.getLogger(__name__)


VENUES = {
    "MSG":      {"venue_id": config.URLS["setlist_fm"]["msg_venue_id"],
                 "target_key": "msg_penn",  "venue_station_id": "318"},
    "BARCLAYS": {"venue_id": config.URLS["setlist_fm"]["barclays_venue_id"],
                 "target_key": "barclays",  "venue_station_id": "617"},
}

API_BASE = config.URLS["setlist_fm"]["base"]
DEFAULT_START = time(20, 0)


def _fetch_venue_pages(venue_label: str, venue_id: str, year: int = 2024) -> list[dict]:
    """Walk setlist.fm pages until we leave the target year."""
    if not config.SETLIST_FM_API_KEY:
        log.warning("SETLIST_FM_API_KEY not set; skipping setlist.fm pulls.")
        return []
    headers = {"x-api-key": config.SETLIST_FM_API_KEY}
    page = 1
    out: list[dict] = []
    while True:
        url = f"{API_BASE}/venue/{venue_id}/setlists"
        cache_path = config.GT_RAW / "setlist_fm" / f"{venue_label}_p{page}.json"
        data = fetch_json(
            url=url,
            cache_path=cache_path,
            delay=config.SETLIST_FM_DELAY,
            headers=headers,
            params={"p": page},
        )
        setlists = data.get("setlist", [])
        if not setlists:
            break
        out.extend(setlists)
        # Date-descending: stop once the last setlist on this page is
        # before our window.
        last_date = setlists[-1].get("eventDate", "")
        try:
            last_year = datetime.strptime(last_date, "%d-%m-%Y").year
        except ValueError:
            last_year = year  # be safe and keep going
        if last_year < year:
            break
        page += 1
        if page > 50:                       # paranoia
            log.warning("[%s] hit page=50 cap", venue_label)
            break
    log.info("[%s] fetched %d setlist records across %d pages", venue_label, len(out), page)
    return out


def _dedup_by_date(records: list[dict]) -> list[dict]:
    """One concert per (date, venue) — the first entry wins (headliner)."""
    seen: set[str] = set()
    deduped: list[dict] = []
    for s in records:
        date_str = s.get("eventDate", "")
        if date_str in seen:
            continue
        seen.add(date_str)
        deduped.append(s)
    return deduped


def collect(year: int = 2024) -> list[Event]:
    events: list[Event] = []
    for label, info in VENUES.items():
        records = _fetch_venue_pages(label, info["venue_id"], year=year)
        # Filter to target year
        in_year = []
        for s in records:
            d_str = s.get("eventDate", "")
            try:
                d = datetime.strptime(d_str, "%d-%m-%Y").date()
            except ValueError:
                continue
            if d.year == year:
                s["_date"] = d
                in_year.append(s)
        deduped = _dedup_by_date(in_year)
        log.info("[%s] %d concerts in %d after dedup", label, len(deduped), year)

        venue_name = "Madison Square Garden" if label == "MSG" else "Barclays Center"
        for s in deduped:
            d = s["_date"]
            artist_name = (s.get("artist") or {}).get("name") or "Unknown"
            tour = (s.get("tour") or {}).get("name") or ""
            end = (
                datetime.combine(d, DEFAULT_START)
                + timedelta(minutes=config.DEFAULT_DURATIONS_MIN["Concert"])
            ).time()
            events.append(
                Event(
                    date=d,
                    start_time=DEFAULT_START,
                    end_time=end,
                    venue_station_id=info["venue_station_id"],
                    target_key=info["target_key"],
                    event_name=f"{artist_name} @ {venue_name}",
                    event_type="Concert",
                    expected_attendance=None,
                    source="setlist.fm",
                    source_url=f"https://www.setlist.fm/setlist/{s.get('id', '')}",
                    notes=(
                        f"start time default (20:00)"
                        + (f"; tour={tour}" if tour else "")
                    ),
                )
            )
    return events
