from enum import Enum


class LayerType(str, Enum):
    TOP = "Top"
    INSULATOR = "Insulator"
    BOTTOM = "Bottom"

    @classmethod
    def ordered(cls) -> list["LayerType"]:
        return [cls.BOTTOM, cls.INSULATOR, cls.TOP]


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
