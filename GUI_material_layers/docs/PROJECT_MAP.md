# Project Map (Readable)

## If you want to edit SQL/data
- File: `sql/db_ops.py`
- DB files: `db/*.db`
- SQL references: `sql/*.sql`

## If you want to edit main page UI
- File: `ui/main_window.py`

## If you want to edit popup dialogs
- NMLC dialog: `ui/dialogs/nested_cycle_dialog.py`
- Material selector: `ui/dialogs/material_selector_dialog.py`
- Save recipe: `ui/dialogs/save_recipe_dialog.py`
- Load/delete recipe: `ui/dialogs/load_recipe_dialog.py`

## If you want to edit business behavior (without SQL)
- `logic/process_service.py`
- `logic/recipe_service.py`

## If you want to edit tool/layer definitions
- `logic/enums.py`
- `logic/params.py`
- `logic/models.py`

## If startup/config fails
- `run.py`
- `bootstrap/config.py`
- `bootstrap/container.py`
