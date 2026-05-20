"""Loader for the hand-curated seed CSVs.

Civic events, US Open sessions, and sports playoffs all share the same
CSV schema and are version-controlled under `ground_truth/data/`. This
module reads them and emits `Event` objects.

The CSVs are intentionally small and human-edited; correctness review
happens via PR diff, not by code.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

from ..schema import Event

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

SEED_FILES = {
    "civic": DATA_DIR / "civic_events.csv",
    "us_open": DATA_DIR / "us_open_2024.csv",
    "playoffs": DATA_DIR / "playoffs_2024.csv",
}


def _parse_time(s: str | float) -> time | None:
    if pd.isna(s):
        return None
    return datetime.strptime(str(s).strip(), "%H:%M").time()


def _load_csv(path: Path, label: str) -> list[Event]:
    df = pd.read_csv(path)
    events: list[Event] = []
    for _, row in df.iterrows():
        events.append(
            Event(
                date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                start_time=_parse_time(row["start_time"]),
                end_time=_parse_time(row["end_time"]),
                venue_station_id=str(row["venue_station_id"]),
                target_key=str(row["target_key"]),
                event_name=str(row["event_name"]),
                event_type=str(row["event_type"]),
                expected_attendance=(
                    int(row["expected_attendance"])
                    if pd.notna(row["expected_attendance"])
                    else None
                ),
                source=str(row["source"]),
                source_url=str(row["source_url"]),
                notes=str(row["notes"]) if pd.notna(row.get("notes")) else "",
            )
        )
    log.info("[%s] loaded %d events from %s", label, len(events), path.name)
    return events


def collect_civic() -> list[Event]:
    return _load_csv(SEED_FILES["civic"], "civic")


def collect_us_open() -> list[Event]:
    return _load_csv(SEED_FILES["us_open"], "us_open")


def collect_playoffs() -> list[Event]:
    return _load_csv(SEED_FILES["playoffs"], "playoffs")
