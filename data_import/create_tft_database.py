"""Create an empty TFT_Database.db with the schema expected by GUI_raw_data.

This builds the schema the GUI actually *reads* (see GUI_raw_data/sql/db_ops.py):

    Recipe -> Wafer -> Die -> Subdie -> Device -> Experiment -> Experimental_Detail
                                            |
                                            +-- Function_Config (TFT_Transfer / TFT_Output)
                                                   |-- Function_TFT_Transfer
                                                   +-- Function_TFT_Output

Key difference from the older recipe_db dump:
- Experiment links to a Function_Config row via Experiment.function_config_id
  (the GUI's validate_database_path() requires this column + the Function_Config table).
- Function_TFT_Transfer / Function_TFT_Output link by function_config_id
  (build_function_row_cache() in db_ops.py keys on function_config_id).

Usage:
    python data_import/create_tft_database.py                 # writes <project_root>/TFT_Database.db
    python data_import/create_tft_database.py path/to/out.db  # custom path
    python data_import/create_tft_database.py --force         # overwrite if it exists
"""

from __future__ import annotations

import os
import sqlite3
import sys

SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Fabrication hierarchy
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Recipe (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_name TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS Wafer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   INTEGER NOT NULL REFERENCES Recipe(id) ON DELETE RESTRICT,
    wafer_name  TEXT NOT NULL,
    lot         TEXT,
    diameter_mm INTEGER,
    UNIQUE(recipe_id, wafer_name)
);

CREATE TABLE IF NOT EXISTS Die (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    wafer_id   INTEGER NOT NULL REFERENCES Wafer(id) ON DELETE CASCADE,
    die_number INTEGER NOT NULL,
    die_type   TEXT NOT NULL,
    UNIQUE(wafer_id, die_number)
);

CREATE TABLE IF NOT EXISTS Subdie (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    die_id                   INTEGER NOT NULL REFERENCES Die(id) ON DELETE CASCADE,
    cross_sectional_area_um2 INTEGER NOT NULL,
    UNIQUE(die_id, cross_sectional_area_um2)
);

CREATE TABLE IF NOT EXISTS Device (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    subdie_id         INTEGER NOT NULL REFERENCES Subdie(id) ON DELETE CASCADE,
    device_name       TEXT,
    channel_width_um  REAL NOT NULL DEFAULT 1.0,
    channel_length_um REAL NOT NULL DEFAULT 1.0,
    pos_x             REAL,
    pos_y             REAL,
    UNIQUE(subdie_id, device_name)
);

-- ---------------------------------------------------------------------------
-- Measurement-function configuration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Function_Config (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    function_type TEXT NOT NULL CHECK (function_type IN ('TFT_Transfer', 'TFT_Output')),
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS Experiment (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id          INTEGER NOT NULL REFERENCES Device(id) ON DELETE RESTRICT,
    function_config_id INTEGER NOT NULL REFERENCES Function_Config(id) ON DELETE RESTRICT,
    experiment_name    TEXT NOT NULL,
    user_name          TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes              TEXT
);

CREATE TABLE IF NOT EXISTS Experimental_Detail (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id  INTEGER NOT NULL REFERENCES Experiment(id) ON DELETE CASCADE,
    step_time_s    REAL,
    v_gs_V         REAL,   -- Gate-Source voltage
    v_ds_V         REAL,   -- Drain-Source voltage
    i_ds_A         REAL,   -- Drain current
    i_gs_A         REAL,   -- Gate leakage current
    resistance_ohm REAL,
    tag            TEXT NOT NULL DEFAULT 'S',
    readtag        TEXT,
    read_voltage_V REAL
);

-- ---------------------------------------------------------------------------
-- Per-function sweep parameters (linked by function_config_id)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Function_TFT_Transfer (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    function_config_id   INTEGER NOT NULL REFERENCES Function_Config(id) ON DELETE CASCADE,
    drain_voltage_V      REAL NOT NULL,
    gate_start_V         REAL NOT NULL,
    gate_stop_V          REAL NOT NULL,
    gate_step_V          REAL NOT NULL,
    cycles               INTEGER DEFAULT 1,
    current_compliance_A REAL,
    UNIQUE (function_config_id)
);

CREATE TABLE IF NOT EXISTS Function_TFT_Output (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    function_config_id   INTEGER NOT NULL REFERENCES Function_Config(id) ON DELETE CASCADE,
    gate_voltages_V      TEXT NOT NULL,   -- JSON list of constant Vgs values
    drain_start_V        REAL NOT NULL,
    drain_stop_V         REAL NOT NULL,
    drain_step_V         REAL NOT NULL,
    cycles               INTEGER DEFAULT 1,
    current_compliance_A REAL,
    UNIQUE (function_config_id)
);

-- ---------------------------------------------------------------------------
-- Indices used by the GUI's per-experiment point fetch
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_detail_experiment ON Experimental_Detail(experiment_id);
CREATE INDEX IF NOT EXISTS idx_experiment_device ON Experiment(device_id);
CREATE INDEX IF NOT EXISTS idx_experiment_fc      ON Experiment(function_config_id);
"""


def default_db_path() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.abspath(os.path.join(here, ".."))
    return os.path.join(project_root, "TFT_Database.db")


def create_database(db_path: str, force: bool = False) -> None:
    if os.path.exists(db_path):
        if not force:
            raise FileExistsError(
                f"{db_path} already exists. Pass --force to overwrite."
            )
        os.remove(db_path)

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    force = "--force" in argv
    positional = [a for a in argv if not a.startswith("--")]
    db_path = positional[0] if positional else default_db_path()

    create_database(db_path, force=force)
    print(f"[OK] empty TFT database created at: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
