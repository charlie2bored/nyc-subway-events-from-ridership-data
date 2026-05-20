"""Cluster the 495 event fingerprints and answer the three pre-registered tests.

Five-dimensional feature vector per event (from `fingerprint.extract`):
  peak_intensity, lead_time_h, lag_time_h, asymmetry_ratio, half_life_h

`half_life_h` is unified across the two decay-fit regimes:
  - exponential fit (R² ≥ 0.7): use ln(2) / λ directly
  - linear fallback:           estimate t_half ≈ lag_time_h / 3
                               (heuristic: 3 half-lives ≈ "back to near baseline")
  - failed both:               imputed with the (target × event_type) median

All features are z-scored globally before clustering, per the prompt
("Feature set: the five metrics above, standardized.").

Algorithms:
  - k-means, k ∈ {2..8}, k chosen by silhouette score (random_state=42).
  - Ward-linkage hierarchical clustering for the dendrogram.
  - UMAP 2D projection for visualization only (NOT used to assign labels).

Pre-registered comparisons:
  1. Knicks vs Rangers at MSG — do the two distributions separate?
  2. MLB day games vs night games at Yankee — are they distinct?
  3. Are concerts a distinct cluster, or do they overlap with sports?

Run as a module:
    python -m fingerprint.cluster

Outputs:
  data/processed/event_features_with_clusters.parquet
  data/processed/cluster_centers.csv
  data/processed/cluster_report.md
  figures/cluster_silhouette.{png,svg}
  figures/cluster_umap.{png,svg}
  figures/cluster_dendrogram.{png,svg}
  figures/test_knicks_vs_rangers.{png,svg}
  figures/test_mlb_day_vs_night.{png,svg}
"""
from __future__ import annotations

import logging
from io import StringIO

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.stats import mannwhitneyu, ttest_ind
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from ingest.config import DATA_PROCESSED, FIGURES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fingerprint.cluster")

RANDOM_STATE = 42
# `peak_intensity` is the ratio of excess to baseline. At low-baseline
# venues (Mets-Willets late at night, baseline ~10 riders) a normal event
# can produce ratios of 100-300; at high-baseline venues (Penn / Times Sq)
# the same kind of event produces ratios under 2. Without compressing
# this scale, peak_intensity dominates the Euclidean distance and forces
# the clusterer to separate stations rather than event types.
#
# log1p() converts the ratio into "orders of magnitude above baseline,"
# which is the dimension we actually want to compare across stations.
# Lead/lag are bounded in hours and don't need it.
FEATURE_COLS_RAW = [
    "peak_intensity",
    "lead_time_h",
    "lag_time_h",
    "asymmetry_ratio",
    "half_life_h",
]
FEATURE_COLS = [
    "peak_intensity_log",     # log1p(peak_intensity)
    "lead_time_h",
    "lag_time_h",
    "asymmetry_ratio",
    "half_life_h",
]
K_RANGE = list(range(2, 9))

# Distinct marker per event_type for figures.
EVENT_TYPE_MARKER = {
    "Sports-MLB": "o",
    "Sports-NBA": "s",
    "Sports-NHL": "D",
    "Concert":    "^",
    "Parade":     "P",
    "Civic":      "X",
    "Other":      "*",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def unify_half_life(row: pd.Series) -> float:
    """Map a row's decay fit to a single half-life-in-hours feature."""
    hl = row.get("decay_half_life_h")
    if pd.notna(hl) and hl > 0:
        return float(hl)
    lag = row.get("lag_time_h")
    if pd.notna(lag):
        # 3 half-lives ≈ 87.5% decayed; lag_time uses a 20% threshold so this
        # is a defensible coarse equivalence.
        return float(lag) / 3
    return np.nan


def _save_fig(fig: plt.Figure, name: str) -> None:
    for ext, kw in (("png", {"dpi": 300}), ("svg", {})):
        path = FIGURES / f"{name}.{ext}"
        fig.savefig(path, bbox_inches="tight", **kw)
        log.info("Wrote %s", path)


def _md_section(buf: StringIO, title: str, level: int = 2) -> None:
    buf.write(f"\n{'#' * level} {title}\n\n")


# ---------------------------------------------------------------------------
# load + prepare
# ---------------------------------------------------------------------------

def load_features() -> pd.DataFrame:
    feats = pd.read_parquet(DATA_PROCESSED / "event_features.parquet")
    feats = feats[feats["status"] == "ok"].copy()
    feats["half_life_h"] = feats.apply(unify_half_life, axis=1)
    # Group-median impute, then global-median backstop.
    feats["half_life_h"] = feats.groupby(
        ["target_key", "event_type"], observed=True
    )["half_life_h"].transform(lambda s: s.fillna(s.median()))
    feats["half_life_h"] = feats["half_life_h"].fillna(feats["half_life_h"].median())
    feats["peak_intensity_log"] = np.log1p(feats["peak_intensity"].clip(lower=0))
    return feats


# ---------------------------------------------------------------------------
# k-means + silhouette
# ---------------------------------------------------------------------------

def run_kmeans_sweep(X: np.ndarray) -> tuple[dict[int, float], KMeans]:
    silhouettes: dict[int, float] = {}
    best_k, best_score, best_model = None, -np.inf, None
    for k in K_RANGE:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=20)
        labels = km.fit_predict(X)
        s = silhouette_score(X, labels)
        silhouettes[k] = s
        if s > best_score:
            best_k, best_score, best_model = k, s, km
        log.info("k=%d  silhouette=%.4f", k, s)
    log.info("Picked k=%d (silhouette=%.4f)", best_k, best_score)
    return silhouettes, best_model


def plot_silhouette_curve(silhouettes: dict[int, float], best_k: int) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ks = sorted(silhouettes)
    ax.plot(ks, [silhouettes[k] for k in ks], marker="o", color="#222")
    ax.axvline(best_k, linestyle="--", color="#c43a31", linewidth=1, label=f"chosen k={best_k}")
    ax.set_xlabel("k")
    ax.set_ylabel("Silhouette score")
    ax.set_title("k-means silhouette over k=2..8")
    ax.legend()
    ax.grid(alpha=0.3)
    _save_fig(fig, "cluster_silhouette")
    plt.close(fig)


# ---------------------------------------------------------------------------
# hierarchical
# ---------------------------------------------------------------------------

def plot_dendrogram(X: np.ndarray, n_clusters: int) -> np.ndarray:
    Z = linkage(X, method="ward")
    hier_labels = fcluster(Z, t=n_clusters, criterion="maxclust")
    fig, ax = plt.subplots(figsize=(11, 5))
    dendrogram(
        Z,
        ax=ax,
        no_labels=True,
        color_threshold=Z[-(n_clusters - 1), 2],
        above_threshold_color="#888",
    )
    ax.set_title(f"Ward-linkage dendrogram (cut at k={n_clusters})")
    ax.set_ylabel("Distance")
    _save_fig(fig, "cluster_dendrogram")
    plt.close(fig)
    return hier_labels


# ---------------------------------------------------------------------------
# UMAP (viz only)
# ---------------------------------------------------------------------------

def umap_project(X: np.ndarray) -> np.ndarray:
    import umap

    reducer = umap.UMAP(n_components=2, random_state=RANDOM_STATE)
    return reducer.fit_transform(X)


def plot_umap(emb: np.ndarray, feats: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 7))
    cluster_palette = plt.get_cmap("tab10")
    for et, marker in EVENT_TYPE_MARKER.items():
        mask = feats["event_type"] == et
        if not mask.any():
            continue
        ax.scatter(
            emb[mask, 0], emb[mask, 1],
            c=[cluster_palette(int(c)) for c in feats.loc[mask, "cluster_kmeans"]],
            marker=marker, s=42, alpha=0.85, edgecolors="white", linewidth=0.4,
            label=et,
        )
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    ax.set_title("UMAP projection of 495 events — color = k-means cluster, marker = event_type")
    # Legend with shape per event_type
    legend_handles = [
        Line2D([0], [0], marker=m, color="w", markerfacecolor="#444",
               markeredgecolor="white", markersize=8, label=t)
        for t, m in EVENT_TYPE_MARKER.items() if (feats["event_type"] == t).any()
    ]
    ax.legend(handles=legend_handles, loc="best", frameon=True)
    ax.grid(alpha=0.25)
    _save_fig(fig, "cluster_umap")
    plt.close(fig)


# ---------------------------------------------------------------------------
# pre-registered comparisons
# ---------------------------------------------------------------------------

def cluster_distribution(feats: pd.DataFrame, mask: pd.Series, group_col: str) -> pd.DataFrame:
    sub = feats.loc[mask].copy()
    tab = pd.crosstab(sub[group_col], sub["cluster_kmeans"])
    tab["total"] = tab.sum(axis=1)
    return tab


def plot_knicks_vs_rangers(feats: pd.DataFrame) -> None:
    sub = feats[
        (feats["target_key"] == "msg_penn")
        & (feats["event_type"].isin(["Sports-NBA", "Sports-NHL"]))
    ].copy()
    fig, ax = plt.subplots(figsize=(8, 6))
    for et, color in (("Sports-NBA", "#1f6feb"), ("Sports-NHL", "#c43a31")):
        m = sub["event_type"] == et
        ax.scatter(
            sub.loc[m, "peak_intensity"], sub.loc[m, "half_life_h"],
            c=color, s=60, alpha=0.7, edgecolor="white", linewidth=0.5,
            label=f"{et} (n={int(m.sum())})",
        )
    ax.set_xlabel("Peak intensity (× baseline above 1)")
    ax.set_ylabel("Post-event half-life (hours)")
    ax.set_title("Knicks (NBA) vs Rangers (NHL) at MSG — fingerprint comparison")
    ax.legend()
    ax.grid(alpha=0.3)
    _save_fig(fig, "test_knicks_vs_rangers")
    plt.close(fig)


def plot_mlb_day_vs_night(feats: pd.DataFrame) -> None:
    yk = feats[(feats["target_key"] == "yankee") & (feats["event_type"] == "Sports-MLB")].copy()
    yk["session"] = yk["event_start_dt"].apply(
        lambda dt: "day" if pd.to_datetime(dt).hour < 17 else "night"
    )
    fig, ax = plt.subplots(figsize=(8, 6))
    for sess, color in (("day", "#f08c00"), ("night", "#1f3a93")):
        m = yk["session"] == sess
        ax.scatter(
            yk.loc[m, "peak_intensity"], yk.loc[m, "half_life_h"],
            c=color, s=60, alpha=0.7, edgecolor="white", linewidth=0.5,
            label=f"{sess} (n={int(m.sum())})",
        )
    ax.set_xlabel("Peak intensity (× baseline above 1)")
    ax.set_ylabel("Post-event half-life (hours)")
    ax.set_title("Yankee Stadium — day vs night MLB games fingerprint")
    ax.legend()
    ax.grid(alpha=0.3)
    _save_fig(fig, "test_mlb_day_vs_night")
    plt.close(fig)


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def _pairwise_tests(df: pd.DataFrame, group_col: str, features: list[str]) -> pd.DataFrame:
    """Mann-Whitney U (nonparametric) and Welch's t-test on every feature."""
    groups = df[group_col].dropna().unique()
    if len(groups) != 2:
        return pd.DataFrame()
    a, b = sorted(groups)
    da = df.loc[df[group_col] == a]
    db = df.loc[df[group_col] == b]
    rows = []
    for f in features:
        x, y = da[f].dropna(), db[f].dropna()
        if len(x) < 2 or len(y) < 2:
            continue
        try:
            u_stat, u_p = mannwhitneyu(x, y, alternative="two-sided")
        except ValueError:
            u_stat, u_p = float("nan"), float("nan")
        try:
            t_stat, t_p = ttest_ind(x, y, equal_var=False)
        except ValueError:
            t_stat, t_p = float("nan"), float("nan")
        rows.append({
            "feature": f,
            f"{a}_median": round(float(x.median()), 3),
            f"{b}_median": round(float(y.median()), 3),
            f"{a}_n": len(x),
            f"{b}_n": len(y),
            "MWU_p": round(float(u_p), 5),
            "ttest_p": round(float(t_p), 5),
            "sig_at_0.05": bool(u_p < 0.05) if not np.isnan(u_p) else False,
        })
    return pd.DataFrame(rows)


def build_report(
    feats: pd.DataFrame,
    silhouettes: dict[int, float],
    best_k: int,
    centers: pd.DataFrame,
    centers_k6: pd.DataFrame,
) -> str:
    buf = StringIO()
    buf.write("# Cluster Analysis Report — 2024 Event Fingerprints\n\n")
    buf.write(
        "*Generated by `fingerprint.cluster`. 5-D feature vector per event, "
        "z-scored globally, k-means with silhouette-picked k. Ward linkage "
        "hierarchical for the dendrogram. UMAP for viz only.*\n"
    )

    _md_section(buf, "Silhouette sweep", 2)
    sil_df = pd.DataFrame(sorted(silhouettes.items()), columns=["k", "silhouette"]).round(4)
    buf.write(sil_df.to_markdown(index=False) + "\n")
    buf.write(f"\n**Chosen k = {best_k}** (highest silhouette = {silhouettes[best_k]:.4f}).\n")

    _md_section(buf, "Cluster centers (z-score space)", 2)
    buf.write(centers.round(2).to_markdown() + "\n")
    buf.write(
        "\n*Each cluster's mean in the standardized feature space. Read each row "
        "as a fingerprint archetype — e.g., positive `peak_intensity` and positive "
        "`half_life_h` means 'big peak, slow decay'.*\n"
    )

    _md_section(buf, "Cluster composition by (target × event_type)", 2)
    comp = pd.crosstab(
        [feats["target_key"], feats["event_type"]],
        feats["cluster_kmeans"],
    )
    comp["total"] = comp.sum(axis=1)
    buf.write(comp.to_markdown() + "\n")

    # ---- forced k=6 comparison (finer structure) -------------------------
    _md_section(buf, "Forced k=6 (finer structure)", 2)
    buf.write(
        "Silhouette picked k=2 because two coarse clusters (indoor-quick vs "
        "outdoor-slow) dominate the variance. To check whether finer "
        "structure exists, we also report k=6 (a local silhouette peak among "
        "higher k):\n\n"
    )
    buf.write("Cluster centers at k=6 (z-score space):\n\n")
    buf.write(centers_k6.round(2).to_markdown() + "\n")
    comp_k6 = pd.crosstab(
        [feats["target_key"], feats["event_type"]],
        feats["cluster_kmeans_k6"],
    )
    comp_k6["total"] = comp_k6.sum(axis=1)
    buf.write("\nCluster composition (k=6) by (target × event_type):\n\n")
    buf.write(comp_k6.to_markdown() + "\n")

    # --- pre-registered test 1: Knicks vs Rangers --------------------------
    _md_section(buf, "Test 1 — Knicks (NBA) vs Rangers (NHL) at MSG", 2)
    kr = feats[
        (feats["target_key"] == "msg_penn")
        & (feats["event_type"].isin(["Sports-NBA", "Sports-NHL"]))
    ]
    kr_tab = pd.crosstab(kr["event_type"], kr["cluster_kmeans"])
    kr_tab["total"] = kr_tab.sum(axis=1)
    buf.write("Cluster assignment:\n\n")
    buf.write(kr_tab.to_markdown() + "\n")
    buf.write(
        "\nFeature medians (raw scale, not log):\n\n"
    )
    buf.write(
        kr.groupby("event_type")[FEATURE_COLS_RAW].median().round(3).to_markdown() + "\n"
    )
    buf.write("\nFeature-level statistical tests (NBA vs NHL):\n\n")
    buf.write(_pairwise_tests(kr, "event_type", FEATURE_COLS_RAW).to_markdown(index=False) + "\n")

    # --- pre-registered test 2: MLB day vs night --------------------------
    _md_section(buf, "Test 2 — MLB day vs night games at Yankee Stadium", 2)
    yk = feats[(feats["target_key"] == "yankee") & (feats["event_type"] == "Sports-MLB")].copy()
    yk["session"] = pd.to_datetime(yk["event_start_dt"]).dt.hour.apply(
        lambda h: "day" if h < 17 else "night"
    )
    yk_tab = pd.crosstab(yk["session"], yk["cluster_kmeans"])
    yk_tab["total"] = yk_tab.sum(axis=1)
    buf.write("Cluster assignment:\n\n")
    buf.write(yk_tab.to_markdown() + "\n")
    buf.write("\nFeature medians (raw scale, not log):\n\n")
    buf.write(yk.groupby("session")[FEATURE_COLS_RAW].median().round(3).to_markdown() + "\n")
    buf.write("\nFeature-level statistical tests (day vs night):\n\n")
    buf.write(_pairwise_tests(yk, "session", FEATURE_COLS_RAW).to_markdown(index=False) + "\n")

    # --- pre-registered test 3: are concerts a distinct cluster? -----------
    _md_section(buf, "Test 3 — Are concerts a distinct cluster?", 2)
    by_cluster = (
        feats.groupby("cluster_kmeans")["event_type"]
        .value_counts()
        .unstack(fill_value=0)
    )
    buf.write(by_cluster.to_markdown() + "\n")
    # Concentration: fraction of all concerts in their modal cluster.
    concerts = feats[feats["event_type"] == "Concert"]
    if not concerts.empty:
        modal = concerts["cluster_kmeans"].mode().iloc[0]
        frac = (concerts["cluster_kmeans"] == modal).mean()
        buf.write(
            f"\nModal cluster for Concert events: **{modal}** "
            f"({frac*100:.1f}% of all concerts).\n"
        )
        # Purity: what fraction of that cluster's events are concerts?
        modal_size = (feats["cluster_kmeans"] == modal).sum()
        modal_concerts = ((feats["cluster_kmeans"] == modal) & (feats["event_type"] == "Concert")).sum()
        buf.write(
            f"Within cluster {modal}: **{modal_concerts}** / "
            f"**{modal_size}** members are concerts ({100*modal_concerts/modal_size:.1f}% purity).\n"
        )

    return buf.getvalue()


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

def main() -> int:
    log.info("Loading features ...")
    feats = load_features()
    log.info("Loaded %d events", len(feats))

    log.info("Standardizing features ...")
    scaler = StandardScaler()
    X = scaler.fit_transform(feats[FEATURE_COLS].values)

    log.info("Running k-means sweep ...")
    silhouettes, best_km = run_kmeans_sweep(X)
    feats["cluster_kmeans"] = best_km.labels_
    best_k = best_km.n_clusters

    # Forced k=6 alongside the silhouette-picked k for finer structure.
    log.info("Running forced k=6 for finer structure ...")
    km6 = KMeans(n_clusters=6, random_state=RANDOM_STATE, n_init=20).fit(X)
    feats["cluster_kmeans_k6"] = km6.labels_

    log.info("Plotting silhouette curve ...")
    plot_silhouette_curve(silhouettes, best_k)

    log.info("Running hierarchical clustering + dendrogram ...")
    hier_labels = plot_dendrogram(X, n_clusters=best_k)
    feats["cluster_hierarchical"] = hier_labels

    log.info("Running UMAP projection ...")
    emb = umap_project(X)
    feats["umap_x"] = emb[:, 0]
    feats["umap_y"] = emb[:, 1]
    plot_umap(emb, feats)

    log.info("Building pre-registered comparison plots ...")
    plot_knicks_vs_rangers(feats)
    plot_mlb_day_vs_night(feats)

    # Cluster center summary, back in z-score space for interpretability.
    centers_z = pd.DataFrame(
        best_km.cluster_centers_,
        columns=FEATURE_COLS,
    )
    centers_z.index.name = "cluster_kmeans"
    sizes = feats["cluster_kmeans"].value_counts().sort_index()
    centers_z.insert(0, "n_events", sizes.values)

    feats.to_parquet(DATA_PROCESSED / "event_features_with_clusters.parquet", index=False)
    log.info("Wrote %s", DATA_PROCESSED / "event_features_with_clusters.parquet")

    centers_z.to_csv(DATA_PROCESSED / "cluster_centers.csv")
    log.info("Wrote %s", DATA_PROCESSED / "cluster_centers.csv")

    centers_k6 = pd.DataFrame(km6.cluster_centers_, columns=FEATURE_COLS)
    centers_k6.index.name = "cluster_kmeans_k6"
    sizes_k6 = feats["cluster_kmeans_k6"].value_counts().sort_index()
    centers_k6.insert(0, "n_events", sizes_k6.values)
    centers_k6.to_csv(DATA_PROCESSED / "cluster_centers_k6.csv")

    report = build_report(feats, silhouettes, best_k, centers_z, centers_k6)
    report_path = DATA_PROCESSED / "cluster_report.md"
    report_path.write_text(report)
    log.info("Wrote %s", report_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
