"""Resolve `station_complex_id` for each target archetype against the live dataset.

Run as a module:
    python -m ingest.resolve_stations

Prints all candidates that match any of an archetype's fuzzy patterns, writes
the full station table to data/processed/station_complex_reference.csv for
the record, and prints a Python literal you can paste back into
ingest/config.py's TARGETS to lock the IDs.
"""
from __future__ import annotations

import logging
import sys

import pandas as pd

from . import config
from .socrata_client import SocrataClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("resolve_stations")


def main() -> int:
    client = SocrataClient(config.HOURLY_DATASET_ID)
    log.info(
        "Querying distinct station complexes from dataset %s ...",
        config.HOURLY_DATASET_ID,
    )
    rows = client.distinct_stations()
    df = pd.DataFrame(rows).sort_values("station_complex").reset_index(drop=True)
    log.info("Got %d distinct station complexes.", len(df))

    out_path = config.DATA_PROCESSED / "station_complex_reference.csv"
    df.to_csv(out_path, index=False)
    log.info("Wrote full reference table -> %s", out_path)

    print("\n" + "=" * 80)
    print("STATION COMPLEX RESOLUTION")
    print("=" * 80)

    resolved: dict[str, list[dict]] = {}
    for target in config.TARGETS:
        mask = pd.Series(False, index=df.index)
        for pat in target.match_patterns:
            mask = mask | df["station_complex"].str.contains(pat, case=False, na=False)
        hits = df[mask].to_dict(orient="records")
        resolved[target.key] = hits

        print(f"\n[{target.key}]  {target.label}  ({target.archetype})")
        print(f"  patterns: {target.match_patterns}")
        if not hits:
            print("  !! NO MATCHES. Check the patterns in config.TARGETS.")
            continue
        for h in hits:
            print(
                f"  complex_id={h['station_complex_id']:>5}  "
                f"borough={h.get('borough', '?'):<3}  "
                f"name={h['station_complex']}"
            )

    print("\n" + "=" * 80)
    print("Paste the chosen IDs into ingest/config.py TARGETS.complex_ids")
    print("=" * 80)
    for target in config.TARGETS:
        ids = tuple(str(h["station_complex_id"]) for h in resolved[target.key])
        print(f"  {target.key:>10}: complex_ids={ids!r}")

    missing = [t.key for t in config.TARGETS if not resolved[t.key]]
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
