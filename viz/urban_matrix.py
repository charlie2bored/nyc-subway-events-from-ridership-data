"""Urban Matrix Heatmap: station × event_type, cell = mean peak intensity."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from ingest.config import DATA_PROCESSED, FIGURES
from viz.style import COLORS, apply_style, save_figure, set_title_subtitle


ROW_LABELS = {
    "yankee":   "Yankee Stadium",
    "mets":     "Mets-Willets / US Open",
    "msg_penn": "MSG (Penn Station)",
    "barclays": "Barclays Center",
    "times_sq": "Times Sq-42 St",
}
ROW_ORDER = ["yankee", "mets", "msg_penn", "barclays", "times_sq"]
COL_ORDER = ["Sports-MLB", "Sports-NBA", "Sports-NHL", "Concert", "Other", "Parade", "Civic"]


def build() -> None:
    apply_style()
    feats = pd.read_parquet(DATA_PROCESSED / "event_features_with_clusters.parquet")
    ok = feats[feats["status"] == "ok"]

    means = (
        ok.groupby(["target_key", "event_type"], observed=True)["peak_intensity"]
        .mean()
        .unstack()
        .reindex(index=ROW_ORDER, columns=COL_ORDER)
    )
    counts = (
        ok.groupby(["target_key", "event_type"], observed=True)["peak_intensity"]
        .count()
        .unstack()
        .reindex(index=ROW_ORDER, columns=COL_ORDER)
    )

    log_means = np.log10(means.where(means > 0))

    cmap = LinearSegmentedColormap.from_list(
        "c2b_blues",
        [COLORS["panel"], COLORS["light_blue"], COLORS["blue"], COLORS["indigo"]],
    )

    fig, ax = plt.subplots(figsize=(11, 5))
    im = ax.imshow(log_means.values, aspect="auto", cmap=cmap, interpolation="nearest")

    # Cell annotations
    vmid = np.nanmean(log_means.values)
    for i, row in enumerate(ROW_ORDER):
        for j, col in enumerate(COL_ORDER):
            mean_v = means.loc[row, col]
            n_v = counts.loc[row, col]
            if pd.isna(mean_v) or pd.isna(n_v):
                # Empty cell: a thin diagonal hatch
                ax.add_patch(plt.Rectangle(
                    (j - 0.5, i - 0.5), 1, 1,
                    fill=False, hatch="///", edgecolor=COLORS["grid"], linewidth=0,
                ))
                continue
            text_color = COLORS["bg"] if log_means.loc[row, col] > vmid else COLORS["ink"]
            ax.text(
                j, i,
                f"{mean_v:.1f}\nn={int(n_v)}",
                ha="center", va="center",
                fontsize=9, color=text_color, linespacing=1.2,
            )

    ax.set_xticks(range(len(COL_ORDER)))
    ax.set_xticklabels(COL_ORDER, rotation=25, ha="right", fontsize=10)
    ax.set_yticks(range(len(ROW_ORDER)))
    ax.set_yticklabels([ROW_LABELS[r] for r in ROW_ORDER], fontsize=10)

    set_title_subtitle(
        ax,
        "Peak intensity by station × event_type",
        "Cell value = mean peak intensity (× baseline). n = matched events in that cell.",
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("log₁₀(mean peak intensity)", fontsize=9)
    cbar.ax.tick_params(labelsize=9)

    ax.grid(False)
    # Move the spines back in (the imshow already gives us cells; hide outer ticks)
    ax.tick_params(axis="both", length=0)

    save_figure(fig, "02_urban_matrix", FIGURES)
    plt.close(fig)


if __name__ == "__main__":
    build()
