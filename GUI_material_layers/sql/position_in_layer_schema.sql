-- position_in_layer_schema.sql
-- Purpose: define and migrate Layer ordering with
--          "position_in_layer" (1 = bottom-most tool inside one layer).
-- Note: layer order for rendering is Top -> Insulator -> Bottom.
--       position_in_layer order inside each layer is 1,2,3... bottom -> top.

/* -------------------------------------------------------------------------- */
/* 1) WORKING DB TARGET TABLE (Manufacture_Process_Database.db)               */
/* -------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS Layer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_type TEXT NOT NULL,
    position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
    tools TEXT NOT NULL,
    thickness_nm REAL,
    CHECK (layer_type IN ('Top', 'Insulator', 'Bottom')),
    UNIQUE (layer_type, position_in_layer)
);

CREATE INDEX IF NOT EXISTS idx_mps_layer_pos
ON Layer(layer_type, position_in_layer);

/* -------------------------------------------------------------------------- */
/* 2) RECIPE DB TARGET TABLE (Database_NEW_V2.db recipe-side subtree)         */
/* -------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS Recipe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS Layer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    layer_type TEXT NOT NULL,
    position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
    tools TEXT NOT NULL,
    thickness_nm REAL,
    CHECK (layer_type IN ('Top', 'Insulator', 'Bottom')),
    UNIQUE (recipe_id, layer_type, position_in_layer),
    FOREIGN KEY (recipe_id) REFERENCES Recipe(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recipe_mps_order
ON Layer(recipe_id, layer_type, position_in_layer);

/* -------------------------------------------------------------------------- */
/* 3) WORKING DB MIGRATION TEMPLATE                                           */
/* -------------------------------------------------------------------------- */
-- For legacy schema containing sub_layer or without position_in_layer.
-- Keep id values stable so Tool_* foreign keys stay valid.

BEGIN IMMEDIATE;
PRAGMA foreign_keys = OFF;

CREATE TABLE Layer_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    layer_type TEXT NOT NULL,
    position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
    tools TEXT NOT NULL,
    thickness_nm REAL,
    CHECK (layer_type IN ('Top', 'Insulator', 'Bottom')),
    UNIQUE (layer_type, position_in_layer)
);

INSERT INTO Layer_new
(id, layer_type, position_in_layer, tools, thickness_nm)
SELECT
    id,
    layer_type,
    ROW_NUMBER() OVER (PARTITION BY layer_type ORDER BY id ASC) AS position_in_layer,
    tools,
    thickness_nm
FROM Layer
WHERE layer_type IN ('Top', 'Insulator', 'Bottom');

DROP TABLE Layer;
ALTER TABLE Layer_new RENAME TO Layer;

CREATE INDEX idx_mps_layer_pos
ON Layer(layer_type, position_in_layer);

PRAGMA foreign_keys = ON;
COMMIT;

/* -------------------------------------------------------------------------- */
/* 4) RECIPE DB MIGRATION TEMPLATE                                            */
/* -------------------------------------------------------------------------- */
-- Use id-order fallback so old data can be normalized safely.

BEGIN IMMEDIATE;
PRAGMA foreign_keys = OFF;

CREATE TABLE Layer_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    layer_type TEXT NOT NULL,
    position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
    tools TEXT NOT NULL,
    thickness_nm REAL,
    CHECK (layer_type IN ('Top', 'Insulator', 'Bottom')),
    UNIQUE (recipe_id, layer_type, position_in_layer),
    FOREIGN KEY (recipe_id) REFERENCES Recipe(id) ON DELETE CASCADE
);

INSERT INTO Layer_new
(id, recipe_id, layer_type, position_in_layer, tools, thickness_nm)
SELECT
    id,
    recipe_id,
    layer_type,
    ROW_NUMBER() OVER (
        PARTITION BY recipe_id, layer_type
        ORDER BY id ASC
    ) AS position_in_layer,
    tools,
    thickness_nm
FROM Layer
WHERE layer_type IN ('Top', 'Insulator', 'Bottom');

DROP TABLE Layer;
ALTER TABLE Layer_new RENAME TO Layer;

CREATE INDEX idx_recipe_mps_order
ON Layer(recipe_id, layer_type, position_in_layer);

PRAGMA foreign_keys = ON;
COMMIT;
