# Architecture

## Runtime Path

`run.py` -> `bootstrap/qt_app.py` -> `ui/main_window.py`

## Responsibilities

- `bootstrap/`
  - High-DPI setup and shared GUI constants
- `ui/`
  - Main user flow, list handling, metadata display, and plotting
- `sql/`
  - Read-only schema validation, metadata preload, point fetches, and exports
- `logic/`
  - Pure helpers for parsing and axis transforms

## Dependency Direction

- `ui/` may import `bootstrap/`, `logic/`, and `sql/`
- `sql/` stays independent of `ui/`
- `logic/` stays free of Qt and SQLite side effects
- `bootstrap/` stays thin and startup-focused

## Main Files

- `ui/main_window.py`
  - Main window state and end-to-end interaction flow
- `ui/list_model.py`
  - Experiment list labels and list-model behavior
- `ui/plot_panel.py`
  - Reusable Matplotlib panel with axis-mode selectors
- `sql/db_ops.py`
  - Read-only database helpers and preload logic

## Reading Order

1. `ui/main_window.py`
2. `sql/db_ops.py`
3. `docs/LOAD_FLOW.md`
4. `logic/id_specs.py` or `logic/plotting.py` only when a specific helper needs to change
