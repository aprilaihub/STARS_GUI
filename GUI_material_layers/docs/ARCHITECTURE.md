# Architecture

## Startup Flow

`run.py` -> big-database picker/validation -> `bootstrap/config.py` -> `bootstrap/container.py` -> `ui/main_window.py`

## Container Wiring

- `sql.db_ops.SQLiteWorkingProcessRepository`
- `sql.db_ops.SQLiteRecipeRepository`
- `logic.process_service.ProcessService`
- `logic.recipe_service.RecipeService`

`build_container(...)` assembles these once, then the main window talks only to the services.

## Responsibilities

- `ui/`
  - Main window, dialogs, drag/drop flow, and widget state
- `logic/`
  - Process-step behavior, recipe save/load/replace rules, enums, and models
- `sql/`
  - SQLite repositories plus schema ensure logic for both the working DB and the big database
- `bootstrap/`
  - Startup config and dependency assembly

## Database Split

- Working DB:
  - `db/Manufacture_Process_Database.db`
  - owned by this package for the editable working state
- Big database:
  - selected at startup, normally `../Database_NEW_V2.db`
  - used for recipe-side save/load/replace operations

The startup picker only targets the big database. The working DB stays fixed.

## Main Files

- `ui/main_window.py`
  - Main editor and recipe operations
- `sql/db_ops.py`
  - Repository implementations and runtime schema setup
- `logic/process_service.py`
  - Working-state operations
- `logic/recipe_service.py`
  - Save/load/replace recipe behavior
