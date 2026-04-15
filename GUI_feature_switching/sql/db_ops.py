"""SQLite access helpers for the switching-fit GUI."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from GUI_raw_data.sql.db_ops import (
    build_function_row_cache,
    fetch_single_row_by_link,
    find_default_db as _raw_find_default_db,
    function_link_column,
    resolve_function_table,
    table_exists,
    validate_database_path as _validate_database_path,
)


@dataclass(frozen=True)
class SeriesData:
    ed_id: np.ndarray
    idx: np.ndarray
    amplitude: np.ndarray
    resistance: np.ndarray
    mean_y: np.ndarray
    mu_dr: np.ndarray
    sigma: np.ndarray
    dRdt: np.ndarray
    relrate: np.ndarray
    pulse_width: np.ndarray


def _to_float(value: Any) -> float:
    try:
        if value is None:
            return np.nan
        return float(value)
    except Exception:
        return np.nan


def find_default_db() -> str:
    return _raw_find_default_db()


def validate_switching_database_path(
    db_path: str,
) -> tuple[sqlite3.Connection, set[str], dict[str, set], set[str], set[str]]:
    conn, tables, table_cols, experiment_cols, function_config_cols = _validate_database_path(db_path)
    try:
        required = [
            "Features_RS_switching",
            "Features_RS_switching_rate_cal_config",
            "Features_RS_switching_rate_cal_result",
        ]
        missing = [table for table in required if not table_exists(conn, table)]
        if missing:
            raise RuntimeError(f"DB missing required switching tables: {missing}")
        return conn, tables, table_cols, experiment_cols, function_config_cols
    except Exception:
        conn.close()
        raise


def list_rate_configs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT
            c.id,
            c.rs_id,
            c.block_kind,
            c.window_n,
            c.created_at,
            c.note,
            s.doi AS rs_doi,
            s.note AS rs_note
        FROM Features_RS_switching_rate_cal_config c
        LEFT JOIN Features_RS_switching s
          ON s.id = c.rs_id
        ORDER BY c.id DESC
        """
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_rate_config_row(conn: sqlite3.Connection, config_id: int) -> Optional[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT
            c.id,
            c.rs_id,
            c.block_kind,
            c.window_n,
            c.created_at,
            c.note,
            s.doi AS rs_doi,
            s.note AS rs_note
        FROM Features_RS_switching_rate_cal_config c
        LEFT JOIN Features_RS_switching s
          ON s.id = c.rs_id
        WHERE c.id = ?
        LIMIT 1
        """,
        (int(config_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def format_rate_config_label(row: dict[str, Any]) -> str:
    created_at = str(row.get("created_at") or "").strip()
    created_suffix = f" | {created_at}" if created_at else ""
    return (
        f"cfg={row.get('id')} | rs={row.get('rs_id')} | "
        f"{row.get('block_kind')} | N={row.get('window_n')}{created_suffix}"
    )


def preload_switching_metadata_cache(
    conn: sqlite3.Connection,
    table_cols: dict[str, set],
    experiment_cols: set[str],
    function_config_cols: set[str],
    progress_every: int,
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """Load experiment metadata limited to experiments with switching-rate results."""
    die_cols = table_cols.get("Die", set())
    wafer_cols = table_cols.get("Wafer", set())

    select_cols = [
        "E.id AS experiment_id",
        "E.device_id AS device_id",
        "DV.subdie_id AS subdie_id",
        "S.die_id AS die_id",
        "D.wafer_id AS wafer_id",
        "W.recipe_id AS recipe_id",
        "E.function_config_id AS function_config_id",
        "E.experiment_name AS experiment_name",
        "FC.function_type AS function_type",
        "DV.wordline AS wordline",
        "DV.bitline AS bitline",
        "S.cross_sectional_area_um2 AS cross_sectional_area_um2",
        "D.die_number AS die_number",
        "R.recipe_name AS recipe_name",
    ]

    if "created_at" in experiment_cols:
        select_cols.append("E.created_at AS created_at")
    if "user_name" in experiment_cols:
        select_cols.append("E.user_name AS user_name")
    if "notes" in experiment_cols:
        select_cols.append("E.notes AS notes")
    if "notes" in function_config_cols:
        select_cols.append("FC.notes AS function_config_notes")
    if "die_type" in die_cols:
        select_cols.append("D.die_type AS die_type")
    if "wafer_name" in wafer_cols:
        select_cols.append("W.wafer_name AS wafer_name")
    if "lot" in wafer_cols:
        select_cols.append("W.lot AS lot")
    if "diameter_mm" in wafer_cols:
        select_cols.append("W.diameter_mm AS diameter_mm")

    sql = f"""
        SELECT
            {", ".join(select_cols)}
        FROM Experiment E
        JOIN Function_Config FC ON FC.id = E.function_config_id
        JOIN Device DV ON DV.id = E.device_id
        JOIN Subdie S ON S.id = DV.subdie_id
        JOIN Die D ON D.id = S.die_id
        JOIN Wafer W ON W.id = D.wafer_id
        JOIN Recipe R ON R.id = W.recipe_id
        WHERE EXISTS (
            SELECT 1
            FROM Experimental_Detail ED
            JOIN Features_RS_switching_rate_cal_result RS
              ON RS.experimental_detail_id = ED.id
            WHERE ED.experiment_id = E.id
            LIMIT 1
        )
        ORDER BY E.id ASC;
    """

    meta_rows: list[dict[str, Any]] = []
    meta_by_eid: dict[int, dict[str, Any]] = {}
    unique_values = {
        "recipe": set(),
        "die": set(),
        "area": set(),
        "wordline": set(),
        "bitline": set(),
        "function": set(),
    }

    t0 = time.perf_counter()
    cur = conn.cursor()
    cur.execute(sql)

    i = 0
    for row in cur:
        eid = int(row["experiment_id"])
        data = dict(row)
        data["experiment_name"] = data.get("experiment_name") or ""
        data["function_type"] = data.get("function_type") or ""

        meta_rows.append(data)
        meta_by_eid[eid] = data

        if data.get("recipe_name") is not None:
            unique_values["recipe"].add(str(data["recipe_name"]))
        if data.get("die_number") is not None:
            unique_values["die"].add(int(data["die_number"]))
        if data.get("cross_sectional_area_um2") is not None:
            unique_values["area"].add(int(data["cross_sectional_area_um2"]))
        if data.get("wordline") is not None:
            unique_values["wordline"].add(int(data["wordline"]))
        if data.get("bitline") is not None:
            unique_values["bitline"].add(int(data["bitline"]))
        if data.get("function_type"):
            unique_values["function"].add(str(data["function_type"]))

        i += 1
        if i % progress_every == 0:
            if on_progress:
                on_progress(i)
            if should_cancel and should_cancel():
                break

    elapsed = time.perf_counter() - t0
    return {
        "loaded_rows": i,
        "elapsed_s": elapsed,
        "meta_rows": meta_rows,
        "meta_by_eid": meta_by_eid,
        "unique_values": unique_values,
    }


def load_experiment_series(
    conn: sqlite3.Connection,
    cfg_id: int,
    experiment_id: int,
) -> SeriesData:
    rows = conn.execute(
        """
        SELECT
            ed.id AS ed_id,
            ed.resistance_ohm,
            ed.amplitude_V,
            ed.read_voltage_V,
            ed.pulse_width_s,
            r.mean_y_ohm,
            r.mu_DR_ohm,
            r.sigma_corr_ohm
        FROM Experimental_Detail ed
        LEFT JOIN Features_RS_switching_rate_cal_result r
          ON r.experimental_detail_id = ed.id
         AND r.config_id = ?
        WHERE ed.experiment_id = ?
        ORDER BY ed.id
        """,
        (int(cfg_id), int(experiment_id)),
    ).fetchall()

    ed_id = np.array([int(row["ed_id"]) for row in rows], dtype=np.int64)
    idx = np.arange(len(rows), dtype=np.int64)

    resistance = np.array([_to_float(row["resistance_ohm"]) for row in rows], dtype=float)
    amplitude = np.array([_to_float(row["amplitude_V"]) for row in rows], dtype=float)
    readv = np.array([_to_float(row["read_voltage_V"]) for row in rows], dtype=float)
    pulse_width = np.array([_to_float(row["pulse_width_s"]) for row in rows], dtype=float)

    mean_y = np.array([_to_float(row["mean_y_ohm"]) for row in rows], dtype=float)
    mu_dr = np.array([_to_float(row["mu_DR_ohm"]) for row in rows], dtype=float)
    sigma = np.array([_to_float(row["sigma_corr_ohm"]) for row in rows], dtype=float)

    amplitude_eff = amplitude.copy()
    mask_amp_bad = ~np.isfinite(amplitude_eff)
    if np.any(mask_amp_bad) and np.any(np.isfinite(readv)):
        amplitude_eff[mask_amp_bad] = readv[mask_amp_bad]

    dRdt = np.full_like(mu_dr, np.nan)
    relrate = np.full_like(mu_dr, np.nan)
    mask_pw = np.isfinite(pulse_width) & (pulse_width > 0)
    if np.any(mask_pw):
        dRdt[mask_pw] = mu_dr[mask_pw] / pulse_width[mask_pw]
        mask_rel = mask_pw & np.isfinite(mean_y) & (mean_y != 0)
        relrate[mask_rel] = mu_dr[mask_rel] / (mean_y[mask_rel] * pulse_width[mask_rel])

    return SeriesData(
        ed_id=ed_id,
        idx=idx,
        amplitude=amplitude_eff,
        resistance=resistance,
        mean_y=mean_y,
        mu_dr=mu_dr,
        sigma=sigma,
        dRdt=dRdt,
        relrate=relrate,
        pulse_width=pulse_width,
    )


__all__ = [
    "SeriesData",
    "build_function_row_cache",
    "fetch_rate_config_row",
    "fetch_single_row_by_link",
    "find_default_db",
    "format_rate_config_label",
    "function_link_column",
    "list_rate_configs",
    "load_experiment_series",
    "preload_switching_metadata_cache",
    "resolve_function_table",
    "validate_switching_database_path",
]
