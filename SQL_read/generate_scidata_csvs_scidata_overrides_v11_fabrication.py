import re
import csv
import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional

# ------------------------------------------------------------
# Simple schema.sql -> Scientific Data CSV generator
# ------------------------------------------------------------
# What this script does well:
# - parses CREATE TABLE blocks from SQLite-style schema.sql
# - extracts columns, basic SQL types, NOT NULL, PK, UNIQUE, CHECK, REFERENCES, ON DELETE
# - extracts foreign-key relationships from inline REFERENCES clauses
# - emits 4 CSVs + 1 README skeleton
#
# What this script cannot infer perfectly from SQL alone:
# - polished manuscript-ready English descriptions
# - pipeline-stage and table-block labels that follow your paper wording
# - units for columns when they are not obvious from the column name
# - which QC rules are "selected" for reader-facing presentation
#
# Therefore the intended workflow is:
#   schema.sql + optional overrides.json -> regenerated CSVs
# ------------------------------------------------------------

PIPELINE_STAGES_DEFAULT = [
    "Memristor Fabrication",
    "Wafer Mapping",
    "Electrical Characterization",
    "Memristor Feature Extraction and Modeling",
]

README_TEXT = """Scientific Data CSV package generated from schema.sql

Files
-----
1. schema_table_overview_scidata_auto.csv
   Table-level overview.
2. schema_column_dictionary_scidata_auto.csv
   Column-level data dictionary. Descriptions are left blank unless provided through overrides.json.
3. schema_core_relationships_scidata_auto.csv
   Core foreign-key relationships.
4. schema_selected_qc_rules_scidata_auto.csv
   Selected reader-facing QC / integrity rules.
5. schema_unit_suffix_conventions_auto.csv
   Reserved unit suffix list and naming guidance.

How this was generated
----------------------
These CSVs were generated from schema.sql, optionally combined with overrides.json.
The SQL file is treated as the structural source of truth for table names, column names,
primary keys, foreign-key relationships, ON DELETE rules, and machine-detectable QC-like rules.

Important limitation
--------------------
SQL alone cannot fully provide manuscript-ready plain-English descriptions, pipeline-stage labels,
all units, or the final curated subset of reader-facing QC rules. In this script, column descriptions
are intentionally left blank unless they are provided through overrides.json.

Column glossary
---------------
Table overview CSV
- pipeline_stage: manuscript pipeline stage associated with the table.
- table_name: exact SQL table name.
- information_stored: short summary of what the table stores.
- primary_key: primary key column(s).
- relationship_and_qc_note: short note on the most important relationship or QC point.

Column dictionary CSV
- pipeline_stage: manuscript pipeline stage associated with the table containing this column.
- table_name: exact SQL table name.
- column_name: exact SQL column name.
- column_role: role of the column, e.g. primary key, foreign key, identifier, metadata, measurement value, derived value, status flag, configuration parameter.
- data_type: SQL type.
- unit: measurement unit if applicable. Preferred non-physical entries are dimensionless, count, and not applicable.
- required: yes if NOT NULL, otherwise no.
- description: plain-English meaning of the column.
- allowed_values_or_codes: controlled values or codes where applicable.

Core relationships CSV
- from_table: child/referencing table.
- from_column: referencing column in the child table.
- to_table: parent/referenced table.
- to_column: referenced column in the parent table.
- relationship_summary: short structural summary of the link.
- on_delete_rule: CASCADE, RESTRICT, SET NULL, NO ACTION, or blank if unspecified.

Selected QC rules CSV
- pipeline_stage: manuscript pipeline stage most relevant to the rule.
- table_name: exact SQL table name.
- column_name: directly affected column, or table_level.
- qc_focus: linkage, uniqueness, allowed values, range check, status consistency, or result completeness.
- rule_definition: short plain-English statement of the rule.
- why_it_matters: why the rule helps preserve validity, interpretability, or reuse.

Unit value glossary
-------------------
- dimensionless: numeric quantity with no physical unit, e.g. ratios, exponents, margins, or R2.
- count: integer count, window size, cycle index, or number of repeated events.
- not applicable: identifiers, categorical labels, flags, codes, timestamps, text, or binary content.

Reserved unit suffix guidance
-----------------------------
See schema_unit_suffix_conventions_auto.csv for the reserved suffix list used for naming review.
Important rule: do not use terminal '_a' as a unit suffix. Reserve '_A' for Ampere only if it is truly needed.

IV nonlinearity glossary
------------------------
- In `Features_IV_nonlinearity_sinh`, branch names follow the fitting-window traversal directions: `pos_up` = `0 -> +Vfit`, `pos_down` = `+Vfit -> 0`, `neg_down` = `0 -> -Vfit`, and `neg_up` = `-Vfit -> 0`.
- `comp_rel_tol` and `comp_abs_tol_uA` are compliance-hit detection parameters, not physical result values.
- Relative tolerance means the measured current may fall slightly below the configured compliance current by a fixed proportion. For example, if compliance = 100 uA and `comp_rel_tol` = 0.01, the relative-tolerance threshold is `100 * (1 - 0.01) = 99 uA`.
- Absolute tolerance means the measured current may fall slightly below the configured compliance current by a fixed absolute amount. For example, if compliance = 100 uA and `comp_abs_tol_uA` = 2, the absolute-tolerance threshold is `100 - 2 = 98 uA`.
- When both are provided, the compliance-hit threshold is the stricter of the two, i.e. `threshold = max(Ic * (1 - rel_tol), Ic - abs_tol)`, where `Ic` is the configured compliance current. In the example above, the threshold is `max(99 uA, 98 uA) = 99 uA`.
- `comp_min_points` is the minimum number of qualifying points required to mark a branch as having reached compliance within the fitting window.
- In `Features_IV_nonlinearity_sinh`, `status` describes result completeness of the four-branch fitting outcome and does not encode device physics.

Electroforming glossary
-----------------------
- In `Features_Electroforming_sinh`, the four fitting branches are interpreted in fixed order: `pos_up`, `pos_down`, `neg_down`, `neg_up`.
- Branch-level electroforming states use a three-level encoding: `1.0` = stable, `0.5` = unsure, and `0.0` = unstable.
- `pattern_bin4` is a derived four-position binary pattern generated from the four branch-level three-level states. Only stable branches (`1.0`) are encoded as `1`; unsure and unstable branches (`0.5` and `0.0`) are encoded as `0`.
- `ef_class` is the final experiment-level electroforming class derived from the ordered branch-state interpretation together with the derived binary pattern.
- `electroform_voltage_V` is a rule-based representative electroforming voltage. When a qualifying compliance-hit event is found, it stores the first qualifying compliance-hit voltage; otherwise it stores the voltage associated with the selected max-drop event.


Switching workflow note
-----------------------
- In the current batch workflow, switching-rate extraction may be applied only to experiments whose nearest previous CurveTracer experiment on the same device has electroforming class `NeEF`, `PoEF`, or `EF`.
- This nearest-previous-CT rule is a workflow-level experiment-inclusion rule used to confirm that the device has already electroformed before switching features are extracted. It is not itself a feature-table field.

Switching–volatility delta glossary
--------------------------------
- These tables store simple segment-level summaries rather than fitted model parameters.
- For each segment, the beginning of the segment is summarised from the first `window_n` valid resistance points, and the end of the segment is summarised from the last `window_n` valid resistance points.
- The summary statistic is chosen by `state_stat_type`, using `mean`, `median`, or `trimmed_mean`.
- `sw_delta_ohm` is calculated as `sw_end_stat_ohm - sw_start_stat_ohm`.
- `vol_delta_ohm` is calculated as `vol_end_stat_ohm - vol_start_stat_ohm` when a paired volatility segment exists.
- `block_pair = switching_only` means the result row stores only switching-segment summaries.
- `block_pair = switching_then_volatility` means the result row stores both switching-segment and following volatility-segment summaries for the same segment index.
- `calc_ok` and `reject_code` describe whether the segment-level calculation succeeded; they do not encode the physical device state.

Volatility glossary
-------------------
- In the current workflow, volatility fitting is performed only on volatility/read segments extracted from `ParameterFit_interRetention` experiments.
- `Features_Volatility` is a method-level table and is intentionally general; it records which volatility-analysis methodology is being used.
- `Features_Volatility_stexp_config` and `Features_Volatility_stexp_result` correspond to the current stretched-exponential implementation used for cycle-level volatility fitting.
- The fitted model is `R(t) = alpha * exp(-(t/tau)^beta) + gamma`.
- `reject_tau_gt_T` and `tau_T_margin` are fit-acceptance rule parameters, not physical result values. When the rule is enabled, rejection is based on whether `tau_s > T_window_s * tau_T_margin`.
- `fit_ok` and `reject_code` describe result validity for a fitted cycle; they do not encode the physical device state.
- In the current batch workflow, volatility extraction may be applied only to experiments whose nearest previous CurveTracer experiment on the same device has electroforming class `NeEF`, `PoEF`, or `EF`. This nearest-previous-CT rule is a workflow-level experiment-inclusion rule.

Ron/Roff glossary
------------------
- Ron/Roff values are derived from stored branch-wise sinh fits rather than from a single raw resistance point.
- The fitted current is evaluated at the fixed read voltage `read_voltage_V` using `I(V)=a*sinh(bV)`.
- For positive polarity, the candidate branches are `pos_up` and `pos_down`; for negative polarity, they are `neg_down` and `neg_up`.
- Within one polarity, the branch with larger fitted current magnitude `|I_fit|` at the fixed read voltage is assigned as Ron, and the branch with smaller fitted current magnitude is assigned as Roff.
- A branch is considered eligible only when its stored raw fit quality meets `minimum_r2` and the fitted current at the fixed read voltage is finite and non-zero.
- In `Features_Ron_Roff_sinh`, numerical Ron/Roff values and selected branch names are stored only when the corresponding polarity status is `OK`; `PARTIAL` and `FAIL` rows keep these fields null.

Fabrication glossary
--------------------
- In the fabrication block, `Layer` defines one concrete stack element in a recipe, while the matching `Tool_*` table stores how that layer was fabricated.
- A tool family such as ALD or sputtering can therefore appear across many different layers and recipes, but each stored `Tool_*` row describes the process definition of one specific layer.
- `Tool_Attachment` preserves the original native recipe file as a binary artifact for provenance, while the curated recipe and tool tables remain separately queryable.
- `Tool_ALD_Material_Gas_Cycle_Relation` uses a parent pointer plus explicit sibling order, which is an adjacency-list style structure for preserving nested ALD super-cycles and process order.

ON DELETE glossary
------------------
- CASCADE: deleting the parent row also deletes dependent child rows.
- RESTRICT: deleting the parent row is blocked while dependent child rows still exist.
- SET NULL: deleting the parent row sets the referencing child value to NULL.
- NO ACTION: no automatic delete propagation is applied, but referential integrity must still hold.
"""

TABLE_OVERVIEW_HEADERS = [
    "pipeline_stage",
    "table_name",
    "information_stored",
    "primary_key",
    "relationship_and_qc_note",
]

COLUMN_DICT_HEADERS = [
    "pipeline_stage",
    "table_name",
    "column_name",
    "column_role",
    "data_type",
    "unit",
    "required",
    "description",
    "allowed_values_or_codes",
]

REL_HEADERS = [
    "from_table",
    "from_column",
    "to_table",
    "to_column",
    "relationship_summary",
    "on_delete_rule",
]

QC_HEADERS = [
    "pipeline_stage",
    "table_name",
    "column_name",
    "qc_focus",
    "rule_definition",
    "why_it_matters",
]


UNIT_SUFFIX_HEADERS = [
    "suffix",
    "preferred_unit",
    "status",
    "guidance",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def split_top_level_commas(s: str) -> List[str]:
    parts, buf = [], []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif not in_single and not in_double:
            if ch == '(':
                depth += 1
                buf.append(ch)
            elif ch == ')':
                depth -= 1
                buf.append(ch)
            elif ch == ',' and depth == 0:
                parts.append(''.join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        else:
            buf.append(ch)
        i += 1
    if ''.join(buf).strip():
        parts.append(''.join(buf).strip())
    return parts


def strip_inline_comment(line: str) -> str:
    # remove -- comments only when outside quotes
    out = []
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        nxt = line[i+1] if i + 1 < len(line) else ''
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == '-' and nxt == '-' and not in_single and not in_double:
            break
        else:
            out.append(ch)
        i += 1
    return ''.join(out).rstrip()


def clean_sql(sql: str) -> str:
    lines = [strip_inline_comment(line) for line in sql.splitlines()]
    return '\n'.join(lines)



def infer_unit(col: str) -> str:
    """
    Infer unit from the column name using a conservative ruleset.

    Naming policy:
    - reserve explicit unit suffixes such as _V, _uA, _ms, _ohm
    - do NOT use terminal '_a' as a unit suffix, because it clashes with fitted parameter a
    - reserve terminal '_A' for Ampere only when truly needed
    """
    exact_mapping = [
        ("_W_per_cm2", "W/cm2"),
        ("_degC_per_s", "degC/s"),
        ("_nm_per_s", "nm/s"),
        ("_mTorr", "mTorr"),
        ("_degC", "degC"),
        ("_kHz", "kHz"),
        ("_sccm", "sccm"),
        ("_slm", "slm"),
        ("_um2", "um2"),
        ("_ohm", "ohm"),
        ("_uA", "uA"),
        ("_mA", "mA"),
        ("_ms", "ms"),
        ("_us", "us"),
        ("_nm", "nm"),
        ("_mm", "mm"),
        ("_W", "W"),
        ("_V", "V"),
        ("_A", "A"),
        ("_s", "s"),
    ]
    for suffix, unit in sorted(exact_mapping, key=lambda x: -len(x[0])):
        if col.endswith(suffix):
            return unit

    low = col.lower()

    # counts
    count_exact = {
        "cycles",
        "pulses",
        "window_n",
        "window_n",
        "cycle_index",
        "cycle_number",
        "n_pulses",
        "min_n_for_accept",
        "interforming_readings",
        "comp_min_points",
        "min_points_per_branch",
        "max_points_per_branch",
        "position_in_layer",
        "die_number",
        "wordline",
        "bitline",
    }
    if low in count_exact or low.endswith("_count") or low.endswith("_index") or low.endswith("_number") or low.endswith("_npts"):
        return "count"

    # dimensionless numeric quantities
    dimensionless_exact = {
        "r2",
        "r2_min",
        "tau_t_margin",
        "beta",
        "fit_f_scale",
        "comp_rel_tol",
        "state_trim_q",
        "minimum_r2",
        "stable_r2_th",
        "unsure_r2_th",
        "drop_ratio",
    }
    if low in dimensionless_exact or low.endswith("_r2") or low.endswith("_ratio"):
        return "dimensionless"

    return "not applicable"


def review_column_name(table_name: str, col_name: str) -> Dict[str, str]:
    """
    Return review notes for the current column name.
    Leave both fields blank when no naming issue is detected.
    """
    specific = {
        ("Experimental_Detail", "resistance"): {
            "column_name_issue": "Unit is not encoded in the column name; consider explicit resistance suffix.",
            "suggested_column_name": "resistance_ohm",
        },
        ("Experimental_Detail", "readvoltage"): {
            "column_name_issue": "Unit is not encoded and underscore style is inconsistent; consider explicit voltage suffix.",
            "suggested_column_name": "read_voltage_V",
        },
        ("Features_Electroforming_max_drop", "v_electroform_volts"): {
            "column_name_issue": "Nonstandard voltage suffix 'volts'; prefer the short schema-wide suffix '_V'.",
            "suggested_column_name": "electroform_voltage_V",
        },
        ("Features_RS_switching_rate_cal_config", "window_N"): {
            "column_name_issue": "Uppercase/lowercase N usage is inconsistent with 'window_n' used elsewhere; review naming normalization.",
            "suggested_column_name": "window_n",
        },
    }
    if (table_name, col_name) in specific:
        return specific[(table_name, col_name)]

    low = col_name.lower()
    if low.endswith("_volts"):
        return {
            "column_name_issue": "Nonstandard voltage suffix 'volts'; prefer the short suffix '_V'.",
            "suggested_column_name": re.sub(r"_volts$", "_V", col_name, flags=re.I),
        }

    return {
        "column_name_issue": "",
        "suggested_column_name": "",
    }



def review_unit_issue(table_name: str, col_name: str, inferred_unit: str, table: "Table") -> Dict[str, str]:
    """
    Return review notes for unit inference.
    Leave both fields blank when no unit issue is detected.
    """
    specific = {
        ("Experimental_Detail", "resistance"): {
            "unit_issue": "Column stores resistance, but the current suffix-based unit inference cannot detect ohm from this name.",
            "suggested_unit": "ohm",
        },
        ("Experimental_Detail", "readvoltage"): {
            "unit_issue": "Column stores read voltage, but the current suffix-based unit inference cannot detect V from this name.",
            "suggested_unit": "V",
        },
        ("Features_Electroforming_max_drop", "v_electroform_volts"): {
            "unit_issue": "Voltage column uses the suffix 'volts', which is not covered by the reserved suffix list.",
            "suggested_unit": "V",
        },
        ("Tool_Sputter", "gas_flow_rate_sccm"): {
            "unit_issue": "The suffix 'sccm' is a valid flow unit and should be captured explicitly by the unit rules.",
            "suggested_unit": "sccm",
        },
        ("Tool_Sputter", "plasma_strike_gas_flow_rate_sccm"): {
            "unit_issue": "The suffix 'sccm' is a valid flow unit and should be captured explicitly by the unit rules.",
            "suggested_unit": "sccm",
        },
        ("Tool_E_beam", "deposition_rate_nm_per_s"): {
            "unit_issue": "Compound unit column; use the explicit unit nm/s rather than interpreting only the terminal '_s'.",
            "suggested_unit": "nm/s",
        },
        ("Tool_Furnace", "ramping_rate_degC_per_s"): {
            "unit_issue": "Compound unit column; use the explicit unit degC/s rather than interpreting only the terminal '_s'.",
            "suggested_unit": "degC/s",
        },
        ("Features_Volatility_stexp_config", "tau_T_margin"): {
            "unit_issue": "",
            "suggested_unit": "dimensionless",
        },
        ("Features_Volatility_stexp_result", "beta"): {
            "unit_issue": "",
            "suggested_unit": "dimensionless",
        },
        ("Features_Volatility_stexp_result", "r2"): {
            "unit_issue": "",
            "suggested_unit": "dimensionless",
        },
        ("Features_Volatility_stexp_result", "N_pulses"): {
            "unit_issue": "",
            "suggested_unit": "count",
        },
        ("Features_Volatility_stexp_result", "cycle_index"): {
            "unit_issue": "",
            "suggested_unit": "count",
        },
    }
    if (table_name, col_name) in specific:
        return specific[(table_name, col_name)]

    low = col_name.lower()

    # Companion *_unit columns: the value column is unit-bearing, but the unit is stored separately.
    if low.endswith("_value"):
        sibling = col_name[:-5] + "_unit"
        if any(c.name == sibling for c in table.columns):
            return {
                "unit_issue": "Unit is stored in a companion '*_unit' column rather than being directly inferable from this column name.",
                "suggested_unit": f"see {sibling}",
            }

    # Fitted sinh parameter a-columns: terminal '_a' must not be treated as Ampere.
    if table_name == "Features_IV_nonlinearity_sinh" and re.search(r"_a$", col_name, flags=re.I):
        return {
            "unit_issue": "This is a fitted parameter column; terminal '_a' should not be treated as Ampere.",
            "suggested_unit": "not applicable",
        }

    # Legacy interval/time names without explicit suffix should be reviewed manually.
    if low in {"interforming_interval", "readtag", "readvoltage"} or (("interval" in low or "window" in low) and inferred_unit == "not applicable"):
        return {
            "unit_issue": "Time or interval-like name without an explicit reserved unit suffix; review manually.",
            "suggested_unit": "",
        }

    return {
        "unit_issue": "",
        "suggested_unit": "",
    }




def build_unit_suffix_rows() -> List[Dict[str, str]]:
    return [
        {"suffix": "_V", "preferred_unit": "V", "status": "reserved", "guidance": "Use for voltage-valued columns."},
        {"suffix": "_uA", "preferred_unit": "uA", "status": "reserved", "guidance": "Use for microampere-valued current columns."},
        {"suffix": "_mA", "preferred_unit": "mA", "status": "reserved", "guidance": "Use for milliampere-valued current columns."},
        {"suffix": "_A", "preferred_unit": "A", "status": "reserved", "guidance": "Use for Ampere only if it is truly needed. Do not replace fitted parameter names with this suffix automatically."},
        {"suffix": "_a", "preferred_unit": "", "status": "avoid", "guidance": "Do not use as a unit suffix. It clashes with fitted parameter a in expressions such as I = a sinh(bV)."},
        {"suffix": "_ms", "preferred_unit": "ms", "status": "reserved", "guidance": "Use for milliseconds."},
        {"suffix": "_us", "preferred_unit": "us", "status": "reserved", "guidance": "Use for microseconds."},
        {"suffix": "_s", "preferred_unit": "s", "status": "reserved", "guidance": "Use for seconds."},
        {"suffix": "_ohm", "preferred_unit": "ohm", "status": "reserved", "guidance": "Use for resistance-valued columns."},
        {"suffix": "_nm", "preferred_unit": "nm", "status": "reserved", "guidance": "Use for nanometres."},
        {"suffix": "_mm", "preferred_unit": "mm", "status": "reserved", "guidance": "Use for millimetres."},
        {"suffix": "_um2", "preferred_unit": "um2", "status": "reserved", "guidance": "Use for square micrometres."},
        {"suffix": "_degC", "preferred_unit": "degC", "status": "reserved", "guidance": "Use for temperature in degrees Celsius."},
        {"suffix": "_mTorr", "preferred_unit": "mTorr", "status": "reserved", "guidance": "Use for pressure in millitorr."},
        {"suffix": "_kHz", "preferred_unit": "kHz", "status": "reserved", "guidance": "Use for kilohertz."},
        {"suffix": "_W", "preferred_unit": "W", "status": "reserved", "guidance": "Use for watts."},
        {"suffix": "_W_per_cm2", "preferred_unit": "W/cm2", "status": "reserved", "guidance": "Use for power density in W/cm2."},
        {"suffix": "_sccm", "preferred_unit": "sccm", "status": "reserved", "guidance": "Use for standard cubic centimetres per minute."},
        {"suffix": "_slm", "preferred_unit": "slm", "status": "reserved", "guidance": "Use for standard litres per minute."},
        {"suffix": "_nm_per_s", "preferred_unit": "nm/s", "status": "reserved", "guidance": "Use for deposition rate in nm/s."},
        {"suffix": "_degC_per_s", "preferred_unit": "degC/s", "status": "reserved", "guidance": "Use for temperature ramping rate in degC/s."},
        {"suffix": "dimensionless", "preferred_unit": "dimensionless", "status": "value", "guidance": "Use in the unit column for numeric quantities with no physical unit, such as ratios, exponents, margins, or R2."},
        {"suffix": "count", "preferred_unit": "count", "status": "value", "guidance": "Use in the unit column for counts, indexes, or window sizes."},
        {"suffix": "not applicable", "preferred_unit": "not applicable", "status": "value", "guidance": "Use in the unit column for identifiers, flags, codes, categories, timestamps, text, or BLOB content."},
    ]


def infer_column_role(col: str, is_pk: bool, has_fk: bool) -> str:
    low = col.lower()
    if is_pk:
        return "primary key"
    if has_fk:
        return "foreign key"
    if low == "id":
        return "identifier"
    if low.endswith("_id"):
        return "identifier"
    if low in {"note", "notes", "description"}:
        return "text note"
    if low in {"status", "reject_code", "fit_ok", "calc_ok"} or low.endswith("_status"):
        return "status flag"
    if any(k in low for k in ["config", "method_type", "function_type", "fit_loss", "bias_type", "iv_span"]):
        return "configuration parameter"
    if any(k in low for k in ["resistance", "current", "voltage", "amplitude", "pulse_width", "tau", "beta", "gamma", "alpha", "r2", "drop_ratio", "ron", "roff"]):
        return "measurement value" if "feature" not in low else "derived value"
    if low in {"created_at", "created", "user_name", "experiment_name", "file_name", "content_hash"}:
        return "metadata"
    return "metadata"


def infer_table_stage(table_name: str, overrides: Dict) -> str:
    if table_name in overrides.get("tables", {}):
        t = overrides["tables"][table_name]
        if "pipeline_stage" in t:
            return t["pipeline_stage"]

    if table_name.startswith("Tool_") or table_name in {"Recipe", "Layer", "Wafer"}:
        return "Memristor Fabrication"
    if table_name in {"Die", "Subdie", "Device"}:
        return "Wafer Mapping"
    if table_name in {
        "Experiment",
        "Experimental_Detail",
        "Function_Config",
        "Function_CurveTracer",
        "Function_ParameterFit",
        "Function_ParameterFit_interRetention",
    }:
        return "Electrical Characterization"
    if table_name.startswith("Features_"):
        return "Memristor Feature Extraction and Modeling"
    return ""


def default_table_description(table_name: str) -> str:
    name = table_name
    desc_map = {
        "Recipe": "Stores one curated fabrication recipe or stack definition.",
        "Layer": "Stores one logical stack layer within a fabrication recipe.",
        "Wafer": "Stores one fabricated wafer linked to a recipe.",
        "Die": "Defines die-level spatial positions within a wafer.",
        "Subdie": "Stores subdie-level positions within a die.",
        "Device": "Defines the uniquely addressable device within a subdie.",
        "Experiment": "Registers one executed electrical experiment on one device.",
        "Experimental_Detail": "Stores point-level or pulse-level raw measurement records for one experiment.",
        "Function_Config": "Top-level registry of measurement function type before linking to a function-specific parameter table.",
        "Function_CurveTracer": "Stores CurveTracer parameter settings for one function configuration.",
        "Function_ParameterFit": "Stores ParameterFit pulse-programming settings for one function configuration.",
        "Function_ParameterFit_interRetention": "Stores ParameterFit_interRetention settings including interleaved read parameters.",
        "Tool_Attachment": "Stores the original native recipe file as a BLOB with file metadata and hash.",
    }
    if name in desc_map:
        return desc_map[name]
    if name.startswith("Tool_"):
        return f"Stores tool- or process-specific fabrication metadata for {name.replace('Tool_', '')}."
    if name.startswith("Features_"):
        return f"Stores feature-related information for {name}."
    return f"Stores records for {name}."


def default_column_description(table: str, col: str) -> str:
    low = col.lower()
    if low == "id":
        return f"Surrogate primary key for the {table} table."
    if low.endswith("_id"):
        target = col[:-3]
        return f"Identifier linking this record to the related {target} record."
    if low == "created_at":
        return "Timestamp indicating when the record was created in the database."
    if low == "notes" or low == "note":
        return "Free-text note for human-readable context or traceability."
    if low == "user_name":
        return "Name of the user associated with the record, if stored."
    if low == "experiment_name":
        return "Human-readable experiment label or name."
    if low == "function_type":
        return "Measurement function class associated with the configuration or experiment."
    if low.endswith("_status") or low == "status":
        return "Status label describing the result completeness or processing outcome."
    if low == "reject_code":
        return "Code describing the reason a result was rejected or not accepted."
    if low == "raw":
        return "Binary file content stored as a BLOB."
    if "voltage" in low or low.endswith("_v"):
        return "Voltage-related value stored for the record."
    if "current" in low or low.endswith("_ua") or low.endswith("_ma") or low.endswith("_a"):
        return "Current-related value stored for the record."
    if "resistance" in low or low.endswith("_ohm"):
        return "Resistance-related value stored for the record."
    if "pulse_width" in low:
        return "Pulse width parameter associated with the protocol or record."
    if low in {"wordline", "bitline"}:
        return "Array addressing coordinate used to locate the device within the subdie."
    if "r2" in low:
        return "Coefficient-of-determination value used to summarize fit quality."
    return f"Column {col} stored in the {table} table."


def allowed_values_from_check(defn: str) -> str:
    # CHECK(col IN ('A','B')) or CHECK (status IN (...))
    m = re.search(r"\bIN\s*\(([^\)]*)\)", defn, flags=re.I | re.S)
    if not m:
        return ""
    inner = m.group(1)
    vals = [v.strip().strip("'").strip('"') for v in split_top_level_commas(inner)]
    vals = [v for v in vals if v]
    return "; ".join(vals)


def normalize_name(name: str) -> str:
    return name.strip().strip('"').strip('`').strip('[').strip(']')


class Column:
    def __init__(self, name: str, data_type: str, raw: str):
        self.name = name
        self.data_type = data_type
        self.raw = raw
        self.not_null = bool(re.search(r"\bNOT\s+NULL\b", raw, flags=re.I))
        self.inline_pk = bool(re.search(r"\bPRIMARY\s+KEY\b", raw, flags=re.I))
        self.references: Optional[Dict[str, str]] = None
        self.checks: List[str] = []
        self.unique = bool(re.search(r"\bUNIQUE\b", raw, flags=re.I))
        self.allowed_values = ""


class Table:
    def __init__(self, name: str):
        self.name = name
        self.columns: List[Column] = []
        self.table_constraints: List[str] = []
        self.primary_key: List[str] = []
        self.uniques: List[str] = []
        self.foreign_keys: List[Dict[str, str]] = []
        self.checks: List[str] = []


def parse_tables(sql: str) -> Dict[str, Table]:
    cleaned = clean_sql(sql)
    tables: Dict[str, Table] = {}
    # capture CREATE TABLE ... ( ... ); including quoted names
    pattern = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\"`\[]?[^\s\(]+[\]`\"]?)\s*\((.*?)\)\s*(?:WITHOUT\s+ROWID\s*)?;", re.I | re.S)
    for m in pattern.finditer(cleaned):
        table_name = normalize_name(m.group(1))
        body = m.group(2)
        table = Table(table_name)
        items = split_top_level_commas(body)
        for item in items:
            item = item.strip()
            if not item:
                continue
            upper = item.upper()
            if upper.startswith("PRIMARY KEY") or upper.startswith("UNIQUE") or upper.startswith("CHECK") or upper.startswith("FOREIGN KEY") or upper.startswith("CONSTRAINT"):
                table.table_constraints.append(item)
                continue

            col_match = re.match(r'([\"`\[]?[^\s]+[\]`\"]?)\s+([A-Z]+(?:\s*\([^\)]*\))?)?(.*)$', item, flags=re.I | re.S)
            if not col_match:
                continue
            col_name = normalize_name(col_match.group(1))
            data_type = (col_match.group(2) or "").strip().upper() or "TEXT"
            rest = (col_match.group(3) or "").strip()
            col = Column(col_name, data_type, rest)

            ref_match = re.search(
                r"REFERENCES\s+([\"`\[]?[^\s\(]+[\]`\"]?)\s*\(([^\)]+)\)(?:\s+ON\s+DELETE\s+(CASCADE|RESTRICT|SET\s+NULL|NO\s+ACTION))?",
                rest,
                flags=re.I | re.S,
            )
            if ref_match:
                col.references = {
                    "to_table": normalize_name(ref_match.group(1)),
                    "to_column": normalize_name(ref_match.group(2)),
                    "on_delete": (ref_match.group(3) or "").upper().replace("  ", " "),
                }
            for chk in re.findall(r"CHECK\s*\((.*?)\)", rest, flags=re.I | re.S):
                col.checks.append(chk.strip())
                vals = allowed_values_from_check(chk)
                if vals:
                    col.allowed_values = vals
            table.columns.append(col)

        # process table constraints
        for c in table.table_constraints:
            cu = c.upper()
            if cu.startswith("CONSTRAINT"):
                # drop constraint name part
                m2 = re.match(r"CONSTRAINT\s+\S+\s+(.*)$", c, flags=re.I | re.S)
                c_eff = m2.group(1).strip() if m2 else c
            else:
                c_eff = c
            ceu = c_eff.upper()
            if ceu.startswith("PRIMARY KEY"):
                inner = re.search(r"PRIMARY\s+KEY\s*\((.*?)\)", c_eff, flags=re.I | re.S)
                if inner:
                    table.primary_key.extend([normalize_name(x) for x in split_top_level_commas(inner.group(1))])
            elif ceu.startswith("UNIQUE"):
                inner = re.search(r"UNIQUE\s*\((.*?)\)", c_eff, flags=re.I | re.S)
                if inner:
                    table.uniques.append(", ".join([normalize_name(x) for x in split_top_level_commas(inner.group(1))]))
            elif ceu.startswith("CHECK"):
                chk = re.search(r"CHECK\s*\((.*?)\)", c_eff, flags=re.I | re.S)
                if chk:
                    table.checks.append(chk.group(1).strip())
            elif ceu.startswith("FOREIGN KEY"):
                fk = re.search(
                    r"FOREIGN\s+KEY\s*\((.*?)\)\s+REFERENCES\s+([\"`\[]?[^\s\(]+[\]`\"]?)\s*\((.*?)\)(?:\s+ON\s+DELETE\s+(CASCADE|RESTRICT|SET\s+NULL|NO\s+ACTION))?",
                    c_eff,
                    flags=re.I | re.S,
                )
                if fk:
                    from_cols = [normalize_name(x) for x in split_top_level_commas(fk.group(1))]
                    to_table = normalize_name(fk.group(2))
                    to_cols = [normalize_name(x) for x in split_top_level_commas(fk.group(3))]
                    on_delete = (fk.group(4) or "").upper().replace("  ", " ")
                    for fc, tc in zip(from_cols, to_cols):
                        table.foreign_keys.append({
                            "from_column": fc,
                            "to_table": to_table,
                            "to_column": tc,
                            "on_delete": on_delete,
                        })

        # inline PK/FK fallback
        if not table.primary_key:
            for col in table.columns:
                if col.inline_pk:
                    table.primary_key.append(col.name)
        for col in table.columns:
            if col.references:
                table.foreign_keys.append({
                    "from_column": col.name,
                    **col.references,
                })

        tables[table.name] = table
    return tables


def load_overrides(path: Optional[Path]) -> Dict:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def pk_string(table: Table) -> str:
    return ", ".join(table.primary_key)


def relationship_note(table: Table) -> str:
    if table.name == "Experiment":
        return "Links each experiment to one device and one function configuration."
    if table.name == "Experimental_Detail":
        return "Stores raw measurement rows linked to one experiment."
    if table.primary_key and len(table.primary_key) > 1:
        return "Uses a composite primary key to preserve row uniqueness at result level."
    if table.foreign_keys:
        return "Contains foreign-key links needed to preserve structural traceability."
    return ""


def relationship_summary(from_table: str, from_col: str, to_table: str) -> str:
    return f"Each {from_table} record references one {to_table} record via {from_col}."


def build_selected_qc(tables: Dict[str, Table], overrides: Dict) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    # selected FKs
    for t in tables.values():
        stage = infer_table_stage(t.name, overrides)
        for fk in t.foreign_keys:
            rows.append({
                "pipeline_stage": stage,
                "table_name": t.name,
                "column_name": fk["from_column"],
                "qc_focus": "linkage",
                "rule_definition": f"{fk['from_column']} must reference an existing {fk['to_table']}.{fk['to_column']} record.",
                "why_it_matters": "Prevents orphan records and preserves cross-table consistency.",
            })
    # selected UNIQUE + CHECK
    for t in tables.values():
        stage = infer_table_stage(t.name, overrides)
        for uq in t.uniques[:5]:
            rows.append({
                "pipeline_stage": stage,
                "table_name": t.name,
                "column_name": "table_level",
                "qc_focus": "uniqueness",
                "rule_definition": f"The combination ({uq}) must be unique within {t.name}.",
                "why_it_matters": "Prevents duplicated structural or result records.",
            })
        # column checks with enumerations / ranges
        for col in t.columns:
            if col.allowed_values:
                rows.append({
                    "pipeline_stage": stage,
                    "table_name": t.name,
                    "column_name": col.name,
                    "qc_focus": "allowed values",
                    "rule_definition": f"{col.name} is restricted to predefined values.",
                    "why_it_matters": "Keeps categorical labels consistent across the dataset.",
                })
            for chk in col.checks[:2]:
                if not col.allowed_values:
                    rows.append({
                        "pipeline_stage": stage,
                        "table_name": t.name,
                        "column_name": col.name,
                        "qc_focus": "range check",
                        "rule_definition": f"{col.name} must satisfy CHECK ({chk}).",
                        "why_it_matters": "Rejects invalid values that would reduce interpretability or data quality.",
                    })
    # optional curated extra rules from overrides
    for row in overrides.get("selected_qc_rules", []):
        rows.append({k: row.get(k, "") for k in QC_HEADERS})

    # deduplicate
    seen = set()
    uniq_rows = []
    for r in rows:
        key = tuple(r.get(h, "") for h in QC_HEADERS)
        if key not in seen:
            seen.add(key)
            uniq_rows.append(r)
    return uniq_rows


def write_csv(path: Path, headers: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in headers})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Scientific Data CSVs from schema.sql"
    )
    parser.add_argument(
        "--schema_sql",
        default=r"D:\PycharmProjects\STARS_GUI\schema.sql",
        help="Path to schema.sql (default: D:\\PycharmProjects\\STARS_GUI\\schema.sql)",
    )
    parser.add_argument(
        "--overrides",
        default=r"D:\PycharmProjects\STARS_GUI\SQL_read\schema_overrides_scidata_v11_fabrication.json",
        help="Optional path to overrides.json (default: D:\\PycharmProjects\\STARS_GUI\\SQL_read\\schema_overrides_scidata_v11_fabrication.json)",
    )
    parser.add_argument(
        "--outdir",
        default=r"D:\PycharmProjects\STARS_GUI\SQL_read\output_csvs",
        help="Output directory (default: D:\\PycharmProjects\\STARS_GUI\\SQL_read\\output_csvs)",
    )
    args = parser.parse_args()

    schema_path = Path(args.schema_sql)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not schema_path.exists():
        raise FileNotFoundError(f"schema.sql not found: {schema_path}")

    overrides_path = Path(args.overrides) if args.overrides else None
    overrides = load_overrides(overrides_path) if (overrides_path and overrides_path.exists()) else {}

    tables = parse_tables(read_text(schema_path))

    # Table overview rows
    table_rows = []
    for table_name in sorted(tables):
        table = tables[table_name]
        stage = infer_table_stage(table_name, overrides)
        t_over = overrides.get("tables", {}).get(table_name, {})
        table_rows.append({
            "pipeline_stage": t_over.get("pipeline_stage", stage),
            "table_name": table_name,
            "information_stored": t_over.get("information_stored", default_table_description(table_name)),
            "primary_key": t_over.get("primary_key", pk_string(table)),
            "relationship_and_qc_note": t_over.get("relationship_and_qc_note", relationship_note(table)),
        })

    # Column dictionary rows
    col_rows = []
    for table_name in sorted(tables):
        table = tables[table_name]
        stage = infer_table_stage(table_name, overrides)
        t_over = overrides.get("tables", {}).get(table_name, {})
        col_overrides = t_over.get("columns", {})
        fk_cols = {fk["from_column"] for fk in table.foreign_keys}
        pk_cols = set(table.primary_key)
        for col in table.columns:
            c_over = col_overrides.get(col.name, {})
            allowed_vals = c_over.get("allowed_values_or_codes", col.allowed_values or "not applicable")
            if col.data_type.upper() in {"INTEGER", "REAL", "TEXT", "BLOB", "BOOLEAN", "TIMESTAMP"} and allowed_vals == "":
                allowed_vals = "not applicable"
            inferred_unit = c_over.get("unit", infer_unit(col.name))
            col_rows.append({
                "pipeline_stage": c_over.get("pipeline_stage", stage),
                "table_name": table_name,
                "column_name": col.name,
                "column_role": c_over.get("column_role", infer_column_role(col.name, col.name in pk_cols, col.name in fk_cols)),
                "data_type": c_over.get("data_type", col.data_type),
                "unit": inferred_unit,
                "required": c_over.get("required", "yes" if col.not_null else "no"),
                "description": c_over.get("description", ""),
                "allowed_values_or_codes": allowed_vals,
            })

    # Relationships rows
    rel_rows = []
    for table_name in sorted(tables):
        table = tables[table_name]
        for fk in table.foreign_keys:
            rel_rows.append({
                "from_table": table_name,
                "from_column": fk["from_column"],
                "to_table": fk["to_table"],
                "to_column": fk["to_column"],
                "relationship_summary": relationship_summary(table_name, fk["from_column"], fk["to_table"]),
                "on_delete_rule": fk.get("on_delete", "") or "",
            })

    qc_rows = build_selected_qc(tables, overrides)

    write_csv(outdir / "schema_table_overview_scidata_auto.csv", TABLE_OVERVIEW_HEADERS, table_rows)
    write_csv(outdir / "schema_column_dictionary_scidata_auto.csv", COLUMN_DICT_HEADERS, col_rows)
    write_csv(outdir / "schema_core_relationships_scidata_auto.csv", REL_HEADERS, rel_rows)
    unit_suffix_rows = build_unit_suffix_rows()

    write_csv(outdir / "schema_selected_qc_rules_scidata_auto.csv", QC_HEADERS, qc_rows)
    write_csv(outdir / "schema_unit_suffix_conventions_auto.csv", UNIT_SUFFIX_HEADERS, unit_suffix_rows)
    (outdir / "schema_scidata_README_auto.txt").write_text(README_TEXT, encoding="utf-8")

    print("Done. Generated files:")
    print(outdir / "schema_table_overview_scidata_auto.csv")
    print(outdir / "schema_column_dictionary_scidata_auto.csv")
    print(outdir / "schema_core_relationships_scidata_auto.csv")
    print(outdir / "schema_selected_qc_rules_scidata_auto.csv")
    print(outdir / "schema_unit_suffix_conventions_auto.csv")
    print(outdir / "schema_scidata_README_auto.txt")


if __name__ == "__main__":
    main()
