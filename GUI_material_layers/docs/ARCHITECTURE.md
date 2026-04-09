# Architecture Draft

## 1. Startup Flow

`run.py` -> `bootstrap.config.AppConfig` -> `bootstrap.container.build_container` -> `ui.main_window.MainWindow`

Container wiring:
- `sql.db_ops.SQLiteWorkingProcessRepository`
- `sql.db_ops.SQLiteRecipeRepository`
- `logic.process_service.ProcessService`
- `logic.recipe_service.RecipeService`

## 2. Layer Responsibilities

- `logic/`
  - Defines tool/layer types and process models.
  - Implements update/save/load business rules.
- `sql/`
  - Owns SQLite schema creation and SQL queries.
  - Persists process steps, candidates, recipes, attachments, and NMLC tree.
  - `db_ops.py` now also keeps runtime schema ensure logic.
- `ui/`
  - Renders main page and dialogs.
  - Calls services only, no direct SQL in normal flow.
- `bootstrap/`
  - Path config and dependency assembly.

## 3. UI Breakdown

- Main page:
  - `ui/main_window.py`
- Dialogs:
  - `ui/dialogs/nested_cycle_dialog.py`
  - `ui/dialogs/material_selector_dialog.py`
  - `ui/dialogs/save_recipe_dialog.py`
  - `ui/dialogs/load_recipe_dialog.py`

## 4. Database Entry Points

- Working DB path: `db/Manufacture_Process_Database.db`
- Recipe DB path: `../Database_NEW_V2.db`
- SQL implementation file: `sql/db_ops.py`
