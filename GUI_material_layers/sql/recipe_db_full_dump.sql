-- Auto-generated schema snapshot from Database_NEW_V2.db
BEGIN TRANSACTION;
-- table: Device
CREATE TABLE Device (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- Surrogate key

    subdie_id       INTEGER NOT NULL                    -- Parent subdie
                        REFERENCES Subdie(id)
                        ON DELETE CASCADE,

    gate            INTEGER NOT NULL,                   -- Gate terminal index within the subdie
    source          INTEGER NOT NULL,                   -- Source terminal index within the subdie
    drain           INTEGER NOT NULL,                   -- Drain terminal index within the subdie

    UNIQUE(subdie_id, gate, source, drain)              -- Unique device address per subdie
);

-- table: Die
CREATE TABLE Die (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- Surrogate key for die

    wafer_id        INTEGER NOT NULL                    -- Parent wafer
                        REFERENCES Wafer(id)
                        ON DELETE CASCADE,             -- Deleting a wafer deletes all its dies

    die_number      INTEGER NOT NULL,                  -- Die index on the wafer (layout-dependent)
    die_type        TEXT NOT NULL,                     -- Die type / design variant

    UNIQUE(wafer_id, die_number)                       -- Unique die_number per wafer
);

-- table: Experiment
CREATE TABLE Experiment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- Surrogate key for experiment

    device_id       INTEGER NOT NULL                     -- Device being measured
                        REFERENCES Device(id)
                        ON DELETE RESTRICT,              -- Do not allow deleting a Device that has experiments

    experiment_name TEXT NOT NULL,                       -- Human-readable experiment label
    user_name       TEXT,                                -- Operator / owner (optional)
    function_type   TEXT,                                -- e.g. 'TFT_Transfer', 'TFT_Output', ...
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- When the experiment record was created
    notes           TEXT                                 -- Free-form comments (optional)
);

-- table: Experimental_Detail
CREATE TABLE Experimental_Detail (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- Surrogate key for detail row

    experiment_id   INTEGER NOT NULL                     -- Parent experiment
                        REFERENCES Experiment(id)
                        ON DELETE CASCADE,

    gate_voltage_V  REAL,                                -- Applied gate-source voltage (Vgs)
    drain_voltage_V REAL,                                -- Applied drain-source voltage (Vds), formerly amplitude_V
    current_A       REAL,                                -- Measured drain-source current (Ids)
    resistance_ohm  REAL,                                -- Derived resistance: drain_voltage_V / current_A
    pulse_width_s   REAL,
    tag             TEXT NOT NULL,                       -- Instrument operation tag
    readtag         TEXT,
    read_voltage_V  REAL                                 -- Read voltage for resistance measurement
);

-- table: Features_TFT_Analysis_Config
CREATE TABLE Features_TFT_Analysis_Config (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    method_name             TEXT NOT NULL UNIQUE,
    vth_extraction_method   TEXT, -- e.g., 'linear_extrapolation', 'constant_current'
    mobility_calculation_info TEXT, -- e.g., 'oxide_capacitance_F_per_cm2=...'
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    note                    TEXT
);

-- table: Features_TFT_Output
CREATE TABLE Features_TFT_Output (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id                   INTEGER NOT NULL
                                        REFERENCES Experiment(id)
                                        ON DELETE RESTRICT,
    analysis_config_id              INTEGER NOT NULL
                                        REFERENCES Features_TFT_Analysis_Config(id)
                                        ON DELETE RESTRICT,

    output_resistance_kOhm          REAL,
    saturation_current_A            REAL,
    status                          TEXT, -- e.g., 'OK', 'FAIL'
    note                            TEXT,

    UNIQUE(experiment_id, analysis_config_id)
);

-- table: Features_TFT_Transfer
CREATE TABLE Features_TFT_Transfer (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id                   INTEGER NOT NULL
                                        REFERENCES Experiment(id)
                                        ON DELETE RESTRICT,
    analysis_config_id              INTEGER NOT NULL
                                        REFERENCES Features_TFT_Analysis_Config(id)
                                        ON DELETE RESTRICT,

    threshold_voltage_V             REAL,
    on_off_ratio                    REAL,
    subthreshold_swing_mV_per_dec   REAL,
    mobility_cm2_per_Vs             REAL,
    on_current_A                    REAL,
    off_current_A                   REAL,
    status                          TEXT, -- e.g., 'OK', 'FAIL'
    note                            TEXT,

    UNIQUE(experiment_id, analysis_config_id)
);

-- table: Function_TFT_Output
CREATE TABLE Function_TFT_Output (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id               INTEGER NOT NULL
                                    REFERENCES Experiment(id)
                                    ON DELETE CASCADE,

    gate_voltages_V             TEXT NOT NULL,    -- JSON list of constant Vgs values for the output sweeps
    drain_start_V               REAL NOT NULL,
    drain_stop_V                REAL NOT NULL,
    drain_step_V                REAL NOT NULL,
    cycles                      INTEGER DEFAULT 1,
    current_compliance_A        REAL,

    UNIQUE (experiment_id)
);

-- table: Function_TFT_Transfer
CREATE TABLE Function_TFT_Transfer (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id               INTEGER NOT NULL
                                    REFERENCES Experiment(id)
                                    ON DELETE CASCADE,

    drain_voltage_V             REAL NOT NULL,    -- Constant Vds for the transfer sweep
    gate_start_V                REAL NOT NULL,
    gate_stop_V                 REAL NOT NULL,
    gate_step_V                 REAL NOT NULL,
    cycles                      INTEGER DEFAULT 1,
    current_compliance_A        REAL,

    UNIQUE (experiment_id)
);

-- table: Layer
CREATE TABLE Layer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER NOT NULL,
                layer_type TEXT NOT NULL,
                position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
                tools TEXT NOT NULL,
                thickness_nm REAL,
                CHECK (layer_type IN ('Gate', 'GateDielectric', 'Semiconductor', 'Contact', 'Insulator', 'Substrate', 'Top', 'Bottom')),
                UNIQUE (recipe_id, layer_type, position_in_layer),
                FOREIGN KEY (recipe_id) REFERENCES Recipe(id) ON DELETE CASCADE
            );

-- table: Recipe
CREATE TABLE Recipe (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,      -- Surrogate key
    recipe_name     TEXT NOT NULL UNIQUE,                   -- Human-readable recipe identifier (must be unique)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,    -- Creation time in the database
    notes           TEXT                                    -- Free-form notes, optional
);

-- table: Subdie
CREATE TABLE Subdie (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,  -- Surrogate key

    die_id                   INTEGER NOT NULL                    -- Parent die
                                  REFERENCES Die(id)
                                  ON DELETE CASCADE,

    cross_sectional_area_um2   INTEGER NOT NULL,                   -- Cross-sectional area in µm²

    UNIQUE(die_id, cross_sectional_area_um2)                       -- Unique per die
);

-- table: Tool_ALD
CREATE TABLE "Tool_ALD" (
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
        );

-- table: Tool_ALD_Cycle
CREATE TABLE "Tool_ALD_Cycle" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            MGCR_id INTEGER NOT NULL UNIQUE,
            cycle_number INTEGER NOT NULL CHECK(cycle_number >= 1),
            FOREIGN KEY (MGCR_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE
        );

-- table: Tool_ALD_Gas
CREATE TABLE Tool_ALD_Gas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            MGCR_id INTEGER NOT NULL UNIQUE,
            gas_type TEXT,
            flow_value REAL,
            flow_unit TEXT NOT NULL DEFAULT 'sccm' CHECK(flow_unit IN ('sccm','slm')),
            FOREIGN KEY (MGCR_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE
        );

-- table: Tool_ALD_Material
CREATE TABLE "Tool_ALD_Material" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            MGCR_id INTEGER NOT NULL UNIQUE,
            desired_material TEXT,
            precursor_name TEXT,
            dep_rate_value REAL,
            dep_rate_unit TEXT DEFAULT 'nm/cycle',
            dep_time_s REAL,
            FOREIGN KEY (MGCR_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE
        );

-- table: Tool_ALD_Material_Gas_Cycle_Relation
CREATE TABLE Tool_ALD_Material_Gas_Cycle_Relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('cycle','material','gas')),
            parent_id INTEGER,
            "order" INTEGER NOT NULL DEFAULT 0,
            ALD_id INTEGER NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES Tool_ALD_Material_Gas_Cycle_Relation(id) ON DELETE CASCADE,
            FOREIGN KEY (ALD_id) REFERENCES Tool_ALD(id) ON DELETE CASCADE
        );

-- table: Tool_Attachment
CREATE TABLE Tool_Attachment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            raw BLOB NOT NULL,
            file_size INTEGER NOT NULL CHECK(file_size >= 0),
            content_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

-- table: Tool_E_beam
CREATE TABLE "Tool_E_beam" (
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
        );

-- table: Tool_Furnace
CREATE TABLE "Tool_Furnace" (
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
        );

-- table: Tool_Sputter
CREATE TABLE "Tool_Sputter" (
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
        );

-- table: Wafer
CREATE TABLE Wafer (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- Surrogate key for wafer

    recipe_id       INTEGER NOT NULL                    -- Fabrication recipe applied to this wafer
                        REFERENCES Recipe(id)
                        ON DELETE RESTRICT,            -- Prevent deleting a Recipe that is used by wafers

    wafer_name      TEXT NOT NULL,                     -- Human-readable wafer identifier (may be reused)
    lot             TEXT,                              -- Lot or batch identifier from the fab
    diameter_mm     INTEGER,                            -- Wafer diameter (e.g. 100, 150, 200)

    UNIQUE(recipe_id, wafer_name)                       -- Unique recipe_id per wafer_name
);

COMMIT;
