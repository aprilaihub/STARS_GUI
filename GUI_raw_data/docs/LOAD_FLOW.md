# Load Flow

This is the path that turns a selected SQLite file into a usable GUI state.

## Open Database

1. The user opens a file from `File -> Open Database...`, or passes a `.db` path on startup.
2. `MainWindow.load_database(...)` validates the file and inspects the schema.
3. Any previous UI state is cleared.
4. The database banner and window title are updated.

## Metadata Preload

1. `_load_all_metadata_once()` loads one joined metadata row per experiment.
2. The preload result populates:
   - `meta_rows`
   - `meta_by_eid`
   - unique values for each filter dropdown
   - `function_row_cache`
3. `_init_filter_options_from_cache()` fills the left-side filter combos.

## After Preload

1. `reload_experiment_list()` filters the preloaded metadata in memory.
2. The experiment list model is reset with the matching ids.
3. If auto-select is enabled, the first visible experiment is selected.
4. Point data is still fetched later, only for the current selection.

## Why Selection Feels Faster

- The expensive joined metadata read happens once per opened database.
- Filtering is then in memory.
- Plot point data is cached per selected experiment.

## If You Need To Change Load Behavior

Read in this order:
1. `ui/main_window.py`
2. `sql/db_ops.py`
