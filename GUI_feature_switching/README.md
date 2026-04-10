# Feature Switching GUI

Structured Qt GUI for switching-fit inspection on top of `Database_NEW_V2.db`.

## Run

```bash
python GUI_feature_switching/run.py
```

## Notes

- Database loading now follows the updated `Experiment -> Function_Config -> Function_*` schema.
- The experiment list is restricted to experiments that actually have `Features_RS_switching_rate_cal_result` rows.
- The right-side metadata panel shows both experiment/function metadata and the selected switching-rate config.
- `fitting_model/engine.py` owns the single-experiment fit engine used by the GUI.
