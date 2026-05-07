-- Auto-generated schema snapshot from Database_NEW_V2.db
BEGIN TRANSACTION;
-- table: Device
CREATE TABLE Device (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- Surrogate key

    subdie_id       INTEGER NOT NULL                    -- Parent subdie
                        REFERENCES Subdie(id)
                        ON DELETE CASCADE,

    wordline        INTEGER NOT NULL,                   -- Wordline index within the subdie
    bitline         INTEGER NOT NULL,                   -- Bitline index within the subdie

    UNIQUE(subdie_id, wordline, bitline)                -- Unique device address per subdie
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
    function_type   TEXT,                                -- e.g. 'CurveTracer', 'FormFinder', ...
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- When the experiment record was created
    notes           TEXT                                 -- Free-form comments (optional)
);

-- table: Experimental_Detail
CREATE TABLE Experimental_Detail (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- Surrogate key for detail row

    experiment_id   INTEGER NOT NULL                     -- Parent experiment
                        REFERENCES Experiment(id)
                        ON DELETE CASCADE,

    resistance_ohm  REAL,
    amplitude_V     REAL,
    pulse_width_s   REAL,
    tag             TEXT NOT NULL,                       -- Existing ArC tag semantics
    readtag         TEXT,
    read_voltage_V  REAL
);

-- table: Features_Electroforming
CREATE TABLE Features_Electroforming (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,

    method_type          TEXT NOT NULL,           -- e.g. 'ct_stability_4branch'

    stable_r2_th         REAL NOT NULL,           -- default 0.9
    unsure_r2_th         REAL NOT NULL,           -- default 0.5

    -- Policies (traceability):
    comp_hit_to_stable   INTEGER NOT NULL DEFAULT 1,  -- 1: comp_hit => state3=1.0
    r2_negative_to_zero  INTEGER NOT NULL DEFAULT 1,  -- 1: r2<0 -> 0 before mapping
    r2_clamp_to_unit     INTEGER NOT NULL DEFAULT 1,  -- 1: clamp r2 into [0,1] before mapping

    doi                  TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    note                 TEXT,

    CHECK (length(trim(method_type)) > 0),
    CHECK (stable_r2_th >= 0 AND stable_r2_th <= 1),
    CHECK (unsure_r2_th >= 0 AND unsure_r2_th <= 1),
    CHECK (stable_r2_th > unsure_r2_th),

    CHECK (comp_hit_to_stable  IN (0,1)),
    CHECK (r2_negative_to_zero IN (0,1)),
    CHECK (r2_clamp_to_unit    IN (0,1))
);

-- table: Features_Electroforming_max_drop
CREATE TABLE Features_Electroforming_max_drop (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ef_sinh_id          INTEGER NOT NULL
                                    REFERENCES Features_Electroforming_sinh(id)
                                    ON DELETE RESTRICT,
            r_before_ohm        REAL,
            r_after_ohm         REAL,
            drop_ratio          REAL,
            electroform_voltage_V REAL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            note                TEXT,
            UNIQUE(ef_sinh_id),
            CHECK (drop_ratio IS NULL OR drop_ratio >= 1)
        );

-- table: Features_Electroforming_sinh
CREATE TABLE Features_Electroforming_sinh (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    ef_id               INTEGER NOT NULL
                            REFERENCES Features_Electroforming(id)
                            ON DELETE RESTRICT,

    -- Provenance: points back to the exact sinh-fit result row
    source_ivnl_sinh_id INTEGER NOT NULL
                            REFERENCES Features_IV_nonlinearity_sinh(id)
                            ON DELETE RESTRICT,

    -- Optional mirror of source status for convenience
    -- Expected: 'OK','FIT_PARTIAL','FAIL','SKIP'
    source_status       TEXT,

    -- Ternary states (0 / 0.5 / 1) per branch
    pos_up_state3       REAL,
    pos_down_state3     REAL,
    neg_down_state3     REAL,
    neg_up_state3       REAL,

    -- Strict binary pattern (optional but convenient), order [pos_up,pos_down,neg_down,neg_up]
    -- Example: '0111'
    pattern_bin4        TEXT,

    -- Final EF class label
    -- Recommended values: 'NoEF','PoEF','NeEF','EF','UNCERTAIN','OTHER','NO_DATA'
    ef_class            TEXT,

    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    note                TEXT,

    UNIQUE(ef_id, source_ivnl_sinh_id),

    CHECK (source_status IN ('OK','FIT_PARTIAL','FAIL','SKIP') OR source_status IS NULL),

    CHECK (pos_up_state3   IN (0,0.5,1) OR pos_up_state3   IS NULL),
    CHECK (pos_down_state3 IN (0,0.5,1) OR pos_down_state3 IS NULL),
    CHECK (neg_down_state3 IN (0,0.5,1) OR neg_down_state3 IS NULL),
    CHECK (neg_up_state3   IN (0,0.5,1) OR neg_up_state3   IS NULL),

    CHECK (pattern_bin4 IS NULL OR (length(pattern_bin4)=4 AND pattern_bin4 GLOB '[01][01][01][01]')),

    CHECK (ef_class IN ('NoEF','PoEF','NeEF','EF','UNCERTAIN','OTHER','NO_DATA') OR ef_class IS NULL)
);

-- table: Features_IV_nonlinearity
CREATE TABLE Features_IV_nonlinearity (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Method/model identifier (similar spirit to Experiment.function_type)
    -- Examples: 'sinh', 'cosh', 'poly', ...
    model_type    TEXT NOT NULL,

    -- Fitting voltage window (read window), e.g. 0.5 means use |V| <= 0.5 V
    v_fit_max_V   REAL NOT NULL,

    -- Optional reference DOI for the method/model choice
    doi           TEXT,

    -- When this configuration record is created
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),

    -- Free-form note (optional). Use for human traceability, not for machine logic.
    note          TEXT,

    -- CHECK #1: v_fit_max_V must be positive (window must be meaningful)
    CHECK (v_fit_max_V > 0),

    -- CHECK #2: model_type should not be empty/whitespace (avoid accidental blank types)
    CHECK (length(trim(model_type)) > 0)
);

-- table: Features_IV_nonlinearity_sinh
CREATE TABLE "Features_IV_nonlinearity_sinh" (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Link to configuration definition (model + parameters)
    ivnl_id         INTEGER NOT NULL
                        REFERENCES Features_IV_nonlinearity(id)
                        ON DELETE RESTRICT,  -- 防止误删“配置”导致结果悬空

    sinh_config_id  INTEGER NOT NULL
                        REFERENCES Features_IV_nonlinearity_sinh_config(id)
                        ON DELETE RESTRICT,

    -- Link to the experiment this result belongs to
    experiment_id   INTEGER NOT NULL
                        REFERENCES Experiment(id)
                        ON DELETE RESTRICT,  -- 防止误删 experiment 造成孤儿记录

    -- -------------------------
    -- Branch definitions (within |V| <= v_fit_max_V):
    --   pos_up   : 0 -> +Vfit
    --   pos_down : +Vfit -> 0
    --   neg_down : 0 -> -Vfit
    --   neg_up   : -Vfit -> 0
    -- -------------------------

    -- pos_up
    pos_up_a        REAL,
    pos_up_b        REAL,
    pos_up_r2_raw   REAL,      -- RAW r2; keep raw (no clamp/binarize) to avoid information loss
    pos_up_npts     INTEGER,   -- number of points used in fit
    pos_up_comp_hit INTEGER,   -- 0/1: compliance reached within FIT WINDOW

    -- pos_down
    pos_down_a        REAL,
    pos_down_b        REAL,
    pos_down_r2_raw   REAL,
    pos_down_npts     INTEGER,
    pos_down_comp_hit INTEGER,

    -- neg_down
    neg_down_a        REAL,
    neg_down_b        REAL,
    neg_down_r2_raw   REAL,
    neg_down_npts     INTEGER,
    neg_down_comp_hit INTEGER,

    -- neg_up
    neg_up_a        REAL,
    neg_up_b        REAL,
    neg_up_r2_raw   REAL,
    neg_up_npts     INTEGER,
    neg_up_comp_hit INTEGER,

    -- --------------------------------------------------------
    -- Audit-only fields (optional but recommended):
    -- status meaning is STRICTLY about "feature availability completeness", NOT physical meaning:
    --   OK         : all 4 branches produced usable raw features
    --   FIT_PARTIAL: only some branches produced features (e.g. insufficient points in others)
    --   FAIL       : no usable features produced (all branches failed / invalid)
    --   SKIP       : intentionally skipped before fitting (filtering, not CT, etc.)
    --
    -- note: short human-readable reason, e.g. "too_few_points: neg_up"
    -- --------------------------------------------------------
    status          TEXT,
    note            TEXT,

    -- UNIQUE #1: for a given configuration (ivnl_id), each experiment has at most one result row
    UNIQUE(ivnl_id, sinh_config_id, experiment_id),

    -- CHECK #3: comp_hit must be 0/1 or NULL
    -- Purpose: prevent accidental insertion of weird values (e.g. True/False, 2, -1).
    CHECK (pos_up_comp_hit   IN (0,1) OR pos_up_comp_hit   IS NULL),
    CHECK (pos_down_comp_hit IN (0,1) OR pos_down_comp_hit IS NULL),
    CHECK (neg_down_comp_hit IN (0,1) OR neg_down_comp_hit IS NULL),
    CHECK (neg_up_comp_hit   IN (0,1) OR neg_up_comp_hit   IS NULL),

    -- CHECK #4: npts must be non-negative or NULL
    -- Purpose: npts is a count; negative implies a write/parse bug.
    -- NULL is allowed to represent "not fitted / no valid points".
    CHECK (pos_up_npts   >= 0 OR pos_up_npts   IS NULL),
    CHECK (pos_down_npts >= 0 OR pos_down_npts IS NULL),
    CHECK (neg_down_npts >= 0 OR neg_down_npts IS NULL),
    CHECK (neg_up_npts   >= 0 OR neg_up_npts   IS NULL),

    -- CHECK #5 (optional but helpful): constrain status to a small enum if provided
    -- Purpose: avoid inconsistent strings ('Ok','okay','PART') that break filtering.
    CHECK (status IN ('OK','FIT_PARTIAL','FAIL','SKIP') OR status IS NULL)
);

-- table: Features_IV_nonlinearity_sinh_config
CREATE TABLE Features_IV_nonlinearity_sinh_config (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Fit parameters (sinh)
    fit_loss                TEXT NOT NULL,     -- e.g. 'soft_l1'
    fit_f_scale             REAL NOT NULL,     -- e.g. 0.1
    min_points_per_branch   INTEGER NOT NULL,  -- e.g. 5
    max_points_per_branch   INTEGER,           -- NULL = no cap

    -- Compliance hit detection parameters (cutoff itself is per experiment; these are detection settings)
    comp_rel_tol            REAL,              -- e.g. 0.01
    comp_abs_tol_uA         REAL,              -- e.g. 0.0
    comp_min_points         INTEGER,           -- e.g. 2

    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    note                    TEXT,

    -- CHECKs: stop nonsense values early
    CHECK (length(trim(fit_loss)) > 0),
    CHECK (fit_f_scale > 0),
    CHECK (min_points_per_branch >= 0),
    CHECK (max_points_per_branch IS NULL OR max_points_per_branch >= 0),
    CHECK (comp_rel_tol IS NULL OR (comp_rel_tol >= 0 AND comp_rel_tol <= 1)),
    CHECK (comp_abs_tol_uA IS NULL OR comp_abs_tol_uA >= 0),
    CHECK (comp_min_points IS NULL OR comp_min_points >= 1)
);

-- table: Features_RS_switching
CREATE TABLE Features_RS_switching (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doi         TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT
);

-- table: Features_RS_switching_rate_cal_config
CREATE TABLE Features_RS_switching_rate_cal_config (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,

    rs_id       INTEGER NOT NULL
        REFERENCES Features_RS_switching(id)
        ON DELETE RESTRICT,

    block_kind  TEXT NOT NULL
        CHECK (block_kind IN ('switching','volatility')),

    window_n    INTEGER NOT NULL
        CHECK (window_n >= 1),

    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT,

    UNIQUE (rs_id, block_kind, window_n)
);

-- table: Features_RS_switching_rate_cal_result
CREATE TABLE Features_RS_switching_rate_cal_result (
    config_id   INTEGER NOT NULL
        REFERENCES Features_RS_switching_rate_cal_config(id)
        ON DELETE RESTRICT,

    experimental_detail_id INTEGER NOT NULL
        REFERENCES Experimental_Detail(id)
        ON DELETE RESTRICT,

    mean_y_ohm     REAL,
    mu_DR_ohm      REAL,
    sigma_corr_ohm REAL,

    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT,

    PRIMARY KEY (config_id, experimental_detail_id)
) WITHOUT ROWID;

-- table: Features_Ron_Roff
CREATE TABLE Features_Ron_Roff (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Method tag for extensibility
    -- Example: 'ron_roff_from_sinh'
    method_type      TEXT NOT NULL,

    -- Fixed read voltage used to evaluate I(V) and compute Ron/Roff
    read_voltage_V   REAL NOT NULL,

    -- Minimum acceptable r2_raw for a branch to be considered eligible
    -- (Eligibility + reason is recorded in the detail table via status/reason.)
    minimum_r2       REAL NOT NULL,

    -- DOI / reference for this derived-feature definition
    -- NOTE: doi is NOT ignored in de-dup.
    doi              TEXT NOT NULL,

    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    note             TEXT,

    -- sanity checks
    CHECK (length(trim(method_type)) > 0),
    CHECK (read_voltage_V > 0),
    CHECK (minimum_r2 >= 0 AND minimum_r2 <= 1),
    CHECK (length(trim(doi)) > 0)
);

-- table: Features_Ron_Roff_sinh
CREATE TABLE Features_Ron_Roff_sinh (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,

    ronroff_id           INTEGER NOT NULL
                             REFERENCES Features_Ron_Roff(id)
                             ON DELETE RESTRICT,

    source_ivnl_sinh_id  INTEGER NOT NULL
                             REFERENCES Features_IV_nonlinearity_sinh(id)
                             ON DELETE RESTRICT,

    -- status（列级 CHECK，OK）
    pos_status           TEXT CHECK (pos_status IN ('OK','PARTIAL','FAIL') OR pos_status IS NULL),
    neg_status           TEXT CHECK (neg_status IN ('OK','PARTIAL','FAIL') OR neg_status IS NULL),

    pos_fail_reason      TEXT,
    neg_fail_reason      TEXT,

    pos_ron_ohm          REAL,
    pos_roff_ohm         REAL,
    neg_ron_ohm          REAL,
    neg_roff_ohm         REAL,

    -- branch（改成列级 CHECK，关键修复点）
    pos_ron_branch       TEXT CHECK (pos_ron_branch  IN ('pos_up','pos_down') OR pos_ron_branch  IS NULL),
    pos_roff_branch      TEXT CHECK (pos_roff_branch IN ('pos_up','pos_down') OR pos_roff_branch IS NULL),
    neg_ron_branch       TEXT CHECK (neg_ron_branch  IN ('neg_down','neg_up') OR neg_ron_branch  IS NULL),
    neg_roff_branch      TEXT CHECK (neg_roff_branch IN ('neg_down','neg_up') OR neg_roff_branch IS NULL),

    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    note                 TEXT,

    UNIQUE(ronroff_id, source_ivnl_sinh_id),

    CHECK (pos_ron_ohm  > 0 OR pos_ron_ohm  IS NULL),
    CHECK (pos_roff_ohm > 0 OR pos_roff_ohm IS NULL),
    CHECK (neg_ron_ohm  > 0 OR neg_ron_ohm  IS NULL),
    CHECK (neg_roff_ohm > 0 OR neg_roff_ohm IS NULL),

    CHECK (
        pos_status IS NULL
        OR (
            pos_status = 'OK'
            AND pos_ron_ohm IS NOT NULL
            AND pos_roff_ohm IS NOT NULL
            AND pos_roff_ohm > pos_ron_ohm
            AND pos_ron_branch IS NOT NULL
            AND pos_roff_branch IS NOT NULL
            AND pos_fail_reason IS NULL
        )
        OR (
            pos_status IN ('PARTIAL','FAIL')
            AND pos_ron_ohm IS NULL
            AND pos_roff_ohm IS NULL
            AND pos_ron_branch IS NULL
            AND pos_roff_branch IS NULL
        )
    ),

    CHECK (
        neg_status IS NULL
        OR (
            neg_status = 'OK'
            AND neg_ron_ohm IS NOT NULL
            AND neg_roff_ohm IS NOT NULL
            AND neg_roff_ohm > neg_ron_ohm
            AND neg_ron_branch IS NOT NULL
            AND neg_roff_branch IS NOT NULL
            AND neg_fail_reason IS NULL
        )
        OR (
            neg_status IN ('PARTIAL','FAIL')
            AND neg_ron_ohm IS NULL
            AND neg_roff_ohm IS NULL
            AND neg_ron_branch IS NULL
            AND neg_roff_branch IS NULL
        )
    )
);

-- table: Features_Switching_Volatility_Delta_config
CREATE TABLE "Features_Switching_Volatility_Delta_config" (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,

    source_function_type    TEXT NOT NULL DEFAULT 'ParameterFit_interRetention',
    block_pair              TEXT NOT NULL DEFAULT 'switching_then_volatility'
        CHECK (block_pair IN ('switching_then_volatility', 'switching_only')),
    window_n                INTEGER NOT NULL
        CHECK (window_n >= 1),

    state_stat_type         TEXT NOT NULL
        CHECK (state_stat_type IN ('mean', 'median', 'trimmed_mean')),
    state_trim_q            REAL NOT NULL DEFAULT 0.0
        CHECK (state_trim_q >= 0.0 AND state_trim_q < 0.5),

    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    note                    TEXT,

    CHECK (length(trim(source_function_type)) > 0),

    UNIQUE (
        source_function_type, block_pair, window_n,
        state_stat_type, state_trim_q
    )
);

-- table: Features_Switching_Volatility_Delta_result
CREATE TABLE "Features_Switching_Volatility_Delta_result" (
    config_id               INTEGER NOT NULL
        REFERENCES Features_Switching_Volatility_Delta_config(id)
        ON DELETE RESTRICT,

    experiment_id           INTEGER NOT NULL
        REFERENCES Experiment(id)
        ON DELETE RESTRICT,

    segment_idx             INTEGER NOT NULL
        CHECK (segment_idx >= 1),

    -- traceability to raw detail ranges
    sw_detail_id_start      INTEGER NOT NULL
        REFERENCES Experimental_Detail(id) ON DELETE RESTRICT,
    vol_detail_id_start     INTEGER
        REFERENCES Experimental_Detail(id) ON DELETE RESTRICT,

    -- base states
    sw_start_stat_ohm       REAL,
    sw_end_stat_ohm         REAL,
    vol_start_stat_ohm      REAL,
    vol_end_stat_ohm        REAL,

    -- derived metrics
    sw_delta_ohm            REAL,
    vol_delta_ohm           REAL,

    -- representative switching segment voltage
    sw_segment_voltage_V    REAL,

    calc_ok                 INTEGER NOT NULL DEFAULT 1 CHECK (calc_ok IN (0,1)),
    reject_code             INTEGER NOT NULL DEFAULT 0 CHECK (reject_code IN (0,1,2,3,4)),

    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    note                    TEXT,

    PRIMARY KEY (config_id, experiment_id, segment_idx),

    CHECK (
        calc_ok = 0 OR (
            sw_start_stat_ohm IS NOT NULL AND
            sw_end_stat_ohm IS NOT NULL
        )
    )
) WITHOUT ROWID;

-- table: Features_Volatility
CREATE TABLE Features_Volatility (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Method identifier (human + machine readable)
    -- Example: 'giotis2020_partII_stretched_exponential'
    method_type TEXT NOT NULL,

    -- Reference DOI for this methodology
    doi         TEXT NOT NULL,

    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    note        TEXT,

    CHECK (length(trim(method_type)) > 0),
    CHECK (length(trim(doi)) > 0)
);

-- table: Features_Volatility_stexp_config
CREATE TABLE Features_Volatility_stexp_config (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,

    vol_id      INTEGER NOT NULL
        REFERENCES Features_Volatility(id)
        ON DELETE RESTRICT,

    -- Data source semantics:
    -- e.g. 'ParameterFit_interRetention' or 'VolatilityRead'
    source_function_type TEXT NOT NULL,

    -- Which block you extracted (for interRetention it's typically 'volatility')
    block_kind  TEXT NOT NULL
        CHECK (block_kind IN ('volatility','switching')),

    -- Decontamination thresholds from the paper:
    -- reject if (tau_s > T_window_s) OR (r2 < r2_min)
    r2_min              REAL NOT NULL DEFAULT 0.1,
    reject_tau_gt_T     INTEGER NOT NULL DEFAULT 1,   -- 1: enforce tau<=T
    tau_T_margin        REAL NOT NULL DEFAULT 1.0,    -- compare tau > (T * margin)

    -- Optional knobs (keep for traceability; can be NULL):
    -- if you later decide to follow paper-specific heuristics like N>100 for tau modeling
    min_N_for_accept    INTEGER,                      -- e.g. 101, or NULL to disable
    fit_engine          TEXT,                         -- e.g. 'scipy_curve_fit'
    fit_loss            TEXT,                         -- if you use robust loss
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    note                TEXT,

    UNIQUE (vol_id, source_function_type, block_kind, r2_min, reject_tau_gt_T, tau_T_margin, min_N_for_accept),

    CHECK (r2_min >= -1 AND r2_min <= 1),
    CHECK (reject_tau_gt_T IN (0,1)),
    CHECK (tau_T_margin > 0),
    CHECK (min_N_for_accept IS NULL OR min_N_for_accept >= 1),
    CHECK (length(trim(source_function_type)) > 0)
);

-- table: Features_Volatility_stexp_result
CREATE TABLE Features_Volatility_stexp_result (
    config_id       INTEGER NOT NULL
        REFERENCES Features_Volatility_stexp_config(id)
        ON DELETE RESTRICT,

    experiment_id   INTEGER NOT NULL
        REFERENCES Experiment(id)
        ON DELETE RESTRICT,

    -- 1-based retention cycle index within this experiment
    cycle_index     INTEGER NOT NULL,

    -- Programming polarity for this cycle (bidirectional modeling)
    program_polarity TEXT
        CHECK (program_polarity IN ('pos','neg') OR program_polarity IS NULL),

    -- Traceability: the exact Experimental_Detail id ranges used (optional but very useful)
    -- switching block range that produced Rstart (optional)
    sw_detail_id_start   INTEGER REFERENCES Experimental_Detail(id) ON DELETE RESTRICT,
    sw_detail_id_end     INTEGER REFERENCES Experimental_Detail(id) ON DELETE RESTRICT,
    -- volatility/read block range used for fitting R(t) (recommended)
    vol_detail_id_start  INTEGER REFERENCES Experimental_Detail(id) ON DELETE RESTRICT,
    vol_detail_id_end    INTEGER REFERENCES Experimental_Detail(id) ON DELETE RESTRICT,

    -- Protocol descriptors (needed to build Part-II dependencies)
    N_pulses        INTEGER,        -- number of program pulses used for this cycle
    VP_program_V    REAL,           -- programming amplitude for this cycle

    -- Time axis info (store in seconds to avoid unit ambiguity)
    dt_s            REAL,           -- sampling interval (seconds)
    T_window_s      REAL,           -- total observation window (seconds)

    -- Key states (optional but extremely helpful)
    Rpre_ohm        REAL,           -- prestimulation (paper uses Rpre)
    Rstart_ohm      REAL,           -- at t=0 of read phase (paper uses Rstart)
    Rend_ohm        REAL,           -- at t=T (paper uses Rend)

    -- Stretched exponential parameters: R(t)=alpha*exp(-(t/tau)^beta)+gamma
    alpha_ohm       REAL,
    tau_s           REAL,
    beta            REAL,
    gamma_ohm       REAL,

    -- Fit quality
    r2              REAL,

    -- Decontamination / status
    fit_ok          INTEGER NOT NULL DEFAULT 0,

    -- reject_code suggestion:
    -- 0 OK
    -- 1 FIT_FAIL (solver failed / nan / etc)
    -- 2 R2_LT_TH
    -- 3 TAU_GT_T
    -- 4 TOO_FEW_POINTS
    -- 5 OTHER
    reject_code     INTEGER NOT NULL DEFAULT 5,

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    note            TEXT,

    PRIMARY KEY (config_id, experiment_id, cycle_index),

    CHECK (cycle_index >= 1),
    CHECK (N_pulses IS NULL OR N_pulses >= 0),
    CHECK (dt_s IS NULL OR dt_s > 0),
    CHECK (T_window_s IS NULL OR T_window_s > 0),
    CHECK (fit_ok IN (0,1)),
    CHECK (reject_code IN (0,1,2,3,4,5)),

    -- If fit_ok=1, enforce core fields exist and are sane.
    CHECK (
        fit_ok = 0
        OR (
            alpha_ohm IS NOT NULL
            AND tau_s IS NOT NULL AND tau_s > 0
            AND beta IS NOT NULL AND beta >= 0 AND beta <= 1
            AND gamma_ohm IS NOT NULL
            AND r2 IS NOT NULL
        )
    )
) WITHOUT ROWID;

-- table: Function_CurveTracer
CREATE TABLE Function_CurveTracer (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id               INTEGER NOT NULL
                                    REFERENCES Experiment(id)
                                    ON DELETE CASCADE,

    positive_voltage_max_V      REAL,
    negative_voltage_max_V      REAL,
    voltage_step_V              REAL,
    start_voltage_V             REAL,
    step_width_ms               REAL,
    cycles                      INTEGER,
    interpulse_time_ms          REAL,
    positive_current_cutoff_uA  REAL,
    negative_current_cutoff_uA  REAL,
    halt_and_return             BOOLEAN,
    bias_type                   TEXT,
    iv_span                     TEXT,

    CONSTRAINT uq_fun_curvetracer_experiment UNIQUE (experiment_id)
);

-- table: Function_ParameterFit
CREATE TABLE Function_ParameterFit (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id                   INTEGER NOT NULL
                                        REFERENCES Experiment(id)
                                        ON DELETE CASCADE,

    pulses                          INTEGER,
    pulse_width_us                  REAL,
    bias_interpulse_ms              REAL,
    iv_interpulse_ms                REAL,
    iv_pulse_width_ms               REAL,
    iv_type                         TEXT,
    iv_start_V                      REAL,
    iv_step_V                       REAL,
    run_iv                          BOOLEAN,
    positive_polarity_v_start_V     REAL,
    positive_polarity_v_step_V      REAL,
    positive_polarity_v_stop_V      REAL,
    positive_polarity_iv_stop_V     REAL,
    negative_polarity_v_start_V     REAL,
    negative_polarity_v_step_V      REAL,
    negative_polarity_v_stop_V      REAL,
    negative_polarity_iv_stop_V     REAL,

    CONSTRAINT uq_fun_paramfit_experiment UNIQUE (experiment_id)
);

-- table: Function_ParameterFit_interRetention
CREATE TABLE Function_ParameterFit_interRetention (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id                   INTEGER NOT NULL
                                        REFERENCES Experiment(id)
                                        ON DELETE CASCADE,

    pulses                          INTEGER,
    pulse_width_us                  REAL,
    bias_interpulse_ms              REAL,
    positive_polarity_v_start_V     REAL,
    positive_polarity_v_step_V      REAL,
    positive_polarity_v_stop_V      REAL,
    negative_polarity_v_start_V     REAL,
    negative_polarity_v_step_V      REAL,
    negative_polarity_v_stop_V      REAL,
    interForming_readings           INTEGER,
    interForming_voltage_V          REAL,
    interForming_interval_ms        REAL,

    CONSTRAINT uq_fun_paramfit_ret_experiment UNIQUE (experiment_id)
);

-- table: Layer
CREATE TABLE Layer (
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
