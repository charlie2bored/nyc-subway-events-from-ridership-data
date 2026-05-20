"""Cluster scatter: peak intensity (y, log) × asymmetry ratio (x).

Color by k=6 cluster (charlie2bored palette), shape by event_type. Four
exemplar events labeled to anchor the reader.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from ingest.config import DATA_PROCESSED, FIGURES
from viz.style import CLUSTER_PALETTE, COLORS, EVENT_TYPE_MARKERS, apply_style, save_figure, set_title_subtitle


EXEMPLAR_DATES = {
    "Yankees vs Dodgers (WS G4)":                "2024-10-29",
    "Knicks vs Pacers (ECSF G7)":                "2024-05-19",
    "US Open Day 8 (Night Session - Labor Day)": "2024-09-02",
    "Macy's Thanksgiving Day Parade":            "2024-11-28",
}


def _resolve_exemplars(feats: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, date in EXEMPLAR_DATES.items():
        m = (feats["event_name"] == name) & (feats["date"] == pd.to_datetime(date).date())
        match = feats[m]
        if not match.empty:
            rows.append(match.iloc[0])
    return pd.DataFrame(rows)


def build() -> None:
    apply_style()
    feats = pd.read_parquet(DATA_PROCESSED / "event_features_with_clusters.parquet")
    ok = feats[feats["status"] == "ok"].copy()
    ok["date"] = pd.to_datetime(ok["date"]).dt.date

    fig, ax = plt.subplots(figsize=(11, 6.5))

    for et, marker in EVENT_TYPE_MARKERS.items():
        for c, color in CLUSTER_PALETTE.items():
            mask = (ok["event_type"] == et) & (ok["cluster_kmeans_k6"] == c)
            if not mask.any():
                continue
            ax.scatter(
                ok.loc[mask, "asymmetry_ratio"],
                ok.loc[mask, "peak_intensity"],
                color=color, marker=marker, s=58, alpha=0.85,
                edgecolor=COLORS["bg"], linewidth=0.6,
            )

    ax.set_yscale("log")
    ax.set_xlabel("Asymmetry ratio (lead time / lag time)")
    ax.set_ylabel("Peak intensity (× baseline above 1, log scale)")
    set_title_subtitle(
        ax,
        "Event fingerprints — peak intensity vs lead/lag asymmetry (k=6)",
        "Color = k=6 cluster.  Shape = event type.  495 matched events.",
    )

    # Annotate exemplars — per-event xytext offsets so labels don't collide.
    exemplars = _resolve_exemplars(ok)
    annot_offsets = {
        "Yankees vs Dodgers (WS G4)":                ( 1.8,  1.4),
        "Knicks vs Pacers (ECSF G7)":                ( 3.5,  6.0),
        "US Open Day 8 (Night Session - Labor Day)": ( 2.0,  2.2),
        "Macy's Thanksgiving Day Parade":            (-3.0,  0.5),
    }
    label_rewrites = {
        "US Open Day 8 (Night Session - Labor Day)": "US Open Day 8 (Night)",
        "Knicks vs Pacers (ECSF G7)":                "Knicks G7 vs Pacers",
    }
    for _, ev in exemplars.iterrows():
        dx, dy_mult = annot_offsets.get(ev["event_name"], (0.6, 1.5))
        label = label_rewrites.get(ev["event_name"], ev["event_name"])
        ax.annotate(
            label,
            xy=(ev["asymmetry_ratio"], ev["peak_intensity"]),
            xytext=(ev["asymmetry_ratio"] + dx, ev["peak_intensity"] * dy_mult),
            arrowprops=dict(arrowstyle="->", color=COLORS["ink"], lw=0.7),
            fontsize=9, color=COLORS["ink"],
            bbox=dict(boxstyle="round,pad=0.25", fc=COLORS["bg"],
                      ec=COLORS["grid"], lw=0.6),
        )

    # Two-part legend: cluster colors + event_type shapes
    cluster_handles = [
        Line2D([0], [0], marker="o", linestyle="", color=CLUSTER_PALETTE[c],
               markeredgecolor=COLORS["bg"], markersize=8,
               label=f"cluster {c}")
        for c in sorted(CLUSTER_PALETTE)
    ]
    event_handles = [
        Line2D([0], [0], marker=m, linestyle="", color=COLORS["ink"],
               markeredgecolor=COLORS["bg"], markersize=8, label=et)
        for et, m in EVENT_TYPE_MARKERS.items()
        if (ok["event_type"] == et).any()
    ]
    leg1 = ax.legend(handles=cluster_handles, loc="upper right",
                     title="cluster", fontsize=9, title_fontsize=10)
    ax.add_artist(leg1)
    ax.legend(handles=event_handles, loc="lower right",
              title="event_type", fontsize=9, title_fontsize=10)

    ax.grid(True, axis="both", alpha=0.4)

    save_figure(fig, "03_cluster_scatter", FIGURES)
    plt.close(fig)


if __name__ == "__main__":
    build()
