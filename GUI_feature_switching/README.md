# GUI_feature_switching

Structured PyQt GUI for switching-fit inspection and compact-model plotting on top of `Database_NEW_V2.db`.

## Run

Install dependencies:

```bash
pip install -r GUI_feature_switching/requirements.txt
```

Start the GUI:

```bash
python GUI_feature_switching/run.py
```

Pass a database path if you want to open a specific file immediately:

```bash
python GUI_feature_switching/run.py path/to/database.db
```

## Current Behavior

- If no path is passed, the GUI tries to find a default `Database_NEW_V2.db`; otherwise it falls back to `File -> Open Database...`
- The experiment list only shows experiments that have `Features_RS_switching_rate_cal_result` rows
- When visible, experiment `43003` is the preferred default selection
- The metadata panel shows experiment, device/function, and switching-rate-config details
- The fit engine now lives in `fitting_model/engine.py`

## Package Layout

- `bootstrap/`
  - Qt startup and app-level constants
- `ui/`
  - Main window and experiment list model
- `sql/`
  - Schema validation, metadata preload, and series lookup
- `logic/`
  - Thin facade and pure helpers
- `fitting_model/`
  - Single-experiment switching-fit engine used by the GUI

## Docs

- `docs/ARCHITECTURE.md`
  - Runtime path, responsibilities, and fit flow
