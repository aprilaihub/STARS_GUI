# GUI_material_layers

Readable project layout for the material process GUI.

## Run
```bash
python run.py
```

## Directory Guide

- `db/`: runtime databases used by this GUI.
  - `Manufacture_Process_Database.db`
- recipe-side DB is now the project-level `Database_NEW_V2.db`
- attachment model:
  - both working db and recipe db store file payloads in `Tool_Attachment`
  - each `Tool_*` row can point to one attachment by `attachment_id`
  - attachment now follows `save recipe`, `load recipe`, and `replace recipe`
- `sql/`: unified database entry, schema helpers, and SQL dumps.
  - `db_ops.py`
  - `*.sql`
- `logic/`: business concepts and use-case services.
  - `enums.py`, `models.py`, `params.py`
  - `process_service.py`, `recipe_service.py`
- `ui/`: GUI code.
  - `main_window.py` (main page)
  - `dialogs/` (small windows)
  - `style.py` (theme helpers)
- `bootstrap/`: app startup assembly.
  - `config.py` (paths)
  - `container.py` (wire repo + service)
- `tests/`: workflow checks.

## Main UI vs Dialogs

- Main page:
  - `ui/main_window.py`
- Dialogs:
  - `ui/dialogs/nested_cycle_dialog.py` (ALD cycle/material tree)
  - `ui/dialogs/material_selector_dialog.py`
  - `ui/dialogs/save_recipe_dialog.py`
  - `ui/dialogs/load_recipe_dialog.py`

## Full Flow Check
```bash
python tests/full_flow_check.py
```

## Notes

- This folder is migrated from the stable `new_material_GUI` implementation.
- Goal is readability-first structure while keeping behavior unchanged.
