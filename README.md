# STARS_GUI

This workspace currently centers on three package-style GUI folders:

- `GUI_feature_switching/`
  - Switching-fit inspection GUI for `Database_NEW_V2.db`
  - entry: `python GUI_feature_switching/run.py [path/to/database.db]`
- `GUI_material_layers/`
  - Material/layer process GUI with a fixed working DB plus a selected big database
  - entry: `python GUI_material_layers/run.py [path/to/Database_NEW_V2.db]`
- `GUI_raw_data/`
  - Raw experiment browser and plotting GUI
  - entry: `python GUI_raw_data/run.py [path/to/database.db]`

## Shared Files

- `Database_NEW_V2.db`
  - Main experiment database used by the raw-data and switching GUIs, and as the big database for material recipes
- `schema.sql`
  - Schema reference snapshot
- `GUI_raw_data.py`
  - Compatibility launcher for `GUI_raw_data/run.py`

## Folder Guide

- `GUI_feature_switching/`
  - Structured switching-fit GUI with `bootstrap/`, `ui/`, `sql/`, `logic/`, and `fitting_model/`
- `GUI_material_layers/`
  - Structured process GUI with split working/recipe database handling
- `GUI_raw_data/`
  - Structured raw-data GUI with focused docs for load flow and edit points

Each of the three GUI folders keeps its own `README.md` and `docs/` notes for package-specific details.
