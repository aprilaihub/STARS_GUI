"""Structured fitting engine exports for the feature-switching GUI."""

from GUI_feature_switching.fitting_model.engine import (
    BLOCK_KIND,
    DEFAULT_TARGET_EXPERIMENT_ID,
    DB_PATH,
    FitBundle,
    FitResult,
    MAX_SCATTER_POINTS,
    OUT_DIR,
    WINDOW_N,
    auto_pick_experiment,
    bundle_to_summary,
    connect_ro,
    draw_combined_3d,
    fit_single_experiment,
    pick_rate_config,
    save_bundle_outputs,
    save_static_plot,
)

__all__ = [
    "BLOCK_KIND",
    "DEFAULT_TARGET_EXPERIMENT_ID",
    "DB_PATH",
    "FitBundle",
    "FitResult",
    "MAX_SCATTER_POINTS",
    "OUT_DIR",
    "WINDOW_N",
    "auto_pick_experiment",
    "bundle_to_summary",
    "connect_ro",
    "draw_combined_3d",
    "fit_single_experiment",
    "pick_rate_config",
    "save_bundle_outputs",
    "save_static_plot",
]
