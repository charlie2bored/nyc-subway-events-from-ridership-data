"""Schema for ground_truth_events.csv.

Every source-specific module (mlb.py, nba.py, setlist_fm.py, ...) returns
a list of `Event` dataclasses. The combiner serializes them all to one
CSV via `events_to_dataframe`.

The `event_id` is a deterministic hash so re-runs produce the same IDs
and de-dup is trivial.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, time
from typing import Literal

import pandas as pd

EventType = Literal[
    "Sports-MLB",
    "Sports-NBA",
    "Sports-NHL",
    "Concert",
    "Parade",
    "Civic",
    "Festival",
    "Other",
]

EVENT_TYPES: tuple[str, ...] = (
    "Sports-MLB",
    "Sports-NBA",
    "Sports-NHL",
    "Concert",
    "Parade",
    "Civic",
    "Festival",
    "Other",
)


@dataclass(frozen=True)
class Event:
    date: date
    start_time: time | None
    end_time: time | None
    venue_station_id: str         # canonical station_complex_id
    target_key: str               # ingest.config archetype slug
    event_name: str
    event_type: EventType
    expected_attendance: int | None
    source: str
    source_url: str
    notes: str = ""
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        # Stable hash of the natural key. Avoid including mutable
        # fields (notes, attendance) so a later correction doesn't
        # change the ID and break joins.
        natural = "|".join(
            [
                self.date.isoformat(),
                self.start_time.isoformat() if self.start_time else "",
                self.venue_station_id,
                self.event_type,
                self.event_name.lower().strip(),
            ]
        )
        h = hashlib.sha1(natural.encode("utf-8")).hexdigest()[:12]
        object.__setattr__(self, "event_id", f"{self._slug()}-{h}")

    def _slug(self) -> str:
        return self.event_type.lower().replace("sports-", "")


def events_to_dataframe(events: list[Event]) -> pd.DataFrame:
    """Serialize events into the canonical CSV schema."""
    if not events:
        return pd.DataFrame(
            columns=[
                "event_id", "date", "start_time", "end_time",
                "venue_station_id", "target_key", "event_name",
                "event_type", "expected_attendance", "source",
                "source_url", "notes",
            ]
        )
    rows = []
    for e in events:
        rows.append(
            {
                "event_id": e.event_id,
                "date": e.date.isoformat(),
                "start_time": e.start_time.strftime("%H:%M") if e.start_time else None,
                "end_time": e.end_time.strftime("%H:%M") if e.end_time else None,
                "venue_station_id": e.venue_station_id,
                "target_key": e.target_key,
                "event_name": e.event_name,
                "event_type": e.event_type,
                "expected_attendance": e.expected_attendance,
                "source": e.source,
                "source_url": e.source_url,
                "notes": e.notes,
            }
        )
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["event_id"]).sort_values(
        ["date", "start_time", "target_key"]
    ).reset_index(drop=True)
