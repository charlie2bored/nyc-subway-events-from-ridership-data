"""Pull 2024 hourly ridership for the resolved targets and cache to Parquet.

Run as a module:
    python -m ingest.pull_2024

Reads `complex_ids` from ingest.config.TARGETS. If any target has an empty
tuple, the script aborts with a clear message asking you to run
`python -m ingest.resolve_stations` first and paste the IDs.

Each target archetype is cached as a single Parquet at
data/raw/hourly_2024_{key}.parquet. Re-runs are idempotent: if the file
already exists it is skipped unless --force is passed.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable

import pandas as pd

from . import config
from .socrata_client import SoQL, SocrataClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pull_2024")


# Columns we care about. Pulling explicit projection keeps row size predictable
# and shields us from future schema additions on the source dataset.
SELECT_COLS = (
    "transit_timestamp",
    "transit_mode",
    "station_complex_id",
    "station_complex",
    "borough",
    "payment_method",
    "fare_class_category",
    "ridership",
    "transfers",
    "latitude",
    "longitude",
)


def _quote_ids(ids: Iterable[str]) -> str:
    """Render an IN-list of station_complex_id values for SoQL.

    The dataset returns station_complex_id as a string in JSON, so we quote.
    """
    return ", ".join(f"'{i}'" for i in ids)


def _build_where(complex_ids: Iterable[str]) -> str:
    return (
        f"station_complex_id IN ({_quote_ids(complex_ids)}) "
        f"AND transit_timestamp >= '{config.PULL_START}' "
        f"AND transit_timestamp < '{config.PULL_END}'"
    )


def pull_target(client: SocrataClient, target: config.StationArchetype) -> pd.DataFrame:
    where = _build_where(target.complex_ids)
    q = SoQL(
        select=", ".join(SELECT_COLS),
        where=where,
        # Composite order to guarantee stable pagination across pages.
        order="transit_timestamp, station_complex_id, payment_method, fare_class_category",
    )
    log.info("[%s] querying complex_ids=%s", target.key, list(target.complex_ids))
    log.info("[%s] where=%s", target.key, where)

    pages: list[pd.DataFrame] = []
    total = 0
    for i, page in enumerate(client.paginate(q)):
        df = pd.DataFrame(page)
        pages.append(df)
        total += len(df)
        log.info("[%s] page %d: %d rows (cumulative %d)", target.key, i + 1, len(df), total)

    if not pages:
        log.warning("[%s] no rows returned!", target.key)
        return pd.DataFrame(columns=list(SELECT_COLS))

    df = pd.concat(pages, ignore_index=True)
    return _coerce_types(df)


def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    # Socrata returns JSON strings for everything. Cast to proper dtypes.
    df = df.copy()
    df["transit_timestamp"] = pd.to_datetime(df["transit_timestamp"], errors="coerce")
    for col in ("ridership", "transfers"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("latitude", "longitude"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # station_complex_id stays as string — that is the canonical key shape.
    if "station_complex_id" in df.columns:
        df["station_complex_id"] = df["station_complex_id"].astype("string")
    for col in ("station_complex", "borough", "payment_method", "fare_class_category", "transit_mode"):
        if col in df.columns:
            df[col] = df[col].astype("string")
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-pull and overwrite existing Parquet caches.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[t.key for t in config.TARGETS],
        help="Restrict to specific target keys.",
    )
    args = parser.parse_args(argv)

    missing = [t.key for t in config.TARGETS if not t.complex_ids]
    if missing:
        log.error(
            "These targets have no complex_ids resolved yet: %s\n"
            "Run `python -m ingest.resolve_stations` and paste the IDs into "
            "ingest/config.py TARGETS first.",
            missing,
        )
        return 2

    client = SocrataClient(config.HOURLY_DATASET_ID)

    selected = config.TARGETS
    if args.only:
        selected = tuple(t for t in selected if t.key in args.only)

    for target in selected:
        out = config.raw_parquet_path(target.key)
        if out.exists() and not args.force:
            log.info("[%s] cache exists, skipping: %s", target.key, out)
            continue
        df = pull_target(client, target)
        df.to_parquet(out, index=False)
        log.info("[%s] wrote %d rows -> %s", target.key, len(df), out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
