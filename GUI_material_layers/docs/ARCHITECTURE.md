# Architecture

## Runtime Overview

`GUI_material_layers` is an editor-oriented GUI with a split runtime model:

- an in-memory working database for the current editing session
- the selected main STARS database for persistent recipe storage

The working side is disposable. The main database is persistent.

## Startup Flow

Current startup flow on `main`:

1. `run.py` creates the Qt application
2. `run.py` builds a runtime container with an in-memory working database
3. `ui/main_window.py` opens the main window
4. `run.py` opens the main-database picker
5. the selected database is validated as the main experiment database
6. the container attaches a real recipe repository to that database
7. the main window enables recipe operations

This means the GUI can exist before a database is selected, but recipe persistence is unavailable until a valid main database is attached.

## Container Wiring

The runtime container assembles:

- `sql.db_ops.SQLiteWorkingProcessRepository`
- `sql.db_ops.SQLiteRecipeRepository`
- `logic.process_service.ProcessService`
- `logic.recipe_service.RecipeService`

`bootstrap/container.py` is responsible for building these pieces and returning them as an `AppContainer`.

## Data Flow

### Working Side

The working side stores the current editor state:

- layer rows
- tool rows
- ALD nested cycle/material/gas trees
- tool attachments
- selector helper values such as available materials or gases

Autosave from the editor writes into this working state only.

### Persistent Side

The persistent side is the selected main database. Recipe operations copy data between the working side and the persistent recipe side.

Main directions:

- `Save Recipe`
  - working state -> main database
- `Load Recipe`
  - main database -> working state
- `Replace Recipe`
  - working state -> existing recipe rows in the main database

## Main Modules

### `run.py`

- creates the app
- opens the main-database picker
- validates the selected file
- attaches the main database to the runtime container

### `bootstrap/config.py`

- defines the config object
- holds default paths and runtime path overrides

### `bootstrap/container.py`

- builds repository/service wiring
- prepares schemas on the working and recipe sides

### `ui/main_window.py`

- main editor UI
- menu bar and recipe actions
- drag/drop layer editing
- autosave and refresh behavior

### `logic/process_service.py`

- working-state CRUD behavior for steps and selector values

### `logic/recipe_service.py`

- persistent recipe save/load/replace/delete behavior
- attachment and NMLC copying between database roles

### `sql/db_ops.py`

- SQLite repository implementations
- schema ensure logic
- attachment helpers
- ALD nested tree copy helpers

## Why The Working State Is In Memory

The current `main` branch uses an in-memory working database so the editor behaves like a session workspace:

- startup does not depend on a local working DB file
- editor autosave stays local to the session
- users do not accidentally treat working-state writes as persistent recipe writes
- persistence happens only through explicit recipe operations

## UI Model

The main editor is organized into three functional areas:

- left panel
  - layer visualization, draggable tools, recipe actions
- center panel
  - editable layer sections and tool placement
- right panel
  - parameter editor for the selected tool

The window is a `QMainWindow` and exposes database entry through the menu bar:

- `File > Open Main Database...`

## Error Handling

Database failures are handled at the startup and recipe-operation boundaries.

Typical checks include:

- selected main database file exists
- required high-level tables exist
- runtime schema can be prepared
- recipe copy/load/replace operations succeed transactionally

If a selected database is readable but cannot be initialized for GUI use, the user gets a retry/cancel dialog.
