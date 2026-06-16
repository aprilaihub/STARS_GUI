from enum import Enum


class LayerType(str, Enum):
    SUBSTRATE = "Substrate"
    SOURCE_DRAIN_ADHESION = "Source_Drain_Adhesion"
    SOURCE_DRAIN_ELECTRODE = "Source_Drain_Electrode"
    CHANNEL = "Channel"
    GATE_DIELECTRIC = "Gate_Dielectric"
    GATE_ADHESION = "Gate_Adhesion"
    GATE_ELECTRODE = "Gate_Electrode"

    @classmethod
    def ordered(cls) -> list["LayerType"]:
        return [cls.SUBSTRATE, cls.SOURCE_DRAIN_ADHESION, cls.SOURCE_DRAIN_ELECTRODE, cls.CHANNEL, cls.GATE_DIELECTRIC, cls.GATE_ADHESION, cls.GATE_ELECTRODE]


class ToolType(str, Enum):
    ALD = "ALD"
    SPUTTER = "Sputter"
    E_BEAM = "E_beam"
    FURNACE = "Furnace"

    @property
    def display_name(self) -> str:
        return f"{self.value} (Tool)"

    @classmethod
    def from_storage(cls, raw: str) -> "ToolType":
        text = (raw or "").strip()
        if text.endswith("(Tool)"):
            text = text.split()[0]
        for item in cls:
            if item.value == text:
                return item
        raise ValueError(f"Unsupported tool type: {raw!r}")
