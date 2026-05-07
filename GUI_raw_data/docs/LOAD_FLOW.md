# Load Flow

This is the path that turns a selected SQLite file into usable GUI state.

## Database Entry

1. `run.py` passes an optional database path into `MainWindow`
2. If a path is provided, `_open_initial_database(...)` opens it immediately
3. If no path is provided, the GUI schedules `Open Database...` on startup and opens the picker at the Windows Desktop
4. The selected file is opened read-only by `sql/db_ops.py`

## Validation And Reset

1. `load_database(...)` validates the minimum schema needed by the GUI
2. Any previous selection, caches, and filter state are cleared
3. The database banner and window title are updated

## Metadata Preload

1. `_load_all_metadata_once()` performs the joined experiment/device/function preload
2. The preload populates:
   - `meta_rows`
   - `meta_by_eid`
   - filter dropdown value sets
   - `function_row_cache`
3. `_init_filter_options_from_cache()` fills the filter widgets from the preload result

## After Preload

1. `reload_experiment_list()` filters the in-memory metadata
2. The list model is reset with the matching experiment ids
3. The current selection drives metadata display and point fetches
4. Raw point data is fetched only for the current experiment

## Why The UI Stays Responsive

- Metadata preload happens once per opened database
- Filtering then runs in memory
- Plot point queries happen only for the current selection
