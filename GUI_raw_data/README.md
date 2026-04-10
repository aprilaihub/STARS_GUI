# GUI_raw_data

Structured PyQt GUI for browsing STARS raw experiment data from a SQLite database.

## Run

Install dependencies:

```bash
pip install -r GUI_raw_data/requirements.txt
```

Start the GUI:

```bash
python GUI_raw_data/run.py
```

If you do not pass a database path, the GUI opens its database picker at startup.

Open a specific database directly:

```bash
python GUI_raw_data/run.py path/to/database.db
```

Compatibility launcher:

```bash
python GUI_raw_data.py
```

## Package Layout

- `bootstrap/`
  - Qt startup and shared config values
- `ui/`
  - Main window, experiment list model, and reusable plot panel
- `sql/`
  - Read-only schema validation, metadata preload, point fetches, and export helpers
- `logic/`
  - Pure helpers for id parsing and plot transforms
- `tests/`
  - Minimal import smoke check
- `docs/`
  - Architecture, load flow, and edit map

## Main Behavior

- Database access is read-only
- The GUI opens a selected database path immediately, or shows a file picker if no path is provided
- Metadata is preloaded once and then filtered in memory
- Plot point data is fetched only for the current selection

## Docs

- `docs/ARCHITECTURE.md`
- `docs/LOAD_FLOW.md`
- `docs/PROJECT_MAP.md`
