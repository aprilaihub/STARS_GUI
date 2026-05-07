"""Main window for the STARS raw-data GUI."""

from __future__ import annotations

import csv
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import matplotlib
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from ..bootstrap.config import (
    AUTO_PLOT_FIRST_ROW,
    IV_PLOT_STYLE,
    LIST_SHOW_LIMIT,
    META_PROGRESS_EVERY,
    PLOT_MODE,
    PLOT1_X_DEFAULT,
    PLOT1_Y_DEFAULT,
    PLOT2_X_DEFAULT,
    PLOT2_Y_DEFAULT,
    PLOT3_X_DEFAULT,
    PLOT3_Y_DEFAULT,
    PRELOAD_ALL_METADATA,
    PRINT_TIMING,
)
from ..logic.id_specs import in_spec, looks_like_id_spec, parse_exp_id_spec
from ..logic.plotting import apply_mode, label_mode
from ..sql.db_ops import (
    build_function_row_cache,
    default_database_picker_dir,
    export_table_by_ids,
    fetch_experiment_points,
    fetch_layer_ids,
    fetch_single_row_by_link,
    function_link_column,
    preload_metadata_cache,
    resolve_function_table,
    validate_database_path,
)
from .list_model import ExperimentListModel
from .plot_panel import MplPanel

IdFilterSpec = tuple[set[int], list[tuple[int, int]]]
ExportStep = tuple[str, str, list[int], str, str]
MetadataFieldSpec = tuple[str, str]


@dataclass(frozen=True)
class FilterState:
    name_text: str
    experiment_id_text: str
    device_id_text: str
    restrict_experiment_id: bool
    restrict_device_id: bool
    recipe: Any
    die_number: Any
    subdie_area: Any
    wordline: Any
    bitline: Any
    function_type: Any


class MainWindow(QtWidgets.QMainWindow):
    NO_DATABASE_MESSAGE = "No database loaded. Use File > Open Database..."
    NO_MATCHING_EXPERIMENTS_MESSAGE = "No experiments match the current filters."
    NO_VALID_POINTS_MESSAGE = "No valid data points are available for the current selection."

    EXPERIMENT_METADATA_FIELDS: tuple[MetadataFieldSpec, ...] = (
        ("experiment_id", "id"),
        ("experiment_name", "experiment_name"),
        ("user_name", "user_name"),
        ("notes", "notes"),
        ("created_at", "created_at"),
    )
    FUNCTION_MAPPING_FIELDS: tuple[MetadataFieldSpec, ...] = (
        ("function_type", "function_type"),
        ("function_config_id", "function_config_id"),
        ("function_config_notes", "function_config_notes"),
    )
    DEVICE_HIERARCHY_FIELDS: tuple[MetadataFieldSpec, ...] = (
        ("recipe_name", "recipe_name"),
        ("die_number", "die_number"),
        ("die_type", "die_type"),
        ("cross_sectional_area_um2", "cross_sectional_area_um2"),
        ("wordline", "wordline"),
        ("bitline", "bitline"),
        ("wafer_name", "wafer_name"),
        ("lot", "lot"),
        ("diameter_mm", "diameter_mm"),
    )

    def __init__(self, db_path: Optional[str] = None):
        super().__init__()

        self._init_database_state()
        self._init_runtime_state()

        self.resize(1600, 900)
        self._set_window_title()
        self._build_file_menu()
        self._build_ui()
        self._connect_signals()

        self._reset_loaded_data_state(clear_filters=True)
        self._show_idle_state(self.NO_DATABASE_MESSAGE)
        self.statusBar().showMessage(self.NO_DATABASE_MESSAGE)
        self._open_initial_database(db_path)

    # Startup wiring

    def _init_database_state(self) -> None:
        self.db_path = ""
        self.conn: Optional[sqlite3.Connection] = None
        self.tables = set()
        self.table_cols: Dict[str, set] = {}
        self.experiment_cols = set()
        self.function_config_cols = set()

    def _init_runtime_state(self) -> None:
        self.meta_rows: list[Dict[str, Any]] = []
        self.meta_by_eid: Dict[int, Dict[str, Any]] = {}
        self.function_row_cache: Dict[tuple[str, int], Dict[str, Any]] = {}

        self._uni_recipe = set()
        self._uni_die = set()
        self._uni_area = set()
        self._uni_wl = set()
        self._uni_bl = set()
        self._uni_fun = set()

        self._suppress_selection = False
        self._last_selected_eids: list[int] = []
        self._points_cache: Dict[int, Dict[str, np.ndarray]] = {}

    def _build_ui(self) -> None:
        self._build_filter_controls()

        self.exp_model = ExperimentListModel(meta_by_eid=self.meta_by_eid, eid_list=[])
        self.list_view.setModel(self.exp_model)

        left_panel = self._build_left_panel()
        plot_panel = self._build_plot_panel_column()
        metadata_panel = self._build_metadata_panel()
        splitter = self._build_main_splitter(left_panel, plot_panel, metadata_panel)
        self._build_central_widget(splitter)

    def _build_filter_controls(self) -> None:
        self.recipe_combo = self._create_filter_combo("Recipe: All")
        self.die_combo = self._create_filter_combo("Die Number: All")
        self.subdie_combo = self._create_filter_combo("Subdie Area (um^2): All")
        self.wordline_combo = self._create_filter_combo("Wordline: All")
        self.bitline_combo = self._create_filter_combo("Bitline: All")
        self.function_combo = self._create_filter_combo("Function Type: All")

        self.filter_name_edit = QtWidgets.QLineEdit()
        self.filter_name_edit.setPlaceholderText("Experiment name contains...")

        self.filter_id_edit = QtWidgets.QLineEdit()
        self.filter_id_edit.setPlaceholderText(
            'Experiment ID: exact if checked, substring if unchecked, or list/range: "1,2,23-100,200"'
        )
        self.filter_id_restrict_cb = self._create_exact_checkbox()

        self.filter_device_edit = QtWidgets.QLineEdit()
        self.filter_device_edit.setPlaceholderText(
            'Device ID: exact if checked, substring if unchecked, or list/range: "1,2,23-100,200"'
        )
        self.filter_device_restrict_cb = self._create_exact_checkbox()

        self.reload_btn = QtWidgets.QPushButton("Refresh List")
        self.export_btn = QtWidgets.QPushButton("Export Selection to CSV")

        self.list_view = QtWidgets.QListView()
        self.list_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setLayoutMode(QtWidgets.QListView.Batched)
        self.list_view.setBatchSize(2000)
        self.list_view.setTextElideMode(QtCore.Qt.ElideRight)

    def _build_left_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)

        layout.addWidget(QtWidgets.QLabel("Filters"))
        for widget in (
            self.recipe_combo,
            self.die_combo,
            self.subdie_combo,
            self.wordline_combo,
            self.bitline_combo,
            self.function_combo,
            self.filter_name_edit,
        ):
            layout.addWidget(widget)

        layout.addWidget(self._create_exact_filter_row(self.filter_id_edit, self.filter_id_restrict_cb))
        layout.addWidget(self._create_exact_filter_row(self.filter_device_edit, self.filter_device_restrict_cb))
        layout.addWidget(self.reload_btn)
        layout.addWidget(QtWidgets.QLabel("Experiments (single or multi-select)"))
        layout.addWidget(self.list_view, stretch=1)
        layout.addWidget(self.export_btn)

        return panel

    def _build_plot_panel_column(self) -> QtWidgets.QWidget:
        self.plot_v = MplPanel(
            "Plot 1: Voltage vs. Index (amplitude_V or read_voltage_V)",
            PLOT1_X_DEFAULT,
            PLOT1_Y_DEFAULT,
        )
        self.plot_logr = MplPanel("Plot 2: Resistance vs. Index", PLOT2_X_DEFAULT, PLOT2_Y_DEFAULT)
        self.plot_iv = MplPanel(
            "Plot 3: I-V (derived from I = V / R; current is not stored in the schema)",
            PLOT3_X_DEFAULT,
            PLOT3_Y_DEFAULT,
        )

        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_v, stretch=1)
        layout.addWidget(self.plot_logr, stretch=1)
        layout.addWidget(self.plot_iv, stretch=1)
        return panel

    def _build_metadata_panel(self) -> QtWidgets.QWidget:
        self.meta_table = QtWidgets.QTableWidget()
        self.meta_table.setColumnCount(2)
        self.meta_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.meta_table.horizontalHeader().setStretchLastSection(True)
        self.meta_table.verticalHeader().setVisible(False)
        self.meta_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.addWidget(QtWidgets.QLabel("Metadata (experiment, hierarchy, and Function_* row)"))
        layout.addWidget(self.meta_table, stretch=1)
        return panel

    def _build_main_splitter(
        self,
        left_panel: QtWidgets.QWidget,
        plot_panel: QtWidgets.QWidget,
        metadata_panel: QtWidgets.QWidget,
    ) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(plot_panel)
        splitter.addWidget(metadata_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setHandleWidth(8)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([450, 900, 450])
        return splitter

    def _build_central_widget(self, splitter: QtWidgets.QSplitter) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        self.db_path_label = QtWidgets.QLabel("Database: Not loaded")
        self.db_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.db_path_label.setWordWrap(True)

        layout.addWidget(self.db_path_label)
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.reload_btn.clicked.connect(self.reload_experiment_list)
        self.export_btn.clicked.connect(self.export_selected_to_csv)

        for combo in self._filter_combos():
            combo.currentIndexChanged.connect(self.reload_experiment_list)

        for line_edit in (self.filter_name_edit, self.filter_id_edit, self.filter_device_edit):
            line_edit.returnPressed.connect(self.reload_experiment_list)

        self.list_view.selectionModel().selectionChanged.connect(self.on_selection_changed_view)

        for panel in (self.plot_v, self.plot_logr, self.plot_iv):
            panel.combo_x.currentIndexChanged.connect(self.replot_from_cache)
            panel.combo_y.currentIndexChanged.connect(self.replot_from_cache)

    def _open_initial_database(self, db_path: Optional[str]) -> None:
        if db_path:
            self.load_database(db_path)
        else:
            QtCore.QTimer.singleShot(0, self.open_database_dialog)

    def _create_filter_combo(self, empty_label: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.addItem(empty_label, "")
        return combo

    def _create_exact_checkbox(self) -> QtWidgets.QCheckBox:
        checkbox = QtWidgets.QCheckBox("Exact")
        checkbox.setChecked(True)
        return checkbox

    def _create_exact_filter_row(
        self,
        line_edit: QtWidgets.QLineEdit,
        checkbox: QtWidgets.QCheckBox,
    ) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, stretch=1)
        layout.addWidget(checkbox)
        return row

    def _filter_combos(self) -> tuple[QtWidgets.QComboBox, ...]:
        return (
            self.recipe_combo,
            self.die_combo,
            self.subdie_combo,
            self.wordline_combo,
            self.bitline_combo,
            self.function_combo,
        )

    def _filter_combo_specs(self):
        return (
            (self.recipe_combo, "Recipe: All", self._uni_recipe, str),
            (self.die_combo, "Die Number: All", self._uni_die, int),
            (self.subdie_combo, "Subdie Area (um^2): All", self._uni_area, int),
            (self.wordline_combo, "Wordline: All", self._uni_wl, int),
            (self.bitline_combo, "Bitline: All", self._uni_bl, int),
            (self.function_combo, "Function Type: All", self._uni_fun, str),
        )

    # Window shell

    def _set_window_title(self):
        suffix = os.path.basename(self.db_path) if self.db_path else "No Database Loaded"
        self.setWindowTitle(f"Raw Data GUI - {suffix}")

    def _build_file_menu(self):
        file_menu = self.menuBar().addMenu("&File")

        open_action = QtWidgets.QAction("Open Database...", self)
        open_action.setShortcut(QtGui.QKeySequence.Open)
        open_action.triggered.connect(self.open_database_dialog)
        file_menu.addAction(open_action)

        reload_action = QtWidgets.QAction("Reload Current Database", self)
        reload_action.triggered.connect(self.reload_current_database)
        file_menu.addAction(reload_action)

        file_menu.addSeparator()

        exit_action = QtWidgets.QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _default_open_dir(self) -> str:
        if self.db_path and os.path.exists(self.db_path):
            return os.path.dirname(self.db_path)
        return default_database_picker_dir()

    def _update_database_banner(self):
        self._set_window_title()
        if self.db_path:
            self.db_path_label.setText(f"Database: {self.db_path}")
        else:
            self.db_path_label.setText("Database: Not loaded")

    def _show_idle_state(self, message: str):
        self.plot_v.clear_with_msg(message)
        self.plot_logr.clear_with_msg(message)
        self.plot_iv.clear_with_msg(message)
        self.meta_table.setRowCount(0)

    def _show_plot_message(self, message: str) -> None:
        self.plot_v.clear_with_msg(message)
        self.plot_logr.clear_with_msg(message)
        self.plot_iv.clear_with_msg(message)

    def _set_filter_combo_signals_blocked(self, blocked: bool) -> None:
        for combo in self._filter_combos():
            combo.blockSignals(blocked)

    def _populate_empty_filter_options(self):
        self._set_filter_combo_signals_blocked(True)
        try:
            for combo, empty_label, _, _ in self._filter_combo_specs():
                combo.clear()
                combo.addItem(empty_label, "")
        finally:
            self._set_filter_combo_signals_blocked(False)

    def _reset_loaded_data_state(self, clear_filters: bool):
        self.meta_rows.clear()
        self.meta_by_eid.clear()
        self.function_row_cache.clear()
        self._uni_recipe.clear()
        self._uni_die.clear()
        self._uni_area.clear()
        self._uni_wl.clear()
        self._uni_bl.clear()
        self._uni_fun.clear()
        self._last_selected_eids = []
        self._points_cache.clear()

        self._suppress_selection = True
        try:
            self.exp_model.set_eids([])
            self.list_view.clearSelection()
        finally:
            self._suppress_selection = False

        self.meta_table.setRowCount(0)
        self._populate_empty_filter_options()

        if clear_filters:
            self.filter_name_edit.clear()
            self.filter_id_edit.clear()
            self.filter_device_edit.clear()
            self.filter_id_restrict_cb.setChecked(True)
            self.filter_device_restrict_cb.setChecked(True)

    # Database lifecycle

    def open_database_dialog(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Database File",
            self._default_open_dir(),
            "SQLite Database Files (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if file_path:
            self.load_database(file_path)

    def reload_current_database(self):
        if not self.db_path:
            self.open_database_dialog()
            return
        self.load_database(self.db_path)

    def load_database(self, db_path: str) -> bool:
        try:
            conn, tables, table_cols, experiment_cols, function_config_cols = validate_database_path(db_path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Open Database",
                f"Failed to open the selected database.\n\nPath:\n{db_path}\n\nReason:\n{exc}",
            )
            return False

        old_conn = self.conn
        self.conn = conn
        self.db_path = os.path.abspath(db_path)
        self.tables = tables
        self.table_cols = table_cols
        self.experiment_cols = experiment_cols
        self.function_config_cols = function_config_cols

        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass

        self._reset_loaded_data_state(clear_filters=True)
        self._update_database_banner()

        try:
            if PRELOAD_ALL_METADATA:
                self._load_all_metadata_once()
                self._init_filter_options_from_cache()
            else:
                raise RuntimeError("This version expects PRELOAD_ALL_METADATA=True.")

            self.reload_experiment_list()
            if not self.meta_rows:
                self._show_idle_state("This database contains no experiments.")

            self.statusBar().showMessage(f"Loaded database: {self.db_path}", 5000)
            return True
        except Exception as exc:
            self._show_idle_state("Failed to load the selected database.")
            QtWidgets.QMessageBox.critical(
                self,
                "Load Database",
                f"The database was opened, but the GUI could not finish loading it.\n\nReason:\n{exc}",
            )
            return False

    def closeEvent(self, event):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        super().closeEvent(event)

    def _cols(self, table: str) -> set:
        return self.table_cols.get(table, set())

    def _function_link_column(self, function_table: str):
        return function_link_column(function_table, self.table_cols)

    def _fetch_function_config_ids(self, eids: list[int]) -> list[int]:
        config_ids = set()
        for eid in sorted({int(x) for x in eids}):
            data = self.meta_by_eid.get(eid) or {}
            if data.get("function_config_id") is not None:
                config_ids.add(int(data["function_config_id"]))
        return sorted(config_ids)

    def _prime_function_row_cache(self) -> None:
        self.function_row_cache = build_function_row_cache(
            conn=self.conn,
            tables=self.tables,
            table_cols=self.table_cols,
        )

    def _load_all_metadata_once(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            prog = QtWidgets.QProgressDialog(
                "Loading metadata (experiments and device hierarchy)...",
                "Cancel",
                0,
                0,
                self,
            )
            prog.setWindowModality(QtCore.Qt.WindowModal)
            prog.setMinimumDuration(0)
            result = preload_metadata_cache(
                conn=self.conn,
                table_cols=self.table_cols,
                experiment_cols=self.experiment_cols,
                function_config_cols=self.function_config_cols,
                progress_every=META_PROGRESS_EVERY,
                on_total=prog.setMaximum,
                on_progress=prog.setValue,
                should_cancel=prog.wasCanceled,
            )
            prog.setValue(result["loaded_rows"] if result["total"] else 0)

            self.meta_rows = result["meta_rows"]
            self.meta_by_eid.clear()
            self.meta_by_eid.update(result["meta_by_eid"])
            self._uni_recipe = result["unique_values"]["recipe"]
            self._uni_die = result["unique_values"]["die"]
            self._uni_area = result["unique_values"]["area"]
            self._uni_wl = result["unique_values"]["wordline"]
            self._uni_bl = result["unique_values"]["bitline"]
            self._uni_fun = result["unique_values"]["function"]

            self._prime_function_row_cache()

            if PRINT_TIMING:
                print(f"[TIMING] preload_metadata: n={len(self.meta_rows)} time={result['elapsed_s']:.3f}s")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _init_filter_options_from_cache(self):
        self._set_filter_combo_signals_blocked(True)
        try:
            for combo, empty_label, values, cast in self._filter_combo_specs():
                combo.clear()
                combo.addItem(empty_label, "")
                for value in sorted(values):
                    combo.addItem(str(value), cast(value))
        finally:
            self._set_filter_combo_signals_blocked(False)

    # Filtering and selection

    def on_selection_changed_view(self, selected, deselected):
        if self._suppress_selection:
            return

        indexes = self.list_view.selectionModel().selectedIndexes()
        if not indexes:
            return

        eids = [int(self.exp_model.data(index, QtCore.Qt.UserRole)) for index in indexes]
        eids.sort()
        self.select_experiments(eids)

    def _current_filters(self) -> FilterState:
        return FilterState(
            name_text=self.filter_name_edit.text().strip(),
            experiment_id_text=self.filter_id_edit.text().strip(),
            device_id_text=self.filter_device_edit.text().strip(),
            restrict_experiment_id=self.filter_id_restrict_cb.isChecked(),
            restrict_device_id=self.filter_device_restrict_cb.isChecked(),
            recipe=self.recipe_combo.currentData(),
            die_number=self.die_combo.currentData(),
            subdie_area=self.subdie_combo.currentData(),
            wordline=self.wordline_combo.currentData(),
            bitline=self.bitline_combo.currentData(),
            function_type=self.function_combo.currentData(),
        )

    def _parse_optional_id_spec(self, raw_text: str) -> IdFilterSpec:
        if raw_text and looks_like_id_spec(raw_text):
            singles, ranges = parse_exp_id_spec(raw_text)
            return set(singles), ranges
        return set(), []

    def _matches_numeric_filter(
        self,
        value: int,
        raw_text: str,
        restrict_exact: bool,
        singles: set[int],
        ranges: list[tuple[int, int]],
    ) -> bool:
        if singles or ranges:
            return in_spec(value, singles, ranges)
        if not raw_text:
            return True

        token = raw_text.strip()
        if token.startswith("~"):
            return token[1:].strip() in str(value)
        if restrict_exact and token.isdigit():
            return value == int(token)
        return token in str(value)

    def _row_matches_filters(
        self,
        data: Dict[str, Any],
        filters: FilterState,
        experiment_spec: IdFilterSpec,
        device_spec: IdFilterSpec,
    ) -> bool:
        if filters.recipe and str(data.get("recipe_name", "")) != str(filters.recipe):
            return False
        if filters.die_number not in (None, "") and data.get("die_number") != int(filters.die_number):
            return False
        if filters.subdie_area not in (None, "") and data.get("cross_sectional_area_um2") != int(filters.subdie_area):
            return False
        if filters.wordline not in (None, "") and data.get("wordline") != int(filters.wordline):
            return False
        if filters.bitline not in (None, "") and data.get("bitline") != int(filters.bitline):
            return False
        if filters.function_type and str(data.get("function_type", "")) != str(filters.function_type):
            return False

        if filters.name_text:
            name = data.get("experiment_name") or ""
            if filters.name_text not in name:
                return False

        if not self._matches_numeric_filter(
            value=int(data.get("experiment_id")),
            raw_text=filters.experiment_id_text,
            restrict_exact=filters.restrict_experiment_id,
            singles=experiment_spec[0],
            ranges=experiment_spec[1],
        ):
            return False

        if not self._matches_numeric_filter(
            value=int(data.get("device_id")),
            raw_text=filters.device_id_text,
            restrict_exact=filters.restrict_device_id,
            singles=device_spec[0],
            ranges=device_spec[1],
        ):
            return False

        return True

    def _set_visible_experiments(self, eids: list[int]) -> None:
        self._suppress_selection = True
        try:
            self.exp_model.set_eids(eids)
            self.list_view.clearSelection()
            self._last_selected_eids = []
            self._points_cache.clear()
        finally:
            self._suppress_selection = False

    def _auto_select_first_experiment(self, first_eid: int) -> None:
        index0 = self.exp_model.index(0, 0)
        self.list_view.setCurrentIndex(index0)
        self.list_view.selectionModel().select(
            index0,
            QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
        )
        self.select_experiments([first_eid])

    def reload_experiment_list(self):
        t0 = time.perf_counter()

        if self.conn is None:
            self.statusBar().showMessage(self.NO_DATABASE_MESSAGE)
            self._show_idle_state(self.NO_DATABASE_MESSAGE)
            return

        if not PRELOAD_ALL_METADATA:
            raise RuntimeError("This version expects PRELOAD_ALL_METADATA=True.")

        filters = self._current_filters()
        experiment_spec = self._parse_optional_id_spec(filters.experiment_id_text)
        device_spec = self._parse_optional_id_spec(filters.device_id_text)

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            t_filter0 = time.perf_counter()
            matched_eids = [
                int(data["experiment_id"])
                for data in self.meta_rows
                if self._row_matches_filters(data, filters, experiment_spec, device_spec)
            ]
            t_filter1 = time.perf_counter()

            total = len(matched_eids)
            shown_eids = matched_eids[:LIST_SHOW_LIMIT]
            t_slice = time.perf_counter()

            t_model0 = time.perf_counter()
            self._set_visible_experiments(shown_eids)
            t_model1 = time.perf_counter()

            if AUTO_PLOT_FIRST_ROW and shown_eids:
                self._auto_select_first_experiment(shown_eids[0])

            if not shown_eids:
                self._show_idle_state(self.NO_MATCHING_EXPERIMENTS_MESSAGE)

            t_end = time.perf_counter()
            if PRINT_TIMING:
                print(
                    f"[TIMING] filter={t_filter1-t_filter0:.3f}s | slice={t_slice-t_filter1:.3f}s"
                    f" | model_set={t_model1-t_model0:.3f}s | matched={total} | shown={len(shown_eids)}"
                    f" | total={t_end-t0:.3f}s"
                )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # Plotting

    def select_experiments(self, eids: list[int]):
        if not eids:
            return

        self._last_selected_eids = list(eids)
        self._fetch_points_for_selection(eids)
        self.replot_from_cache()
        self.load_metadata(eids[-1])

    def _fetch_points_for_selection(self, eids: list[int]):
        if self.conn is None:
            return

        t0 = time.perf_counter()
        selected_eids = [int(x) for x in eids]
        selected_set = set(selected_eids)

        for cached_eid in list(self._points_cache.keys()):
            if cached_eid not in selected_set:
                self._points_cache.pop(cached_eid, None)

        missing_eids = [eid for eid in selected_eids if eid not in self._points_cache]

        fetched_exp_count = 0
        fetched_point_count = 0
        if missing_eids:
            fetched_cache, fetched_exp_count, fetched_point_count = fetch_experiment_points(self.conn, missing_eids)
            self._points_cache.update(fetched_cache)

        t1 = time.perf_counter()
        if PRINT_TIMING:
            print(
                f"[TIMING] fetch_points: selected={len(selected_eids)} "
                f"missing={len(missing_eids)} fetched_exp={fetched_exp_count} "
                f"fetched_pts={fetched_point_count} cache_size={len(self._points_cache)} "
                f"time={t1-t0:.3f}s"
            )

    def replot_from_cache(self):
        eids = self._last_selected_eids
        if not eids:
            return

        self.plot_v.ax.clear()
        self.plot_logr.ax.clear()
        self.plot_iv.ax.clear()

        colors = matplotlib.rcParams["axes.prop_cycle"].by_key()["color"]
        current_x_offset = 0

        x1_mode, y1_mode = self.plot_v.get_modes()
        x2_mode, y2_mode = self.plot_logr.get_modes()
        x3_mode, y3_mode = self.plot_iv.get_modes()

        any_plotted = False
        for i, eid in enumerate(eids):
            data = self._points_cache.get(int(eid))
            if not data:
                continue

            color = colors[i % len(colors)]
            voltage = data["V"]
            resistance = data["R"]
            current = data["I"]
            point_count = int(voltage.shape[0])

            if PLOT_MODE == "OVERLAP":
                x_base = np.arange(point_count, dtype=float)
            else:
                x_base = np.arange(point_count, dtype=float) + float(current_x_offset)

            if np.isfinite(voltage).any():
                x1 = apply_mode(x_base, x1_mode, is_index=True)
                y1 = apply_mode(voltage, y1_mode, is_index=False)
                self.plot_v.ax.plot(x1, y1, color=color, alpha=0.8, label=f"ID:{eid}")
                any_plotted = True

            if np.isfinite(resistance).any():
                x2 = apply_mode(x_base, x2_mode, is_index=True)
                y2 = apply_mode(resistance, y2_mode, is_index=False)
                self.plot_logr.ax.plot(x2, y2, color=color, alpha=0.8, label=f"ID:{eid}")
                any_plotted = True

            mask = np.isfinite(voltage) & np.isfinite(current)
            if mask.any():
                x3 = apply_mode(voltage[mask], x3_mode, is_index=False)
                y3 = apply_mode(current[mask], y3_mode, is_index=False)
                if IV_PLOT_STYLE == "LINE":
                    self.plot_iv.ax.plot(x3, y3, color=color, linewidth=1.2, alpha=0.7)
                else:
                    self.plot_iv.ax.scatter(x3, y3, color=color, s=6, alpha=0.6)
                any_plotted = True

            current_x_offset += point_count

        if not any_plotted:
            self._show_plot_message(self.NO_VALID_POINTS_MESSAGE)
            return

        self.plot_v.ax.set_xlabel(label_mode("index", x1_mode, is_index=True))
        self.plot_v.ax.set_ylabel(label_mode("V (V)", y1_mode, is_index=False))

        self.plot_logr.ax.set_xlabel(label_mode("index", x2_mode, is_index=True))
        self.plot_logr.ax.set_ylabel(label_mode("R (ohm)", y2_mode, is_index=False))

        self.plot_iv.ax.set_xlabel(label_mode("V (V)", x3_mode, is_index=False))
        self.plot_iv.ax.set_ylabel(label_mode("I (A)", y3_mode, is_index=False))

        for panel in (self.plot_v, self.plot_logr, self.plot_iv):
            panel.ax.grid(True, alpha=0.2)

        if len(eids) > 1:
            self.plot_logr.ax.legend(fontsize="x-small", loc="upper right", ncol=min(len(eids), 4))

        self.plot_iv.ensure_xlabel_visible(bottom=0.2)
        self.plot_v.canvas.draw_idle()
        self.plot_logr.canvas.draw_idle()
        self.plot_iv.canvas.draw_idle()

    # Metadata panel

    def load_metadata(self, experiment_id: int):
        self.meta_table.setRowCount(0)
        if self.conn is None:
            return

        row = self.meta_by_eid.get(int(experiment_id))
        if not row:
            self._append_meta("experiment_id", experiment_id)
            self._append_meta("meta", "Not found")
            return

        self._append_meta_section("Experiment")
        self._append_metadata_fields(row, self.EXPERIMENT_METADATA_FIELDS)

        self._append_meta_section("Function mapping")
        self._append_metadata_fields(row, self.FUNCTION_MAPPING_FIELDS)

        self._append_meta_section("Device hierarchy")
        self._append_metadata_fields(row, self.DEVICE_HIERARCHY_FIELDS)

        self._append_function_parameters(row, experiment_id)

    def _append_meta_section(self, title: str, value: str = "") -> None:
        self._append_meta(f"=== {title} ===", value)

    def _append_metadata_fields(self, row: Dict[str, Any], fields: tuple[MetadataFieldSpec, ...]) -> None:
        for key, label in fields:
            if key in row:
                self._append_meta(label, row[key])

    def _append_function_parameters(self, row: Dict[str, Any], experiment_id: int) -> None:
        function_table = resolve_function_table(row["function_type"], self.tables)
        if not function_table or function_table not in self.tables:
            self._append_meta_section("Function Parameters", "No matching Function_* table found.")
            return

        self._append_meta_section("Function Parameters")
        self._append_meta("(function table)", function_table)

        link_col = self._function_link_column(function_table)
        if not link_col:
            self._append_meta("(function row)", "Link column not found")
            return

        function_row, error = self._load_function_parameter_row(
            row=row,
            experiment_id=experiment_id,
            function_table=function_table,
            link_col=link_col,
        )
        if error:
            self._append_meta("(function query error)", error)
            return
        if not function_row:
            self._append_meta("(function row)", "Not found")
            return

        items = function_row.items() if isinstance(function_row, dict) else ((key, function_row[key]) for key in function_row.keys())
        for key, value in items:
            if key in ("id", "experiment_id", "function_config_id"):
                continue
            self._append_meta(key, value)

    def _load_function_parameter_row(
        self,
        row: Dict[str, Any],
        experiment_id: int,
        function_table: str,
        link_col: str,
    ) -> tuple[Any, Optional[str]]:
        link_value = row["function_config_id"] if link_col == "function_config_id" else experiment_id
        if link_value is None:
            return None, None

        function_row = None
        if link_col == "function_config_id":
            function_row = self.function_row_cache.get((row["function_type"], int(link_value)))

        if function_row is not None:
            return function_row, None

        try:
            function_row = fetch_single_row_by_link(
                conn=self.conn,
                table_name=function_table,
                link_col=link_col,
                link_value=link_value,
            )
        except Exception as exc:
            return None, str(exc)

        return function_row, None

    def _append_meta(self, field, value):
        row = self.meta_table.rowCount()
        self.meta_table.insertRow(row)
        self.meta_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(field)))
        self.meta_table.setItem(row, 1, QtWidgets.QTableWidgetItem("" if value is None else str(value)))

    # Export

    def _get_selected_eids_for_export(self) -> list[int]:
        if self._last_selected_eids:
            return sorted({int(x) for x in self._last_selected_eids})

        selection_model = self.list_view.selectionModel()
        if not selection_model:
            return []

        eids = []
        for index in selection_model.selectedIndexes():
            try:
                eids.append(int(self.exp_model.data(index, QtCore.Qt.UserRole)))
            except Exception:
                pass
        return sorted(set(eids))

    def _fetch_upstream_ids(self, eids: list[int]) -> Dict[str, list[int]]:
        out = {
            "device_id": set(),
            "subdie_id": set(),
            "die_id": set(),
            "wafer_id": set(),
            "recipe_id": set(),
        }
        if not eids:
            return {key: [] for key in out.keys()}

        for eid in sorted({int(x) for x in eids}):
            data = self.meta_by_eid.get(eid) or {}
            for key in out.keys():
                if data.get(key) is not None:
                    out[key].add(int(data[key]))

        return {key: sorted(value) for key, value in out.items()}

    def _choose_export_base_dir(self) -> str:
        return QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose Export Folder",
            os.path.dirname(self.db_path) if self.db_path else os.getcwd(),
        )

    def _build_export_output_dir(self, base_dir: str, eids: list[int]) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(base_dir, f"export_{timestamp}_n{len(eids)}_{eids[0]}-{eids[-1]}")

    def _write_selected_experiment_ids(self, out_dir: str, eids: list[int]) -> None:
        with open(os.path.join(out_dir, "selected_experiment_ids.txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(str(x) for x in eids) + "\n")

    def _build_export_steps(self, eids: list[int]) -> list[ExportStep]:
        upstream = self._fetch_upstream_ids(eids)
        function_config_ids = self._fetch_function_config_ids(eids)
        recipe_ids = upstream.get("recipe_id", [])
        layer_ids = fetch_layer_ids(self.conn, recipe_ids) if "Layer" in self.tables else []

        steps: list[ExportStep] = [("Experiment", "id", eids, "Experiment.csv", "id")]

        for table in sorted(self.tables):
            if table == "Experiment":
                continue
            cols = self._cols(table)
            if "experiment_id" in cols:
                order_by = "experiment_id, id" if "id" in cols else "experiment_id"
                steps.append((table, "experiment_id", eids, f"{table}.csv", order_by))

        if function_config_ids:
            if "Function_Config" in self.tables:
                steps.append(("Function_Config", "id", function_config_ids, "Function_Config.csv", "id"))
            for table in sorted(self.tables):
                if table in {"Experiment", "Function_Config"}:
                    continue
                cols = self._cols(table)
                if "function_config_id" in cols:
                    order_by = "function_config_id, id" if "id" in cols else "function_config_id"
                    steps.append((table, "function_config_id", function_config_ids, f"{table}.csv", order_by))

        for table, key in (
            ("Device", "device_id"),
            ("Subdie", "subdie_id"),
            ("Die", "die_id"),
            ("Wafer", "wafer_id"),
            ("Recipe", "recipe_id"),
        ):
            if table in self.tables and upstream.get(key):
                steps.append((table, "id", upstream[key], f"{table}.csv", "id"))

        if "Layer" in self.tables and recipe_ids:
            order_by = "recipe_id, id" if "id" in self._cols("Layer") else "recipe_id"
            steps.append(("Layer", "recipe_id", recipe_ids, "Layer.csv", order_by))

        if layer_ids:
            for table in sorted(self.tables):
                if table.startswith("Tool_") and "layer_id" in self._cols(table):
                    order_by = "layer_id, id" if "id" in self._cols(table) else "layer_id"
                    steps.append((table, "layer_id", layer_ids, f"{table}.csv", order_by))

        return steps

    def _run_export_steps(self, out_dir: str, steps: list[ExportStep], writer: csv.writer) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            prog = QtWidgets.QProgressDialog("Exporting selected data to CSV...", "Cancel", 0, len(steps), self)
            prog.setWindowModality(QtCore.Qt.WindowModal)
            prog.setMinimumDuration(0)

            for i, (table, id_col, ids, csv_name, order_by) in enumerate(steps, start=1):
                prog.setValue(i - 1)
                prog.setLabelText(f"Exporting {table}...")
                QtWidgets.QApplication.processEvents()
                if prog.wasCanceled():
                    break

                out_csv = os.path.join(out_dir, csv_name)
                rows = export_table_by_ids(
                    conn=self.conn,
                    table=table,
                    id_col=id_col,
                    ids=ids,
                    out_csv=out_csv,
                    order_by=order_by,
                    chunk_size=800,
                )

                if rows <= 0:
                    try:
                        if os.path.exists(out_csv):
                            os.remove(out_csv)
                    except Exception:
                        pass
                    continue

                writer.writerow([table, csv_name, rows])

            prog.setValue(len(steps))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def export_selected_to_csv(self):
        if self.conn is None:
            QtWidgets.QMessageBox.warning(self, "Export", "No database is loaded.")
            return

        eids = self._get_selected_eids_for_export()
        if not eids:
            QtWidgets.QMessageBox.warning(self, "Export", "No experiments are selected.")
            return

        base_dir = self._choose_export_base_dir()
        if not base_dir:
            return

        out_dir = self._build_export_output_dir(base_dir, eids)
        os.makedirs(out_dir, exist_ok=True)
        self._write_selected_experiment_ids(out_dir, eids)

        manifest_path = os.path.join(out_dir, "manifest.csv")
        steps = self._build_export_steps(eids)
        with open(manifest_path, "w", newline="", encoding="utf-8-sig") as manifest_file:
            writer = csv.writer(manifest_file)
            writer.writerow(["table", "csv_file", "rows_written"])
            self._run_export_steps(out_dir, steps, writer)

        QtWidgets.QMessageBox.information(
            self,
            "Export",
            f"Export complete.\n\nExperiments: {len(eids)}\nOutput folder: {out_dir}",
        )
