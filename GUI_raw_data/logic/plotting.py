"""Plot transform helpers shared across the raw-data GUI."""

from __future__ import annotations

import numpy as np


_EPS = 1e-30


def apply_mode(arr: np.ndarray, mode: str, is_index: bool = False) -> np.ndarray:
    if arr is None:
        return arr
    if mode == "linear":
        return arr
    if mode == "log10":
        if is_index:
            return np.log10(np.maximum(arr, 0) + 1.0)
        return np.log10(np.maximum(np.abs(arr), _EPS))
    if mode == "sqrt":
        return np.sqrt(np.maximum(np.abs(arr), 0))
    return arr


def label_mode(base: str, mode: str, is_index: bool = False) -> str:
    if mode == "linear":
        return base
    if mode == "log10":
        return "log10(index+1)" if is_index else f"log10(|{base}|)"
    if mode == "sqrt":
        return f"sqrt(|{base}|)"
    return base


def group_data_for_tft_output(
    v_gs: np.ndarray, v_ds: np.ndarray, i_ds: np.ndarray
) -> list[dict[str, np.ndarray | str]]:
    """Groups sweep data by V_gs for a standard TFT output characteristics plot."""
    datasets = []
    # Round Vgs to a reasonable precision to group sweeps
    unique_v_gs_steps = np.unique(np.round(v_gs, decimals=2))

    for v_gs_step in unique_v_gs_steps:
        mask = np.isclose(v_gs, v_gs_step, atol=1e-3)
        if not np.any(mask):
            continue

        sort_indices = np.argsort(v_ds[mask])
        datasets.append(
            {"x": v_ds[mask][sort_indices], "y": i_ds[mask][sort_indices], "label": f"Vgs={v_gs_step:.2f}V"}
        )
    return datasets
