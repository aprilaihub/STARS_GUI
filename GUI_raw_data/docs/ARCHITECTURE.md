# Architecture

## Runtime Path

`GUI_raw_data/run.py` -> `bootstrap/qt_app.py` -> `ui/main_window.py`

## Design Goal

Keep the package easy to read in one pass:
- `ui/` coordinates the user flow
- `sql/` owns direct database access
- `logic/` stays pure and reusable
- `bootstrap/` only handles startup and shared config

## Dependency Direction

- `ui/` may import from `bootstrap/`, `logic/`, and `sql/`
- `sql/` should not depend on `ui/`
- `logic/` should stay free of Qt and SQLite side effects
- `bootstrap/` should stay thin and startup-focused

## Main Files

- `ui/main_window.py`
  - Main window state, UI assembly, filtering, plotting, metadata display, and export flow.
- `ui/list_model.py`
  - Virtual list model for the experiment list.
- `ui/plot_panel.py`
  - Reusable Matplotlib panel with axis-mode controls.
- `sql/db_ops.py`
  - Schema validation, metadata preload, point fetches, exports, and function-row lookups.

## Reading Order

1. `ui/main_window.py`
2. `sql/db_ops.py`
3. `docs/LOAD_FLOW.md` if you need the startup/load path
4. `logic/` helpers only when a specific transformation needs to change
