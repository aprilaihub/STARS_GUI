from __future__ import annotations

from dataclasses import dataclass, field

from .enums import ToolType


@dataclass(frozen=True, slots=True)
class ParamSpec:
    key: str
    label: str
    unit: str = "-"
    input_kind: str = "text"  # text | combo | material
    choices: tuple[str, ...] = field(default_factory=tuple)


TOOL_PARAM_SPECS: dict[ToolType, tuple[ParamSpec, ...]] = {
    ToolType.ALD: (
        ParamSpec("instrument_name", "Instrument Name"),
        ParamSpec("desired_material", "Desired Material", input_kind="material"),
        ParamSpec("precursor_name", "Precursor Name", input_kind="material"),
        ParamSpec("precursor_pod_temperature_degC", "Precursor Pod Temperature", "degC"),
        ParamSpec("dep_method", "Deposition Method", input_kind="combo", choices=("Thermal", "Plasma")),
        ParamSpec("reactant_name", "Reactant Name", input_kind="combo", choices=("Ozone", "Water", "O2 Plasma")),
        ParamSpec("table_temperature_degC", "Table Temperature", "degC"),
    ),
    ToolType.SPUTTER: (
        ParamSpec("instrument_name", "Instrument Name"),
        ParamSpec("desired_material", "Desired Material", input_kind="material"),
        ParamSpec("target_material", "Target Material", input_kind="material"),
        ParamSpec("gas_used", "Gas Used", input_kind="material"),
        ParamSpec("gas_flow_rate_sccm", "Gas Flow Rate", "sccm"),
        ParamSpec("plasma_strike_gas_used", "Plasma Strike Gas", input_kind="material"),
        ParamSpec("plasma_strike_gas_flow_rate_sccm", "Plasma Strike Gas Flow", "sccm"),
        ParamSpec("deposition_voltage_V", "Deposition Voltage", "V"),
        ParamSpec("gun_type", "Gun Type", input_kind="combo", choices=("DC", "PDC", "RF")),
        ParamSpec("voltage_frequency_kHz", "Voltage Frequency", "kHz"),
        ParamSpec("chamber_pressure_mTorr", "Chamber Pressure", "mTorr"),
        ParamSpec("power_density_W_per_cm2", "Power Density", "W/cm2"),
    ),
    ToolType.E_BEAM: (
        ParamSpec("instrument_name", "Instrument Name"),
        ParamSpec("desired_material", "Desired Material", input_kind="material"),
        ParamSpec("chamber_pressure_mTorr", "Chamber Pressure", "mTorr"),
        ParamSpec("power_W", "Power", "W"),
        ParamSpec("deposition_rate_nm_per_s", "Deposition Rate", "nm/s"),
    ),
    ToolType.FURNACE: (
        ParamSpec("instrument_name", "Instrument Name"),
        ParamSpec("ramping_rate_degC_per_s", "Ramping Rate", "degC/s"),
        ParamSpec("annealing_temperature_degC", "Annealing Temperature", "degC"),
        ParamSpec("annealing_time_s", "Annealing Time", "s"),
        ParamSpec("annealing_gas", "Annealing Gas", input_kind="material"),
        ParamSpec("idle_temperature_degC", "Idle Temperature", "degC"),
    ),
}


def specs_for(tool_type: ToolType) -> tuple[ParamSpec, ...]:
    return TOOL_PARAM_SPECS.get(tool_type, ())


def material_keys_for(tool_type: ToolType) -> tuple[str, ...]:
    return tuple(spec.key for spec in specs_for(tool_type) if spec.input_kind == "material")
