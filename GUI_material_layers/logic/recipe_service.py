from __future__ import annotations

import sqlite3
from typing import Any

from .models import RecipeSummary
from .repositories import RecipeRepository, WorkingProcessRepository
from ..sql import db_ops


class RecipeService:
    def __init__(self, working_repo: WorkingProcessRepository, recipe_repo: RecipeRepository):
        self.working_repo = working_repo
        self.recipe_repo = recipe_repo

    def save_current_as_recipe(self, recipe_name: str) -> int:
        steps = self.working_repo.list_steps()
        if not steps:
            raise ValueError("No process steps found in working database")

        recipe_id = self.recipe_repo.create_recipe(recipe_name, steps)

        # Copy ALD nested cycle/material tree into recipe DB.
        try:
            source_conn = self._sqlite_conn(self.working_repo)
            target_conn = self._sqlite_conn(self.recipe_repo)
            if source_conn is not None and target_conn is not None:
                recipe_steps = self.recipe_repo.load_recipe_steps(recipe_id)
                step_map = self._build_step_map(steps, recipe_steps)
                db_ops.copy_tool_attachments_between(source_conn, target_conn, step_map)
                db_ops.copy_nmlc_between(source_conn, target_conn, step_map)
        except Exception:
            # Keep recipe DB consistent if NMLC copy fails.
            try:
                self.recipe_repo.delete_recipe(recipe_id)
            except Exception:
                pass
            raise

        return recipe_id

    def list_recipes(self) -> list[RecipeSummary]:
        return self.recipe_repo.list_recipes()

    def replace_recipe_from_working(self, recipe_id: int) -> int:
        steps = self.working_repo.list_steps()
        if not steps:
            raise ValueError("No process steps found in working database")

        source_conn = self._sqlite_conn(self.working_repo)
        target_conn = self._sqlite_conn(self.recipe_repo)
        if source_conn is None or target_conn is None:
            self.recipe_repo.replace_recipe_contents(recipe_id, steps)
            return len(steps)

        db_ops.begin_immediate(target_conn)
        try:
            self.recipe_repo.replace_recipe_contents(recipe_id, steps, commit=False)
            recipe_steps = self.recipe_repo.load_recipe_steps(recipe_id)
            step_map = self._build_step_map(steps, recipe_steps)
            db_ops.copy_tool_attachments_between(
                source_conn,
                target_conn,
                step_map,
                manage_transaction=False,
            )
            db_ops.copy_nmlc_between(
                source_conn,
                target_conn,
                step_map,
                manage_transaction=False,
            )
            target_conn.commit()
        except Exception:
            target_conn.rollback()
            raise

        return len(steps)

    def load_recipe_into_working(self, recipe_id: int) -> int:
        recipe_steps = self.recipe_repo.load_recipe_steps(recipe_id)
        self.working_repo.clear_all_steps()

        step_map: dict[int, int] = {}
        count = 0
        for step in recipe_steps:
            created = self.working_repo.add_step(
                step.layer,
                step.tool_type,
                position_in_layer=step.position_in_layer,
            )
            created.thickness_nm = step.thickness_nm
            created.parameters = dict(step.parameters)
            self.working_repo.update_step(created)
            if step.step_id is not None and created.step_id is not None:
                step_map[int(step.step_id)] = int(created.step_id)
            count += 1

        # Copy ALD nested cycle/material tree from recipe DB to working DB.
        source_conn = self._sqlite_conn(self.recipe_repo)
        target_conn = self._sqlite_conn(self.working_repo)
        if source_conn is not None and target_conn is not None and step_map:
            db_ops.copy_tool_attachments_between(source_conn, target_conn, step_map)
            db_ops.copy_nmlc_between(source_conn, target_conn, step_map)

        return count

    def delete_recipe(self, recipe_id: int) -> None:
        self.recipe_repo.delete_recipe(recipe_id)

    @staticmethod
    def _sqlite_conn(repo_obj: Any) -> sqlite3.Connection | None:
        conn = getattr(repo_obj, "conn", None)
        return conn if isinstance(conn, sqlite3.Connection) else None

    @staticmethod
    def _step_key(step) -> tuple[str, int, str] | None:
        if step.step_id is None:
            return None
        return (
            step.layer.value,
            int(step.position_in_layer),
            step.tool_type.value,
        )

    def _build_step_map(self, source_steps: list, target_steps: list) -> dict[int, int]:
        src_by_key: dict[tuple[str, int, str], int] = {}
        dst_by_key: dict[tuple[str, int, str], int] = {}

        for s in source_steps:
            k = self._step_key(s)
            if k is None:
                continue
            src_by_key[k] = int(s.step_id)

        for s in target_steps:
            k = self._step_key(s)
            if k is None:
                continue
            dst_by_key[k] = int(s.step_id)

        mapping: dict[int, int] = {}
        for k, src_id in src_by_key.items():
            dst_id = dst_by_key.get(k)
            if dst_id is not None:
                mapping[src_id] = dst_id
        return mapping
