# -*- coding: utf-8 -*-
"""
Single-experiment PF/PFIR switching fit demo (V1 DB, read-only).

What this version does:
1) Default experiment is fixed to 43003 (override with TARGET_EXPERIMENT_ID).
2) Fit positive/negative polarities separately with linear-R piecewise model:
   - negative branch (n): An*(exp(|V|/tn)-1)*(an*|V|+bn-R)^2 * I(an*|V|+bn>R)
   - positive branch (p): Ap*(exp(|V|/tp)-1)*(ap*|V|+bp-R)^2 * I(ap*|V|+bp<R)
3) Plot both polarities in ONE combined 3D axis:
   - x > 0: positive pulses
   - x < 0: negative pulses

Safety:
- Opens DB in read-only mode.
- No DB writes, no schema changes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

try:
    from GUI_feature_switching.bootstrap.config import DEFAULT_TARGET_EXPERIMENT_ID
except ImportError:
    DEFAULT_TARGET_EXPERIMENT_ID = 43003


# ============================================================
# Config
# ============================================================
ENGINE_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = ENGINE_DIR.parent
PROJECT_ROOT = PACKAGE_DIR.parent


def _default_db_path() -> Path:
    candidates = [
        PROJECT_ROOT / "Database_NEW_V2.db",
        PROJECT_ROOT / "Database_NEW.db",
        PACKAGE_DIR / "Database_NEW_V2.db",
        PACKAGE_DIR / "Database_NEW.db",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return candidates[0]


DB_PATH = _default_db_path()
OUT_DIR = PACKAGE_DIR / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BLOCK_KIND = "switching"
WINDOW_N = 15

_env_target = os.getenv("TARGET_EXPERIMENT_ID", "").strip()
if _env_target:
    if _env_target.lower() == "auto":
        TARGET_EXPERIMENT_ID: Optional[int] = None
    else:
        TARGET_EXPERIMENT_ID = int(_env_target)
else:
    TARGET_EXPERIMENT_ID = DEFAULT_TARGET_EXPERIMENT_ID

V_ABS_MIN = 0.05
MIN_POINTS_PER_POLARITY = 200
MAX_SCATTER_POINTS = 3000
X_AXIS_VIEW_EXPAND = 1.30

# Fit on binned points (more stable)
BIN_X_STEP = 0.10
BIN_Y_STEP = 40.0
MIN_BIN_COUNT = 8
FIT_ON_BINNED_POINTS = False  # fit uses raw points by default (linear-R from head to tail)

# Hard gate mode: non-active branch points are set to 0 directly.
GATE_MODE = "hard"

# Paper/tool exported initial hints (used as additional seeds).
PAPER_SEED_NEG = np.array([0.04315, 68.61, 2540.0, 1.325], dtype=float)   # [An, an, bn, tn]
PAPER_SEED_POS = np.array([-5.654, -122.2, 2818.0, 1.212], dtype=float)   # [Ap, ap, bp, tp]

# Multi-start setup (starting points/limits are important for this non-linear fit)
START_NOISE_SCALE = 0.20
N_STARTS = 20
RANDOM_SEED = 20260216

# Combined-view display controls
GRID_N_X = 60
GRID_N_Y = 60
CENTER_GAP_V = 0.0  # set 0 to visually stitch positive/negative branches at x=0
COMPRESS_SIDE_FROM_MIN_V = True  # reduce left-right split if min |V| is large

# Fig2-style overlays
N_GREEN_V_LINES_PER_POL = 4
N_RED_R_LINES = 3
PURPLE_EPS_AUTO_Q = 15.0
OVERLAY_LINES_FROM_OBSERVED_BINS = False

# Z offset for boundary lines / lower z-limit.
# Lower value = deeper base plane; use a small fraction to avoid over-dropping.
ZOFF_MARGIN_FRACTION = 0.00

# Limit fitted surface z-values for plotting only (fit itself is unchanged).
# - mode="hide": outside range -> NaN (not shown, no flat cutoff plane)
# - mode="clip": outside range -> clipped to edge value
SURFACE_LIMIT_TO_OBSERVED = True
SURFACE_LIMIT_MARGIN_FRACTION = 0.00
SURFACE_LIMIT_MODE = "hide"

# Optional boundary lines on base z-plane.
DRAW_BASE_BOUNDARY_LINES = True

# Plot style.
SURFACE_COLOR = "#d9d9d9"  # light gray for stitched surface
POINT_COLOR = "#4f79a7"    # data points color (different from surface)
V_LINE_GRAY = "#138a2e"   # fixed-V lines (paper-style green)
R_LINE_GRAY = "#d61f1f"   # fixed-R lines (paper-style red)
BOUNDARY_GRAY = "#6b6b6b"
GATE_BOUNDARY_PURPLE = "#7A3DB8"


@dataclass
class FitResult:
    polarity: str
    theta0: np.ndarray
    theta: np.ndarray
    rmse: float
    r2: float
    n_points: int
    n_starts: int
    rmse_raw: Optional[float] = None
    r2_raw: Optional[float] = None


@dataclass
class FitBundle:
    db_path: str
    exp_id: int
    cfg_id: int
    df_all: pd.DataFrame
    df_pos: pd.DataFrame
    df_neg: pd.DataFrame
    df_fit_pos: pd.DataFrame
    df_fit_neg: pd.DataFrame
    fit_pos: FitResult
    fit_neg: FitResult


def connect_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def pick_rate_config(
    conn: sqlite3.Connection,
    block_kind: str,
    window_n: int,
    config_id: Optional[int] = None,
) -> int:
    if config_id is not None:
        row = conn.execute(
            """
            SELECT c.id
            FROM Features_RS_switching_rate_cal_config c
            WHERE c.id=?
            LIMIT 1
            """,
            (int(config_id),),
        ).fetchone()
        if not row:
            raise RuntimeError(f"No rate config found for config_id={config_id}")
        return int(row["id"])

    row = conn.execute(
        """
        SELECT c.id
        FROM Features_RS_switching_rate_cal_config c
        JOIN Features_RS_switching s ON s.id = c.rs_id
        WHERE c.block_kind=? AND c.window_N=?
        ORDER BY c.id DESC
        LIMIT 1
        """,
        (str(block_kind), int(window_n)),
    ).fetchone()
    if not row:
        raise RuntimeError(f"No rate config found for block_kind={block_kind}, window_N={window_n}")
    return int(row["id"])


def auto_pick_experiment(conn: sqlite3.Connection, config_id: int, v_abs_min: float) -> int:
    row = conn.execute(
        """
        SELECT
            d.experiment_id AS experiment_id,
            COUNT(*) AS n_total,
            SUM(CASE WHEN d.amplitude_V > 0 THEN 1 ELSE 0 END) AS n_pos,
            SUM(CASE WHEN d.amplitude_V < 0 THEN 1 ELSE 0 END) AS n_neg,
            COUNT(DISTINCT ROUND(ABS(d.amplitude_V), 2)) AS n_v_levels
        FROM Features_RS_switching_rate_cal_result r
        JOIN Experimental_Detail d ON d.id = r.experimental_detail_id
        WHERE r.config_id=?
          AND d.amplitude_V IS NOT NULL
          AND d.pulse_width_s IS NOT NULL
          AND d.pulse_width_s > 0
          AND ABS(d.amplitude_V) >= ?
          AND r.mean_y_ohm IS NOT NULL
          AND r.mean_y_ohm > 0
          AND r.mu_DR_ohm IS NOT NULL
        GROUP BY d.experiment_id
        HAVING n_pos >= ? AND n_neg >= ?
        ORDER BY n_v_levels DESC, n_total DESC, d.experiment_id ASC
        LIMIT 1
        """,
        (int(config_id), float(v_abs_min), int(MIN_POINTS_PER_POLARITY), int(MIN_POINTS_PER_POLARITY)),
    ).fetchone()
    if not row:
        raise RuntimeError("No suitable experiment found for automatic selection.")
    return int(row["experiment_id"])


def load_experiment_points(conn: sqlite3.Connection, config_id: int, experiment_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT
            d.id AS detail_id,
            d.experiment_id AS experiment_id,
            d.amplitude_V AS v,
            d.pulse_width_s AS pulse_width_s,
            r.mean_y_ohm AS mean_y_ohm,
            r.mu_DR_ohm AS mu_dr_ohm
        FROM Features_RS_switching_rate_cal_result r
        JOIN Experimental_Detail d ON d.id = r.experimental_detail_id
        WHERE r.config_id=?
          AND d.experiment_id=?
        ORDER BY d.id
        """,
        conn,
        params=(int(config_id), int(experiment_id)),
    )

    if df.empty:
        return df

    df = df.copy()
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    df["pulse_width_s"] = pd.to_numeric(df["pulse_width_s"], errors="coerce")
    df["mean_y_ohm"] = pd.to_numeric(df["mean_y_ohm"], errors="coerce")
    df["mu_dr_ohm"] = pd.to_numeric(df["mu_dr_ohm"], errors="coerce")

    df = df[
        df["v"].notna()
        & df["pulse_width_s"].notna()
        & (df["pulse_width_s"] > 0)
        & df["mean_y_ohm"].notna()
        & (df["mean_y_ohm"] > 0)
        & df["mu_dr_ohm"].notna()
        & (df["v"].abs() >= float(V_ABS_MIN))
    ].copy()

    if df.empty:
        return df

    df["dRdt"] = df["mu_dr_ohm"] / df["pulse_width_s"]
    df["x"] = df["v"].abs().astype(float)  # |V|
    df["y"] = df["mean_y_ohm"].astype(float)  # mean_y (Ohm)
    df["polarity"] = np.where(df["v"] > 0, "pos", "neg")
    return df


def _bin_floor(values: np.ndarray, step: float) -> np.ndarray:
    return np.floor(values / step + 1e-12) * step


def build_fit_points(df_pol: pd.DataFrame) -> pd.DataFrame:
    d = df_pol.copy()
    d["x_bin"] = _bin_floor(d["x"].to_numpy(float), float(BIN_X_STEP))
    d["y_bin"] = _bin_floor(d["y"].to_numpy(float), float(BIN_Y_STEP))
    g = (
        d.groupby(["x_bin", "y_bin"], as_index=False)
        .agg(n=("dRdt", "size"), z=("dRdt", "mean"))
    )
    g = g[g["n"] >= int(MIN_BIN_COUNT)].copy()
    if g.empty:
        raise RuntimeError("No binned fit points left. Try lowering MIN_BIN_COUNT.")
    g.rename(columns={"x_bin": "x", "y_bin": "y"}, inplace=True)
    return g


def _pick_z_column(df_points: pd.DataFrame) -> str:
    return "z" if "z" in df_points.columns else "dRdt"


def _hard_gate(k: np.ndarray, polarity: str) -> np.ndarray:
    # n branch (negative pulses): I(k>0), p branch (positive pulses): I(k<0)
    return _active_mask_for_polarity(k, polarity=polarity).astype(float)


def _active_mask_for_polarity(k: np.ndarray, polarity: str) -> np.ndarray:
    return (k > 0.0) if polarity == "neg" else (k < 0.0)


def model_surface(theta: np.ndarray, x: np.ndarray, y: np.ndarray, polarity: str) -> np.ndarray:
    # theta = [A, a, b, t], with:
    # z = A*(exp(|x|/t)-1)*(a*|x|+b-y)^2*I(gate_condition)
    # For neg branch: I(a*|x|+b-y > 0 and x < 0)
    # For pos branch: I(a*|x|+b-y < 0 and x >= 0)
    A, a, b, t = [float(v) for v in theta]
    xx = np.abs(np.asarray(x, dtype=float))
    yy = np.asarray(y, dtype=float)
    x_signed = xx if polarity == "pos" else -xx
    t_safe = max(1e-6, t)
    k = a * xx + b - yy
    expo = np.expm1(np.clip(xx / t_safe, -30.0, 30.0))
    gate_k = _hard_gate(k, polarity=polarity)
    if polarity == "neg":
        gate_x = (x_signed < 0.0).astype(float)
    else:
        gate_x = (x_signed >= 0.0).astype(float)
    gate = gate_k * gate_x
    return A * expo * (k * k) * gate


def _estimate_boundary_line(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> Tuple[float, float]:
    rows: List[Tuple[float, float]] = []
    x_levels = np.unique(np.round(x, 6))
    for xv in x_levels:
        m = np.isclose(x, xv, atol=1e-12)
        if int(np.sum(m)) < 8:
            continue
        ym = y[m]
        zm = z[m]
        idx = int(np.argmin(np.abs(zm)))
        rows.append((float(xv), float(ym[idx])))
    if len(rows) >= 2:
        arr = np.asarray(rows, dtype=float)
        slope, intercept = np.polyfit(arr[:, 0], arr[:, 1], 1)
        return float(slope), float(intercept)
    return 0.0, float(np.median(y))


def _build_paper_seed(polarity: str, y_median: float, y_span: float) -> np.ndarray:
    base = PAPER_SEED_NEG.copy() if polarity == "neg" else PAPER_SEED_POS.copy()
    if not np.isfinite(base[2]) or (base[2] < y_median - 2.0 * y_span) or (base[2] > y_median + 2.0 * y_span):
        base[2] = y_median
    base[3] = max(0.05, float(abs(base[3])))
    return base


def make_starting_point(df_fit: pd.DataFrame, polarity: str) -> np.ndarray:
    z_col = _pick_z_column(df_fit)
    x = df_fit["x"].to_numpy(float)
    y = df_fit["y"].to_numpy(float)
    z = df_fit[z_col].to_numpy(float)

    y_q05, y_q95 = float(np.quantile(y, 0.05)), float(np.quantile(y, 0.95))
    y_span = max(1.0, y_q95 - y_q05)
    y_median = float(np.median(y))

    a0, b0 = _estimate_boundary_line(x, y, z)
    if not np.isfinite(a0):
        a0 = 0.0
    if not np.isfinite(b0):
        b0 = y_median

    x_mid = float(np.median(x))
    y_line_mid = a0 * x_mid + b0
    if (y_line_mid < y_q05 - y_span) or (y_line_mid > y_q95 + y_span):
        a0 = 0.0
        b0 = y_median

    t0 = 1.325 if polarity == "neg" else 1.212
    k0 = a0 * x + b0 - y
    active = _active_mask_for_polarity(k0, polarity=polarity)
    if int(np.sum(active)) < 20:
        active = np.ones_like(k0, dtype=bool)

    basis = np.expm1(np.clip(x / max(1e-6, t0), -30.0, 30.0)) * np.maximum(k0 * k0, 1e-12)
    valid = active & np.isfinite(z) & np.isfinite(basis) & (np.abs(basis) > 1e-12)
    if int(np.sum(valid)) >= 8:
        A0 = float(np.median(z[valid] / basis[valid]))
    else:
        A0 = float(np.mean(z) / max(1e-6, np.mean(np.abs(basis))))
    if not np.isfinite(A0):
        A0 = 1e-6 if polarity == "neg" else -1e-6

    return np.array([A0, a0, b0, t0], dtype=float)


def _build_bounds(x: np.ndarray, y: np.ndarray, z: np.ndarray, theta0: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    x_q05, x_q95 = float(np.quantile(x, 0.05)), float(np.quantile(x, 0.95))
    y_q05, y_q95 = float(np.quantile(y, 0.05)), float(np.quantile(y, 0.95))
    x_span = max(1e-6, x_q95 - x_q05)
    y_span = max(1.0, y_q95 - y_q05)

    slope_scale = max(1.0, y_span / x_span)
    k0 = theta0[1] * x + theta0[2] - y
    basis0 = np.expm1(np.clip(x / max(1e-6, theta0[3]), -30.0, 30.0)) * np.maximum(k0 * k0, 1e-12)
    z_q99 = max(1e-6, float(np.quantile(np.abs(z), 0.99)))
    basis_q90 = max(1e-9, float(np.quantile(np.abs(basis0), 0.90)))
    a_abs = max(abs(float(theta0[0])) * 50.0, (z_q99 / basis_q90) * 2000.0, 1e-8)

    lower = np.array(
        [
            -a_abs,
            -20.0 * slope_scale,
            float(np.min(y) - 2.0 * y_span),
            0.05,
        ],
        dtype=float,
    )
    upper = np.array(
        [
            a_abs,
            20.0 * slope_scale,
            float(np.max(y) + 2.0 * y_span),
            20.0,
        ],
        dtype=float,
    )
    return lower, upper


def fit_one_polarity(df_fit: pd.DataFrame, polarity: str) -> FitResult:
    z_col = _pick_z_column(df_fit)
    x = df_fit["x"].to_numpy(float)
    y = df_fit["y"].to_numpy(float)
    z = df_fit[z_col].to_numpy(float)
    theta0 = make_starting_point(df_fit, polarity=polarity)
    lower, upper = _build_bounds(x, y, z, theta0)

    y_q05, y_q95 = float(np.quantile(y, 0.05)), float(np.quantile(y, 0.95))
    y_span = max(1.0, y_q95 - y_q05)
    slope_scale = max(1.0, y_span / max(1e-6, float(np.quantile(x, 0.95) - np.quantile(x, 0.05))))
    paper_seed = _build_paper_seed(polarity=polarity, y_median=float(np.median(y)), y_span=y_span)

    def residual(theta: np.ndarray) -> np.ndarray:
        return model_surface(theta, x, y, polarity=polarity) - z

    rng = np.random.default_rng(RANDOM_SEED + (0 if polarity == "pos" else 1))
    starts: List[np.ndarray] = [np.clip(theta0, lower, upper), np.clip(paper_seed, lower, upper)]
    for _ in range(max(0, int(N_STARTS) - 2)):
        pert = theta0.copy()
        noise = rng.normal(0.0, 1.0, size=theta0.shape)
        scale = np.array(
            [
                max(abs(theta0[0]) * START_NOISE_SCALE, 1e-8),
                max(slope_scale * START_NOISE_SCALE, 0.1),
                max(y_span * START_NOISE_SCALE, 1.0),
                max(abs(theta0[3]) * START_NOISE_SCALE, 0.15),
            ],
            dtype=float,
        )
        starts.append(np.clip(pert + noise * scale, lower, upper))

    best = None
    best_rmse = float("inf")
    f_scale = max(float(np.std(z)) * 0.25, 1e-6)
    for st in starts:
        try:
            res = least_squares(
                residual,
                x0=st,
                loss="soft_l1",
                f_scale=f_scale,
                bounds=(lower, upper),
                max_nfev=5000,
            )
            z_hat = model_surface(res.x, x, y, polarity=polarity)
            rmse = float(np.sqrt(np.mean((z_hat - z) ** 2)))
            if rmse < best_rmse and np.isfinite(rmse):
                best_rmse = rmse
                best = res.x.copy()
        except Exception:
            continue

    if best is None:
        raise RuntimeError(f"Fitting failed for polarity={polarity}")

    z_hat = model_surface(best, x, y, polarity=polarity)
    sse = float(np.sum((z - z_hat) ** 2))
    sst = float(np.sum((z - np.mean(z)) ** 2))
    r2 = float(1.0 - sse / sst) if sst > 0 else float("nan")

    return FitResult(
        polarity=polarity,
        theta0=theta0,
        theta=best,
        rmse=best_rmse,
        r2=r2,
        n_points=len(df_fit),
        n_starts=len(starts),
    )


def evaluate_on_points(theta: np.ndarray, df_points: pd.DataFrame, polarity: str) -> Tuple[float, float]:
    x = df_points["x"].to_numpy(float)
    y = df_points["y"].to_numpy(float)
    z = df_points["dRdt"].to_numpy(float)
    z_hat = model_surface(theta, x, y, polarity=polarity)
    rmse = float(np.sqrt(np.mean((z_hat - z) ** 2)))
    sse = float(np.sum((z - z_hat) ** 2))
    sst = float(np.sum((z - np.mean(z)) ** 2))
    r2 = float(1.0 - sse / sst) if sst > 0 else float("nan")
    return rmse, r2


def build_surface_grid_from_span(df_span: pd.DataFrame, fit: FitResult) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Use raw point span (not binned-only span) so surface better covers full point cloud.
    x_min, x_max = float(df_span["x"].min()), float(df_span["x"].max())
    y_min, y_max = float(df_span["y"].min()), float(df_span["y"].max())
    xs = np.linspace(x_min, x_max, int(GRID_N_X))
    ys = np.linspace(y_min, y_max, int(GRID_N_Y))
    x_grid, y_grid = np.meshgrid(xs, ys)
    z_grid = model_surface(fit.theta, x_grid, y_grid, polarity=fit.polarity)
    return x_grid, y_grid, z_grid


def _pick_overlay_levels(df_fit: pd.DataFrame) -> Tuple[List[float], List[float]]:
    vx = (
        df_fit.groupby("x", as_index=False)["n"]
        .sum()
        .sort_values("n", ascending=False)["x"]
        .tolist()
    )
    vy = (
        df_fit.groupby("y", as_index=False)["n"]
        .sum()
        .sort_values("n", ascending=False)["y"]
        .tolist()
    )
    return vx, vy


def _pick_even_indices(n: int, k: int, edge_frac: float = 0.10) -> np.ndarray:
    n = int(n)
    k = int(k)
    if n <= 0 or k <= 0:
        return np.asarray([], dtype=int)
    lo = int(round(max(0.0, min(0.45, edge_frac)) * (n - 1)))
    hi = int(round((1.0 - max(0.0, min(0.45, edge_frac))) * (n - 1)))
    hi = max(lo, hi)
    cnt = min(k, hi - lo + 1)
    idx = np.linspace(lo, hi, num=cnt)
    return np.unique(np.clip(np.round(idx).astype(int), 0, n - 1))


def _choose_purple_eps(*z_arrays: np.ndarray) -> float:
    vals = []
    for arr in z_arrays:
        a = np.asarray(arr, dtype=float)
        a = np.abs(a[np.isfinite(a)])
        if a.size:
            vals.append(a)
    if not vals:
        return 1e-12
    all_abs = np.concatenate(vals)
    return float(max(1e-12, np.percentile(all_abs, float(PURPLE_EPS_AUTO_Q))))


def _extract_boundaries_from_surface(
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    z_grid: np.ndarray,
    eps: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    x_vals = x_grid[0, :].astype(float)
    y_vals = y_grid[:, 0].astype(float)

    xb: List[float] = []
    ylow: List[float] = []
    yhigh: List[float] = []
    for j, xv in enumerate(x_vals):
        col = z_grid[:, j]
        idx = np.where(np.isfinite(col) & (np.abs(col) >= float(eps)))[0]
        if idx.size == 0:
            continue
        xb.append(float(xv))
        ylow.append(float(y_vals[int(idx.min())]))
        yhigh.append(float(y_vals[int(idx.max())]))
    return np.asarray(xb, float), np.asarray(ylow, float), np.asarray(yhigh, float)


def _signed_x_for_plot(
    x_abs: np.ndarray,
    polarity: str,
    x_min_abs: float,
    center_gap_v: float = CENTER_GAP_V,
) -> np.ndarray:
    xa = np.asarray(x_abs, dtype=float)
    if COMPRESS_SIDE_FROM_MIN_V:
        base = np.maximum(0.0, xa - float(x_min_abs))
    else:
        base = xa
    base = base + float(center_gap_v) * 0.5
    return base if polarity == "pos" else -base


def _draw_overlay_lines_from_bins(
    ax,
    df_fit: pd.DataFrame,
    polarity: str,
    x_min_abs: float,
    v_levels: List[float],
    y_levels: List[float],
) -> None:
    # green: constant-V slices from observed bins
    for v0 in v_levels:
        sub = df_fit[np.isclose(df_fit["x"].to_numpy(float), float(v0), atol=1e-12)].copy()
        if len(sub) < 2:
            continue
        sub = sub.sort_values("y")
        x_line = _signed_x_for_plot(sub["x"].to_numpy(float), polarity, x_min_abs)
        y_line = sub["y"].to_numpy(float)
        z_line = sub["z"].to_numpy(float)
        ax.plot(x_line, y_line, z_line, color=V_LINE_GRAY, linewidth=2.2, alpha=0.95)

    # red: constant-R slices from observed bins
    for y0 in y_levels:
        sub = df_fit[np.isclose(df_fit["y"].to_numpy(float), float(y0), atol=1e-12)].copy()
        if len(sub) < 2:
            continue
        sub = sub.sort_values("x")
        x_line = _signed_x_for_plot(sub["x"].to_numpy(float), polarity, x_min_abs)
        y_line = sub["y"].to_numpy(float)
        z_line = sub["z"].to_numpy(float)
        ax.plot(x_line, y_line, z_line, color=R_LINE_GRAY, linewidth=2.2, alpha=0.95)


def downsample(df_pol: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(df_pol) <= max_points:
        return df_pol
    return df_pol.sample(n=max_points, random_state=RANDOM_SEED).copy()


def _active_display_points(df_pol: pd.DataFrame, theta: np.ndarray, polarity: str) -> pd.DataFrame:
    x = df_pol["x"].to_numpy(float)
    y = df_pol["y"].to_numpy(float)
    k = float(theta[1]) * x + float(theta[2]) - y
    m = _active_mask_for_polarity(k, polarity=polarity)
    if not np.any(m):
        return df_pol.iloc[0:0].copy()
    return df_pol[m].copy()


def fit_single_experiment(
    experiment_id: Optional[int] = None,
    db_path: Path = DB_PATH,
    block_kind: str = BLOCK_KIND,
    window_n: int = WINDOW_N,
    config_id: Optional[int] = None,
) -> FitBundle:
    conn = connect_ro(db_path)
    try:
        cfg_id = pick_rate_config(conn, block_kind, window_n, config_id=config_id)
        exp_id = int(experiment_id) if experiment_id is not None else auto_pick_experiment(conn, cfg_id, V_ABS_MIN)
        df = load_experiment_points(conn, cfg_id, exp_id)
    finally:
        conn.close()

    if df.empty:
        raise RuntimeError(f"No valid points for experiment_id={exp_id}")

    df_pos = df[df["polarity"] == "pos"].copy()
    df_neg = df[df["polarity"] == "neg"].copy()
    if len(df_pos) < MIN_POINTS_PER_POLARITY or len(df_neg) < MIN_POINTS_PER_POLARITY:
        raise RuntimeError(
            f"Experiment {exp_id} polarity points too small: pos={len(df_pos)}, neg={len(df_neg)}; "
            f"need at least {MIN_POINTS_PER_POLARITY} each."
        )

    df_fit_pos = build_fit_points(df_pos)
    df_fit_neg = build_fit_points(df_neg)
    fit_input_pos = df_fit_pos if FIT_ON_BINNED_POINTS else df_pos
    fit_input_neg = df_fit_neg if FIT_ON_BINNED_POINTS else df_neg
    fit_pos = fit_one_polarity(fit_input_pos, "pos")
    fit_neg = fit_one_polarity(fit_input_neg, "neg")
    fit_pos.rmse_raw, fit_pos.r2_raw = evaluate_on_points(fit_pos.theta, df_pos, polarity="pos")
    fit_neg.rmse_raw, fit_neg.r2_raw = evaluate_on_points(fit_neg.theta, df_neg, polarity="neg")

    return FitBundle(
        db_path=str(Path(db_path).resolve()),
        exp_id=exp_id,
        cfg_id=cfg_id,
        df_all=df,
        df_pos=df_pos,
        df_neg=df_neg,
        df_fit_pos=df_fit_pos,
        df_fit_neg=df_fit_neg,
        fit_pos=fit_pos,
        fit_neg=fit_neg,
    )


def draw_combined_3d(
    ax,
    bundle: FitBundle,
    scatter_limit: int = MAX_SCATTER_POINTS,
    show_raw_points: bool = True,
    hide_purple_region_points: bool = False,
) -> None:
    # Use shared R-range (min/max across positive+negative) to stitch a single plane-like surface.
    y_global_min = float(min(bundle.df_pos["y"].min(), bundle.df_neg["y"].min()))
    y_global_max = float(max(bundle.df_pos["y"].max(), bundle.df_neg["y"].max()))
    x_min_abs = float(min(bundle.df_all["x"].min(), bundle.df_fit_pos["x"].min(), bundle.df_fit_neg["x"].min()))
    x_max_abs = float(max(bundle.df_pos["x"].max(), bundle.df_neg["x"].max()))

    x_abs_vals = np.linspace(x_min_abs, x_max_abs, int(GRID_N_X))
    y_vals = np.linspace(y_global_min, y_global_max, int(GRID_N_Y))
    x_abs_grid, y_grid = np.meshgrid(x_abs_vals, y_vals)

    # Evaluate each half-surface on the same (|V|, R) grid.
    z_pos_half = model_surface(bundle.fit_pos.theta, x_abs_grid, y_grid, polarity="pos")
    z_neg_half = model_surface(bundle.fit_neg.theta, x_abs_grid, y_grid, polarity="neg")

    # Observed z-range from raw points.
    z_obs = bundle.df_all["dRdt"].to_numpy(float)
    z_obs = z_obs[np.isfinite(z_obs)]

    if SURFACE_LIMIT_TO_OBSERVED and z_obs.size:
        z_obs_min = float(np.nanmin(z_obs))
        z_obs_max = float(np.nanmax(z_obs))
        z_obs_span = max(1e-12, (z_obs_max - z_obs_min))
        z_clip_lo = z_obs_min - float(SURFACE_LIMIT_MARGIN_FRACTION) * z_obs_span
        z_clip_hi = z_obs_max + float(SURFACE_LIMIT_MARGIN_FRACTION) * z_obs_span
        if str(SURFACE_LIMIT_MODE).lower() == "clip":
            z_pos_plot = np.clip(z_pos_half, z_clip_lo, z_clip_hi)
            z_neg_plot = np.clip(z_neg_half, z_clip_lo, z_clip_hi)
            z_pos_line_plot = z_pos_plot
            z_neg_line_plot = z_neg_plot
        else:
            z_pos_plot = z_pos_half.copy()
            z_neg_plot = z_neg_half.copy()
            z_pos_plot[(z_pos_plot < z_clip_lo) | (z_pos_plot > z_clip_hi)] = np.nan
            z_neg_plot[(z_neg_plot < z_clip_lo) | (z_neg_plot > z_clip_hi)] = np.nan
            # Keep lines continuous while still bounded in z-range.
            z_pos_line_plot = np.clip(z_pos_half, z_clip_lo, z_clip_hi)
            z_neg_line_plot = np.clip(z_neg_half, z_clip_lo, z_clip_hi)
    else:
        z_pos_plot = z_pos_half
        z_neg_plot = z_neg_half
        z_pos_line_plot = z_pos_half
        z_neg_line_plot = z_neg_half

    x_pos_half = np.tile(_signed_x_for_plot(x_abs_vals, "pos", x_min_abs=x_min_abs), (int(GRID_N_Y), 1))
    x_neg_half = np.tile(_signed_x_for_plot(x_abs_vals, "neg", x_min_abs=x_min_abs), (int(GRID_N_Y), 1))

    # Stitch NEG(left) + POS(right) into one surface.
    x_stitched = np.concatenate([np.fliplr(x_neg_half), x_pos_half], axis=1)
    y_stitched = np.concatenate([np.fliplr(y_grid), y_grid], axis=1)
    z_stitched = np.concatenate([np.fliplr(z_neg_plot), z_pos_plot], axis=1)

    ax.plot_surface(
        x_stitched,
        y_stitched,
        z_stitched,
        color=SURFACE_COLOR,
        alpha=0.70,
        linewidth=0,
        antialiased=True,
    )

    # Keep overlay lines only inside the displayed surface band for each x-column.
    # This trims the unwanted outer extension while preserving both the side
    # slopes and the interior part of the fitted slices.
    y_lo_pos = np.full_like(x_abs_vals, np.nan, dtype=float)
    y_hi_pos = np.full_like(x_abs_vals, np.nan, dtype=float)
    y_lo_neg = np.full_like(x_abs_vals, np.nan, dtype=float)
    y_hi_neg = np.full_like(x_abs_vals, np.nan, dtype=float)

    for j in range(len(x_abs_vals)):
        mcol_pos = np.isfinite(z_pos_plot[:, j])
        if np.any(mcol_pos):
            yv_pos = y_vals[mcol_pos]
            y_lo_pos[j] = float(np.min(yv_pos))
            y_hi_pos[j] = float(np.max(yv_pos))

        mcol_neg = np.isfinite(z_neg_plot[:, j])
        if np.any(mcol_neg):
            yv_neg = y_vals[mcol_neg]
            y_lo_neg[j] = float(np.min(yv_neg))
            y_hi_neg[j] = float(np.max(yv_neg))

    overlay_mask_pos = (
        np.isfinite(y_lo_pos)[None, :]
        & np.isfinite(y_hi_pos)[None, :]
        & (y_grid >= y_lo_pos[None, :])
        & (y_grid <= y_hi_pos[None, :])
    )
    overlay_mask_neg = (
        np.isfinite(y_lo_neg)[None, :]
        & np.isfinite(y_hi_neg)[None, :]
        & (y_grid >= y_lo_neg[None, :])
        & (y_grid <= y_hi_neg[None, :])
    )
    z_pos_line_visible = np.where(overlay_mask_pos, z_pos_line_plot, np.nan)
    z_neg_line_visible = np.where(overlay_mask_neg, z_neg_line_plot, np.nan)

    pos_points_for_plot = bundle.df_pos
    neg_points_for_plot = bundle.df_neg
    if hide_purple_region_points:
        pos_points_for_plot = _active_display_points(bundle.df_pos, bundle.fit_pos.theta, polarity="pos")
        neg_points_for_plot = _active_display_points(bundle.df_neg, bundle.fit_neg.theta, polarity="neg")

    if show_raw_points:
        dpos = downsample(pos_points_for_plot, scatter_limit)
        dneg = downsample(neg_points_for_plot, scatter_limit)

        if len(dpos) > 0:
            ax.scatter(
                _signed_x_for_plot(dpos["x"].to_numpy(float), "pos", x_min_abs=x_min_abs),
                dpos["y"].to_numpy(float),
                dpos["dRdt"].to_numpy(float),
                s=8,
                c=POINT_COLOR,
                alpha=0.30,
                label=f"POS points (shown {len(pos_points_for_plot)}/{len(bundle.df_pos)})",
            )
        if len(dneg) > 0:
            ax.scatter(
                _signed_x_for_plot(dneg["x"].to_numpy(float), "neg", x_min_abs=x_min_abs),
                dneg["y"].to_numpy(float),
                dneg["dRdt"].to_numpy(float),
                s=8,
                c=POINT_COLOR,
                alpha=0.30,
                label=f"NEG points (shown {len(neg_points_for_plot)}/{len(bundle.df_neg)})",
            )

    # -------- Fig2-style overlays --------
    v_levels_pos, y_levels_pos = _pick_overlay_levels(bundle.df_fit_pos)
    v_levels_neg, y_levels_neg = _pick_overlay_levels(bundle.df_fit_neg)
    v_levels_pos = v_levels_pos[: int(N_GREEN_V_LINES_PER_POL)]
    v_levels_neg = v_levels_neg[: int(N_GREEN_V_LINES_PER_POL)]
    y_levels_pos = y_levels_pos[: int(N_RED_R_LINES)]
    y_levels_neg = y_levels_neg[: int(N_RED_R_LINES)]

    if OVERLAY_LINES_FROM_OBSERVED_BINS:
        _draw_overlay_lines_from_bins(
            ax=ax,
            df_fit=bundle.df_fit_pos,
            polarity="pos",
            x_min_abs=x_min_abs,
            v_levels=v_levels_pos,
            y_levels=y_levels_pos,
        )
        _draw_overlay_lines_from_bins(
            ax=ax,
            df_fit=bundle.df_fit_neg,
            polarity="neg",
            x_min_abs=x_min_abs,
            v_levels=v_levels_neg,
            y_levels=y_levels_neg,
        )
    else:
        # Draw overlays directly from fitted surface on evenly spaced slices.
        v_idx = _pick_even_indices(len(x_abs_vals), int(N_GREEN_V_LINES_PER_POL), edge_frac=0.12)
        y_idx = _pick_even_indices(len(y_vals), int(N_RED_R_LINES), edge_frac=0.12)

        yrows = y_vals
        for j in v_idx:
            x_v = float(x_abs_vals[j])
            x_line_pos = np.full_like(yrows, _signed_x_for_plot(np.array([x_v]), "pos", x_min_abs)[0], dtype=float)
            x_line_neg = np.full_like(yrows, _signed_x_for_plot(np.array([x_v]), "neg", x_min_abs)[0], dtype=float)
            ax.plot(x_line_pos, yrows, z_pos_line_visible[:, j], color=V_LINE_GRAY, linewidth=2.2, alpha=0.95)
            ax.plot(x_line_neg, yrows, z_neg_line_visible[:, j], color=V_LINE_GRAY, linewidth=2.2, alpha=0.95)

        for i in y_idx:
            y0 = float(y_vals[i])
            ax.plot(
                x_pos_half[i, :],
                np.full_like(x_pos_half[i, :], y0),
                z_pos_line_visible[i, :],
                color=R_LINE_GRAY,
                linewidth=2.2,
                alpha=0.95,
            )
            ax.plot(
                x_neg_half[i, :],
                np.full_like(x_neg_half[i, :], y0),
                z_neg_line_visible[i, :],
                color=R_LINE_GRAY,
                linewidth=2.2,
                alpha=0.95,
            )

    # purple gate-boundary line(s) on base plane
    # gate boundary: a*|V| + b - R = 0  =>  R = a*|V| + b

    z_all = np.concatenate([z_pos_plot[np.isfinite(z_pos_plot)], z_neg_plot[np.isfinite(z_neg_plot)]]) if (
        np.isfinite(z_pos_plot).any() and np.isfinite(z_neg_plot).any()
    ) else np.concatenate([z_pos_plot[np.isfinite(z_pos_plot)], z_neg_plot[np.isfinite(z_neg_plot)]])
    z_surf_min = float(np.nanmin(z_all)) if z_all.size else -1.0
    z_surf_max = float(np.nanmax(z_all)) if z_all.size else 1.0

    # Use observed points to set z-axis range, so extreme fitted tails do not push zoff too low.
    if z_obs.size:
        z_obs_min = float(np.nanmin(z_obs))
        z_obs_max = float(np.nanmax(z_obs))
    else:
        z_obs_min, z_obs_max = z_surf_min, z_surf_max

    z_floor = z_obs_min
    z_top = max(z_obs_max, z_surf_max)
    z_span = max(1e-12, (z_top - z_floor))
    zoff = z_floor - float(ZOFF_MARGIN_FRACTION) * z_span

    if DRAW_BASE_BOUNDARY_LINES:
        y_gate_pos = bundle.fit_pos.theta[1] * x_abs_vals + bundle.fit_pos.theta[2]
        y_gate_neg = bundle.fit_neg.theta[1] * x_abs_vals + bundle.fit_neg.theta[2]

        # Keep gate lines only where the displayed surface exists at that x-column.
        m_pos = (
            np.isfinite(y_gate_pos)
            & np.isfinite(y_lo_pos)
            & np.isfinite(y_hi_pos)
            & (y_gate_pos >= y_lo_pos)
            & (y_gate_pos <= y_hi_pos)
        )
        m_neg = (
            np.isfinite(y_gate_neg)
            & np.isfinite(y_lo_neg)
            & np.isfinite(y_hi_neg)
            & (y_gate_neg >= y_lo_neg)
            & (y_gate_neg <= y_hi_neg)
        )

        if np.any(m_pos):
            y_line_pos = np.where(m_pos, y_gate_pos, np.nan)
            z_line_pos = np.where(m_pos, 0.0, np.nan)
            ax.plot(
                _signed_x_for_plot(x_abs_vals, "pos", x_min_abs),
                y_line_pos,
                z_line_pos,
                color=GATE_BOUNDARY_PURPLE,
                linewidth=2.6,
                alpha=0.95,
            )
        if np.any(m_neg):
            y_line_neg = np.where(m_neg, y_gate_neg, np.nan)
            z_line_neg = np.where(m_neg, 0.0, np.nan)
            ax.plot(
                _signed_x_for_plot(x_abs_vals, "neg", x_min_abs),
                y_line_neg,
                z_line_neg,
                color=GATE_BOUNDARY_PURPLE,
                linewidth=2.6,
                alpha=0.95,
            )

    ax.set_xlabel("Pulse voltage (V)")
    ax.set_ylabel("mean_y (Ohm)")
    ax.set_zlabel("dR/dt (Ohm/s)")
    pos_raw_r2 = bundle.fit_pos.r2_raw if bundle.fit_pos.r2_raw is not None else float("nan")
    neg_raw_r2 = bundle.fit_neg.r2_raw if bundle.fit_neg.r2_raw is not None else float("nan")
    if not show_raw_points:
        point_desc = "gray surface, raw data points hidden"
    elif hide_purple_region_points:
        point_desc = "gray surface, blue points (purple-gated region hidden)"
    else:
        point_desc = "gray surface, blue data points"

    ax.set_title(
        f"exp_id={bundle.exp_id} | POS R2(fit/raw)={bundle.fit_pos.r2:.3f}/{pos_raw_r2:.3f} | "
        f"NEG R2(fit/raw)={bundle.fit_neg.r2:.3f}/{neg_raw_r2:.3f}\n"
        f"stitched surface on shared R-range (pos+neg min/max): {point_desc}"
    )

    x_plot_max = float(np.nanmax(np.abs(x_stitched.ravel())))
    x_plot_max = max(x_plot_max, 0.1)
    ax.set_xlim(-x_plot_max * 1.05 * X_AXIS_VIEW_EXPAND, x_plot_max * 1.05 * X_AXIS_VIEW_EXPAND)
    ax.set_zlim(zoff, z_top)
    ax.view_init(elev=24, azim=-122)
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) > 0:
        ax.legend(loc="upper right", fontsize=8)


def save_static_plot(bundle: FitBundle, out_dir: Path = OUT_DIR) -> Path:
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(11.5, 8))
    ax = fig.add_subplot(1, 1, 1, projection="3d")
    draw_combined_3d(ax, bundle)
    fig.tight_layout()

    out_png = out_dir / f"v1_single_exp_veriloga_fit3d_combined_exp{bundle.exp_id}_cfg{bundle.cfg_id}.png"
    fig.savefig(out_png, dpi=220)
    plt.close(fig)
    return out_png


def _theta_named(theta: np.ndarray, polarity: str) -> Dict[str, float]:
    A, a, b, t = [float(v) for v in theta]
    if polarity == "neg":
        return {"An": A, "a_n": a, "b_n": b, "tn": t}
    return {"Ap": A, "a_p": a, "b_p": b, "tp": t}


def bundle_to_summary(bundle: FitBundle, plot_png: Optional[Path] = None) -> Dict:
    return {
        "db_path": bundle.db_path,
        "block_kind": BLOCK_KIND,
        "window_n": WINDOW_N,
        "model": {
            "type": "linear_R_piecewise_exp_absx_boundary_square",
            "fit_on_binned_points": bool(FIT_ON_BINNED_POINTS),
            "gate_mode": str(GATE_MODE),
            "surface_limit_to_observed": bool(SURFACE_LIMIT_TO_OBSERVED),
            "surface_limit_mode": str(SURFACE_LIMIT_MODE),
            "surface_limit_margin_fraction": float(SURFACE_LIMIT_MARGIN_FRACTION),
            "draw_base_boundary_lines": bool(DRAW_BASE_BOUNDARY_LINES),
            "formula_global": (
                "An*(exp(|V|/tn)-1)*(a_n*|V|+b_n-R)^2*I(a_n*|V|+b_n>R & V<0) + "
                "Ap*(exp(|V|/tp)-1)*(a_p*|V|+b_p-R)^2*I(a_p*|V|+b_p<R & V>=0)"
            ),
            "formula_neg_n": "An*(exp(|V|/tn)-1)*(a_n*|V|+b_n-R)^2 * I(a_n*|V|+b_n>R & V<0)",
            "formula_pos_p": "Ap*(exp(|V|/tp)-1)*(a_p*|V|+b_p-R)^2 * I(a_p*|V|+b_p<R & V>=0)",
        },
        "config_id": bundle.cfg_id,
        "experiment_id": bundle.exp_id,
        "n_points_total": int(len(bundle.df_all)),
        "n_points_pos": int(len(bundle.df_pos)),
        "n_points_neg": int(len(bundle.df_neg)),
        "fit": {
            "pos": {
                "params_named": _theta_named(bundle.fit_pos.theta, "pos"),
                "theta0": bundle.fit_pos.theta0.tolist(),
                "theta": bundle.fit_pos.theta.tolist(),
                "rmse": bundle.fit_pos.rmse,
                "r2": bundle.fit_pos.r2,
                "rmse_raw": bundle.fit_pos.rmse_raw,
                "r2_raw": bundle.fit_pos.r2_raw,
                "n_fit_points": bundle.fit_pos.n_points,
                "n_starts": bundle.fit_pos.n_starts,
            },
            "neg": {
                "params_named": _theta_named(bundle.fit_neg.theta, "neg"),
                "theta0": bundle.fit_neg.theta0.tolist(),
                "theta": bundle.fit_neg.theta.tolist(),
                "rmse": bundle.fit_neg.rmse,
                "r2": bundle.fit_neg.r2,
                "rmse_raw": bundle.fit_neg.rmse_raw,
                "r2_raw": bundle.fit_neg.r2_raw,
                "n_fit_points": bundle.fit_neg.n_points,
                "n_starts": bundle.fit_neg.n_starts,
            },
        },
        "plot_png": str(plot_png) if plot_png else None,
    }


def save_bundle_outputs(bundle: FitBundle, out_dir: Path = OUT_DIR, plot_png: Optional[Path] = None) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"v1_single_exp_veriloga_fit3d_combined_exp{bundle.exp_id}_cfg{bundle.cfg_id}.json"
    out_csv = out_dir / f"v1_single_exp_points_exp{bundle.exp_id}_cfg{bundle.cfg_id}.csv"

    summary = bundle_to_summary(bundle, plot_png=plot_png)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    bundle.df_all.to_csv(out_csv, index=False)
    return out_json, out_csv


def main() -> None:
    bundle = fit_single_experiment(experiment_id=TARGET_EXPERIMENT_ID)
    out_png = save_static_plot(bundle, OUT_DIR)
    out_json, out_csv = save_bundle_outputs(bundle, OUT_DIR, plot_png=out_png)

    print("[OK] Done")
    print("  experiment_id:", bundle.exp_id)
    print("  config_id:", bundle.cfg_id)
    print("  n_points_total:", len(bundle.df_all))
    print("  n_points_pos/neg:", len(bundle.df_pos), len(bundle.df_neg))
    print("  pos RMSE/R2 (fit):", bundle.fit_pos.rmse, bundle.fit_pos.r2)
    print("  neg RMSE/R2 (fit):", bundle.fit_neg.rmse, bundle.fit_neg.r2)
    print("  pos RMSE/R2 (raw):", bundle.fit_pos.rmse_raw, bundle.fit_pos.r2_raw)
    print("  neg RMSE/R2 (raw):", bundle.fit_neg.rmse_raw, bundle.fit_neg.r2_raw)
    print("  plot:", out_png)
    print("  summary:", out_json)
    print("  points_csv:", out_csv)


if __name__ == "__main__":
    main()
