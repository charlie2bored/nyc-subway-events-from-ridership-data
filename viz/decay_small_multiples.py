"""Bonus: 3×3 grid of post-event ridership decay curves with fitted overlay.

Nine representative events across event types and venues. Each panel
plots the post-event hourly ridership as points, with either the
exponential decay (fit succeeded, R² ≥ 0.7) or the linear fallback
overlaid. Panel title carries the event name and the fitted half-life
(or linear slope when the exponential fit failed).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from ingest.config import DATA_PROCESSED, FIGURES, TARGETS
from viz.style import COLORS, apply_style, save_figure, set_fig_title_subtitle


PANEL_EVENTS = [
    # row 1: postseason drama
    {"date": "2024-10-29", "target": "yankee",   "name_contains": "WS G4"},
    {"date": "2024-10-17", "target": "mets",     "name_contains": "NLCS G4"},
    {"date": "2024-05-19", "target": "msg_penn", "name_contains": "Pacers (ECSF G7)"},
    # row 2: regular season at three different venues
    {"date": "2024-04-05", "target": "yankee",   "name_contains": "TOR"},
    {"date": "2024-09-20", "target": "mets",     "name_contains": "PHI"},
    {"date": "2024-04-23", "target": "msg_penn", "name_contains": "Capitals (R1 G2)"},
    # row 3: variety
    {"date": "2024-09-02", "target": "mets",     "name_contains": "US Open Day 8"},
    {"date": "2024-11-28", "target": "times_sq", "name_contains": "Thanksgiving"},
    {"date": "2024-12-30", "target": "msg_penn", "name_contains": "Phish"},
]

POST_HOURS = 10


def _target_complexes(target: str) -> list[str]:
    for t in TARGETS:
        if t.key == target:
            return list(t.complex_ids)
    return []


def _find_event(features: pd.DataFrame, spec: dict) -> pd.Series | None:
    date = pd.to_datetime(spec["date"]).date()
    mask = (
        (features["target_key"] == spec["target"])
        & (features["date"] == date)
        & (features["event_name"].str.contains(spec["name_contains"], na=False, regex=False))
    )
    sub = features[mask]
    if sub.empty:
        return None
    return sub.iloc[0]


def _exp_curve(t: np.ndarray, A: float, lam: float, baseline: float) -> np.ndarray:
    return baseline + A * np.exp(-lam * t)


def _fit_overlay(t: np.ndarray, y: np.ndarray, baseline: float) -> tuple[np.ndarray, str]:
    """Return (y_curve_at_t, annotation_str). Annotation includes half-life."""
    # Try exponential first
    A0 = max(y[0] - baseline, 1.0)
    try:
        popt, _ = curve_fit(
            lambda tt, A, lam: baseline + A * np.exp(-lam * tt),
            t, y,
            p0=[A0, 0.3], maxfev=4000,
            bounds=([0, 0.001], [np.inf, 10.0]),
        )
        A_fit, lam_fit = popt
        y_pred = baseline + A_fit * np.exp(-lam_fit * t)
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        if r2 >= 0.7:
            half = np.log(2) / lam_fit
            return y_pred, f"exp fit: t½ = {half:.2f}h (R² = {r2:.2f})"
    except (RuntimeError, ValueError):
        pass

    # Linear fallback
    slope, intercept = np.polyfit(t, y, 1)
    y_pred = slope * t + intercept
    return y_pred, f"linear: slope = {slope:.0f}/h"


def build() -> None:
    apply_style()
    feats = pd.read_parquet(DATA_PROCESSED / "event_features_with_clusters.parquet")
    feats["date"] = pd.to_datetime(feats["date"]).dt.date

    ridership = pd.read_parquet(DATA_PROCESSED / "ridership_with_baseline_v2.parquet")
    ridership["transit_timestamp"] = pd.to_datetime(ridership["transit_timestamp"])

    fig, axes = plt.subplots(3, 3, figsize=(13, 9.5), sharex=True)
    axes = axes.flatten()

    for ax, spec in zip(axes, PANEL_EVENTS):
        ev = _find_event(feats, spec)
        if ev is None:
            ax.set_title(f"{spec['name_contains']}\n(no match)", fontsize=10, color=COLORS["muted"])
            ax.text(0.5, 0.5, "not found", ha="center", va="center",
                    transform=ax.transAxes, color=COLORS["subtle"])
            continue

        event_end = pd.to_datetime(ev["event_end_dt"])
        complexes = _target_complexes(ev["target_key"])
        window_end = event_end + timedelta(hours=POST_HOURS)
        sub = ridership.loc[
            (ridership["target_key"] == ev["target_key"])
            & (ridership["transit_timestamp"] > event_end)
            & (ridership["transit_timestamp"] <= window_end)
        ]
        hourly = (
            sub.groupby("transit_timestamp")[["ridership", "baseline_ridership"]]
            .sum()
            .sort_index()
        )
        if len(hourly) < 3:
            ax.set_title(f"{ev['event_name']}\n(too few post-event hours)")
            continue

        t = np.array([(idx - event_end).total_seconds() / 3600 for idx in hourly.index], dtype=float)
        y = hourly["ridership"].to_numpy(dtype=float)
        baseline = float(hourly["baseline_ridership"].median())

        # Data points
        ax.scatter(t, y, color=COLORS["blue"], s=42, zorder=3,
                   edgecolor=COLORS["bg"], linewidth=0.6)
        # Baseline line
        ax.axhline(baseline, color=COLORS["subtle"], linestyle="--",
                   linewidth=1, label="baseline" if ax is axes[0] else None)
        # Fit overlay
        t_dense = np.linspace(t.min(), t.max(), 100)
        # Recompute fit using same routine
        y_pred_dense, label = _fit_overlay(
            t_dense, np.interp(t_dense, t, y), baseline
        )
        # Use the same fit determined from the actual points
        y_pred_actual, label = _fit_overlay(t, y, baseline)
        # Recreate dense by reusing the parameters captured in label — but
        # _fit_overlay does both. Simpler: just plot the line segments between
        # the actual fitted values to keep curve crisp.
        ax.plot(t, y_pred_actual, color=COLORS["indigo"], linewidth=1.8, alpha=0.9)

        # Title and annotation
        short_name = ev["event_name"][:50]
        ax.set_title(f"{short_name}\n{label}", fontsize=9.5)
        ax.tick_params(axis="both", labelsize=8)
        ax.grid(axis="y", alpha=0.4)
        ax.set_xlim(0, POST_HOURS)
        ax.set_ylim(bottom=0)

    # Shared labels
    fig.supxlabel("Hours since event end", fontsize=11, color=COLORS["text"], y=0.04)
    fig.supylabel("Riders / hour at venue station(s)", fontsize=11, color=COLORS["text"], x=0.02)
    set_fig_title_subtitle(
        fig,
        "Post-event ridership decay — nine representative events",
        "Indigo line = best fit (exponential where R² ≥ 0.7, linear otherwise).  "
        "Dashed gray = median baseline at that hour.",
    )

    plt.tight_layout(rect=[0.03, 0.04, 1, 0.92])
    save_figure(fig, "04_decay_small_multiples", FIGURES)
    plt.close(fig)


if __name__ == "__main__":
    build()
