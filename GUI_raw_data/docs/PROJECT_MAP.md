# Project Map

Use this as the quick edit guide.

## Startup And App Setup

- `run.py`
  - Entry point and optional database-path handoff
- `bootstrap/qt_app.py`
  - High-DPI setup and global fonts
- `bootstrap/config.py`
  - Plot defaults, preload flags, and UI constants

## Main UI

- `ui/main_window.py`
  - First file to read for most behavior changes
- `ui/list_model.py`
  - Left-side experiment list labels
- `ui/plot_panel.py`
  - Shared plot widget for the center plots

## Database Work

- `sql/db_ops.py`
  - Schema validation, metadata preload SQL, point fetching, export helpers, and function-row lookups

## Pure Helpers

- `logic/id_specs.py`
  - Experiment/device id parsing such as `1,2,10-20`
- `logic/plotting.py`
  - Axis transforms and label formatting

## Tests

- `tests/smoke_import.py`
  - Minimal import check for a ready GUI environment
