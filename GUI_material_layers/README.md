# GUI_material_layers

Structured PyQt GUI for editing material/layer process flows.

This package uses two database roles:

- working DB: `db/Manufacture_Process_Database.db`
- big database: `Database_NEW_V2.db`, chosen at startup or passed on the command line

## Run

```bash
python GUI_material_layers/run.py
```

Startup opens a picker for the big database. You can also pass that path directly:

```bash
python GUI_material_layers/run.py ..\Database_NEW_V2.db
```

## Package Layout

- `bootstrap/`
  - Path config and dependency wiring
- `ui/`
  - Main page plus small dialogs
- `logic/`
  - Process and recipe services, enums, and models
- `sql/`
  - Schema ensure logic and SQLite repositories
- `db/`
  - Working DB owned by this package
- `tests/`
  - Full-flow check

## Main Behavior

- The working DB stays fixed inside this package
- The big database is selected at startup and validated before the GUI opens
- Recipes are saved to and loaded from the big database
- Attachments are stored on both the working side and recipe side through `Tool_Attachment`

## Docs

- `docs/ARCHITECTURE.md`
  - Startup path and module responsibilities
- `docs/DB_MAP.md`
  - Working DB vs big database tables
- `docs/PROJECT_MAP.md`
  - Shortcut for where to edit common behaviors

## Check

```bash
python GUI_material_layers/tests/full_flow_check.py
```
