"""Build all four portfolio deliverable charts in one go."""
from __future__ import annotations

import logging

from viz import cluster_scatter, decay_small_multiples, hero_baseline, urban_matrix

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("viz.build_all")


CHARTS = [
    ("hero baseline (Knicks G7)", hero_baseline.build),
    ("urban matrix heatmap",      urban_matrix.build),
    ("cluster scatter",           cluster_scatter.build),
    ("decay small multiples",     decay_small_multiples.build),
]


def main() -> int:
    for name, fn in CHARTS:
        log.info("--- building: %s ---", name)
        try:
            fn()
        except Exception as e:
            log.exception("[%s] failed: %s", name, e)
            return 1
    log.info("All four charts rendered.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
