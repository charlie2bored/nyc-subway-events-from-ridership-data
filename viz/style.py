"""matplotlib style + palette extracted from charlie2bored.com.

Apply at the top of every chart module:

    from viz.style import apply_style, COLORS, CLUSTER_PALETTE, EVENT_TYPE_MARKERS
    apply_style()

The palette has 5 distinct accent colors. For charts that need more
distinct categorical hues (e.g., 6-cluster scatter, 7 event_types), we
fall back to shape encoding rather than introducing palette drift.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# raw palette (hex values pulled from /_next/static/chunks/<hash>.css on
# charlie2bored.com 2026-05-19)
# ---------------------------------------------------------------------------

COLORS = {
    # text / structural
    "ink":          "#0a0a0a",
    "text":         "#171717",
    "muted":        "#404040",
    "subtle":       "#99a1af",
    "grid":         "#e5e7eb",
    "panel":        "#f1f1f1",
    "bg":           "#ffffff",
    # accents (ordered most-to-least vibrant)
    "blue":         "#155dfc",   # primary
    "indigo":       "#4f46e5",
    "bright_blue":  "#3080ff",
    "light_blue":   "#54a2ff",
    "slate":        "#364153",
}

# Ordered cycle for categorical plotting. 6 distinct hues so the 6-cluster
# scatter has no repeats. Order chosen to maximize hue separation across
# adjacent positions.
CYCLE = [
    COLORS["blue"],         # 0
    COLORS["indigo"],       # 1
    COLORS["bright_blue"],  # 2
    COLORS["slate"],        # 3
    COLORS["light_blue"],   # 4
    COLORS["subtle"],       # 5
]

CLUSTER_PALETTE = {i: c for i, c in enumerate(CYCLE)}

# Markers for the 7 event_types. Color is reserved for clusters; event_type
# distinguishes by marker shape.
EVENT_TYPE_MARKERS = {
    "Sports-MLB": "o",
    "Sports-NBA": "s",
    "Sports-NHL": "D",
    "Concert":    "^",
    "Parade":     "P",
    "Civic":      "X",
    "Other":      "*",
}


# ---------------------------------------------------------------------------
# rcParams
# ---------------------------------------------------------------------------

def _build_rc() -> dict:
    return {
        # figure
        "figure.facecolor":     COLORS["bg"],
        "figure.edgecolor":     COLORS["bg"],
        "figure.dpi":           110,
        "savefig.facecolor":    COLORS["bg"],
        "savefig.edgecolor":    COLORS["bg"],
        "savefig.dpi":          300,
        "savefig.bbox":         "tight",
        # axes
        "axes.facecolor":       COLORS["bg"],
        "axes.edgecolor":       COLORS["subtle"],
        "axes.linewidth":       0.8,
        "axes.labelcolor":      COLORS["text"],
        "axes.labelweight":     "regular",
        "axes.titlecolor":      COLORS["ink"],
        "axes.titleweight":     "bold",
        "axes.titlesize":       13,
        "axes.titlepad":        14,
        "axes.spines.top":      False,
        "axes.spines.right":    False,
        "axes.prop_cycle":      mpl.cycler(color=CYCLE),
        # ticks
        "xtick.color":          COLORS["muted"],
        "ytick.color":          COLORS["muted"],
        "xtick.labelsize":      10,
        "ytick.labelsize":      10,
        # grid
        "grid.color":           COLORS["grid"],
        "grid.linewidth":       0.7,
        "grid.linestyle":       "-",
        "axes.grid":            True,
        "axes.grid.axis":       "y",
        "axes.axisbelow":       True,
        # text
        "text.color":           COLORS["text"],
        "font.family":          ["sans-serif"],
        "font.sans-serif":      ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size":            11,
        # legend
        "legend.frameon":       False,
        "legend.fontsize":      10,
        "legend.title_fontsize": 10,
        # lines
        "lines.linewidth":      2.0,
        "lines.markersize":     6,
    }


def apply_style() -> None:
    """Install the charlie2bored matplotlib style into the current process."""
    mpl.rcParams.update(_build_rc())


# ---------------------------------------------------------------------------
# helpers for the chart modules
# ---------------------------------------------------------------------------

def save_figure(fig, name: str, figures_dir: Path) -> None:
    """Write the same figure to both PNG (300 dpi) and SVG."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    for ext, kw in (("png", {"dpi": 300}), ("svg", {})):
        path = figures_dir / f"{name}.{ext}"
        fig.savefig(path, bbox_inches="tight", **kw)
        print(f"wrote {path}")


def set_title_subtitle(ax, title: str, subtitle: str) -> None:
    """Place a bold left-aligned title above an axes, with a muted subtitle
    line beneath it that doesn't collide with the title.

    The pad value and the y-coordinate are tuned together so the subtitle
    always sits in the strip between the title and the plot area.
    """
    ax.set_title(title, loc="left", pad=28, fontsize=13,
                 fontweight="bold", color=COLORS["ink"])
    ax.text(0, 1.04, subtitle, transform=ax.transAxes,
            fontsize=10, color=COLORS["muted"], ha="left", va="bottom")


def set_fig_title_subtitle(fig, title: str, subtitle: str) -> None:
    """Figure-level title+subtitle for multi-panel charts. Pair with
    plt.tight_layout(rect=[0, 0, 1, 0.92]) in the caller to leave room.
    """
    fig.suptitle(title, x=0.05, ha="left", fontsize=14,
                 fontweight="bold", color=COLORS["ink"], y=0.985)
    fig.text(0.05, 0.945, subtitle, fontsize=10, color=COLORS["muted"], ha="left")
