# Data Notes & Decisions - 2024 MTA Hourly Ridership

Decisions made during Phase 1 ingest that downstream modules
(`baseline/`, `anomaly/`, `fingerprint/`) must respect.

## Penn Station is two complexes

The `msg_penn` archetype maps to **two** `station_complex_id` values, not one:

| complex_id | line group | borough   | name                            |
|-----------:|:-----------|:----------|:--------------------------------|
| 318        | IRT West Side: 1/2/3 | Manhattan | 34 St-Penn Station (1,2,3) |
| 164        | IND 8th Ave: A/C/E   | Manhattan | 34 St-Penn Station (A,C,E) |

Both physically feed Madison Square Garden - the arena sits directly above
the IRT station and one block south of the IND. The MTA records them as
separate complexes because the platforms are not paid-area connected.

**Implications for downstream code:**
- The cached Parquet `data/raw/hourly_2024_msg_penn.parquet` contains both
  complexes interleaved. Filter by `station_complex_id` to look at one
  side.
- The IRT side (318) is the direct MSG feed and is expected to show the
  stronger event signal. IND (164) carries some overflow plus Penn
  Station commuter rail transfers.
- Baselines will be computed **per complex_id** to preserve the structural
  difference. Aggregation to a single MSG signal happens at the anomaly /
  fingerprint layer, where we want one event signature per archetype.

## Missing hours are NaN, not zero

The DQ report shows one hour missing per complex for four of the five
archetypes, and 8 missing hours at Mets-Willets.

**Decision:** when reindexing to a full hourly grid (`pd.date_range`),
missing hours become `NaN`. They are **not** filled with 0. Treating a
service-suspension hour as zero ridership would skew the median baseline
downward (median is robust to high outliers but still moves with the
floor) and would mask the gap in subsequent visual review.

**Likely sources of the gaps:**
- The single missing hour at most complexes corresponds to the
  **2024-03-10 02:00 DST spring-forward** - that local clock hour does not
  exist. To be verified in Step 2 by checking the timestamp of the gap.
- The extra 7 missing hours at Mets-Willets are likely a real **7-train
  service interruption** (weekend maintenance is common on the Flushing
  line). To be cross-referenced against the MTA service-alerts archive
  when ground truth is assembled in Phase 2.

**Operational rule for baseline computation:**
```python
df = df.set_index("transit_timestamp").reindex(
    pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")
)  # missing hours -> all-NaN row
# median(skipna=True) is then the right baseline operator.
```

## Timestamps are floating local time

The Socrata field `transit_timestamp` is delivered as a naive timestamp
with no timezone. The MTA records it in **America/New_York local clock
time**. This is why DST creates a literal one-hour gap rather than
shifting downstream data by an hour. Do not localize-and-convert; treat
the column as a naive datetime and let DST gaps remain NaN.

## station_complex_id is a string

JSON-typed in the API response and treated as a string throughout the
pipeline. Do not cast to int - the dataset has historical IDs that may
include non-numeric values in earlier transit modes (Staten Island
Railway, Roosevelt Island Tram), even though the subway IDs we use here
happen to be all-digit.
