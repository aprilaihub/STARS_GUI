# Architecture

## Runtime Path

`GUI_feature_switching/run.py` -> `bootstrap/qt_app.py` -> `ui/main_window.py`

## Design Goal

Match the newer GUI package layout used elsewhere in the repo:

- `ui/` owns Qt widgets and user flow
- `sql/` owns schema-aware database access
- `logic/` keeps reusable helpers and a thin facade over the fit engine
- `fitting_model/` owns the relocated single-experiment fit engine
- `bootstrap/` stays limited to startup configuration

## Main Files

- `ui/main_window.py`
  - Experiment filtering, metadata display, fit orchestration, and plotting.
- `sql/db_ops.py`
  - Updated schema validation, switching experiment preload, rate-config lookup, and compact-curve series loading.
- `logic/fitting.py`
  - Thin facade used by the GUI to access the structured fit engine.
- `fitting_model/engine.py`
  - Relocated single-experiment switching-fit core formerly kept at the package root.
