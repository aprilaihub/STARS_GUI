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
    return arr


def label_mode(base: str, mode: str, is_index: bool = False) -> str:
    if mode == "linear":
        return base
    if mode == "log10":
        return "log10(index+1)" if is_index else f"log10(|{base}|)"
    return base
