# Project Map

Use this as the quick "where do I edit this?" guide.

## Startup Or Database Picking

- `run.py`
  - Big-database picker, validation, and app bootstrap
- `bootstrap/config.py`
  - Default paths and config object
- `bootstrap/container.py`
  - Repository/service wiring

## Main Editor UI

- `ui/main_window.py`
  - Main page layout, drag/drop flow, autosave, and recipe actions
- `ui/style.py`
  - Theme helpers

## Dialogs

- `ui/dialogs/nested_cycle_dialog.py`
  - ALD nested material/gas/cycle editor
- `ui/dialogs/material_selector_dialog.py`
  - Selector popup for material-like values
- `ui/dialogs/save_recipe_dialog.py`
  - Save current working state as a recipe
- `ui/dialogs/load_recipe_dialog.py`
  - Load, replace, or delete recipe-side data

## Business Logic

- `logic/process_service.py`
  - Working-state process behavior
- `logic/recipe_service.py`
  - Recipe save/load/replace behavior
- `logic/enums.py`
- `logic/params.py`
- `logic/models.py`

## SQL And Schema

- `sql/db_ops.py`
  - Repository implementations and runtime schema ensure logic
- `sql/*.sql`
  - Reference schema dumps and migration notes
