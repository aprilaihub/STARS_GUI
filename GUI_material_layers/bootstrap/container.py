from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from ..sql.db_ops import SQLiteRecipeRepository, SQLiteWorkingProcessRepository, prepare_runtime_databases
from ..logic.process_service import ProcessService
from ..logic.recipe_service import RecipeService


@dataclass
class AppContainer:
    config: AppConfig
    working_repo: SQLiteWorkingProcessRepository
    recipe_repo: SQLiteRecipeRepository
    process_service: ProcessService
    recipe_service: RecipeService

    def close(self) -> None:
        self.working_repo.close()
        self.recipe_repo.close()


def build_container(config: AppConfig) -> AppContainer:
    working_repo = SQLiteWorkingProcessRepository(config.working_db_path)
    recipe_repo = SQLiteRecipeRepository(config.recipe_db_path)

    prepare_runtime_databases(working_repo.conn, recipe_repo.conn)

    process_service = ProcessService(working_repo)
    recipe_service = RecipeService(working_repo, recipe_repo)

    return AppContainer(
        config=config,
        working_repo=working_repo,
        recipe_repo=recipe_repo,
        process_service=process_service,
        recipe_service=recipe_service,
    )
