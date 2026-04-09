from __future__ import annotations

from typing import Any

from .enums import LayerType, ToolType
from .models import ProcessStep
from .params import material_keys_for
from .repositories import WorkingProcessRepository


class ProcessService:
    def __init__(self, working_repo: WorkingProcessRepository):
        self.working_repo = working_repo

    def list_steps(self) -> list[ProcessStep]:
        return self.working_repo.list_steps()

    def add_step(self, layer: str, tool_type: str, position_in_layer: int | None = None) -> ProcessStep:
        layer_enum = LayerType(layer)
        tool_enum = ToolType(tool_type)
        return self.working_repo.add_step(layer_enum, tool_enum, position_in_layer=position_in_layer)

    def update_step(
        self,
        step_id: int,
        layer: str,
        thickness_raw: str,
        parameters: dict[str, Any],
        position_in_layer: int | None = None,
    ) -> ProcessStep:
        step = self.working_repo.get_step(step_id)
        if step is None:
            raise ValueError(f"Step {step_id} does not exist")

        step.layer = LayerType(layer)
        if position_in_layer is not None:
            step.position_in_layer = int(position_in_layer)
        step.thickness_nm = self._parse_thickness(thickness_raw)
        step.parameters = {
            key: ("" if value is None else str(value).strip())
            for key, value in parameters.items()
        }

        self.working_repo.update_step(step)

        for key in material_keys_for(step.tool_type):
            val = (step.parameters.get(key) or "").strip()
            if val:
                self.working_repo.upsert_material_candidate(step.tool_type, key, val)

        refreshed = self.working_repo.get_step(step_id)
        if refreshed is None:
            raise RuntimeError(f"Step {step_id} vanished after update")
        return refreshed

    def delete_step(self, step_id: int) -> None:
        step = self.working_repo.get_step(step_id)
        if step is None:
            return
        self.working_repo.delete_step(step_id, step.tool_type)

    def get_step(self, step_id: int) -> ProcessStep | None:
        return self.working_repo.get_step(step_id)

    def list_candidates(self, step: ProcessStep, param_key: str) -> list[str]:
        return self.working_repo.list_material_candidates(step.tool_type, param_key)

    def list_candidates_for(self, tool_type: ToolType, param_key: str) -> list[str]:
        return self.working_repo.list_material_candidates(tool_type, param_key)

    def add_candidate(self, tool_type: ToolType, param_key: str, value: str) -> None:
        self.working_repo.upsert_material_candidate(tool_type, param_key, value)

    def remove_candidate(self, tool_type: ToolType, param_key: str, value: str) -> None:
        self.working_repo.delete_material_candidate(tool_type, param_key, value)

    @staticmethod
    def _parse_thickness(raw: str) -> float | None:
        text = (raw or "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"Invalid thickness value: {raw!r}")
