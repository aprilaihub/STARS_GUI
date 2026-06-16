from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..logic.enums import LayerType, ToolType
from ..logic.models import ProcessStep, RecipeSummary
from ..logic.params import specs_for
from ..logic.repositories import RecipeRepository, WorkingProcessRepository

_TOOL_TABLE_MAP: dict[ToolType, str] = {
    ToolType.ALD: "Tool_ALD",
    ToolType.SPUTTER: "Tool_Sputter",
    ToolType.E_BEAM: "Tool_E_beam",
    ToolType.FURNACE: "Tool_Furnace",
}

_LAYER_ORDER_SQL = """
CASE layer_type
    WHEN 'Substrate' THEN 0
    WHEN 'Source_Drain_Adhesion' THEN 1
    WHEN 'Source_Drain_Electrode' THEN 2
    WHEN 'Channel' THEN 3
    WHEN 'Gate_Dielectric' THEN 4
    WHEN 'Gate_Adhesion' THEN 5
    WHEN 'Gate_Electrode' THEN 6
    ELSE 99
END
"""

_LAYER_ORDER_TOP_DOWN = {
    "Substrate": 0,
    "Source_Drain_Adhesion": 1,
    "Source_Drain_Electrode": 2,
    "Channel": 3,
    "Gate_Dielectric": 4,
    "Gate_Adhesion": 5,
    "Gate_Electrode": 6,
}
_RECIPE_TABLE = "Recipe"
_LEGACY_RECIPE_TABLE = "Recipe_Info"
_LAYER_TABLE = "Layer"
_LEGACY_LAYER_TABLE = "Material_Process_Size"
_REL_TABLE = "Tool_ALD_Material_Gas_Cycle_Relation"
_PREVIOUS_REL_TABLE = "Tool_ALD_Material_Cycle_Relation"
_OLDER_REL_TABLE = "Material_Cycle_Relation"
_LEGACY_REL_TABLE = "Material_Loop_Relation"
_CYCLE_TABLE = "Tool_ALD_Cycle"
_PREVIOUS_CYCLE_TABLE = "Cycle_Table"
_LEGACY_CYCLE_TABLE = "Loop_Table"
_ALD_MATERIAL_TABLE = "Tool_ALD_Material"
_ALD_GAS_TABLE = "Tool_ALD_Gas"
_LEGACY_ALD_MATERIAL_TABLE = "Material_Table"
_NODE_REF_COL = "MGCR_id"
_PREVIOUS_NODE_REF_COL = "MCR_id"
_LEGACY_NODE_REF_COL = "MLR_id"
_ORDER_COL = "order"
_ORDER_SQL = '"order"'
_LAYER_FK_COL = "layer_id"
_ATTACHMENT_TABLE = "Tool_Attachment"
_PREVIOUS_ATTACHMENT_TABLE = "Attachment"

_TOOL_COLUMN_DEFS: dict[ToolType, tuple[str, ...]] = {
    ToolType.ALD: (
        "instrument_name TEXT",
        "desired_material TEXT",
        "precursor_name TEXT",
        "precursor_pod_temperature_degC REAL",
        "dep_method TEXT",
        "reactant_name TEXT",
        "table_temperature_degC REAL",
    ),
    ToolType.SPUTTER: (
        "instrument_name TEXT",
        "desired_material TEXT",
        "target_material TEXT",
        "gas_used TEXT",
        "gas_flow_rate_sccm REAL",
        "plasma_strike_gas_used TEXT",
        "plasma_strike_gas_flow_rate_sccm REAL",
        "deposition_voltage_V REAL",
        "gun_type TEXT",
        "voltage_frequency_kHz REAL",
        "chamber_pressure_mTorr REAL",
        "power_density_W_per_cm2 REAL",
    ),
    ToolType.E_BEAM: (
        "instrument_name TEXT",
        "desired_material TEXT",
        "chamber_pressure_mTorr REAL",
        "power_W REAL",
        "deposition_rate_nm_per_s REAL",
    ),
    ToolType.FURNACE: (
        "instrument_name TEXT",
        "ramping_rate_degC_per_s REAL",
        "annealing_temperature_degC REAL",
        "annealing_time_s REAL",
        "annealing_gas TEXT",
        "idle_temperature_degC REAL",
    ),
}

_WORKING_LAYER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS Layer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_type TEXT NOT NULL,
    position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
    tools TEXT NOT NULL,
    thickness_nm REAL,
    CHECK (layer_type IN ('Substrate', 'Source_Drain_Adhesion', 'Source_Drain_Electrode', 'Channel', 'Gate_Dielectric', 'Gate_Adhesion', 'Gate_Electrode')),
    UNIQUE (layer_type, position_in_layer)
)
"""

_RECIPE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS Recipe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
)
"""

_RECIPE_LAYER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS Layer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    layer_type TEXT NOT NULL,
    position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
    tools TEXT NOT NULL,
    thickness_nm REAL,
    CHECK (layer_type IN ('Substrate', 'Source_Drain_Adhesion', 'Source_Drain_Electrode', 'Channel', 'Gate_Dielectric', 'Gate_Adhesion', 'Gate_Electrode')),
    UNIQUE (recipe_id, layer_type, position_in_layer),
    FOREIGN KEY (recipe_id) REFERENCES Recipe(id) ON DELETE CASCADE
)
"""

_ATTACHMENT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS Tool_Attachment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    raw BLOB NOT NULL,
    file_size INTEGER NOT NULL CHECK(file_size >= 0),
    content_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

_REL_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Tool_ALD_Material_Gas_Cycle_Relation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK(type IN ('cycle','material','gas')),
    parent_id INTEGER,
    "order" INTEGER NOT NULL DEFAULT 0,
    ALD_id INTEGER NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE,
    FOREIGN KEY (ALD_id) REFERENCES Tool_ALD(id) ON DELETE CASCADE
)
"""

_CYCLE_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Tool_ALD_Cycle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    MGCR_id INTEGER NOT NULL UNIQUE,
    cycle_number INTEGER NOT NULL CHECK(cycle_number >= 1),
    FOREIGN KEY (MGCR_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE
)
"""

_MATERIAL_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Tool_ALD_Material (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    MGCR_id INTEGER NOT NULL UNIQUE,
    desired_material TEXT,
    precursor_name TEXT,
    dep_rate_value REAL,
    dep_rate_unit TEXT DEFAULT 'nm/cycle',
    dep_time_s REAL,
    FOREIGN KEY (MGCR_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE
)
"""

_GAS_TABLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS Tool_ALD_Gas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    MGCR_id INTEGER NOT NULL UNIQUE,
    gas_type TEXT,
    flow_value REAL,
    flow_unit TEXT NOT NULL DEFAULT 'sccm' CHECK(flow_unit IN ('sccm','slm')),
    FOREIGN KEY (MGCR_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE
)
"""

_WORKING_CANDIDATE_TABLES: dict[str, str] = {
    "Available_Gases_ALD": """
        CREATE TABLE IF NOT EXISTS Available_Gases_ALD (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gas_name TEXT UNIQUE
        )
    """,
    "Available_Gases_Sputter": """
        CREATE TABLE IF NOT EXISTS Available_Gases_Sputter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gas_name TEXT UNIQUE
        )
    """,
    "Available_Materials_ALD": """
        CREATE TABLE IF NOT EXISTS Available_Materials_ALD (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material TEXT UNIQUE
        )
    """,
    "Available_Materials_E_beam": """
        CREATE TABLE IF NOT EXISTS Available_Materials_E_beam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material TEXT UNIQUE
        )
    """,
    "Available_Materials_Furnace": """
        CREATE TABLE IF NOT EXISTS Available_Materials_Furnace (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material TEXT UNIQUE
        )
    """,
    "Available_Materials_Sputter": """
        CREATE TABLE IF NOT EXISTS Available_Materials_Sputter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            desired_material TEXT UNIQUE,
            target_material TEXT UNIQUE
        )
    """,
    "Available_Precursors_ALD": """
        CREATE TABLE IF NOT EXISTS Available_Precursors_ALD (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            precursor_name TEXT UNIQUE
        )
    """,
}

_SCHEMA_TOOL_TABLE_SQL: dict[str, str] = {
    "Tool_ALD": """
        CREATE TABLE IF NOT EXISTS Tool_ALD (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            layer_id INTEGER UNIQUE,
            attachment_id INTEGER,
            instrument_name TEXT,
            desired_material TEXT,
            precursor_name TEXT,
            precursor_pod_temperature_degC REAL,
            dep_method TEXT,
            reactant_name TEXT,
            table_temperature_degC REAL,
            FOREIGN KEY (layer_id) REFERENCES Layer(id) ON DELETE CASCADE,
            FOREIGN KEY (attachment_id) REFERENCES Tool_Attachment(id) ON DELETE SET NULL
        )
    """,
    "Tool_Sputter": """
        CREATE TABLE IF NOT EXISTS Tool_Sputter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            layer_id INTEGER UNIQUE,
            attachment_id INTEGER,
            instrument_name TEXT,
            desired_material TEXT,
            target_material TEXT,
            gas_used TEXT,
            gas_flow_rate_sccm REAL,
            plasma_strike_gas_used TEXT,
            plasma_strike_gas_flow_rate_sccm REAL,
            deposition_voltage_V REAL,
            gun_type TEXT,
            voltage_frequency_kHz REAL,
            chamber_pressure_mTorr REAL,
            power_density_W_per_cm2 REAL,
            FOREIGN KEY (layer_id) REFERENCES Layer(id) ON DELETE CASCADE,
            FOREIGN KEY (attachment_id) REFERENCES Tool_Attachment(id) ON DELETE SET NULL
        )
    """,
    "Tool_E_beam": """
        CREATE TABLE IF NOT EXISTS Tool_E_beam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            layer_id INTEGER UNIQUE,
            attachment_id INTEGER,
            instrument_name TEXT,
            desired_material TEXT,
            chamber_pressure_mTorr REAL,
            power_W REAL,
            deposition_rate_nm_per_s REAL,
            FOREIGN KEY (layer_id) REFERENCES Layer(id) ON DELETE CASCADE,
            FOREIGN KEY (attachment_id) REFERENCES Tool_Attachment(id) ON DELETE SET NULL
        )
    """,
    "Tool_Furnace": """
        CREATE TABLE IF NOT EXISTS Tool_Furnace (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            layer_id INTEGER UNIQUE,
            attachment_id INTEGER,
            instrument_name TEXT,
            ramping_rate_degC_per_s REAL,
            annealing_temperature_degC REAL,
            annealing_time_s REAL,
            annealing_gas TEXT,
            idle_temperature_degC REAL,
            FOREIGN KEY (layer_id) REFERENCES Layer(id) ON DELETE CASCADE,
            FOREIGN KEY (attachment_id) REFERENCES Tool_Attachment(id) ON DELETE SET NULL
        )
    """,
}

_SCHEMA_EXPECTED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "Tool_ALD": (
        ("layer_id", "INTEGER"),
        ("attachment_id", "INTEGER"),
        ("instrument_name", "TEXT"),
        ("desired_material", "TEXT"),
        ("precursor_name", "TEXT"),
        ("precursor_pod_temperature_degC", "REAL"),
        ("dep_method", "TEXT"),
        ("reactant_name", "TEXT"),
        ("table_temperature_degC", "REAL"),
    ),
    "Tool_Sputter": (
        ("layer_id", "INTEGER"),
        ("attachment_id", "INTEGER"),
        ("instrument_name", "TEXT"),
        ("desired_material", "TEXT"),
        ("target_material", "TEXT"),
        ("gas_used", "TEXT"),
        ("gas_flow_rate_sccm", "REAL"),
        ("plasma_strike_gas_used", "TEXT"),
        ("plasma_strike_gas_flow_rate_sccm", "REAL"),
        ("deposition_voltage_V", "REAL"),
        ("gun_type", "TEXT"),
        ("voltage_frequency_kHz", "REAL"),
        ("chamber_pressure_mTorr", "REAL"),
        ("power_density_W_per_cm2", "REAL"),
    ),
    "Tool_E_beam": (
        ("layer_id", "INTEGER"),
        ("attachment_id", "INTEGER"),
        ("instrument_name", "TEXT"),
        ("desired_material", "TEXT"),
        ("chamber_pressure_mTorr", "REAL"),
        ("power_W", "REAL"),
        ("deposition_rate_nm_per_s", "REAL"),
    ),
    "Tool_Furnace": (
        ("layer_id", "INTEGER"),
        ("attachment_id", "INTEGER"),
        ("instrument_name", "TEXT"),
        ("ramping_rate_degC_per_s", "REAL"),
        ("annealing_temperature_degC", "REAL"),
        ("annealing_time_s", "REAL"),
        ("annealing_gas", "TEXT"),
        ("idle_temperature_degC", "REAL"),
    ),
    "Tool_Attachment": (
        ("file_name", "TEXT"),
        ("raw", "BLOB"),
        ("file_size", "INTEGER"),
        ("content_hash", "TEXT"),
        ("created_at", "TIMESTAMP"),
    ),
    "Tool_ALD_Material_Gas_Cycle_Relation": (
        ("type", "TEXT"),
        ("parent_id", "INTEGER"),
        ("order", "INTEGER"),
        ("ALD_id", "INTEGER"),
    ),
    "Tool_ALD_Cycle": (
        ("MGCR_id", "INTEGER"),
        ("cycle_number", "INTEGER"),
    ),
    "Tool_ALD_Material": (
        ("MGCR_id", "INTEGER"),
        ("desired_material", "TEXT"),
        ("precursor_name", "TEXT"),
        ("dep_rate_value", "REAL"),
        ("dep_rate_unit", "TEXT"),
        ("dep_time_s", "REAL"),
    ),
    "Tool_ALD_Gas": (
        ("MGCR_id", "INTEGER"),
        ("gas_type", "TEXT"),
        ("flow_value", "REAL"),
        ("flow_unit", "TEXT"),
    ),
    "Layer": (
        ("layer_type", "TEXT"),
        ("position_in_layer", "INTEGER"),
        ("tools", "TEXT"),
        ("thickness_nm", "REAL"),
    ),
    "RecipeLayer": (
        ("recipe_id", "INTEGER"),
        ("layer_type", "TEXT"),
        ("position_in_layer", "INTEGER"),
        ("tools", "TEXT"),
        ("thickness_nm", "REAL"),
    ),
    "Recipe": (
        ("recipe_name", "TEXT"),
        ("created_at", "TIMESTAMP"),
        ("notes", "TEXT"),
    ),
}


def _none_if_blank(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _float_or_none(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(r[1]) for r in rows]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _normalize_mgcr_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in {"loop", "cycle"}:
        return "cycle"
    if text == "gas":
        return "gas"
    return "material"


def _coerce_tool_type(tool_type: ToolType | str) -> ToolType:
    if isinstance(tool_type, ToolType):
        return tool_type
    return ToolType.from_storage(str(tool_type))


def _tool_param_columns(tool_type: ToolType) -> list[str]:
    return [spec.key for spec in specs_for(tool_type)]


def _add_missing_columns(
    conn: sqlite3.Connection,
    table_name: str,
    expected_columns: Iterable[tuple[str, str]],
) -> None:
    existing = set(_table_columns(conn, table_name))
    for column_name, column_type in expected_columns:
        if column_name in existing:
            continue
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _ensure_layer_position_column(conn: sqlite3.Connection, *, recipe_side: bool) -> None:
    columns = set(_table_columns(conn, _LAYER_TABLE))
    if "position_in_layer" not in columns:
        conn.execute(f"ALTER TABLE {_LAYER_TABLE} ADD COLUMN position_in_layer INTEGER")

    if recipe_side and "recipe_id" not in columns:
        conn.execute(f"ALTER TABLE {_LAYER_TABLE} ADD COLUMN recipe_id INTEGER")

    rows = conn.execute(
        f"""
        SELECT id
        FROM {_LAYER_TABLE}
        WHERE position_in_layer IS NULL OR position_in_layer < 1
        ORDER BY id ASC
        """
    ).fetchall()
    if not rows:
        return

    current_columns = set(_table_columns(conn, _LAYER_TABLE))
    if recipe_side and "recipe_id" in current_columns:
        ordering = conn.execute(
            f"""
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY recipe_id, layer_type
                       ORDER BY id ASC
                   ) AS seq
            FROM {_LAYER_TABLE}
            WHERE position_in_layer IS NULL OR position_in_layer < 1
            """
        ).fetchall()
    else:
        ordering = conn.execute(
            f"""
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY layer_type
                       ORDER BY id ASC
                   ) AS seq
            FROM {_LAYER_TABLE}
            WHERE position_in_layer IS NULL OR position_in_layer < 1
            """
        ).fetchall()

    for row_id, seq in ordering:
        conn.execute(
            f"UPDATE {_LAYER_TABLE} SET position_in_layer = ? WHERE id = ?",
            (int(seq), int(row_id)),
        )


def _ensure_tool_table_columns(conn: sqlite3.Connection, table_name: str) -> None:
    legacy_columns = set(_table_columns(conn, table_name))
    had_legacy_tools_id = "tools_id" in legacy_columns and _LAYER_FK_COL not in legacy_columns
    _add_missing_columns(conn, table_name, _SCHEMA_EXPECTED_COLUMNS[table_name])
    columns = set(_table_columns(conn, table_name))
    if had_legacy_tools_id and _LAYER_FK_COL in columns:
        conn.execute(f"UPDATE {table_name} SET {_LAYER_FK_COL} = tools_id WHERE {_LAYER_FK_COL} IS NULL")
    if "attachment_id" not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN attachment_id INTEGER")


def _ensure_tool_tables(conn: sqlite3.Connection) -> None:
    for table_name, create_sql in _SCHEMA_TOOL_TABLE_SQL.items():
        conn.execute(create_sql)
        _ensure_tool_table_columns(conn, table_name)

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_attachment_hash_size "
        f"ON {_ATTACHMENT_TABLE}(content_hash, file_size)"
    )

    for table_name in _SCHEMA_TOOL_TABLE_SQL:
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name.lower()}_layer_id "
            f"ON {table_name}({_LAYER_FK_COL})"
        )


def _ensure_ald_tree_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_REL_TABLE_SCHEMA_SQL)
    conn.execute(_CYCLE_TABLE_SCHEMA_SQL)
    conn.execute(_MATERIAL_TABLE_SCHEMA_SQL)
    conn.execute(_GAS_TABLE_SCHEMA_SQL)
    _add_missing_columns(conn, _REL_TABLE, _SCHEMA_EXPECTED_COLUMNS[_REL_TABLE])
    _add_missing_columns(conn, _CYCLE_TABLE, _SCHEMA_EXPECTED_COLUMNS[_CYCLE_TABLE])
    _add_missing_columns(conn, _ALD_MATERIAL_TABLE, _SCHEMA_EXPECTED_COLUMNS[_ALD_MATERIAL_TABLE])
    _add_missing_columns(conn, _ALD_GAS_TABLE, _SCHEMA_EXPECTED_COLUMNS[_ALD_GAS_TABLE])
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_ald_rel_parent_order "
        f"ON {_REL_TABLE}(ALD_id, parent_id, {_ORDER_SQL})"
    )


def _ensure_working_candidates(conn: sqlite3.Connection) -> None:
    for create_sql in _WORKING_CANDIDATE_TABLES.values():
        conn.execute(create_sql)


def ensure_attachment_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_ATTACHMENT_TABLE_SQL)
    _add_missing_columns(conn, _ATTACHMENT_TABLE, _SCHEMA_EXPECTED_COLUMNS[_ATTACHMENT_TABLE])
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_attachment_hash_size "
        f"ON {_ATTACHMENT_TABLE}(content_hash, file_size)"
    )
    conn.commit()


def ensure_working_db_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(_WORKING_LAYER_TABLE_SQL)
    _add_missing_columns(conn, _LAYER_TABLE, _SCHEMA_EXPECTED_COLUMNS[_LAYER_TABLE])
    _ensure_layer_position_column(conn, recipe_side=False)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_working_layer_position "
        f"ON {_LAYER_TABLE}(layer_type, position_in_layer)"
    )
    ensure_attachment_schema(conn)
    _ensure_tool_tables(conn)
    _ensure_ald_tree_tables(conn)
    _ensure_working_candidates(conn)
    conn.commit()


def ensure_recipe_db_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(_RECIPE_TABLE_SQL)
    _add_missing_columns(conn, _RECIPE_TABLE, _SCHEMA_EXPECTED_COLUMNS[_RECIPE_TABLE])
    conn.execute(_RECIPE_LAYER_TABLE_SQL)
    _add_missing_columns(conn, _LAYER_TABLE, _SCHEMA_EXPECTED_COLUMNS["RecipeLayer"])
    _ensure_layer_position_column(conn, recipe_side=True)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recipe_layer_position "
        f"ON {_LAYER_TABLE}(recipe_id, layer_type, position_in_layer)"
    )
    ensure_attachment_schema(conn)
    _ensure_tool_tables(conn)
    _ensure_ald_tree_tables(conn)
    conn.commit()


def prepare_runtime_databases(
    working_conn: sqlite3.Connection,
    recipe_conn: sqlite3.Connection,
) -> None:
    ensure_working_db_schema(working_conn)
    ensure_recipe_db_schema(recipe_conn)


def _ensure_tool_row_internal(conn: sqlite3.Connection, tool_type: ToolType, layer_id: int) -> int:
    table = _TOOL_TABLE_MAP[tool_type]
    row = conn.execute(
        f"SELECT id FROM {table} WHERE {_LAYER_FK_COL} = ?",
        (int(layer_id),),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cur = conn.cursor()
    cur.execute(f"INSERT INTO {table} ({_LAYER_FK_COL}) VALUES (?)", (int(layer_id),))
    return int(cur.lastrowid)


def _attachment_ref_count(conn: sqlite3.Connection, attachment_id: int) -> int:
    total = 0
    for table in _TOOL_TABLE_MAP.values():
        if not _table_exists(conn, table):
            continue
        cols = _table_columns(conn, table)
        if "attachment_id" not in cols:
            continue
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE attachment_id = ?",
            (int(attachment_id),),
        ).fetchone()
        total += int((row or [0])[0] or 0)
    return total


def _delete_attachment_if_orphan(conn: sqlite3.Connection, attachment_id: int | None) -> None:
    if attachment_id is None:
        return
    if _attachment_ref_count(conn, int(attachment_id)) == 0:
        conn.execute(f"DELETE FROM {_ATTACHMENT_TABLE} WHERE id = ?", (int(attachment_id),))


def _prune_orphan_attachments(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, _ATTACHMENT_TABLE):
        return
    referenced_ids: set[int] = set()
    for table in _TOOL_TABLE_MAP.values():
        if not _table_exists(conn, table):
            continue
        cols = _table_columns(conn, table)
        if "attachment_id" not in cols:
            continue
        for (attachment_id,) in conn.execute(
            f"SELECT DISTINCT attachment_id FROM {table} WHERE attachment_id IS NOT NULL"
        ).fetchall():
            if attachment_id is not None:
                referenced_ids.add(int(attachment_id))
    if referenced_ids:
        qmarks = ", ".join("?" for _ in referenced_ids)
        conn.execute(
            f"DELETE FROM {_ATTACHMENT_TABLE} WHERE id NOT IN ({qmarks})",
            tuple(sorted(referenced_ids)),
        )
    else:
        conn.execute(f"DELETE FROM {_ATTACHMENT_TABLE}")


def _ensure_attachment_row(
    conn: sqlite3.Connection,
    *,
    file_name: str,
    raw: bytes,
    file_size: int | None = None,
    content_hash: str | None = None,
) -> tuple[int, bool]:
    payload = bytes(raw)
    size = int(file_size if file_size is not None else len(payload))
    digest = str(content_hash or _sha256_hex(payload)).strip().lower()
    row = conn.execute(
        f"SELECT id FROM {_ATTACHMENT_TABLE} WHERE content_hash = ? AND file_size = ?",
        (digest, size),
    ).fetchone()
    if row is not None:
        return int(row[0]), True
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT INTO {_ATTACHMENT_TABLE} (file_name, raw, file_size, content_hash)
        VALUES (?, ?, ?, ?)
        """,
        (str(file_name), sqlite3.Binary(payload), size, digest),
    )
    return int(cur.lastrowid), False


class _ToolSqlMixin:
    @staticmethod
    def _tool_table(tool_type: ToolType) -> str:
        return _TOOL_TABLE_MAP[tool_type]

    @staticmethod
    def _tool_columns(tool_type: ToolType) -> list[str]:
        return _tool_param_columns(tool_type)

    def _fetch_tool_params(self, conn: sqlite3.Connection, tool_type: ToolType, layer_id: int) -> dict[str, Any]:
        cols = self._tool_columns(tool_type)
        if not cols:
            return {}
        table = self._tool_table(tool_type)
        sql = f"SELECT {', '.join(cols)} FROM {table} WHERE {_LAYER_FK_COL} = ?"
        row = conn.execute(sql, (layer_id,)).fetchone()
        if row is None:
            return {c: "" for c in cols}
        return {
            col: ("" if row[idx] is None else str(row[idx]))
            for idx, col in enumerate(cols)
        }

    def _upsert_tool_params(
        self,
        conn: sqlite3.Connection,
        tool_type: ToolType,
        layer_id: int,
        params: dict[str, Any],
    ) -> None:
        cols = self._tool_columns(tool_type)
        if not cols:
            return
        table = self._tool_table(tool_type)
        values = [_none_if_blank(params.get(c)) for c in cols]

        exists = conn.execute(
            f"SELECT id FROM {table} WHERE {_LAYER_FK_COL} = ?",
            (layer_id,),
        ).fetchone()
        if exists:
            set_sql = ", ".join(f"{c} = ?" for c in cols)
            conn.execute(
                f"UPDATE {table} SET {set_sql} WHERE {_LAYER_FK_COL} = ?",
                (*values, layer_id),
            )
        else:
            all_cols = [_LAYER_FK_COL, *cols]
            placeholders = ", ".join("?" for _ in all_cols)
            conn.execute(
                f"INSERT INTO {table} ({', '.join(all_cols)}) VALUES ({placeholders})",
                (layer_id, *values),
            )


class SQLiteWorkingProcessRepository(WorkingProcessRepository, _ToolSqlMixin):
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def ensure_schema(self) -> None:
        ensure_working_db_schema(self.conn)

    def _layer_max_position(self, layer: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(position_in_layer), 0) FROM Layer WHERE layer_type = ?",
            (layer,),
        ).fetchone()
        return int((row or [0])[0] or 0)

    @staticmethod
    def _normalize_position(requested: int | None, max_pos: int, allow_append: bool = True) -> int:
        if requested is None:
            return max_pos + 1 if allow_append else max(1, max_pos)
        pos = int(requested)
        if pos < 1:
            return 1
        upper = max_pos + 1 if allow_append else max(1, max_pos)
        return min(pos, upper)

    def _shift_positions(self, layer: str, condition_sql: str, params: tuple[Any, ...], delta: int) -> None:
        if delta == 0:
            return
        order = "DESC" if delta > 0 else "ASC"
        rows = self.conn.execute(
            f"""
            SELECT id, position_in_layer
            FROM Layer
            WHERE layer_type = ? AND ({condition_sql})
            ORDER BY position_in_layer {order}, id {order}
            """,
            (layer, *params),
        ).fetchall()
        for row_id, pos in rows:
            self.conn.execute(
                "UPDATE Layer SET position_in_layer = ? WHERE id = ?",
                (int(pos) + int(delta), int(row_id)),
            )

    def list_steps(self) -> list[ProcessStep]:
        rows = self.conn.execute(
            f"""
            SELECT id, layer_type, position_in_layer, tools, thickness_nm
            FROM Layer
            ORDER BY {_LAYER_ORDER_SQL}, position_in_layer ASC, id ASC
            """
        ).fetchall()

        steps: list[ProcessStep] = []
        for step_id, layer_raw, pos_in_layer, tool_raw, thickness in rows:
            try:
                layer = LayerType(layer_raw)
                tool_type = ToolType.from_storage(tool_raw)
            except ValueError:
                continue

            params = self._fetch_tool_params(self.conn, tool_type, int(step_id))
            steps.append(
                ProcessStep(
                    step_id=int(step_id),
                    layer=layer,
                    tool_type=tool_type,
                    position_in_layer=int(pos_in_layer or 1),
                    thickness_nm=_float_or_none(thickness),
                    parameters=params,
                )
            )
        return steps

    def get_step(self, step_id: int) -> ProcessStep | None:
        row = self.conn.execute(
            "SELECT id, layer_type, position_in_layer, tools, thickness_nm FROM Layer WHERE id = ?",
            (step_id,),
        ).fetchone()
        if row is None:
            return None

        try:
            layer = LayerType(row[1])
            tool_type = ToolType.from_storage(row[3])
        except ValueError:
            return None

        params = self._fetch_tool_params(self.conn, tool_type, int(row[0]))
        return ProcessStep(
            step_id=int(row[0]),
            layer=layer,
            tool_type=tool_type,
            position_in_layer=int(row[2] or 1),
            thickness_nm=_float_or_none(row[4]),
            parameters=params,
        )

    def add_step(self, layer: LayerType, tool_type: ToolType, position_in_layer: int | None = None) -> ProcessStep:
        layer_name = layer.value
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            max_pos = self._layer_max_position(layer_name)
            new_pos = self._normalize_position(position_in_layer, max_pos, allow_append=True)
            if new_pos <= max_pos:
                self._shift_positions(layer_name, "position_in_layer >= ?", (new_pos,), +1)

            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO Layer (layer_type, position_in_layer, tools)
                VALUES (?, ?, ?)
                """,
                (layer_name, int(new_pos), tool_type.display_name),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        created = self.get_step(int(cur.lastrowid))
        if created is None:
            raise RuntimeError("Failed to create process step")
        return created

    def update_step(self, step: ProcessStep) -> None:
        if step.step_id is None:
            raise ValueError("step_id is required for update")
        row = self.conn.execute(
            "SELECT layer_type, position_in_layer FROM Layer WHERE id = ?",
            (int(step.step_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Step {step.step_id} does not exist")

        old_layer = str(row[0])
        old_pos = int(row[1])
        new_layer = step.layer.value

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if new_layer == old_layer:
                max_pos = self._layer_max_position(new_layer)
                new_pos = self._normalize_position(step.position_in_layer, max_pos, allow_append=False)
                if new_pos != old_pos:
                    temp_pos = max_pos + 1
                    self.conn.execute(
                        "UPDATE Layer SET position_in_layer = ? WHERE id = ?",
                        (int(temp_pos), int(step.step_id)),
                    )
                    if new_pos > old_pos:
                        self._shift_positions(
                            new_layer,
                            "position_in_layer > ? AND position_in_layer <= ?",
                            (old_pos, new_pos),
                            -1,
                        )
                    else:
                        self._shift_positions(
                            new_layer,
                            "position_in_layer >= ? AND position_in_layer < ?",
                            (new_pos, old_pos),
                            +1,
                        )
            else:
                max_old = self._layer_max_position(old_layer)
                temp_pos = max_old + 1
                self.conn.execute(
                    "UPDATE Layer SET position_in_layer = ? WHERE id = ?",
                    (int(temp_pos), int(step.step_id)),
                )
                self._shift_positions(
                    old_layer,
                    "position_in_layer > ? AND position_in_layer < ?",
                    (old_pos, temp_pos),
                    -1,
                )

                max_new = self._layer_max_position(new_layer)
                new_pos = self._normalize_position(step.position_in_layer, max_new, allow_append=True)
                if new_pos <= max_new:
                    self._shift_positions(
                        new_layer,
                        "position_in_layer >= ?",
                        (new_pos,),
                        +1,
                    )

            step.position_in_layer = int(new_pos)
            self.conn.execute(
                """
                UPDATE Layer
                SET layer_type = ?, position_in_layer = ?, tools = ?, thickness_nm = ?
                WHERE id = ?
                """,
                (
                    new_layer,
                    int(step.position_in_layer),
                    step.tool_type.display_name,
                    _none_if_blank(step.thickness_nm),
                    int(step.step_id),
                ),
            )
            self._upsert_tool_params(self.conn, step.tool_type, int(step.step_id), step.parameters)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def delete_step(self, step_id: int, tool_type: ToolType) -> None:
        row = self.conn.execute(
            "SELECT layer_type, position_in_layer FROM Layer WHERE id = ?",
            (int(step_id),),
        ).fetchone()
        if row is None:
            return
        layer = str(row[0])
        pos = int(row[1])

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            table = self._tool_table(tool_type)
            attachment_id = None
            if "attachment_id" in _table_columns(self.conn, table):
                att_row = self.conn.execute(
                    f"SELECT attachment_id FROM {table} WHERE {_LAYER_FK_COL} = ?",
                    (int(step_id),),
                ).fetchone()
                attachment_id = None if att_row is None else att_row[0]
            self.conn.execute(f"DELETE FROM {table} WHERE {_LAYER_FK_COL} = ?", (step_id,))
            _delete_attachment_if_orphan(self.conn, None if attachment_id is None else int(attachment_id))
            self.conn.execute("DELETE FROM Layer WHERE id = ?", (step_id,))
            self._shift_positions(layer, "position_in_layer > ?", (pos,), -1)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def clear_all_steps(self) -> None:
        for table in ["Tool_ALD", "Tool_Sputter", "Tool_E_beam", "Tool_Furnace"]:
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM Layer")
        if _table_exists(self.conn, _ATTACHMENT_TABLE):
            self.conn.execute(f"DELETE FROM {_ATTACHMENT_TABLE}")
        self.conn.commit()

    def list_material_candidates(self, tool_type: ToolType, key: str) -> list[str]:
        mapping = self._candidate_table_and_col(tool_type, key)
        if mapping is None:
            return []
        table, column = mapping
        rows = self.conn.execute(f"SELECT {column} FROM {table}").fetchall()
        vals = [str(r[0]).strip() for r in rows if r and r[0] is not None and str(r[0]).strip()]
        return sorted(set(vals))

    def upsert_material_candidate(self, tool_type: ToolType, key: str, value: str) -> None:
        text = (value or "").strip()
        if not text:
            return
        mapping = self._candidate_table_and_col(tool_type, key)
        if mapping is None:
            return
        table, column = mapping
        self.conn.execute(
            f"INSERT OR IGNORE INTO {table} ({column}) VALUES (?)",
            (text,),
        )
        self.conn.commit()

    def delete_material_candidate(self, tool_type: ToolType, key: str, value: str) -> None:
        text = (value or "").strip()
        if not text:
            return
        mapping = self._candidate_table_and_col(tool_type, key)
        if mapping is None:
            return
        table, column = mapping
        self.conn.execute(
            f"DELETE FROM {table} WHERE {column} = ?",
            (text,),
        )
        self.conn.commit()

    @staticmethod
    def _candidate_table_and_col(tool_type: ToolType, key: str) -> tuple[str, str] | None:
        if tool_type == ToolType.ALD and key == "desired_material":
            return "Available_Materials_ALD", "material"
        if tool_type == ToolType.ALD and key == "precursor_name":
            return "Available_Precursors_ALD", "precursor_name"
        if tool_type == ToolType.SPUTTER and key in {"desired_material", "target_material"}:
            return "Available_Materials_Sputter", key
        if tool_type == ToolType.SPUTTER and key in {"gas_used", "plasma_strike_gas_used"}:
            return "Available_Gases_Sputter", "gas_name"
        if tool_type == ToolType.E_BEAM and key == "desired_material":
            return "Available_Materials_E_beam", "material"
        if tool_type == ToolType.FURNACE and key == "annealing_gas":
            return "Available_Materials_Furnace", "material"
        return None

    def close(self) -> None:
        self.conn.close()


class SQLiteRecipeRepository(RecipeRepository, _ToolSqlMixin):
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA foreign_keys = ON;")

    def ensure_schema(self) -> None:
        ensure_recipe_db_schema(self.conn)

    def create_recipe(self, recipe_name: str, steps: list[ProcessStep]) -> int:
        name = (recipe_name or "").strip()
        if not name:
            raise ValueError("Recipe name cannot be empty")

        cur = self.conn.cursor()
        cur.execute("INSERT INTO Recipe (recipe_name) VALUES (?)", (name,))
        recipe_id = int(cur.lastrowid)

        for step in steps:
            cur.execute(
                """
                INSERT INTO Layer (recipe_id, layer_type, position_in_layer, tools, thickness_nm)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recipe_id,
                    step.layer.value,
                    int(step.position_in_layer),
                    step.tool_type.display_name,
                    _none_if_blank(step.thickness_nm),
                ),
            )
            recipe_step_id = int(cur.lastrowid)
            self._upsert_tool_params(self.conn, step.tool_type, recipe_step_id, step.parameters)

        self.conn.commit()
        return recipe_id

    def replace_recipe_contents(
        self,
        recipe_id: int,
        steps: list[ProcessStep],
        *,
        commit: bool = True,
    ) -> None:
        rid = int(recipe_id)
        owns_tx = bool(commit)
        if owns_tx:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            exists = self.conn.execute(
                "SELECT 1 FROM Recipe WHERE id = ?",
                (rid,),
            ).fetchone()
            if exists is None:
                raise ValueError(f"Recipe {rid} does not exist")

            self.conn.execute(
                "DELETE FROM Layer WHERE recipe_id = ?",
                (rid,),
            )
            _prune_orphan_attachments(self.conn)

            cur = self.conn.cursor()
            for step in steps:
                cur.execute(
                    """
                    INSERT INTO Layer (recipe_id, layer_type, position_in_layer, tools, thickness_nm)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        rid,
                        step.layer.value,
                        int(step.position_in_layer),
                        step.tool_type.display_name,
                        _none_if_blank(step.thickness_nm),
                    ),
                )
                recipe_step_id = int(cur.lastrowid)
                self._upsert_tool_params(self.conn, step.tool_type, recipe_step_id, step.parameters)

            if owns_tx:
                self.conn.commit()
        except Exception:
            if owns_tx:
                self.conn.rollback()
            raise

    def list_recipes(self) -> list[RecipeSummary]:
        rows = self.conn.execute(
            "SELECT id, recipe_name, created_at FROM Recipe ORDER BY id DESC"
        ).fetchall()
        return [
            RecipeSummary(recipe_id=int(r[0]), recipe_name=str(r[1]), created_at=r[2])
            for r in rows
        ]

    def load_recipe_steps(self, recipe_id: int) -> list[ProcessStep]:
        rows = self.conn.execute(
            f"""
            SELECT id, layer_type, position_in_layer, tools, thickness_nm
            FROM Layer
            WHERE recipe_id = ?
            ORDER BY {_LAYER_ORDER_SQL}, position_in_layer ASC, id ASC
            """,
            (recipe_id,),
        ).fetchall()

        steps: list[ProcessStep] = []
        for step_id, layer_raw, pos_in_layer, tools_raw, thickness in rows:
            try:
                layer = LayerType(layer_raw)
                tool_type = ToolType.from_storage(tools_raw)
            except ValueError:
                continue
            params = self._fetch_tool_params(self.conn, tool_type, int(step_id))
            steps.append(
                ProcessStep(
                    step_id=int(step_id),
                    layer=layer,
                    tool_type=tool_type,
                    position_in_layer=int(pos_in_layer or 1),
                    thickness_nm=_float_or_none(thickness),
                    parameters=params,
                )
            )
        return steps

    def delete_recipe(self, recipe_id: int) -> None:
        rid = int(recipe_id)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = self.conn.execute("DELETE FROM Recipe WHERE id = ?", (rid,))
            if cur.rowcount == 0:
                self.conn.rollback()
                raise ValueError(f"Recipe {rid} does not exist")
            _prune_orphan_attachments(self.conn)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self) -> None:
        self.conn.close()


def table_exists(conn: sqlite3.Connection | None, table_name: str) -> bool:
    if conn is None:
        return False
    return _table_exists(conn, table_name)


def table_columns(conn: sqlite3.Connection | None, table_name: str) -> list[str]:
    if conn is None:
        return []
    if not _table_exists(conn, table_name):
        return []
    return _table_columns(conn, table_name)


def column_exists(conn: sqlite3.Connection | None, table_name: str, column_name: str) -> bool:
    return column_name in table_columns(conn, table_name)


def begin_immediate(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def ensure_tool_row(conn: sqlite3.Connection, tool_type: ToolType | str, layer_id: int) -> int:
    tool_enum = _coerce_tool_type(tool_type)
    row = conn.execute(
        f"SELECT id FROM {_TOOL_TABLE_MAP[tool_enum]} WHERE {_LAYER_FK_COL} = ?",
        (int(layer_id),),
    ).fetchone()
    if row is not None:
        return int(row[0])
    cur = conn.cursor()
    cur.execute(f"INSERT INTO {_TOOL_TABLE_MAP[tool_enum]} ({_LAYER_FK_COL}) VALUES (?)", (int(layer_id),))
    conn.commit()
    return int(cur.lastrowid)


def ensure_ald_row(conn: sqlite3.Connection, tools_layer_id: int) -> int:
    return ensure_tool_row(conn, ToolType.ALD, int(tools_layer_id))


def list_ald_material_values(conn: sqlite3.Connection | None, step_id: int) -> list[str]:
    if conn is None:
        return []
    if not (table_exists(conn, "Tool_ALD") and table_exists(conn, _ALD_MATERIAL_TABLE)):
        return []
    if not table_exists(conn, _REL_TABLE):
        return []

    ald_row = conn.execute(
        f"SELECT id FROM Tool_ALD WHERE {_LAYER_FK_COL} = ?",
        (int(step_id),),
    ).fetchone()
    if ald_row is None:
        return []
    ald_id = int(ald_row[0])

    rows = conn.execute(
        f"""
        SELECT m.desired_material
        FROM {_ALD_MATERIAL_TABLE} m
        JOIN {_REL_TABLE} r ON r.id = m.{_NODE_REF_COL}
        WHERE r.ALD_id = ?
          AND m.desired_material IS NOT NULL
          AND TRIM(m.desired_material) <> ''
        ORDER BY COALESCE(r.parent_id, -1), r.{_ORDER_SQL}, r.id
        """,
        (ald_id,),
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0] is not None]


def list_candidate_values(conn: sqlite3.Connection | None, tool_name: str, material_type: str) -> list[str]:
    if conn is None:
        return []
    mt = str(material_type or "").strip()
    tl = str(tool_name or "").strip()
    sql = ""
    if mt == "gas" and tl == "Sputter":
        sql = "SELECT gas_name FROM Available_Gases_Sputter"
    elif mt == "gas" and tl == "ALD":
        sql = "SELECT gas_name FROM Available_Gases_ALD"
    elif mt == "precursor_name" and tl == "ALD":
        sql = "SELECT precursor_name FROM Available_Precursors_ALD"
    elif tl == "Sputter":
        col = mt if mt in {"desired_material", "target_material"} else "desired_material"
        sql = f"SELECT {col} FROM Available_Materials_Sputter"
    elif tl == "ALD" and mt == "desired_material":
        sql = "SELECT material FROM Available_Materials_ALD"
    elif tl in {"E_beam", "Furnace"}:
        sql = f"SELECT material FROM Available_Materials_{tl}"
    if not sql:
        return []
    rows = conn.execute(sql).fetchall()
    values = [str(r[0]).strip() for r in rows if r and r[0] is not None and str(r[0]).strip()]
    return sorted(set(values))


def add_candidate_value(conn: sqlite3.Connection, tool_name: str, material_type: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    mt = str(material_type or "").strip()
    tl = str(tool_name or "").strip()
    if mt == "gas" and tl == "Sputter":
        conn.execute("INSERT OR IGNORE INTO Available_Gases_Sputter (gas_name) VALUES (?)", (text,))
    elif mt == "gas" and tl == "ALD":
        conn.execute("INSERT OR IGNORE INTO Available_Gases_ALD (gas_name) VALUES (?)", (text,))
    elif mt == "precursor_name" and tl == "ALD":
        conn.execute("INSERT OR IGNORE INTO Available_Precursors_ALD (precursor_name) VALUES (?)", (text,))
    elif tl == "Sputter":
        col = mt if mt in {"desired_material", "target_material"} else "desired_material"
        conn.execute(f"INSERT OR IGNORE INTO Available_Materials_Sputter ({col}) VALUES (?)", (text,))
    elif tl == "ALD" and mt == "desired_material":
        conn.execute("INSERT OR IGNORE INTO Available_Materials_ALD (material) VALUES (?)", (text,))
    elif tl in {"E_beam", "Furnace"}:
        conn.execute(f"INSERT OR IGNORE INTO Available_Materials_{tl} (material) VALUES (?)", (text,))
    conn.commit()


def remove_candidate_value(conn: sqlite3.Connection, tool_name: str, material_type: str, value: str) -> None:
    text = str(value or "").strip()
    if not text:
        return
    mt = str(material_type or "").strip()
    tl = str(tool_name or "").strip()
    if mt == "gas" and tl == "Sputter":
        conn.execute("DELETE FROM Available_Gases_Sputter WHERE gas_name = ?", (text,))
    elif mt == "gas" and tl == "ALD":
        conn.execute("DELETE FROM Available_Gases_ALD WHERE gas_name = ?", (text,))
    elif mt == "precursor_name" and tl == "ALD":
        conn.execute("DELETE FROM Available_Precursors_ALD WHERE precursor_name = ?", (text,))
    elif tl == "Sputter":
        col = mt if mt in {"desired_material", "target_material"} else "desired_material"
        conn.execute(f"DELETE FROM Available_Materials_Sputter WHERE {col} = ?", (text,))
    elif tl == "ALD" and mt == "desired_material":
        conn.execute("DELETE FROM Available_Materials_ALD WHERE material = ?", (text,))
    elif tl in {"E_beam", "Furnace"}:
        conn.execute(f"DELETE FROM Available_Materials_{tl} WHERE material = ?", (text,))
    conn.commit()


def get_tool_attachment_summary(
    conn: sqlite3.Connection | None,
    *,
    tool_type: ToolType | str,
    layer_id: int,
) -> dict[str, Any] | None:
    if conn is None:
        return None
    tool_enum = _coerce_tool_type(tool_type)
    table = _TOOL_TABLE_MAP[tool_enum]
    if not (_table_exists(conn, table) and _table_exists(conn, _ATTACHMENT_TABLE)):
        return None
    row = conn.execute(
        f"""
        SELECT a.id, a.file_name, a.file_size, a.content_hash, a.created_at
        FROM {table} t
        JOIN {_ATTACHMENT_TABLE} a ON a.id = t.attachment_id
        WHERE t.{_LAYER_FK_COL} = ?
        """,
        (int(layer_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "attachment_id": int(row[0]),
        "file_name": str(row[1]),
        "file_size": int(row[2] or 0),
        "content_hash": str(row[3] or ""),
        "created_at": None if row[4] is None else str(row[4]),
    }


def link_attachment_to_tool(
    conn: sqlite3.Connection,
    *,
    tool_type: ToolType | str,
    layer_id: int,
    file_name: str,
    raw: bytes,
) -> dict[str, Any]:
    tool_enum = _coerce_tool_type(tool_type)
    table = _TOOL_TABLE_MAP[tool_enum]
    payload = bytes(raw)
    file_size = len(payload)
    digest = _sha256_hex(payload)

    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_attachment_schema(conn)
        _ensure_tool_row_internal(conn, tool_enum, int(layer_id))
        current_row = conn.execute(
            f"SELECT attachment_id FROM {table} WHERE {_LAYER_FK_COL} = ?",
            (int(layer_id),),
        ).fetchone()
        old_attachment_id = None if current_row is None or current_row[0] is None else int(current_row[0])
        attachment_id, reused = _ensure_attachment_row(
            conn,
            file_name=str(file_name),
            raw=payload,
            file_size=file_size,
            content_hash=digest,
        )
        conn.execute(
            f"UPDATE {table} SET attachment_id = ? WHERE {_LAYER_FK_COL} = ?",
            (attachment_id, int(layer_id)),
        )
        if old_attachment_id is not None and old_attachment_id != attachment_id:
            _delete_attachment_if_orphan(conn, old_attachment_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    summary = get_tool_attachment_summary(conn, tool_type=tool_enum, layer_id=int(layer_id))
    return {
        "attachment_id": attachment_id,
        "reused": bool(reused),
        "summary": summary,
    }


def detach_attachment_from_tool(
    conn: sqlite3.Connection,
    *,
    tool_type: ToolType | str,
    layer_id: int,
) -> bool:
    tool_enum = _coerce_tool_type(tool_type)
    table = _TOOL_TABLE_MAP[tool_enum]
    if not _table_exists(conn, table):
        return False
    row = conn.execute(
        f"SELECT attachment_id FROM {table} WHERE {_LAYER_FK_COL} = ?",
        (int(layer_id),),
    ).fetchone()
    if row is None or row[0] is None:
        return False
    attachment_id = int(row[0])
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE {table} SET attachment_id = NULL WHERE {_LAYER_FK_COL} = ?",
            (int(layer_id),),
        )
        _delete_attachment_if_orphan(conn, attachment_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def fetch_attachment_export(conn: sqlite3.Connection, attachment_id: int) -> tuple[str, bytes] | None:
    row = conn.execute(
        f"SELECT file_name, raw FROM {_ATTACHMENT_TABLE} WHERE id=?",
        (int(attachment_id),),
    ).fetchone()
    if row is None:
        return None
    return (str(row[0] or "attachment.bin"), row[1])


def copy_tool_attachments_between(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    source_to_target_step_ids: dict[int, int],
    *,
    manage_transaction: bool = True,
) -> None:
    if not source_to_target_step_ids:
        return
    if not (_table_exists(source_conn, _LAYER_TABLE) and _table_exists(target_conn, _LAYER_TABLE)):
        return
    if not (_table_exists(source_conn, _ATTACHMENT_TABLE) and _table_exists(target_conn, _ATTACHMENT_TABLE)):
        return

    if manage_transaction:
        target_conn.execute("BEGIN IMMEDIATE")
    try:
        for src_step_id, dst_step_id in source_to_target_step_ids.items():
            src_layer = source_conn.execute(
                f"SELECT tools FROM {_LAYER_TABLE} WHERE id = ?",
                (int(src_step_id),),
            ).fetchone()
            if src_layer is None:
                continue
            try:
                tool_type = ToolType.from_storage(str(src_layer[0]))
            except ValueError:
                continue
            table = _TOOL_TABLE_MAP[tool_type]
            if not (_table_exists(source_conn, table) and _table_exists(target_conn, table)):
                continue
            if "attachment_id" not in _table_columns(source_conn, table):
                continue
            if "attachment_id" not in _table_columns(target_conn, table):
                continue

            _ensure_tool_row_internal(target_conn, tool_type, int(dst_step_id))
            current_row = target_conn.execute(
                f"SELECT attachment_id FROM {table} WHERE {_LAYER_FK_COL} = ?",
                (int(dst_step_id),),
            ).fetchone()
            old_attachment_id = None if current_row is None or current_row[0] is None else int(current_row[0])

            payload_row = source_conn.execute(
                f"""
                SELECT a.file_name, a.raw, a.file_size, a.content_hash
                FROM {table} t
                JOIN {_ATTACHMENT_TABLE} a ON a.id = t.attachment_id
                WHERE t.{_LAYER_FK_COL} = ?
                """,
                (int(src_step_id),),
            ).fetchone()

            if payload_row is None:
                target_conn.execute(
                    f"UPDATE {table} SET attachment_id = NULL WHERE {_LAYER_FK_COL} = ?",
                    (int(dst_step_id),),
                )
                _delete_attachment_if_orphan(target_conn, old_attachment_id)
                continue

            attachment_id, _ = _ensure_attachment_row(
                target_conn,
                file_name=str(payload_row[0] or "attachment.bin"),
                raw=bytes(payload_row[1]),
                file_size=int(payload_row[2] or len(payload_row[1])),
                content_hash=None if payload_row[3] is None else str(payload_row[3]),
            )
            target_conn.execute(
                f"UPDATE {table} SET attachment_id = ? WHERE {_LAYER_FK_COL} = ?",
                (int(attachment_id), int(dst_step_id)),
            )
            if old_attachment_id is not None and old_attachment_id != attachment_id:
                _delete_attachment_if_orphan(target_conn, old_attachment_id)

        if manage_transaction:
            target_conn.commit()
    except Exception:
        if manage_transaction:
            target_conn.rollback()
        raise


def nmlc_next_order(conn: sqlite3.Connection | None, ald_id: int | None, parent_mgcr_id: int | None) -> int:
    if conn is None or ald_id is None:
        return 0
    cur = conn.cursor()
    if parent_mgcr_id is None:
        cur.execute(
            f"SELECT COALESCE(MAX({_ORDER_SQL}), -1) + 1 FROM {_REL_TABLE} WHERE ALD_id=? AND parent_id IS NULL",
            (int(ald_id),),
        )
    else:
        cur.execute(
            f"SELECT COALESCE(MAX({_ORDER_SQL}), -1) + 1 FROM {_REL_TABLE} WHERE ALD_id=? AND parent_id=?",
            (int(ald_id), int(parent_mgcr_id)),
        )
    row = cur.fetchone()
    return int((row or [0])[0] or 0)


def _nmlc_parent_where_sql(parent_mgcr_id: int | None) -> tuple[str, tuple[Any, ...]]:
    if parent_mgcr_id is None:
        return "parent_id IS NULL", ()
    return "parent_id = ?", (int(parent_mgcr_id),)


def _nmlc_shift_orders(
    conn: sqlite3.Connection,
    *,
    ald_id: int,
    parent_mgcr_id: int | None,
    min_order: int | None = None,
    max_order: int | None = None,
    delta: int,
    exclude_mgcr_id: int | None = None,
) -> None:
    if delta == 0:
        return
    parent_where, parent_params = _nmlc_parent_where_sql(parent_mgcr_id)
    conditions = [f"ALD_id = ?", parent_where]
    params: list[Any] = [int(ald_id), *parent_params]
    if min_order is not None:
        conditions.append(f"{_ORDER_SQL} >= ?")
        params.append(int(min_order))
    if max_order is not None:
        conditions.append(f"{_ORDER_SQL} <= ?")
        params.append(int(max_order))
    if exclude_mgcr_id is not None:
        conditions.append("id <> ?")
        params.append(int(exclude_mgcr_id))
    where_sql = " AND ".join(conditions)
    conn.execute(
        f"UPDATE {_REL_TABLE} SET {_ORDER_SQL} = {_ORDER_SQL} + ? WHERE {where_sql}",
        (int(delta), *params),
    )


def nmlc_create_node(
    conn: sqlite3.Connection,
    *,
    ald_id: int,
    kind: str,
    parent_mgcr_id: int | None,
    order_value: int | None,
) -> dict[str, int]:
    owns_tx = not conn.in_transaction
    order_num = nmlc_next_order(conn, int(ald_id), parent_mgcr_id) if order_value is None else max(0, int(order_value))
    normalized_kind = str(kind).strip().lower()
    if normalized_kind == "cycle":
        db_type = "cycle"
    elif normalized_kind == "gas":
        db_type = "gas"
    else:
        db_type = "material"
    if owns_tx:
        conn.execute("BEGIN IMMEDIATE")
    try:
        if order_value is not None:
            _nmlc_shift_orders(
                conn,
                ald_id=int(ald_id),
                parent_mgcr_id=parent_mgcr_id,
                min_order=int(order_num),
                delta=1,
            )
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {_REL_TABLE}(type,parent_id,{_ORDER_SQL},ALD_id) VALUES (?,?,?,?)",
            (db_type, None if parent_mgcr_id is None else int(parent_mgcr_id), int(order_num), int(ald_id)),
        )
        mgcr_id = int(cur.lastrowid)
        if db_type == "cycle":
            cur.execute(f"INSERT INTO {_CYCLE_TABLE}({_NODE_REF_COL}, cycle_number) VALUES (?, 1)", (mgcr_id,))
        elif db_type == "gas":
            cur.execute(
                f"INSERT INTO {_ALD_GAS_TABLE}({_NODE_REF_COL}, gas_type, flow_value, flow_unit) VALUES (?, ?, ?, ?)",
                (mgcr_id, "", None, "sccm"),
            )
        else:
            cur.execute(
                f"INSERT INTO {_ALD_MATERIAL_TABLE}({_NODE_REF_COL},desired_material,precursor_name,dep_rate_value,dep_rate_unit,dep_time_s) VALUES (?,?,?,?,?,?)",
                (mgcr_id, "", "", None, "nm/cycle", None),
            )
        if owns_tx:
            conn.commit()
        return {"mgcr_id": mgcr_id, "ald_id": int(ald_id)}
    except Exception:
        if owns_tx:
            conn.rollback()
        raise


def nmlc_delete_node(conn: sqlite3.Connection, *, mgcr_id: int) -> int | None:
    row = conn.execute(
        f"SELECT parent_id, ALD_id, {_ORDER_SQL} FROM {_REL_TABLE} WHERE id = ?",
        (int(mgcr_id),),
    ).fetchone()
    if row is None:
        return None
    parent_id = None if row[0] is None else int(row[0])
    ald_id = int(row[1])
    old_order = int(row[2] or 0)
    owns_tx = not conn.in_transaction
    if owns_tx:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"DELETE FROM {_REL_TABLE} WHERE id = ?", (int(mgcr_id),))
        _nmlc_shift_orders(
            conn,
            ald_id=ald_id,
            parent_mgcr_id=parent_id,
            min_order=old_order + 1,
            delta=-1,
        )
        if owns_tx:
            conn.commit()
        return parent_id
    except Exception:
        if owns_tx:
            conn.rollback()
        raise


def nmlc_move_node(
    conn: sqlite3.Connection,
    *,
    ald_id: int,
    mgcr_id: int,
    old_parent_id: int | None,
    new_parent_id: int | None,
    new_order: int,
) -> None:
    row = conn.execute(
        f"SELECT parent_id, {_ORDER_SQL} FROM {_REL_TABLE} WHERE id = ?",
        (int(mgcr_id),),
    ).fetchone()
    if row is None:
        return
    current_parent = None if row[0] is None else int(row[0])
    current_order = int(row[1] or 0)
    target_parent = None if new_parent_id is None else int(new_parent_id)
    target_order = max(0, int(new_order))
    owns_tx = not conn.in_transaction
    if owns_tx:
        conn.execute("BEGIN IMMEDIATE")
    try:
        if current_parent == target_parent:
            if target_order < current_order:
                _nmlc_shift_orders(
                    conn,
                    ald_id=ald_id,
                    parent_mgcr_id=current_parent,
                    min_order=target_order,
                    max_order=current_order - 1,
                    delta=1,
                    exclude_mgcr_id=int(mgcr_id),
                )
            elif target_order > current_order:
                _nmlc_shift_orders(
                    conn,
                    ald_id=ald_id,
                    parent_mgcr_id=current_parent,
                    min_order=current_order + 1,
                    max_order=target_order,
                    delta=-1,
                    exclude_mgcr_id=int(mgcr_id),
                )
            else:
                if owns_tx:
                    conn.rollback()
                return
        else:
            _nmlc_shift_orders(
                conn,
                ald_id=ald_id,
                parent_mgcr_id=current_parent,
                min_order=current_order + 1,
                delta=-1,
                exclude_mgcr_id=int(mgcr_id),
            )
            _nmlc_shift_orders(
                conn,
                ald_id=ald_id,
                parent_mgcr_id=target_parent,
                min_order=target_order,
                delta=1,
                exclude_mgcr_id=int(mgcr_id),
            )

        conn.execute(
            f"UPDATE {_REL_TABLE} SET parent_id=?, {_ORDER_SQL}=? WHERE id=?",
            (target_parent, target_order, int(mgcr_id)),
        )
        if owns_tx:
            conn.commit()
    except Exception:
        if owns_tx:
            conn.rollback()
        raise


def nmlc_reorder_siblings(conn: sqlite3.Connection, *, ald_id: int, parent_mgcr_id: int | None) -> None:
    if parent_mgcr_id is None:
        rows = conn.execute(
            f"SELECT id FROM {_REL_TABLE} WHERE ALD_id=? AND parent_id IS NULL ORDER BY {_ORDER_SQL}, id",
            (int(ald_id),),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id FROM {_REL_TABLE} WHERE ALD_id=? AND parent_id=? ORDER BY {_ORDER_SQL}, id",
            (int(ald_id), int(parent_mgcr_id)),
        ).fetchall()
    for idx, (rid,) in enumerate(rows):
        conn.execute(f"UPDATE {_REL_TABLE} SET {_ORDER_SQL}=? WHERE id=?", (int(idx), int(rid)))
    conn.commit()


def nmlc_upsert_material(
    conn: sqlite3.Connection,
    *,
    mgcr_id: int,
    ald_id: int | None,
    desired_material: str,
    precursor_name: str,
    dep_rate_value: float | None,
    dep_rate_unit: str,
    dep_time_s: float | None,
) -> None:
    _ = ald_id
    cur = conn.cursor()
    cur.execute(
        f"UPDATE {_ALD_MATERIAL_TABLE} SET desired_material=?, precursor_name=?, dep_rate_value=?, dep_rate_unit=?, dep_time_s=? WHERE {_NODE_REF_COL}=?",
        (desired_material, precursor_name, dep_rate_value, dep_rate_unit, dep_time_s, int(mgcr_id)),
    )
    if cur.rowcount == 0:
        cur.execute(
            f"INSERT INTO {_ALD_MATERIAL_TABLE}({_NODE_REF_COL},desired_material,precursor_name,dep_rate_value,dep_rate_unit,dep_time_s) VALUES (?,?,?,?,?,?)",
            (int(mgcr_id), desired_material, precursor_name, dep_rate_value, dep_rate_unit, dep_time_s),
        )
    conn.commit()


def nmlc_upsert_gas(
    conn: sqlite3.Connection,
    *,
    mgcr_id: int,
    gas_type: str,
    flow_value: float | None,
    flow_unit: str,
) -> None:
    cur = conn.cursor()
    cur.execute(
        f"UPDATE {_ALD_GAS_TABLE} SET gas_type=?, flow_value=?, flow_unit=? WHERE {_NODE_REF_COL}=?",
        (gas_type, flow_value, flow_unit, int(mgcr_id)),
    )
    if cur.rowcount == 0:
        cur.execute(
            f"INSERT INTO {_ALD_GAS_TABLE}({_NODE_REF_COL}, gas_type, flow_value, flow_unit) VALUES (?, ?, ?, ?)",
            (int(mgcr_id), gas_type, flow_value, flow_unit),
        )
    conn.commit()


def nmlc_upsert_cycle(conn: sqlite3.Connection, *, mgcr_id: int, cycle_number: int) -> None:
    cur = conn.cursor()
    cur.execute(f"UPDATE {_CYCLE_TABLE} SET cycle_number=? WHERE {_NODE_REF_COL}=?", (int(cycle_number), int(mgcr_id)))
    if cur.rowcount == 0:
        cur.execute(f"INSERT INTO {_CYCLE_TABLE}({_NODE_REF_COL}, cycle_number) VALUES (?,?)", (int(mgcr_id), int(cycle_number)))
    conn.commit()


def nmlc_load_tree(conn: sqlite3.Connection | None, ald_id: int | None) -> list[dict[str, Any]]:
    if conn is None or ald_id is None or not table_exists(conn, _REL_TABLE):
        return []
    rows = conn.execute(
        f"SELECT id, type, parent_id, {_ORDER_SQL}, ALD_id FROM {_REL_TABLE} WHERE ALD_id=? ORDER BY {_ORDER_SQL}, id",
        (int(ald_id),),
    ).fetchall()
    if not rows:
        return []

    cycle_ids = [int(r[0]) for r in rows if _normalize_mgcr_type(r[1]) == "cycle"]
    material_ids = [int(r[0]) for r in rows if _normalize_mgcr_type(r[1]) == "material"]
    gas_ids = [int(r[0]) for r in rows if _normalize_mgcr_type(r[1]) == "gas"]

    cycle_map: dict[int, int] = {}
    if cycle_ids and table_exists(conn, _CYCLE_TABLE):
        qmarks = ", ".join("?" for _ in cycle_ids)
        for mgcr_id, cycle_num in conn.execute(
            f"SELECT {_NODE_REF_COL}, cycle_number FROM {_CYCLE_TABLE} WHERE {_NODE_REF_COL} IN ({qmarks})",
            tuple(cycle_ids),
        ).fetchall():
            cycle_map[int(mgcr_id)] = int(cycle_num or 1)

    material_map: dict[int, tuple[str, str, float | None, str, float | None]] = {}
    if material_ids and table_exists(conn, _ALD_MATERIAL_TABLE):
        qmarks = ", ".join("?" for _ in material_ids)
        for mgcr_id, dm, pc, val, unit, dep_time_s in conn.execute(
            f"SELECT {_NODE_REF_COL}, desired_material, precursor_name, dep_rate_value, dep_rate_unit, dep_time_s FROM {_ALD_MATERIAL_TABLE} WHERE {_NODE_REF_COL} IN ({qmarks})",
            tuple(material_ids),
        ).fetchall():
            material_map[int(mgcr_id)] = (
                "" if dm is None else str(dm),
                "" if pc is None else str(pc),
                None if val is None else float(val),
                "nm/cycle" if unit is None else str(unit),
                None if dep_time_s is None else float(dep_time_s),
            )

    gas_map: dict[int, tuple[str, float | None, str]] = {}
    if gas_ids and table_exists(conn, _ALD_GAS_TABLE):
        qmarks = ", ".join("?" for _ in gas_ids)
        for mgcr_id, gas_type, flow_value, flow_unit in conn.execute(
            f"SELECT {_NODE_REF_COL}, gas_type, flow_value, flow_unit FROM {_ALD_GAS_TABLE} WHERE {_NODE_REF_COL} IN ({qmarks})",
            tuple(gas_ids),
        ).fetchall():
            gas_map[int(mgcr_id)] = (
                "" if gas_type is None else str(gas_type),
                None if flow_value is None else float(flow_value),
                "sccm" if flow_unit is None else str(flow_unit),
            )

    nodes: dict[int, dict[str, Any]] = {}
    children: dict[int, list[tuple[int, int]]] = {}
    roots: list[tuple[int, int]] = []

    for node_id, db_type, parent_id, order_value, row_ald_id in rows:
        nid = int(node_id)
        kind = _normalize_mgcr_type(db_type)
        if kind == "cycle":
            node = {
                "type": "cycle",
                "mgcr_id": nid,
                "ald_id": int(row_ald_id),
                "cycle_num": int(cycle_map.get(nid, 1)),
                "children": [],
            }
        elif kind == "gas":
            gas_type, flow_value, flow_unit = gas_map.get(nid, ("", None, "sccm"))
            node = {
                "type": "gas",
                "mgcr_id": nid,
                "ald_id": int(row_ald_id),
                "gas_type": gas_type,
                "flow_value": flow_value,
                "flow_unit": flow_unit,
            }
        else:
            dm, pc, val, unit, dep_time_s = material_map.get(nid, ("", "", None, "nm/cycle", None))
            node = {
                "type": "material",
                "mgcr_id": nid,
                "ald_id": int(row_ald_id),
                "desired_material": dm,
                "precursor_name": pc,
                "dep_rate_value": val,
                "dep_rate_unit": unit,
                "dep_time_s": dep_time_s,
            }
        nodes[nid] = node
        if parent_id is None:
            roots.append((int(order_value or 0), nid))
        else:
            children.setdefault(int(parent_id), []).append((int(order_value or 0), nid))

    roots.sort(key=lambda x: x[0])

    def attach(parent_id: int) -> None:
        if nodes[parent_id]["type"] != "cycle":
            return
        kids = sorted(children.get(parent_id, []), key=lambda x: x[0])
        nodes[parent_id]["children"] = [nodes[child_id] for _, child_id in kids]
        for _, child_id in kids:
            if nodes[child_id]["type"] == "cycle":
                attach(child_id)

    for _, root_id in roots:
        if nodes[root_id]["type"] == "cycle":
            attach(root_id)

    return [nodes[root_id] for _, root_id in roots]


def ald_by_step(conn: sqlite3.Connection, step_ids: list[int]) -> dict[int, int]:
    if not step_ids:
        return {}
    qmarks = ", ".join("?" for _ in step_ids)
    rows = conn.execute(
        f"SELECT id, {_LAYER_FK_COL} FROM Tool_ALD WHERE {_LAYER_FK_COL} IN ({qmarks})",
        tuple(int(x) for x in step_ids),
    ).fetchall()
    return {int(layer_id): int(ald_id) for ald_id, layer_id in rows}


def copy_nmlc_between(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    source_to_target_step_ids: dict[int, int],
    *,
    manage_transaction: bool = True,
) -> None:
    if not source_to_target_step_ids:
        return
    required = {_REL_TABLE, _CYCLE_TABLE, _ALD_MATERIAL_TABLE, _ALD_GAS_TABLE, "Tool_ALD"}
    if not all(table_exists(source_conn, table) for table in required):
        return
    if not all(table_exists(target_conn, table) for table in required):
        return

    src_ald_by_step = ald_by_step(source_conn, list(source_to_target_step_ids.keys()))
    dst_ald_by_step = ald_by_step(target_conn, list(source_to_target_step_ids.values()))
    for src_step_id, dst_step_id in source_to_target_step_ids.items():
        src_ald = src_ald_by_step.get(int(src_step_id))
        dst_ald = dst_ald_by_step.get(int(dst_step_id))
        if src_ald is None or dst_ald is None:
            continue
        copy_nmlc_for_ald(
            source_conn,
            target_conn,
            source_ald_id=int(src_ald),
            target_ald_id=int(dst_ald),
            manage_transaction=manage_transaction,
        )


def copy_nmlc_for_ald(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    *,
    source_ald_id: int,
    target_ald_id: int,
    manage_transaction: bool = True,
) -> None:
    rows = source_conn.execute(
        f"""
        SELECT id, type, parent_id, {_ORDER_SQL}
        FROM {_REL_TABLE}
        WHERE ALD_id = ?
        ORDER BY
            CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END,
            parent_id,
            {_ORDER_SQL},
            id
        """,
        (int(source_ald_id),),
    ).fetchall()

    if manage_transaction:
        target_conn.execute("BEGIN IMMEDIATE")
    try:
        target_conn.execute(f"DELETE FROM {_REL_TABLE} WHERE ALD_id = ?", (int(target_ald_id),))
        if not rows:
            if manage_transaction:
                target_conn.commit()
            return

        old_to_new: dict[int, int] = {}
        parent_refs: dict[int, int | None] = {}
        for old_id, ntype, parent_id, order_value in rows:
            node_kind = _normalize_mgcr_type(ntype)
            db_type = "cycle" if node_kind == "cycle" else ("gas" if node_kind == "gas" else "material")
            cur = target_conn.cursor()
            cur.execute(
                f"INSERT INTO {_REL_TABLE} (type, parent_id, {_ORDER_SQL}, ALD_id) VALUES (?, NULL, ?, ?)",
                (db_type, int(order_value or 0), int(target_ald_id)),
            )
            new_id = int(cur.lastrowid)
            old_to_new[int(old_id)] = new_id
            parent_refs[int(old_id)] = None if parent_id is None else int(parent_id)

        for old_id, old_parent in parent_refs.items():
            if old_parent is None:
                continue
            new_parent = old_to_new.get(int(old_parent))
            if new_parent is None:
                continue
            target_conn.execute(
                f"UPDATE {_REL_TABLE} SET parent_id = ? WHERE id = ?",
                (int(new_parent), int(old_to_new[int(old_id)])),
            )

        old_ids = list(old_to_new.keys())
        qmarks = ", ".join("?" for _ in old_ids)
        cycle_rows = source_conn.execute(
            f"SELECT {_NODE_REF_COL}, cycle_number FROM {_CYCLE_TABLE} WHERE {_NODE_REF_COL} IN ({qmarks})",
            tuple(old_ids),
        ).fetchall()
        for old_mgcr_id, cycle_number in cycle_rows:
            new_mgcr_id = old_to_new.get(int(old_mgcr_id))
            if new_mgcr_id is None:
                continue
            target_conn.execute(
                f"INSERT INTO {_CYCLE_TABLE} ({_NODE_REF_COL}, cycle_number) VALUES (?, ?)",
                (int(new_mgcr_id), int(cycle_number or 1)),
            )

        material_rows = source_conn.execute(
            f"""
            SELECT {_NODE_REF_COL}, desired_material, precursor_name, dep_rate_value, dep_rate_unit, dep_time_s
            FROM {_ALD_MATERIAL_TABLE}
            WHERE {_NODE_REF_COL} IN ({qmarks})
            """,
            tuple(old_ids),
        ).fetchall()

        for row in material_rows:
            old_mgcr_id = int(row[0])
            new_mgcr_id = old_to_new.get(old_mgcr_id)
            if new_mgcr_id is None:
                continue
            desired = row[1]
            precursor = row[2]
            dep_rate_value = row[3]
            dep_rate_unit = row[4]
            dep_time_s = row[5]
            target_conn.execute(
                f"""
                INSERT INTO {_ALD_MATERIAL_TABLE}
                ({_NODE_REF_COL}, desired_material, precursor_name, dep_rate_value, dep_rate_unit, dep_time_s)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(new_mgcr_id), desired, precursor, dep_rate_value, dep_rate_unit, dep_time_s),
            )

        gas_rows = source_conn.execute(
            f"""
            SELECT {_NODE_REF_COL}, gas_type, flow_value, flow_unit
            FROM {_ALD_GAS_TABLE}
            WHERE {_NODE_REF_COL} IN ({qmarks})
            """,
            tuple(old_ids),
        ).fetchall()

        for old_mgcr_id, gas_type, flow_value, flow_unit in gas_rows:
            new_mgcr_id = old_to_new.get(int(old_mgcr_id))
            if new_mgcr_id is None:
                continue
            target_conn.execute(
                f"""
                INSERT INTO {_ALD_GAS_TABLE}
                ({_NODE_REF_COL}, gas_type, flow_value, flow_unit)
                VALUES (?, ?, ?, ?)
                """,
                (int(new_mgcr_id), gas_type, flow_value, flow_unit),
            )

        if manage_transaction:
            target_conn.commit()
    except Exception:
        if manage_transaction:
            target_conn.rollback()
        raise
