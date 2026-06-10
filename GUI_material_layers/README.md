# GUI_material_layers

PyQt GUI for building and editing material-layer process flows, then saving those flows as recipes inside the main STARS database.

## What This GUI Does

This GUI is for process composition, not for browsing raw experiment records.

Inside the editor you can:

- build a layer stack with `Top`, `Insulator`, and `Bottom` sections
- add tool steps for `ALD`, `Sputter`, `E_beam`, and `Furnace`
- edit thickness and tool parameters
- manage ALD nested cycle/material/gas trees
- save the current process flow as a recipe in the main database
- load an existing recipe back into the editor
- replace an existing recipe with the current editor state
- delete recipes from the main database

## Runtime Model

This GUI uses two different data scopes.

### Main Database

The main database is the selected STARS database, usually `Memristor_Database.db`.

It is used for persistent recipe storage. The GUI validates that the selected file looks like the main experiment database before it enables recipe operations.

### Working State

The editable working state lives in an in-memory SQLite database for the lifetime of the GUI session.

That means:

- the current layer/tool edits are available while the GUI stays open
- autosave inside the editor writes into memory, not directly into the main database
- closing the GUI discards unsaved working data
- recipe data only becomes persistent when you explicitly save or replace a recipe in the main database

## Startup Behavior

When the GUI starts:

1. the main window opens first
2. a database picker opens for the main database
3. once a valid main database is selected, recipe operations become available

You can reopen the picker from the menu bar:

- `File > Open Main Database...`

If no database is loaded:

- the editor UI still opens
- recipe save/load/replace actions stay disabled

## Run

Start the GUI:

```bash
python GUI_material_layers/run.py
```

You can also pass the main database path directly:

```bash
python GUI_material_layers/run.py ..\Memristor_Database.db
```

If no path is passed, the startup picker opens from a sensible default directory, usually the Windows Desktop.

## Save And Load Semantics

### Save Recipe

`Save Recipe` reads the current in-memory working state and creates a new recipe in the main database.

This includes:

- layer ordering
- tool parameters
- ALD nested cycle/material/gas data
- tool attachments

### Recipe Operation

`Recipe Operation` opens the recipe management dialog.

From there you can:

- load a recipe into the current working editor
- replace an existing recipe with the current working editor state
- delete a recipe from the main database

Loading a recipe clears the current working state and rebuilds it from the selected saved recipe.

## Package Layout

- `run.py`
  - app entry point, startup picker, and main-database attachment
- `bootstrap/`
  - config object and dependency wiring
- `ui/`
  - main window, dialogs, drag/drop flow, and widget behavior
- `logic/`
  - process services, recipe services, enums, and models
- `sql/`
  - SQLite repositories, schema ensure logic, and attachment/NMLC copy helpers
- `tests/`
  - GUI flow checks and runtime verification helpers

## Main Files

- `ui/main_window.py`
  - main editor, menu bar, tool panels, autosave, and recipe actions
- `logic/process_service.py`
  - working-state CRUD behavior for process steps
- `logic/recipe_service.py`
  - save/load/replace behavior between working state and the main database
- `sql/db_ops.py`
  - repository implementations and schema preparation
- `bootstrap/container.py`
  - repository/service container assembly

## Related Docs

- `docs/ARCHITECTURE.md`
  - runtime wiring and responsibility split
- `docs/DB_MAP.md`
  - current database roles and touched tables
- `docs/PROJECT_MAP.md`
  - quick edit guide for common tasks

## Check

Run the flow check:

```bash
python GUI_material_layers/tests/full_flow_check.py
```
