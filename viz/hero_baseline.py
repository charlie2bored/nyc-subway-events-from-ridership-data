"""Hero chart: 24h ridership at MSG on Knicks ECSF G7 (2024-05-19).

This is the chart at the top of the README. It has to be readable in 5
seconds: median baseline (dashed), the actual day (solid), shaded delta
between them, event window marked, and three annotations naming the
lead spike, the peak, and the post-game decay.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.dates import DateFormatter, HourLocator

from ingest.config import DATA_PROCESSED, FIGURES
from viz.style import COLORS, apply_style, save_figure, set_title_subtitle


HERO_DATE = pd.Timestamp("2024-05-19")
EVENT_START = pd.Timestamp("2024-05-19 15:30")
EVENT_END = pd.Timestamp("2024-05-19 18:00")
TARGET = "msg_penn"


def build() -> None:
    apply_style()
    df = pd.read_parquet(DATA_PROCESSED / "ridership_with_baseline_v2.parquet")
    df["transit_timestamp"] = pd.to_datetime(df["transit_timestamp"])

    day = df[
        (df["target_key"] == TARGET)
        & (df["transit_timestamp"].dt.date == HERO_DATE.date())
    ]
    hourly = (
        day.groupby("transit_timestamp")[["ridership", "baseline_ridership"]]
        .sum()
        .sort_index()
    )

    fig, ax = plt.subplots(figsize=(11.5, 5.5))

    # Baseline
    ax.plot(
        hourly.index, hourly["baseline_ridership"],
        linestyle="--", color=COLORS["subtle"], linewidth=2,
        label="Median baseline (event-aware)",
    )

    # Actual
    ax.plot(
        hourly.index, hourly["ridership"],
        color=COLORS["blue"], linewidth=2.6, marker="o", markersize=4,
        markeredgecolor=COLORS["bg"], markeredgewidth=0.6,
        label="Actual ridership",
    )

    # Shade delta
    ax.fill_between(
        hourly.index,
        hourly["baseline_ridership"],
        hourly["ridership"],
        where=hourly["ridership"] > hourly["baseline_ridership"],
        color=COLORS["blue"], alpha=0.12,
        label="Excess ridership (AUC)",
    )

    # Event window
    ax.axvspan(EVENT_START, EVENT_END, color=COLORS["indigo"], alpha=0.06)
    ax.axvline(EVENT_START, color=COLORS["indigo"], linestyle=":", linewidth=1)
    ax.axvline(EVENT_END, color=COLORS["indigo"], linestyle=":", linewidth=1)
    ymax = hourly["ridership"].max()
    ax.text(
        EVENT_START + (EVENT_END - EVENT_START) / 2,
        ymax * 1.04,
        "Game: 15:30 – 18:00",
        ha="center", fontsize=10, color=COLORS["indigo"], fontweight="bold",
    )

    # Annotation: peak
    peak_hour = hourly["ridership"].idxmax()
    peak_value = hourly.loc[peak_hour, "ridership"]
    ax.annotate(
        f"Peak: {int(peak_value):,} riders\n({peak_hour.strftime('%H:%M')})",
        xy=(peak_hour, peak_value),
        xytext=(peak_hour + pd.Timedelta(hours=2.5), peak_value * 0.85),
        arrowprops=dict(arrowstyle="->", color=COLORS["ink"], lw=0.9),
        fontsize=10, color=COLORS["ink"],
    )

    # Annotation: lead spike (first hour ratio>=1.5 before event)
    ratio = hourly["ridership"] / hourly["baseline_ridership"]
    pre = ratio.loc[(ratio.index < EVENT_START) & (ratio >= 1.5)]
    if not pre.empty:
        lead_idx = pre.index[0]
        lead_val = hourly.loc[lead_idx, "ridership"]
        ax.annotate(
            "Pre-game arrival\n(ridership crosses 1.5× baseline)",
            xy=(lead_idx, lead_val),
            xytext=(lead_idx - pd.Timedelta(hours=4.5), lead_val + 1200),
            arrowprops=dict(arrowstyle="->", color=COLORS["ink"], lw=0.9),
            fontsize=10, color=COLORS["ink"],
        )

    # Annotation: post-game decay
    post = hourly.loc[hourly.index > EVENT_END]
    if len(post) >= 2:
        decay_anchor = post.index[1]
        decay_val = post.loc[decay_anchor, "ridership"]
        ax.annotate(
            "Post-game decay",
            xy=(decay_anchor, decay_val),
            xytext=(decay_anchor + pd.Timedelta(hours=1.5), decay_val + 1800),
            arrowprops=dict(arrowstyle="->", color=COLORS["ink"], lw=0.9),
            fontsize=10, color=COLORS["ink"],
        )

    # X axis formatting
    ax.xaxis.set_major_locator(HourLocator(byhour=range(0, 24, 3)))
    ax.xaxis.set_major_formatter(DateFormatter("%H:%M"))
    ax.set_xlim(hourly.index.min(), hourly.index.max())

    ax.set_xlabel("Hour of day (NYC local time)")
    ax.set_ylabel("Riders entering Penn Station (IRT 1/2/3 + IND A/C/E)")
    set_title_subtitle(
        ax,
        "Knicks vs Pacers, Conference Semifinals Game 7 — Penn Station / MSG",
        "May 19, 2024 (Sunday). Pacers eliminated the Knicks 130–109 in front of 19,812.",
    )

    ax.legend(loc="upper left", fontsize=10)
    ax.grid(axis="y", alpha=0.6)
    ax.set_ylim(bottom=0)

    save_figure(fig, "01_hero_baseline_msg_g7", FIGURES)
    plt.close(fig)


if __name__ == "__main__":
    build()
