"""SQLite access helpers for the STARS raw-data GUI.

Design rule for this module:
- all direct database access should live here
- UI code should pass parameters in and receive plain Python results back
- query construction, cursor usage, and row-to-dict conversion stay centralized
"""

from __future__ import annotations

import csv
import os
import sqlite3
import time
from typing import Any, Callable, Optional

import numpy as np

_FUNCTION_TABLE_MAP = {
    "CurveTracer": "Function_CurveTracer",
    "ParameterFit": "Function_ParameterFit",
    "ParameterFit_interRetention": "Function_ParameterFit_interRetention",
}


def qident(name: str) -> str:
    """Quote a SQLite identifier safely."""
    return '"' + (name or "").replace('"', '""') + '"'


def connect_ro(db_path: str) -> sqlite3.Connection:
    """Open the selected SQLite file in read-only mode."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    """Return all user tables in the current SQLite database."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    return [r["name"] for r in cur.fetchall()]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check whether a table exists."""
    cur = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;", (table,))
    return cur.fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set:
    """Return the column names for a given table."""
    try:
        cur = conn.execute(f"PRAGMA table_info({qident(table)});")
        return {r["name"] for r in cur.fetchall()}
    except Exception:
        return set()


def inspect_database(conn: sqlite3.Connection) -> tuple[set[str], dict[str, set], set, set]:
    """Inspect the current database and return schema metadata used by the GUI."""
    tables = set(list_tables(conn))
    table_cols = {table: table_columns(conn, table) for table in tables}
    experiment_cols = table_cols.get("Experiment", set())
    function_config_cols = table_cols.get("Function_Config", set())
    return tables, table_cols, experiment_cols, function_config_cols


def validate_database_path(db_path: str) -> tuple[sqlite3.Connection, set[str], dict[str, set], set, set]:
    """Open a database and validate the minimum schema needed by this GUI."""
    conn = connect_ro(db_path)
    try:
        required = ["Experiment", "Experimental_Detail", "Device", "Subdie", "Die", "Wafer", "Recipe", "Function_Config"]
        missing = [t for t in required if not table_exists(conn, t)]
        if missing:
            raise RuntimeError(f"DB missing required tables: {missing}")

        tables, table_cols, experiment_cols, function_config_cols = inspect_database(conn)
        if "function_config_id" not in experiment_cols:
            raise RuntimeError("DB missing required Experiment.function_config_id column")

        return conn, tables, table_cols, experiment_cols, function_config_cols
    except Exception:
        conn.close()
        raise


def safe_float(value):
    """Convert a value to float, returning NaN for empty/invalid values."""
    try:
        if value is None:
            return np.nan
        return float(value)
    except Exception:
        return np.nan


def find_default_db() -> str:
    """Try a few common project paths for Database_NEW_V2.db."""
    candidates = []
    here = os.path.abspath(os.path.dirname(__file__))
    package_root = os.path.abspath(os.path.join(here, ".."))
    project_root = os.path.abspath(os.path.join(here, "..", ".."))

    candidates.append(os.path.join(project_root, "Database_NEW_V2.db"))
    candidates.append(os.path.join(package_root, "Database_NEW_V2.db"))
    candidates.append(os.path.join(os.getcwd(), "A_ETL_STAGE_4_V2", "Database_NEW_V2.db"))
    candidates.append(os.path.join(os.getcwd(), "Database_NEW_V2.db"))

    for path in candidates:
        if os.path.exists(path) and os.path.isfile(path):
            return path
    return ""


def function_link_column(function_table: str, table_cols: dict[str, set]) -> Optional[str]:
    """Return the column that links a Function_* table back to the main entities."""
    cols = table_cols.get(function_table, set())
    if "function_config_id" in cols:
        return "function_config_id"
    if "experiment_id" in cols:
        return "experiment_id"
    return None


def resolve_function_table(function_type: Optional[str], tables: set[str]) -> Optional[str]:
    """Map a function_type to the backing Function_* table if it exists."""
    if not function_type:
        return None
    table_name = _FUNCTION_TABLE_MAP.get(function_type)
    if table_name and table_name in tables:
        return table_name
    return None


def build_function_row_cache(
    conn: sqlite3.Connection,
    tables: set[str],
    table_cols: dict[str, set],
) -> dict[tuple[str, int], dict[str, Any]]:
    """Preload Function_* rows keyed by (function_type, function_config_id)."""
    cache: dict[tuple[str, int], dict[str, Any]] = {}
    for function_type, table_name in _FUNCTION_TABLE_MAP.items():
        if table_name not in tables:
            continue
        if function_link_column(table_name, table_cols) != "function_config_id":
            continue
        cur = conn.execute(f"SELECT * FROM {table_name} ORDER BY function_config_id")
        for row in cur:
            cfg_id = row["function_config_id"]
            if cfg_id is not None:
                cache[(function_type, int(cfg_id))] = dict(row)
    return cache


def preload_metadata_cache(
    conn: sqlite3.Connection,
    table_cols: dict[str, set],
    experiment_cols: set,
    function_config_cols: set,
    progress_every: int,
    on_total: Optional[Callable[[int], None]] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """Load the experiment-level metadata join used by the list and filters."""
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
        "S.cross_section_area_um2 AS cross_section_area_um2",
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
        ORDER BY E.id ASC;
    """

    total = conn.execute("SELECT COUNT(*) AS n FROM Experiment;").fetchone()["n"]
    if on_total:
        on_total(int(total) if total else 0)
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
        if data.get("cross_section_area_um2") is not None:
            unique_values["area"].add(int(data["cross_section_area_um2"]))
        if data.get("wordline") is not None:
            unique_values["wordline"].add(int(data["wordline"]))
        if data.get("bitline") is not None:
            unique_values["bitline"].add(int(data["bitline"]))
        if data.get("function_type"):
            unique_values["function"].add(str(data["function_type"]))

        i += 1
        if total and (i % progress_every == 0):
            if on_progress:
                on_progress(i)
            if should_cancel and should_cancel():
                break

    elapsed = time.perf_counter() - t0
    return {
        "total": int(total) if total else 0,
        "loaded_rows": i,
        "elapsed_s": elapsed,
        "meta_rows": meta_rows,
        "meta_by_eid": meta_by_eid,
        "unique_values": unique_values,
    }


def fetch_experiment_points(
    conn: sqlite3.Connection,
    eids: list[int],
) -> tuple[dict[int, dict[str, np.ndarray]], int, int]:
    """Fetch raw Experimental_Detail points for the given experiments."""
    point_cache: dict[int, dict[str, np.ndarray]] = {}
    fetched_exp_count = 0
    fetched_point_count = 0

    cur = conn.cursor()
    for eid in eids:
        cur.execute(
            """
            SELECT resistance, amplitude_V, readvoltage
            FROM Experimental_Detail
            WHERE experiment_id = ?
            ORDER BY id
            """,
            (eid,),
        )
        points = cur.fetchall()
        if points:
            amp_v = np.array([safe_float(point["amplitude_V"]) for point in points], dtype=float)
            read_v = np.array([safe_float(point["readvoltage"]) for point in points], dtype=float)
            resistance = np.array([safe_float(point["resistance"]) for point in points], dtype=float)

            voltage = np.where(np.isfinite(amp_v), amp_v, read_v)
            eps = 1e-30
            current = voltage / (resistance + np.sign(resistance) * eps)

            point_cache[eid] = {
                "V": voltage,
                "R": resistance,
                "I": current,
                "n": np.array([len(points)], dtype=int),
            }
            fetched_point_count += len(points)
        else:
            point_cache[eid] = {
                "V": np.empty(0, dtype=float),
                "R": np.empty(0, dtype=float),
                "I": np.empty(0, dtype=float),
                "n": np.array([0], dtype=int),
            }
        fetched_exp_count += 1

    return point_cache, fetched_exp_count, fetched_point_count


def fetch_single_row_by_link(
    conn: sqlite3.Connection,
    table_name: str,
    link_col: str,
    link_value: Any,
) -> Optional[dict[str, Any]]:
    """Fetch a single linked row from a Function_* table."""
    cur = conn.execute(
        f"SELECT * FROM {qident(table_name)} WHERE {qident(link_col)} = ? LIMIT 1",
        (link_value,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def export_sql_to_csv(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple,
    out_csv: str,
    append: bool = False,
    fetch_size: int = 50000,
) -> int:
    """Stream a query result set into a CSV file."""
    written = 0
    mode = "a" if append else "w"
    with open(out_csv, mode, newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        cur = conn.execute(sql, params)

        if not append:
            header = [desc[0] for desc in (cur.description or [])]
            if header:
                writer.writerow(header)

        while True:
            rows = cur.fetchmany(fetch_size)
            if not rows:
                break
            for row in rows:
                writer.writerow(list(row))
            written += len(rows)

    return written


def export_table_by_ids(
    conn: sqlite3.Connection,
    table: str,
    id_col: str,
    ids: list[int],
    out_csv: str,
    order_by: Optional[str] = None,
    chunk_size: int = 800,
    fetch_size: int = 50000,
) -> int:
    """Export rows from a table using a chunked IN-clause."""
    if not ids:
        return 0

    total_written = 0
    first = True
    ids_sorted = sorted({int(x) for x in ids})

    for start in range(0, len(ids_sorted), chunk_size):
        part = ids_sorted[start:start + chunk_size]
        placeholders = ",".join(["?"] * len(part))
        sql = f"SELECT * FROM {qident(table)} WHERE {qident(id_col)} IN ({placeholders})"
        if order_by:
            sql += f" ORDER BY {order_by}"
        total_written += export_sql_to_csv(
            conn=conn,
            sql=sql,
            params=tuple(part),
            out_csv=out_csv,
            append=(not first),
            fetch_size=fetch_size,
        )
        first = False

    return total_written


def fetch_layer_ids(conn: sqlite3.Connection, recipe_ids: list[int], chunk_size: int = 800) -> list[int]:
    """Fetch Layer ids for the selected recipe ids."""
    if not recipe_ids:
        return []

    layer_ids = set()
    recipe_ids = sorted(set(recipe_ids))
    for start in range(0, len(recipe_ids), chunk_size):
        part = recipe_ids[start:start + chunk_size]
        placeholders = ",".join(["?"] * len(part))
        sql = f"SELECT id FROM Layer WHERE recipe_id IN ({placeholders})"
        for row in conn.execute(sql, tuple(part)):
            if row["id"] is not None:
                layer_ids.add(int(row["id"]))
    return sorted(layer_ids)
