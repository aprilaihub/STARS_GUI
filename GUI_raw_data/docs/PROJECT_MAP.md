# Project Map

Use this as the "where do I edit this?" shortcut.

## Startup and Entry

- `run.py`
  - Application entry point.
- `bootstrap/qt_app.py`
  - High-DPI setup and global font configuration.
- `bootstrap/config.py`
  - Plot defaults, preload flags, list limits, and timing toggles.

## Main UI

- `ui/main_window.py`
  - First file to read for almost every behavior change.
  - Owns filter widgets, list refresh, selection handling, plotting, metadata display, and export flow.
- `ui/list_model.py`
  - Controls how experiments are labeled in the left-side list.
- `ui/plot_panel.py`
  - Shared plot panel widget used by the three center plots.

## Database Work

- `sql/db_ops.py`
  - Change this file for schema validation, metadata preload SQL, point fetching, CSV export, or function-row lookup logic.

## Pure Helpers

- `logic/id_specs.py`
  - Experiment and device id parsing such as `1,2,10-20`.
- `logic/plotting.py`
  - Axis transforms and label formatting.

## Tests

- `tests/smoke_import.py`
  - Minimal import check for a ready environment with GUI dependencies installed.
