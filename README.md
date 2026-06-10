# STARS_GUI

Multi-GUI workspace for exploring STARS experiment data, inspecting switching fits, and building material-layer process recipes.

## Repository Overview

This repository currently centers on three PyQt applications:

- `GUI_raw_data/`
  - raw experiment browser and plotting GUI
- `GUI_feature_switching/`
  - switching-fit inspection and compact-model plotting GUI
- `GUI_material_layers/`
  - material/layer process editor with recipe persistence into the main STARS database

Each GUI folder has its own `README.md` and `docs/` directory for package-specific details.

## Database Expectation

All three GUIs expect a STARS SQLite database, usually named `Memristor_Database.db`.

Important practical note:

- the repository may contain a local database snapshot in your own workspace
- that database file should be treated as local runtime data, not as repository documentation
- the authoritative schema reference for readers is `schema.sql`

## Which GUI To Use

### `GUI_raw_data`

Use this when you want to:

- browse experiments
- inspect metadata
- plot raw voltage/resistance style traces
- export selected data

Entry:

```bash
python GUI_raw_data/run.py [path/to/Memristor_Database.db]
```

Compatibility launcher:

```bash
python GUI_raw_data.py
```

### `GUI_feature_switching`

Use this when you want to:

- inspect switching-related experiments
- view switching-rate fit outputs
- work with the switching compact-model workflow

Entry:

```bash
python GUI_feature_switching/run.py [path/to/Memristor_Database.db]
```

### `GUI_material_layers`

Use this when you want to:

- build layer stacks
- add ALD, Sputter, E-beam, or Furnace process steps
- edit tool parameters
- manage ALD nested cycle/material/gas structures
- save or load process recipes in the main STARS database

Entry:

```bash
python GUI_material_layers/run.py [path/to/Memristor_Database.db]
```

Current runtime model:

- the main database is selected at startup or passed on the command line
- the editable working state lives in an in-memory SQLite session
- recipe persistence happens only through explicit recipe operations

## Top-Level Files And Folders

- `GUI_raw_data/`
  - structured raw-data GUI package
- `GUI_feature_switching/`
  - structured switching GUI package
- `GUI_material_layers/`
  - structured process/recipe GUI package
- `SQL_read/`
  - SQL-side data helpers and related outputs
- `schema.sql`
  - schema reference snapshot
- `er_diagram.svg`
  - schema/entity relationship diagram asset
- `SQL_extractor.py`
  - standalone extraction utility
- `sql_to_svg.py`
  - standalone schema/diagram helper

## Startup Behavior

If no database path is passed:

- `GUI_raw_data` opens its database picker at startup
- `GUI_feature_switching` opens its database picker through its own startup flow
- `GUI_material_layers` opens the main window first, then prompts for the main database

## Suggested Reading Order

If you are new to the repository:

1. read this top-level `README.md`
2. open the `README.md` inside the GUI folder you want to use
3. check that package's `docs/` folder for architecture and edit maps

## Package-Specific Docs

- `GUI_raw_data/README.md`
- `GUI_feature_switching/README.md`
- `GUI_material_layers/README.md`

## Current Repository Shape

This repository is a workspace rather than a single packaged application.

That means it intentionally contains:

- multiple GUI packages
- shared schema artifacts
- standalone helper scripts
- local development files that may exist in individual workspaces but are not part of the conceptual product surface
