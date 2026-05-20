"""NYC permitted parade events from NYC Open Data.

Status: empirically thin. The `tvpp-9vvx` dataset only retains records
from 2024-06-30 forward (we probed it on 2026-05-19 and confirmed the
min date), and even within that window no 2024 events are tagged with
parade-ish `event_type` values. The dataset is now primarily a
forward-looking permit registry.

The major 2024 NYC parades (Macy's Thanksgiving, Pride, St. Patrick's,
Veterans Day, West Indian Day, NYE) are therefore hand-curated in
`ground_truth/data/civic_events.csv` with `event_type=Parade`. We keep
this scraper as a no-op for documentation and future use (it will work
again if NYC Open Data backfills history or for forward-looking 2025+
events).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, time

import pandas as pd

from ingest.config import SOCRATA_BASE
from ingest.socrata_client import SoQL, SocrataClient

from .. import config
from ..schema import Event

log = logging.getLogger(__name__)


PARADE_TERMS = ("parade", "march", "procession", "run/walk")

# Substring match on the permit's `event_location_borough_block` or
# location text to figure out which archetype to attribute the event to.
# Order matters — first hit wins.
LOCATION_TO_TARGET: list[tuple[str, str, str]] = [
    # (substring, target_key, venue_station_id)
    ("eastern parkway",        "barclays", "617"),    # West Indian Day route
    ("atlantic avenue",        "barclays", "617"),
    ("flatbush avenue",        "barclays", "617"),
    ("times square",           "times_sq", "611"),
    ("broadway",               "times_sq", "611"),
    ("5th avenue",             "times_sq", "611"),
    ("fifth avenue",           "times_sq", "611"),
    ("sixth avenue",           "times_sq", "611"),
    ("7th avenue",             "times_sq", "611"),
    ("seventh avenue",         "times_sq", "611"),
    ("42 street",              "times_sq", "611"),
    ("42nd street",            "times_sq", "611"),
    ("34 street",              "msg_penn", "318"),
    ("34th street",            "msg_penn", "318"),
    ("herald square",          "times_sq", "611"),
    ("queens boulevard",       "mets",     "448"),    # rough; Mets-Willets is far from most parades
    ("grand concourse",        "yankee",   "604"),
    ("161 street",             "yankee",   "604"),
]


def _classify_location(location_text: str) -> tuple[str | None, str | None]:
    if not isinstance(location_text, str):
        return (None, None)
    lower = location_text.lower()
    for substr, target_key, station_id in LOCATION_TO_TARGET:
        if substr in lower:
            return (target_key, station_id)
    return (None, None)


def _parse_event_time(s: str | float) -> time | None:
    if pd.isna(s):
        return None
    try:
        return datetime.fromisoformat(str(s)).time()
    except ValueError:
        return None


def collect() -> list[Event]:
    dataset_id = config.URLS["nyc_open_data"]["dataset_id"]
    client = SocrataClient(dataset_id=dataset_id, base=SOCRATA_BASE)

    # Permits have `start_date_time` and `end_date_time`. Filter to 2024 and
    # to event_type names that match parade-like terms. We also pull the
    # location columns so we can route to a target archetype.
    where_parts = [
        f"start_date_time >= '2024-01-01T00:00:00.000'",
        f"start_date_time < '2025-01-01T00:00:00.000'",
        "(" + " OR ".join(
            f"lower(event_type) like '%{t}%'" for t in PARADE_TERMS
        ) + ")",
    ]
    q = SoQL(
        select=(
            "event_id, event_name, event_type, "
            "start_date_time, end_date_time, "
            "event_borough, event_street_side, event_location, "
            "event_agency"
        ),
        where=" AND ".join(where_parts),
        order="start_date_time",
        limit=50_000,
    )
    rows = client.query(q)
    log.info("Fetched %d candidate parade permits from NYC Open Data", len(rows))

    df = pd.DataFrame(rows)
    if df.empty:
        log.warning("No parade permits returned; check the filter.")
        return []

    events: list[Event] = []
    for _, row in df.iterrows():
        loc = " ".join(
            str(row.get(c, "")) for c in ("event_location", "event_street_side", "event_borough")
        )
        target_key, station_id = _classify_location(loc)
        if not target_key:
            continue
        start_dt = pd.to_datetime(row.get("start_date_time"), errors="coerce")
        end_dt = pd.to_datetime(row.get("end_date_time"), errors="coerce")
        if pd.isna(start_dt):
            continue
        events.append(
            Event(
                date=start_dt.date(),
                start_time=start_dt.time() if pd.notna(start_dt) else None,
                end_time=end_dt.time() if pd.notna(end_dt) else None,
                venue_station_id=station_id,
                target_key=target_key,
                event_name=str(row.get("event_name") or row.get("event_type") or "Unnamed parade"),
                event_type="Parade",
                expected_attendance=None,
                source="data.cityofnewyork.us",
                source_url=f"https://data.cityofnewyork.us/d/{dataset_id}",
                notes=f"permit_id={row.get('event_id')}; agency={row.get('event_agency')}",
            )
        )

    log.info("Mapped %d permits to archetype stations", len(events))
    return events
