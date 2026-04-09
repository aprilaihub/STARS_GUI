from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import LayerType, ToolType


@dataclass(slots=True)
class ProcessStep:
    step_id: int | None
    layer: LayerType
    tool_type: ToolType
    position_in_layer: int = 1  # 1 is the bottom-most tool inside a layer.
    thickness_nm: float | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecipeSummary:
    recipe_id: int
    recipe_name: str
    created_at: str | None = None


@dataclass(slots=True)
class Recipe:
    summary: RecipeSummary
    steps: list[ProcessStep]
