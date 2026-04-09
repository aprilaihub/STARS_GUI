from __future__ import annotations

from abc import ABC, abstractmethod

from .enums import LayerType, ToolType
from .models import ProcessStep, RecipeSummary


class WorkingProcessRepository(ABC):
    @abstractmethod
    def ensure_schema(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_steps(self) -> list[ProcessStep]:
        raise NotImplementedError

    @abstractmethod
    def get_step(self, step_id: int) -> ProcessStep | None:
        raise NotImplementedError

    @abstractmethod
    def add_step(self, layer: LayerType, tool_type: ToolType, position_in_layer: int | None = None) -> ProcessStep:
        raise NotImplementedError

    @abstractmethod
    def update_step(self, step: ProcessStep) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_step(self, step_id: int, tool_type: ToolType) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_all_steps(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_material_candidates(self, tool_type: ToolType, key: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def upsert_material_candidate(self, tool_type: ToolType, key: str, value: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_material_candidate(self, tool_type: ToolType, key: str, value: str) -> None:
        raise NotImplementedError


class RecipeRepository(ABC):
    @abstractmethod
    def ensure_schema(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_recipe(self, recipe_name: str, steps: list[ProcessStep]) -> int:
        raise NotImplementedError

    @abstractmethod
    def replace_recipe_contents(
        self,
        recipe_id: int,
        steps: list[ProcessStep],
        *,
        commit: bool = True,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_recipes(self) -> list[RecipeSummary]:
        raise NotImplementedError

    @abstractmethod
    def load_recipe_steps(self, recipe_id: int) -> list[ProcessStep]:
        raise NotImplementedError

    @abstractmethod
    def delete_recipe(self, recipe_id: int) -> None:
        raise NotImplementedError
