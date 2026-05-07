-- Auto-generated schema snapshot from Manufacture_Process_Database.db
BEGIN TRANSACTION;
-- table: Available_Gases_ALD
CREATE TABLE Available_Gases_ALD (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gas_name TEXT UNIQUE
        );

-- table: Available_Gases_Sputter
CREATE TABLE Available_Gases_Sputter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gas_name TEXT UNIQUE
            );

-- table: Available_Materials_ALD
CREATE TABLE Available_Materials_ALD (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT UNIQUE
            );

-- table: Available_Materials_E_beam
CREATE TABLE Available_Materials_E_beam (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT UNIQUE
            );

-- table: Available_Materials_Furnace
CREATE TABLE Available_Materials_Furnace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material TEXT UNIQUE
            );

-- table: Available_Materials_Sputter
CREATE TABLE Available_Materials_Sputter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                desired_material TEXT UNIQUE,
                target_material TEXT UNIQUE
            );

-- table: Available_Precursors_ALD
CREATE TABLE Available_Precursors_ALD (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                precursor_name TEXT UNIQUE
            );

-- table: Layer
CREATE TABLE Layer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer_type TEXT NOT NULL,
                position_in_layer INTEGER NOT NULL CHECK(position_in_layer >= 1),
                tools TEXT NOT NULL,
                thickness_nm REAL,
                CHECK (layer_type IN ('Top', 'Insulator', 'Bottom')),
                UNIQUE (layer_type, position_in_layer)
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

COMMIT;
