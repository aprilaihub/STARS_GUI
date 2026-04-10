# Architecture

## Runtime Path

`run.py` -> `bootstrap/qt_app.py` -> `ui/main_window.py`

## Package Responsibilities

- `bootstrap/`
  - High-DPI setup and app constants such as default window size and preferred experiment id
- `ui/`
  - Window assembly, filter widgets, list refresh, metadata display, and plotting
- `sql/`
  - Read-only database validation, metadata preload, compact-series loading, and rate-config lookup
- `logic/`
  - Thin facade and helper functions with no widget code
- `fitting_model/`
  - Single-experiment switching-fit engine and plot-generation logic

## Load And Selection Flow

1. `MainWindow` receives an optional database path from `run.py`
2. If no path is passed, `sql/db_ops.find_default_db()` is used before falling back to `Open Database...`
3. `load_database(...)` validates the switching schema and preloads switching-only metadata
4. `reload_experiment_list()` filters the preloaded metadata in memory
5. The preferred selection order is:
   - current selection
   - current fitted experiment
   - experiment `43003`
   - first visible experiment
6. Running a fit calls `logic/fitting.py`, which forwards to `fitting_model/engine.py`

## Main Files

- `ui/main_window.py`
  - Main user flow, list filtering, fit orchestration, and plot rendering
- `sql/db_ops.py`
  - Switching schema validation, metadata preload, and compact-series fetches
- `logic/fitting.py`
  - Thin import surface for the fit engine
- `fitting_model/engine.py`
  - Switching-fit math, output summaries, and static 3D plot generation
