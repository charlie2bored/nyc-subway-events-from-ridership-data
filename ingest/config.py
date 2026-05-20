"""Centralized configuration for the ingest layer.

The single source of truth for:
  - Socrata dataset IDs and endpoints
  - The five target station archetypes and their fuzzy-match patterns
  - File paths

Every other module imports from here. No constants live elsewhere.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project paths -------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
FIGURES = PROJECT_ROOT / "figures"
DOCS = PROJECT_ROOT / "docs"

for _p in (DATA_RAW, DATA_PROCESSED, FIGURES, DOCS):
    _p.mkdir(parents=True, exist_ok=True)

# Socrata -------------------------------------------------------------------

# MTA Subway Hourly Ridership: Beginning February 2022
# https://data.ny.gov/Transportation/MTA-Subway-Hourly-Ridership-Beginning-February-202/wujg-7c2s
HOURLY_DATASET_ID = "wujg-7c2s"
SOCRATA_DOMAIN = "data.ny.gov"
SOCRATA_BASE = f"https://{SOCRATA_DOMAIN}/resource"

SODA_APP_TOKEN = os.environ.get("SODA_APP_TOKEN", "").strip() or None

# Pull configuration --------------------------------------------------------

# 2024 calendar year. transit_timestamp is a floating timestamp on Socrata.
PULL_START = "2024-01-01T00:00:00.000"
PULL_END = "2025-01-01T00:00:00.000"  # exclusive upper bound

PAGE_SIZE = 50_000   # Socrata hard cap for $limit
REQUEST_TIMEOUT = 60  # seconds
MAX_RETRIES = 4
BACKOFF_BASE = 1.6   # seconds; exponential

# Target stations -----------------------------------------------------------

@dataclass(frozen=True)
class StationArchetype:
    """One of the five archetypes in the study.

    `match_patterns` are case-insensitive substrings used by the resolver to
    locate candidates in the dataset's `station_complex` field. The resolver
    prints all candidates; the human picks which `complex_ids` go in here.
    """
    key: str                              # short slug used in filenames
    label: str                            # human-readable display label
    archetype: str                        # what kind of venue this is
    match_patterns: tuple[str, ...]       # substrings the resolver searches
    complex_ids: tuple[str, ...] = field(default_factory=tuple)  # filled after resolve


# Resolved 2026-05-19 against dataset wujg-7c2s by ingest.resolve_stations.
# MSG/Penn aggregates both Penn Station complexes (IRT 1/2/3 and IND A/C/E)
# because both feed the arena. Times Sq-42 St / 42 St-PA is a single merged
# complex (611) in this dataset.
TARGETS: tuple[StationArchetype, ...] = (
    StationArchetype(
        key="msg_penn",
        label="34 St-Penn Station / MSG",
        archetype="Arena+Rail Hub (Knicks, Rangers, concerts)",
        match_patterns=("34 St-Penn Station",),
        complex_ids=("318", "164"),
    ),
    StationArchetype(
        key="barclays",
        label="Atlantic Av-Barclays Ctr",
        archetype="Arena (Nets, concerts)",
        match_patterns=("Atlantic Av-Barclays",),
        complex_ids=("617",),
    ),
    StationArchetype(
        key="mets",
        label="Mets-Willets Pt",
        archetype="Stadium (Mets, US Open)",
        match_patterns=("Mets-Willets", "Willets Point"),
        complex_ids=("448",),
    ),
    StationArchetype(
        key="yankee",
        label="161 St-Yankee Stadium",
        archetype="Stadium (Yankees)",
        match_patterns=("161 St-Yankee", "Yankee Stadium"),
        complex_ids=("604",),
    ),
    StationArchetype(
        key="times_sq",
        label="Times Sq-42 St",
        archetype="Civic Baseline (NYE, parades, Broadway)",
        match_patterns=("Times Sq-42 St", "Times Sq"),
        complex_ids=("611",),
    ),
)


def get_target(key: str) -> StationArchetype:
    for t in TARGETS:
        if t.key == key:
            return t
    raise KeyError(f"No target with key={key!r}. Known: {[t.key for t in TARGETS]}")


def raw_parquet_path(key: str) -> Path:
    return DATA_RAW / f"hourly_2024_{key}.parquet"
