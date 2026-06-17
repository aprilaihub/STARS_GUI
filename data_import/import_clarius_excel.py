"""Import Keysight Clarius TFT measurement .xls/.xlsx files into TFT_Database.db.

Handles the two reference-measurement layouts you have:

  * Id-Vg (transfer): one or more "Run" sheets, each a transfer sweep at a
    constant Vds. Columns per block: DrainI, DrainV, GateI, GateV. Vgs is swept,
    Vds is held. -> one Experiment (function_type = 'TFT_Transfer') per block.

  * Id-Vd (output): a single "Run" sheet with one or more column blocks
    (DrainI(1), DrainV(1), ... , DrainI(n), ...). Vds is swept, Vgs is held at a
    different value per block. -> one Experiment (function_type = 'TFT_Output')
    holding the whole Vgs family.

The GUI reads the database read-only, so this script is how raw data gets *in*.

------------------------------------------------------------------------------
METADATA IS ENTERED MANUALLY
------------------------------------------------------------------------------
Edit the META dict below (or pass --meta a JSON file with the same keys) before
running. Channel width/length are auto-read from the filename pattern L<L>W<W>
when present, but every field can be overridden. Rows in the fabrication
hierarchy (Recipe -> Wafer -> Die -> Subdie -> Device) are reused if they
already exist, so re-running with the same metadata appends experiments to the
same device instead of duplicating it.

Usage:
    python data_import/import_clarius_excel.py FILE.xls [FILE2.xls ...]
        [--db path/to/TFT_Database.db]   (default: <project_root>/TFT_Database.db)
        [--meta device_meta.json]        (optional metadata override file)
        [--dry-run]                      (parse + report, write nothing)

Requires: openpyxl (for .xlsx), xlrd>=2.0 (for .xls). Install with:
    pip install openpyxl "xlrd>=2.0"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# MANUAL METADATA -- edit these for the device you are importing.
# ---------------------------------------------------------------------------
META: Dict[str, Any] = {
    "recipe_name": "TiPt-200C",        # fabrication recipe identifier
    "recipe_notes": None,

    "wafer_name": "R-wafer",           # human-readable wafer id
    "lot": None,
    "diameter_mm": None,

    "die_number": 42,                  # integer die index on the wafer
    "die_type": "C4R2",                # die design / coordinate label

    "cross_sectional_area_um2": 50,    # subdie cross-sectional area (um^2)

    "device_name": "c1r2-ch3",         # unique device label on the subdie
    "channel_width_um": None,          # auto-filled from filename L#W# if None
    "channel_length_um": None,         # auto-filled from filename L#W# if None
    "pos_x": None,
    "pos_y": None,

    "user_name": "Ege",                # operator stored on each experiment
}

# Default drain current compliance recorded on the function rows (A).
DEFAULT_CURRENT_COMPLIANCE_A = 0.1

# Column-name -> database-field mapping for one measurement block.
_COLMAP = {
    "DrainI": "i_ds_A",
    "DrainV": "v_ds_V",
    "GateI": "i_gs_A",
    "GateV": "v_gs_V",
}


# ===========================================================================
# Spreadsheet loading (.xls via xlrd, .xlsx via openpyxl)
# ===========================================================================
def load_sheets(path: str) -> Dict[str, List[list]]:
    """Return {sheet_name: [row_values, ...]} for an .xls or .xlsx workbook."""
    ext = os.path.splitext(path)[1].lower()
    sheets: Dict[str, List[list]] = {}

    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        for ws in wb.worksheets:
            sheets[ws.title] = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif ext == ".xls":
        import xlrd  # xlrd>=2.0 reads legacy .xls
        book = xlrd.open_workbook(path)
        for sh in book.sheets():
            rows = [sh.row_values(r) for r in range(sh.nrows)]
            sheets[sh.name] = rows
    else:
        raise ValueError(f"Unsupported file type: {ext} ({path})")
    return sheets


# ===========================================================================
# Parsing Clarius run sheets into measurement blocks
# ===========================================================================
def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _split_header(name: str) -> Tuple[str, int]:
    """'DrainI(2)' -> ('DrainI', 2); 'GateV' -> ('GateV', 1)."""
    m = re.match(r"^\s*([A-Za-z_]+)\s*(?:\((\d+)\))?\s*$", str(name))
    if not m:
        return str(name).strip(), 1
    base = m.group(1)
    block = int(m.group(2)) if m.group(2) else 1
    return base, block


def _is_run_sheet(name: str, header: list) -> bool:
    if not header:
        return False
    bases = {_split_header(h)[0] for h in header if h is not None}
    return {"DrainI", "DrainV", "GateI", "GateV"}.issubset(bases)


def parse_blocks(sheets: Dict[str, List[list]]) -> List[Dict[str, Any]]:
    """Extract per-block point arrays from every run sheet in the workbook.

    Each returned block: {sheet, block, points:[{v_gs_V,v_ds_V,i_ds_A,i_gs_A}], ...}
    """
    blocks: List[Dict[str, Any]] = []
    for sheet_name, rows in sheets.items():
        if not rows:
            continue
        header = rows[0]
        if not _is_run_sheet(sheet_name, header):
            continue

        # Map each column index -> (db_field, block_index)
        col_assign: Dict[int, Tuple[str, int]] = {}
        for ci, h in enumerate(header):
            if h is None:
                continue
            base, blk = _split_header(h)
            field = _COLMAP.get(base)
            if field:
                col_assign[ci] = (field, blk)

        block_ids = sorted({blk for (_f, blk) in col_assign.values()})
        for blk in block_ids:
            cols = {field: ci for ci, (field, b) in col_assign.items() if b == blk}
            points = []
            for r in rows[1:]:
                pt = {}
                ok = False
                for field, ci in cols.items():
                    val = _to_float(r[ci]) if ci < len(r) else None
                    pt[field] = val
                    if field in ("i_ds_A",) and val is not None:
                        ok = True
                if pt.get("v_gs_V") is None and pt.get("v_ds_V") is None:
                    continue
                points.append(pt)
            if points:
                blocks.append({"sheet": sheet_name, "block": blk, "points": points})
    return blocks


def _uniqueness(points: List[dict], field: str) -> int:
    vals = {round(p[field], 4) for p in points if p.get(field) is not None}
    return len(vals)


def classify_block(points: List[dict]) -> str:
    """Return 'TFT_Transfer' (Vgs swept) or 'TFT_Output' (Vds swept)."""
    n_vgs = _uniqueness(points, "v_gs_V")
    n_vds = _uniqueness(points, "v_ds_V")
    return "TFT_Transfer" if n_vgs >= n_vds else "TFT_Output"


def _const(points: List[dict], field: str) -> Optional[float]:
    vals = [p[field] for p in points if p.get(field) is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def _sweep_stats(points: List[dict], field: str) -> Tuple[float, float, float]:
    vals = sorted({round(p[field], 6) for p in points if p.get(field) is not None})
    if not vals:
        return 0.0, 0.0, 0.0
    start, stop = vals[0], vals[-1]
    step = round(vals[1] - vals[0], 6) if len(vals) > 1 else 0.0
    return start, stop, step


# ===========================================================================
# Build experiment plans from parsed blocks
# ===========================================================================
def build_experiments(blocks: List[Dict[str, Any]], source_label: str) -> List[Dict[str, Any]]:
    """Group blocks into experiment plans.

    - Each TFT_Transfer block becomes its own experiment (one constant Vds).
    - All TFT_Output blocks in the workbook are merged into one experiment
      (the Vgs family), since the GUI groups output curves by Vgs itself.
    """
    transfers = []
    outputs = []
    for b in blocks:
        if classify_block(b["points"]) == "TFT_Transfer":
            transfers.append(b)
        else:
            outputs.append(b)

    plans: List[Dict[str, Any]] = []

    for b in transfers:
        pts = b["points"]
        vds = _const(pts, "v_ds_V")
        gstart, gstop, gstep = _sweep_stats(pts, "v_gs_V")
        plans.append({
            "function_type": "TFT_Transfer",
            "experiment_name": f"{source_label} {b['sheet']} (Vds={vds} V)",
            "function_params": {
                "drain_voltage_V": vds if vds is not None else 0.0,
                "gate_start_V": gstart,
                "gate_stop_V": gstop,
                "gate_step_V": gstep,
                "cycles": 1,
                "current_compliance_A": DEFAULT_CURRENT_COMPLIANCE_A,
            },
            "points": pts,
        })

    if outputs:
        all_pts: List[dict] = []
        gate_voltages = []
        dstart = dstop = dstep = 0.0
        for b in outputs:
            pts = b["points"]
            vgs = _const(pts, "v_gs_V")
            if vgs is not None:
                gate_voltages.append(vgs)
            dstart, dstop, dstep = _sweep_stats(pts, "v_ds_V")
            all_pts.extend(pts)
        plans.append({
            "function_type": "TFT_Output",
            "experiment_name": f"{source_label} output (Vgs={gate_voltages} V)",
            "function_params": {
                "gate_voltages_V": json.dumps(gate_voltages),
                "drain_start_V": dstart,
                "drain_stop_V": dstop,
                "drain_step_V": dstep,
                "cycles": 1,
                "current_compliance_A": DEFAULT_CURRENT_COMPLIANCE_A,
            },
            "points": all_pts,
        })

    return plans


# ===========================================================================
# Database get-or-create helpers
# ===========================================================================
def _get_or_create(conn, table, match: dict, insert: dict) -> int:
    where = " AND ".join(f'"{k}" IS ?' if v is None else f'"{k}" = ?'
                         for k, v in match.items())
    params = tuple(match.values())
    row = conn.execute(f'SELECT id FROM "{table}" WHERE {where} LIMIT 1', params).fetchone()
    if row:
        return int(row[0])
    cols = ", ".join(f'"{k}"' for k in insert)
    qs = ", ".join("?" for _ in insert)
    cur = conn.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({qs})', tuple(insert.values()))
    return int(cur.lastrowid)


def resolve_device(conn, meta: Dict[str, Any]) -> int:
    recipe_id = _get_or_create(
        conn, "Recipe",
        {"recipe_name": meta["recipe_name"]},
        {"recipe_name": meta["recipe_name"], "notes": meta.get("recipe_notes")},
    )
    wafer_id = _get_or_create(
        conn, "Wafer",
        {"recipe_id": recipe_id, "wafer_name": meta["wafer_name"]},
        {"recipe_id": recipe_id, "wafer_name": meta["wafer_name"],
         "lot": meta.get("lot"), "diameter_mm": meta.get("diameter_mm")},
    )
    die_id = _get_or_create(
        conn, "Die",
        {"wafer_id": wafer_id, "die_number": meta["die_number"]},
        {"wafer_id": wafer_id, "die_number": meta["die_number"], "die_type": meta["die_type"]},
    )
    subdie_id = _get_or_create(
        conn, "Subdie",
        {"die_id": die_id, "cross_sectional_area_um2": meta["cross_sectional_area_um2"]},
        {"die_id": die_id, "cross_sectional_area_um2": meta["cross_sectional_area_um2"]},
    )
    device_id = _get_or_create(
        conn, "Device",
        {"subdie_id": subdie_id, "device_name": meta["device_name"]},
        {"subdie_id": subdie_id, "device_name": meta["device_name"],
         "channel_width_um": meta.get("channel_width_um") or 1.0,
         "channel_length_um": meta.get("channel_length_um") or 1.0,
         "pos_x": meta.get("pos_x"), "pos_y": meta.get("pos_y")},
    )
    return device_id


def insert_experiment(conn, device_id: int, plan: dict, user_name: Optional[str]) -> int:
    fc = conn.execute(
        'INSERT INTO Function_Config (function_type, notes) VALUES (?, ?)',
        (plan["function_type"], plan["experiment_name"]),
    )
    fc_id = int(fc.lastrowid)

    exp = conn.execute(
        'INSERT INTO Experiment (device_id, function_config_id, experiment_name, user_name) '
        'VALUES (?, ?, ?, ?)',
        (device_id, fc_id, plan["experiment_name"], user_name),
    )
    exp_id = int(exp.lastrowid)

    params = dict(plan["function_params"])
    params["function_config_id"] = fc_id
    table = "Function_TFT_Transfer" if plan["function_type"] == "TFT_Transfer" else "Function_TFT_Output"
    cols = ", ".join(f'"{k}"' for k in params)
    qs = ", ".join("?" for _ in params)
    conn.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({qs})', tuple(params.values()))

    detail_rows = []
    for p in plan["points"]:
        v_ds = p.get("v_ds_V")
        i_ds = p.get("i_ds_A")
        resistance = (v_ds / i_ds) if (v_ds is not None and i_ds not in (None, 0)) else None
        detail_rows.append((
            exp_id, None, p.get("v_gs_V"), v_ds, i_ds, p.get("i_gs_A"),
            resistance, "S", None, None,
        ))
    conn.executemany(
        'INSERT INTO Experimental_Detail '
        '(experiment_id, step_time_s, v_gs_V, v_ds_V, i_ds_A, i_gs_A, resistance_ohm, tag, readtag, read_voltage_V) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        detail_rows,
    )
    return exp_id


# ===========================================================================
# Filename metadata helpers
# ===========================================================================
def meta_from_filename(path: str, base_meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(base_meta)
    name = os.path.basename(path)
    m = re.search(r"[Ll](\d+(?:\.\d+)?)[Ww](\d+(?:\.\d+)?)", name)
    if m:
        if meta.get("channel_length_um") is None:
            meta["channel_length_um"] = float(m.group(1))
        if meta.get("channel_width_um") is None:
            meta["channel_width_um"] = float(m.group(2))
    return meta


def default_db_path() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(os.path.abspath(os.path.join(here, "..")), "TFT_Database.db")


# ===========================================================================
# Main
# ===========================================================================
def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Import Clarius TFT .xls/.xlsx into TFT_Database.db")
    ap.add_argument("files", nargs="+", help="Clarius .xls/.xlsx files (Id-Vg and/or Id-Vd)")
    ap.add_argument("--db", default=default_db_path(), help="target TFT_Database.db")
    ap.add_argument("--meta", help="JSON file overriding the METADATA dict")
    ap.add_argument("--dry-run", action="store_true", help="parse and report only")
    args = ap.parse_args(argv)

    base_meta = dict(META)
    if args.meta:
        with open(args.meta, "r", encoding="utf-8") as fh:
            base_meta.update(json.load(fh))

    if not os.path.exists(args.db) and not args.dry_run:
        raise SystemExit(
            f"Database not found: {args.db}\n"
            f"Create it first:  python data_import/create_tft_database.py"
        )

    conn = None if args.dry_run else sqlite3.connect(args.db)
    if conn is not None:
        conn.execute("PRAGMA foreign_keys=ON;")

    total_exp = 0
    try:
        for path in args.files:
            sheets = load_sheets(path)
            blocks = parse_blocks(sheets)
            label = os.path.splitext(os.path.basename(path))[0].split("-")[0] or os.path.basename(path)
            plans = build_experiments(blocks, label)
            meta = meta_from_filename(path, base_meta)

            print(f"\n{os.path.basename(path)}")
            print(f"  device: {meta['device_name']} "
                  f"(W={meta.get('channel_width_um')} um, L={meta.get('channel_length_um')} um)")
            for plan in plans:
                npts = len(plan["points"])
                print(f"  - {plan['function_type']:13s} {npts:4d} pts  {plan['experiment_name']}")

            if conn is not None:
                device_id = resolve_device(conn, meta)
                for plan in plans:
                    insert_experiment(conn, device_id, plan, meta.get("user_name"))
                    total_exp += 1

        if conn is not None:
            conn.commit()
            print(f"\n[OK] imported {total_exp} experiment(s) into {args.db}")
        else:
            print("\n[DRY-RUN] nothing written")
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
