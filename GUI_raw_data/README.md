# STARS Raw Data GUI

PyQt GUI for browsing STARS experiment raw data from a SQLite database.

The current codebase is intentionally shallow:
- one main window class in `ui/main_window.py`
- one SQL access layer in `sql/db_ops.py`
- small pure helpers in `logic/`

## Quick Start

Install dependencies:

```bash
pip install -r GUI_raw_data/requirements.txt
```

Run the package entry:

```bash
python GUI_raw_data/run.py
```

Pass a database path if you already know which file to open:

```bash
python GUI_raw_data/run.py path/to/database.db
```

Legacy launcher still works:

```bash
python GUI_raw_data.py
```

## Read This First

If you are changing:
- UI flow, filters, plotting, metadata, or export: `ui/main_window.py`
- SQL queries or preload behavior: `sql/db_ops.py`
- experiment/device id parsing: `logic/id_specs.py`
- plot axis transforms: `logic/plotting.py`

## Package Layout

- `bootstrap/`
  - Qt app startup and shared config values.
- `ui/`
  - Window assembly, list model, and plot widget.
  - `main_window.py` now owns the full user flow end-to-end.
- `sql/`
  - All direct database access for validation, preload, point fetches, metadata lookup, and export.
- `logic/`
  - Pure helpers with no widget or database side effects.
- `tests/`
  - Import-level smoke check.
- `docs/`
  - Small focused docs for architecture, load flow, and file lookup.

## Current Cleanup State

- Old `ui/mixins/` behavior has been merged into `ui/main_window.py`.
- `GUI_raw_data.py` is only a compatibility launcher.
- Local Python cache files under this package are ignored via `GUI_raw_data/.gitignore`.
- The docs folder only keeps current-state documentation, not speculative rewrite notes.

## Docs

- `docs/ARCHITECTURE.md`: responsibilities and dependency direction.
- `docs/LOAD_FLOW.md`: what happens when a database is opened.
- `docs/PROJECT_MAP.md`: where to go for common edits.
