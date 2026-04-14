"""Main window for the STARS switching-fit GUI."""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib

matplotlib.use("Qt5Agg")

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from ..bootstrap.config import (
    DEFAULT_FEATURE_KEY,
    DEFAULT_HIDE_PURPLE,
    DEFAULT_LOG_R,
    DEFAULT_SHOW_RAW,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    LIST_SHOW_LIMIT,
    META_PROGRESS_EVERY,
)
from ..logic import fitting as core
from ..logic.id_specs import in_spec, looks_like_id_spec, parse_exp_id_spec
from ..sql.db_ops import (
    SeriesData,
    build_function_row_cache,
    fetch_rate_config_row,
    fetch_single_row_by_link,
    find_default_db,
    format_rate_config_label,
    function_link_column,
    list_rate_configs,
    load_experiment_series,
    preload_switching_metadata_cache,
    resolve_function_table,
    validate_switching_database_path,
)
from .list_model import ExperimentListModel

DEFAULT_VIEW_ELEV = 17.8
DEFAULT_VIEW_AZIM = 62.1
DEFAULT_VIEW_ROLL = 1.1

FIG_LEFT = 0.050
FIG_RIGHT = 0.998
FIG_BOTTOM = 0.028
FIG_TOP = 0.994
FIG_HSPACE = 0.12
GRID_HEIGHT_RATIOS = (0.46, 0.46, 0.62, 5.95)

AX3D_BOX_ASPECT = (2.00, 1.16, 1.02)
AX3D_ZOOM = 1.36
AX3D_X_SHIFT = -1
AX3D_Y_SHIFT = -0.018
AX3D_W_GROW = 2
AX3D_H_GROW = 0.026

MetadataFieldSpec = tuple[str, str]
IdFilterSpec = tuple[set[int], list[tuple[int, int]]]

FEATURE_SPECS = {
    "mu_dr": {
        "label": "mu_DR",
        "attr": "mu_dr",
        "color": "#1f77b4",
        "ylabel": "mu_DR (Ohm/pulse)",
    },
    "mean_y": {
        "label": "mean_y",
        "attr": "mean_y",
        "color": "#ff7f0e",
        "ylabel": "mean_y (Ohm)",
    },
    "dRdt": {
        "label": "dR/dt",
        "attr": "dRdt",
        "color": "#2ca02c",
        "ylabel": "dR/dt (Ohm/s)",
    },
    "sigma": {
        "label": "sigma_corr",
        "attr": "sigma",
        "color": "#d62728",
        "ylabel": "sigma_corr (Ohm)",
    },
    "relrate": {
        "label": "rel rate",
        "attr": "relrate",
        "color": "#8c564b",
        "ylabel": "rel rate (1/s)",
    },
}


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


class FitWorker(QtCore.QThread):
    ok = QtCore.pyqtSignal(object, object)
    fail = QtCore.pyqtSignal(str)

    def __init__(self, db_path: str, exp_id: int, config_id: Optional[int]):
        super().__init__()
        self.db_path = db_path
        self.exp_id = int(exp_id)
        self.config_id = int(config_id) if config_id is not None else None

    def run(self) -> None:
        try:
            bundle = core.fit_single_experiment(
                experiment_id=self.exp_id,
                db_path=Path(self.db_path),
                config_id=self.config_id,
            )
            conn = core.connect_ro(Path(self.db_path))
            try:
                series = load_experiment_series(conn, bundle.cfg_id, bundle.exp_id)
            finally:
                conn.close()
            self.ok.emit(bundle, series)
        except Exception as exc:
            self.fail.emit(str(exc))


class MainWindow(QtWidgets.QMainWindow):
    NO_DATABASE_MESSAGE = "No database loaded. Use File > Open Database..."
    NO_MATCHING_EXPERIMENTS_MESSAGE = "No switching experiments match the current filters."
    NO_EXPERIMENT_SELECTED_MESSAGE = "Select an experiment and click Fit Selected Experiment."
    NO_VALID_POINTS_MESSAGE = "No valid switching points are available for the current selection."

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
        ("cross_section_area_um2", "cross_section_area_um2"),
        ("wordline", "wordline"),
        ("bitline", "bitline"),
        ("wafer_name", "wafer_name"),
        ("lot", "lot"),
        ("diameter_mm", "diameter_mm"),
    )
    RATE_CONFIG_FIELDS: tuple[MetadataFieldSpec, ...] = (
        ("id", "config_id"),
        ("rs_id", "rs_id"),
        ("block_kind", "block_kind"),
        ("window_n", "window_n"),
        ("created_at", "created_at"),
        ("note", "note"),
        ("rs_doi", "rs_doi"),
        ("rs_note", "rs_note"),
    )

    def __init__(self, db_path: Optional[str] = None):
        super().__init__()

        self._init_database_state()
        self._init_runtime_state()

        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self._set_window_title()
        self._build_file_menu()
        self._build_ui()
        self._connect_signals()

        self._reset_loaded_data_state(clear_filters=True)
        self._show_plot_message(self.NO_DATABASE_MESSAGE)
        self._set_summary_text(self.NO_DATABASE_MESSAGE)
        self.statusBar().showMessage(self.NO_DATABASE_MESSAGE)
        self._open_initial_database(db_path)

    def _init_database_state(self) -> None:
        self.db_path = ""
        self.conn: Optional[sqlite3.Connection] = None
        self.tables = set()
        self.table_cols: Dict[str, set] = {}
        self.experiment_cols = set()
        self.function_config_cols = set()
        self.rate_configs: list[dict[str, Any]] = []
        self.rate_config_by_id: Dict[int, dict[str, Any]] = {}

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
        self._current_selected_eid: Optional[int] = None

        self.current_bundle: Optional[core.FitBundle] = None
        self.current_series: Optional[SeriesData] = None
        self.worker: Optional[FitWorker] = None
        self.ax3d = None
        self.last_view_text = "Current 3D view: N/A"

    def _build_ui(self) -> None:
        self._build_filter_controls()
        self.exp_model = ExperimentListModel(meta_by_eid=self.meta_by_eid, eid_list=[])
        self.list_view.setModel(self.exp_model)

        left_panel = self._build_left_panel()
        plot_panel = self._build_plot_panel()
        info_panel = self._build_info_panel()
        splitter = self._build_main_splitter(left_panel, plot_panel, info_panel)
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

        self.list_view = QtWidgets.QListView()
        self.list_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setLayoutMode(QtWidgets.QListView.Batched)
        self.list_view.setBatchSize(2000)
        self.list_view.setTextElideMode(QtCore.Qt.ElideRight)

        self.config_combo = QtWidgets.QComboBox()
        self.config_combo.addItem("Switching config: not loaded", None)

        self.show_raw_cb = QtWidgets.QCheckBox("Show raw datapoints (blue)")
        self.show_raw_cb.setChecked(DEFAULT_SHOW_RAW)

        self.hide_purple_raw_cb = QtWidgets.QCheckBox("Hide points in purple-gated region")
        self.hide_purple_raw_cb.setChecked(DEFAULT_HIDE_PURPLE)

        self.log_r_cb = QtWidgets.QCheckBox("Compact resistance uses log-y")
        self.log_r_cb.setChecked(DEFAULT_LOG_R)

        self.feature_combo = QtWidgets.QComboBox()
        self.feature_combo.addItem("mu_DR", "mu_dr")
        self.feature_combo.addItem("mean_y", "mean_y")
        self.feature_combo.addItem("dR/dt", "dRdt")
        self.feature_combo.addItem("sigma_corr", "sigma")
        self.feature_combo.addItem("rel rate", "relrate")
        feature_index = max(0, self.feature_combo.findData(DEFAULT_FEATURE_KEY))
        self.feature_combo.setCurrentIndex(feature_index)

        self.fit_btn = QtWidgets.QPushButton("Fit Selected Experiment")
        self.replot_btn = QtWidgets.QPushButton("Replot Current Fit")
        self.view_btn = QtWidgets.QPushButton("Print 3D Angle")
        self.save_btn = QtWidgets.QPushButton("Save PNG")

        self.status_label = QtWidgets.QLabel(self.NO_EXPERIMENT_SELECTED_MESSAGE)
        self.status_label.setWordWrap(True)

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
        layout.addWidget(QtWidgets.QLabel("Switching Experiments"))
        layout.addWidget(self.list_view, stretch=1)

        fit_group = QtWidgets.QGroupBox("Switching Fit")
        fit_layout = QtWidgets.QVBoxLayout(fit_group)
        fit_layout.addWidget(self.config_combo)
        fit_layout.addWidget(self.show_raw_cb)
        fit_layout.addWidget(self.hide_purple_raw_cb)
        fit_layout.addWidget(self.log_r_cb)
        fit_layout.addWidget(QtWidgets.QLabel("Feature for compact plot 3"))
        fit_layout.addWidget(self.feature_combo)
        fit_layout.addWidget(self.fit_btn)
        fit_layout.addWidget(self.replot_btn)
        fit_layout.addWidget(self.view_btn)
        fit_layout.addWidget(self.save_btn)
        layout.addWidget(fit_group)
        layout.addWidget(self.status_label)

        return panel

    def _build_plot_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.figure = Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.canvas.mpl_connect("scroll_event", self._on_scroll_zoom)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, stretch=1)
        return panel

    def _build_info_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)

        tabs = QtWidgets.QTabWidget()

        self.summary_box = QtWidgets.QPlainTextEdit()
        self.summary_box.setReadOnly(True)
        tabs.addTab(self.summary_box, "Fit Summary")

        self.meta_table = QtWidgets.QTableWidget()
        self.meta_table.setColumnCount(2)
        self.meta_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.meta_table.horizontalHeader().setStretchLastSection(True)
        self.meta_table.verticalHeader().setVisible(False)
        self.meta_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        tabs.addTab(self.meta_table, "Metadata")

        layout.addWidget(tabs)
        return panel

    def _build_main_splitter(
        self,
        left_panel: QtWidgets.QWidget,
        plot_panel: QtWidgets.QWidget,
        info_panel: QtWidgets.QWidget,
    ) -> QtWidgets.QSplitter:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(plot_panel)
        splitter.addWidget(info_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setHandleWidth(8)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([420, 980, 460])
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
        self.fit_btn.clicked.connect(self.run_fit_for_selected_experiment)
        self.replot_btn.clicked.connect(self.on_replot)
        self.view_btn.clicked.connect(self.on_log_view_angle)
        self.save_btn.clicked.connect(self.on_save_png)

        for combo in self._filter_combos():
            combo.currentIndexChanged.connect(self.reload_experiment_list)

        for line_edit in (self.filter_name_edit, self.filter_id_edit, self.filter_device_edit):
            line_edit.returnPressed.connect(self.reload_experiment_list)

        self.config_combo.currentIndexChanged.connect(self._on_rate_config_changed)
        self.show_raw_cb.toggled.connect(self._on_plot_option_changed)
        self.hide_purple_raw_cb.toggled.connect(self._on_plot_option_changed)
        self.log_r_cb.toggled.connect(self._on_plot_option_changed)
        self.feature_combo.currentIndexChanged.connect(self._on_plot_option_changed)

        self.list_view.selectionModel().selectionChanged.connect(self.on_selection_changed_view)
        self.list_view.doubleClicked.connect(lambda _index: self.run_fit_for_selected_experiment())

    def _open_initial_database(self, db_path: Optional[str]) -> None:
        if db_path:
            self.load_database(db_path)
            return
        default_db = find_default_db()
        if default_db:
            self.load_database(default_db)
            return
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

    def _set_window_title(self) -> None:
        suffix = os.path.basename(self.db_path) if self.db_path else "No Database Loaded"
        self.setWindowTitle(f"Feature Switching GUI - {suffix}")

    def _build_file_menu(self) -> None:
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
        fallback = find_default_db()
        if fallback:
            return os.path.dirname(fallback)
        return os.getcwd()

    def _update_database_banner(self) -> None:
        self._set_window_title()
        if self.db_path:
            self.db_path_label.setText(f"Database: {self.db_path}")
        else:
            self.db_path_label.setText("Database: Not loaded")

    def _show_plot_message(self, message: str) -> None:
        self.figure.clear()
        ax = self.figure.add_subplot(1, 1, 1)
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        self.ax3d = None
        self.canvas.draw_idle()

    def _set_summary_text(self, text: str) -> None:
        self.summary_box.setPlainText(text.strip())
        bar = self.summary_box.verticalScrollBar()
        bar.setValue(0)

    def _set_status(self, text: str, timeout_ms: int = 5000) -> None:
        self.status_label.setText(text)
        self.statusBar().showMessage(text, timeout_ms)

    def _set_filter_combo_signals_blocked(self, blocked: bool) -> None:
        for combo in self._filter_combos():
            combo.blockSignals(blocked)

    def _populate_empty_filter_options(self) -> None:
        self._set_filter_combo_signals_blocked(True)
        try:
            for combo, empty_label, _, _ in self._filter_combo_specs():
                combo.clear()
                combo.addItem(empty_label, "")
        finally:
            self._set_filter_combo_signals_blocked(False)

    def _clear_rate_configs(self) -> None:
        self.config_combo.blockSignals(True)
        try:
            self.config_combo.clear()
            self.config_combo.addItem("Switching config: not loaded", None)
        finally:
            self.config_combo.blockSignals(False)

    def _reset_loaded_data_state(self, clear_filters: bool) -> None:
        self.meta_rows.clear()
        self.meta_by_eid.clear()
        self.function_row_cache.clear()
        self.rate_configs = []
        self.rate_config_by_id.clear()
        self._uni_recipe.clear()
        self._uni_die.clear()
        self._uni_area.clear()
        self._uni_wl.clear()
        self._uni_bl.clear()
        self._uni_fun.clear()
        self._current_selected_eid = None

        self.current_bundle = None
        self.current_series = None
        self.worker = None
        self.last_view_text = "Current 3D view: N/A"

        self._suppress_selection = True
        try:
            self.exp_model.set_eids([])
            self.list_view.clearSelection()
        finally:
            self._suppress_selection = False

        self.meta_table.setRowCount(0)
        self._set_summary_text(self.NO_EXPERIMENT_SELECTED_MESSAGE)
        self._populate_empty_filter_options()
        self._clear_rate_configs()
        self._show_plot_message(self.NO_EXPERIMENT_SELECTED_MESSAGE)

        if clear_filters:
            self.filter_name_edit.clear()
            self.filter_id_edit.clear()
            self.filter_device_edit.clear()
            self.filter_id_restrict_cb.setChecked(True)
            self.filter_device_restrict_cb.setChecked(True)

    def open_database_dialog(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Database File",
            self._default_open_dir(),
            "SQLite Database Files (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if file_path:
            self.load_database(file_path)

    def reload_current_database(self) -> None:
        if not self.db_path:
            self.open_database_dialog()
            return
        self.load_database(self.db_path)

    def load_database(self, db_path: str) -> bool:
        try:
            conn, tables, table_cols, experiment_cols, function_config_cols = validate_switching_database_path(db_path)
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
            self._load_rate_configs()
            self._load_switching_metadata()
            self._init_filter_options_from_cache()
            self.reload_experiment_list()

            if not self.meta_rows:
                self._show_plot_message("This database contains no switching experiments.")
                self._set_summary_text("This database contains no switching experiments.")

            self._set_status(f"Loaded database: {self.db_path}")
            return True
        except Exception as exc:
            self._show_plot_message("Failed to load the selected database.")
            QtWidgets.QMessageBox.critical(
                self,
                "Load Database",
                f"The database was opened, but the GUI could not finish loading it.\n\nReason:\n{exc}",
            )
            return False

    def closeEvent(self, event) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        super().closeEvent(event)

    def _load_rate_configs(self) -> None:
        self.rate_configs = list_rate_configs(self.conn)
        self.rate_config_by_id = {int(row["id"]): row for row in self.rate_configs if row.get("id") is not None}
        self.config_combo.blockSignals(True)
        try:
            self.config_combo.clear()
            for row in self.rate_configs:
                self.config_combo.addItem(format_rate_config_label(row), int(row["id"]))
            if not self.rate_configs:
                self.config_combo.addItem("No switching config found", None)
        finally:
            self.config_combo.blockSignals(False)

        if not self.rate_configs:
            raise RuntimeError("No Features_RS_switching_rate_cal_config rows were found.")

    def _load_switching_metadata(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        prog = QtWidgets.QProgressDialog("Loading switching experiments...", "Cancel", 0, 0, self)
        prog.setWindowModality(QtCore.Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()
        try:
            result = preload_switching_metadata_cache(
                conn=self.conn,
                table_cols=self.table_cols,
                experiment_cols=self.experiment_cols,
                function_config_cols=self.function_config_cols,
                progress_every=META_PROGRESS_EVERY,
                on_progress=lambda value: self._update_load_progress(prog, value),
                should_cancel=prog.wasCanceled,
            )
        finally:
            prog.close()
            QtWidgets.QApplication.restoreOverrideCursor()

        self.meta_rows = result["meta_rows"]
        self.meta_by_eid.clear()
        self.meta_by_eid.update(result["meta_by_eid"])
        self._uni_recipe = result["unique_values"]["recipe"]
        self._uni_die = result["unique_values"]["die"]
        self._uni_area = result["unique_values"]["area"]
        self._uni_wl = result["unique_values"]["wordline"]
        self._uni_bl = result["unique_values"]["bitline"]
        self._uni_fun = result["unique_values"]["function"]
        self.function_row_cache = build_function_row_cache(
            conn=self.conn,
            tables=self.tables,
            table_cols=self.table_cols,
        )

    def _update_load_progress(self, prog: QtWidgets.QProgressDialog, value: int) -> None:
        prog.setLabelText(f"Loading switching experiments... {value:,} rows")
        QtWidgets.QApplication.processEvents()

    def _init_filter_options_from_cache(self) -> None:
        self._set_filter_combo_signals_blocked(True)
        try:
            for combo, empty_label, values, cast in self._filter_combo_specs():
                combo.clear()
                combo.addItem(empty_label, "")
                for value in sorted(values):
                    combo.addItem(str(value), cast(value))
        finally:
            self._set_filter_combo_signals_blocked(False)

    def on_selection_changed_view(self, _selected, _deselected) -> None:
        if self._suppress_selection:
            return

        indexes = self.list_view.selectionModel().selectedIndexes()
        if not indexes:
            self._current_selected_eid = None
            self.meta_table.setRowCount(0)
            if self.current_bundle is None:
                self._set_summary_text(self.NO_EXPERIMENT_SELECTED_MESSAGE)
                self._show_plot_message(self.NO_EXPERIMENT_SELECTED_MESSAGE)
            return

        eid = int(self.exp_model.data(indexes[0], QtCore.Qt.UserRole))
        self._current_selected_eid = eid
        self.load_metadata(eid)
        if self._has_current_fit_for_selection():
            self._set_summary_text(self._build_info_text())
        else:
            self._set_summary_text(self._build_prefit_summary(eid))

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
        if filters.subdie_area not in (None, "") and data.get("cross_section_area_um2") != int(filters.subdie_area):
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
            self._current_selected_eid = None
        finally:
            self._suppress_selection = False

    def _select_experiment(self, eid: int) -> None:
        try:
            row = self.exp_model.eids.index(int(eid))
        except ValueError:
            return
        index = self.exp_model.index(row, 0)
        self.list_view.setCurrentIndex(index)
        self.list_view.selectionModel().select(
            index,
            QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
        )
        self._current_selected_eid = int(eid)
        self.load_metadata(int(eid))
        if self._has_current_fit_for_selection():
            self._set_summary_text(self._build_info_text())
        else:
            self._set_summary_text(self._build_prefit_summary(int(eid)))

    def reload_experiment_list(self) -> None:
        t0 = time.perf_counter()

        if self.conn is None:
            self._set_status(self.NO_DATABASE_MESSAGE)
            self._show_plot_message(self.NO_DATABASE_MESSAGE)
            self._set_summary_text(self.NO_DATABASE_MESSAGE)
            return

        filters = self._current_filters()
        experiment_spec = self._parse_optional_id_spec(filters.experiment_id_text)
        device_spec = self._parse_optional_id_spec(filters.device_id_text)

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            matched_eids = [
                int(data["experiment_id"])
                for data in self.meta_rows
                if self._row_matches_filters(data, filters, experiment_spec, device_spec)
            ]

            previous_eid = self._current_selected_eid
            shown_eids = matched_eids[:LIST_SHOW_LIMIT]
            self._set_visible_experiments(shown_eids)

            if shown_eids:
                if previous_eid in shown_eids:
                    preferred = previous_eid
                elif self.current_bundle is not None and self.current_bundle.exp_id in shown_eids:
                    preferred = int(self.current_bundle.exp_id)
                elif core.DEFAULT_TARGET_EXPERIMENT_ID in shown_eids:
                    preferred = core.DEFAULT_TARGET_EXPERIMENT_ID
                else:
                    preferred = shown_eids[0]
                self._select_experiment(preferred)
            else:
                self.meta_table.setRowCount(0)
                self._set_summary_text(self.NO_MATCHING_EXPERIMENTS_MESSAGE)
                if self.current_bundle is None:
                    self._show_plot_message(self.NO_MATCHING_EXPERIMENTS_MESSAGE)

            elapsed = time.perf_counter() - t0
            self._set_status(
                f"Matched {len(matched_eids):,} switching experiments; showing {len(shown_eids):,}. "
                f"Filter time {elapsed:.2f}s.",
                timeout_ms=4000,
            )
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _selected_feature_spec(self) -> dict[str, Any]:
        key = str(self.feature_combo.currentData() or "mu_dr")
        return FEATURE_SPECS.get(key, FEATURE_SPECS["mu_dr"])

    def _selected_rate_config_id(self) -> Optional[int]:
        value = self.config_combo.currentData()
        return int(value) if value not in (None, "") else None

    def _selected_rate_config_row(self) -> Optional[dict[str, Any]]:
        config_id = self._selected_rate_config_id()
        if config_id is None:
            return None
        row = self.rate_config_by_id.get(config_id)
        if row is not None:
            return row
        if self.conn is None:
            return None
        row = fetch_rate_config_row(self.conn, config_id)
        if row:
            self.rate_config_by_id[config_id] = row
        return row

    def _on_rate_config_changed(self) -> None:
        if self._current_selected_eid is not None:
            self.load_metadata(self._current_selected_eid)
            if self._has_current_fit_for_selection():
                self._set_summary_text(self._build_info_text())
            else:
                self._set_summary_text(self._build_prefit_summary(self._current_selected_eid))
        if self.current_bundle is not None and self.current_bundle.cfg_id != self._selected_rate_config_id():
            self._set_status("Switching config changed. Click Fit Selected Experiment to rerun.", timeout_ms=6000)

    def _has_current_fit_for_selection(self) -> bool:
        if self.current_bundle is None:
            return False
        if self._current_selected_eid is None:
            return False
        return (
            int(self.current_bundle.exp_id) == int(self._current_selected_eid)
            and int(self.current_bundle.cfg_id) == int(self._selected_rate_config_id() or -1)
        )

    def _build_prefit_summary(self, experiment_id: int) -> str:
        row = self.meta_by_eid.get(int(experiment_id)) or {}
        cfg = self._selected_rate_config_row() or {}
        lines = [
            f"Selected experiment: {experiment_id}",
            f"Experiment name: {row.get('experiment_name', '')}",
            f"Function type: {row.get('function_type', '')}",
            f"Function config ID: {row.get('function_config_id', '')}",
            f"Device ID: {row.get('device_id', '')}",
            f"Recipe / die / area: {row.get('recipe_name', '')} / {row.get('die_number', '')} / {row.get('cross_section_area_um2', '')}",
            f"Wordline / bitline: {row.get('wordline', '')} / {row.get('bitline', '')}",
            "",
            "Selected switching config:",
            f"- config_id: {cfg.get('id', '')}",
            f"- block_kind: {cfg.get('block_kind', '')}",
            f"- window_n: {cfg.get('window_n', '')}",
            f"- rs_id: {cfg.get('rs_id', '')}",
            "",
            "Press 'Fit Selected Experiment' to run the switching fit.",
        ]
        return "\n".join(lines)

    def _build_info_text(self) -> str:
        bundle = self.current_bundle
        series = self.current_series
        if bundle is None or series is None:
            if self._current_selected_eid is not None:
                return self._build_prefit_summary(self._current_selected_eid)
            return self.NO_EXPERIMENT_SELECTED_MESSAGE

        row = self.meta_by_eid.get(int(bundle.exp_id)) or {}
        cfg = self.rate_config_by_id.get(int(bundle.cfg_id)) or {}
        feature = self._selected_feature_spec()
        n_rows = int(series.idx.size)
        n_mu = int(np.isfinite(series.mu_dr).sum())
        n_mean = int(np.isfinite(series.mean_y).sum())
        n_sigma = int(np.isfinite(series.sigma).sum())
        n_pw = int((np.isfinite(series.pulse_width) & (series.pulse_width > 0)).sum())
        n_amp = int(np.isfinite(series.amplitude).sum())
        n_r = int(np.isfinite(series.resistance).sum())

        lines = [
            f"Experiment ID: {bundle.exp_id}",
            f"Experiment name: {row.get('experiment_name', '')}",
            f"Function type / config: {row.get('function_type', '')} / {row.get('function_config_id', '')}",
            f"Switching config: {bundle.cfg_id} ({cfg.get('block_kind', '')}, window_n={cfg.get('window_n', '')})",
            f"Database: {bundle.db_path}",
            self.last_view_text,
            "",
            "Data scope:",
            f"- total raw rows used by fit input: {len(bundle.df_all)}",
            f"- positive rows: {len(bundle.df_pos)}",
            f"- negative rows: {len(bundle.df_neg)}",
            f"- compact-curve rows: {n_rows}",
            "",
            "Display options:",
            f"- Show raw datapoints: {'Yes' if self.show_raw_cb.isChecked() else 'No'}",
            f"- Hide purple-gated region points: {'Yes' if self.hide_purple_raw_cb.isChecked() else 'No'}",
            f"- Compact resistance scale: {'log-y' if self.log_r_cb.isChecked() else 'linear-y'}",
            f"- Plot-3 feature: {feature['label']} ({feature['ylabel']})",
            "",
            "Data availability:",
            f"- amplitude finite rows: {n_amp}/{n_rows}",
            f"- resistance finite rows: {n_r}/{n_rows}",
            f"- mean_y rows: {n_mean}/{n_rows}",
            f"- mu_DR rows: {n_mu}/{n_rows}",
            f"- sigma rows: {n_sigma}/{n_rows}",
            f"- pulse_width_s > 0 rows: {n_pw}/{n_rows}",
            "",
            "Fit quality:",
            f"- POS R2(fit/raw): {bundle.fit_pos.r2:.4f} / {bundle.fit_pos.r2_raw:.4f}",
            f"- NEG R2(fit/raw): {bundle.fit_neg.r2:.4f} / {bundle.fit_neg.r2_raw:.4f}",
        ]
        return "\n".join(lines)

    def _set_busy(self, busy: bool) -> None:
        enabled = not busy
        has_bundle = self.current_bundle is not None

        self.fit_btn.setEnabled(enabled)
        self.replot_btn.setEnabled(enabled and has_bundle)
        self.view_btn.setEnabled(enabled and has_bundle)
        self.save_btn.setEnabled(enabled and has_bundle)
        self.config_combo.setEnabled(enabled)
        self.show_raw_cb.setEnabled(enabled)
        self.hide_purple_raw_cb.setEnabled(enabled and self.show_raw_cb.isChecked())
        self.log_r_cb.setEnabled(enabled)
        self.feature_combo.setEnabled(enabled)
        self.reload_btn.setEnabled(enabled)
        self.list_view.setEnabled(enabled)
        self.filter_name_edit.setEnabled(enabled)
        self.filter_id_edit.setEnabled(enabled)
        self.filter_device_edit.setEnabled(enabled)
        self.filter_id_restrict_cb.setEnabled(enabled)
        self.filter_device_restrict_cb.setEnabled(enabled)
        for combo in self._filter_combos():
            combo.setEnabled(enabled)

    def _on_plot_option_changed(self, *_args) -> None:
        self.hide_purple_raw_cb.setEnabled(self.show_raw_cb.isChecked())
        if self.current_bundle is not None and self.worker is None:
            self._draw_bundle()
            self._set_summary_text(self._build_info_text())

    def _draw_compact_curves(self, ax_amp, ax_res, ax_feat) -> None:
        series = self.current_series
        if series is None or self.current_bundle is None:
            for ax in (ax_amp, ax_res, ax_feat):
                ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
                ax.set_axis_off()
            return

        idx = series.idx

        m_amp = np.isfinite(series.amplitude)
        if np.any(m_amp):
            ax_amp.plot(
                idx[m_amp],
                series.amplitude[m_amp],
                marker=".",
                linestyle="none",
                markersize=2.1,
                color="#1f77b4",
            )
        ax_amp.set_ylabel("Amp (V)")
        ax_amp.grid(True, alpha=0.35)
        ax_amp.tick_params(axis="x", labelbottom=False)

        m_res = np.isfinite(series.resistance)
        if self.log_r_cb.isChecked():
            m_res = m_res & (series.resistance > 0)
            if np.any(m_res):
                ax_res.plot(
                    idx[m_res],
                    series.resistance[m_res],
                    marker=".",
                    linestyle="none",
                    markersize=2.1,
                    color="#9467bd",
                )
                ax_res.set_yscale("log")
        else:
            if np.any(m_res):
                ax_res.plot(
                    idx[m_res],
                    series.resistance[m_res],
                    marker=".",
                    linestyle="none",
                    markersize=2.1,
                    color="#9467bd",
                )
        ax_res.set_ylabel("R [log]" if self.log_r_cb.isChecked() else "R (Ohm)")
        ax_res.grid(True, which="both", alpha=0.35)
        ax_res.tick_params(axis="x", labelbottom=False)

        feature = self._selected_feature_spec()
        values = np.asarray(getattr(series, str(feature["attr"])), dtype=float)
        mask = np.isfinite(values)
        if np.any(mask):
            ax_feat.plot(
                idx[mask],
                values[mask],
                marker=".",
                linestyle="none",
                markersize=1.9,
                color=str(feature["color"]),
            )
        ax_feat.set_xlabel("Point index", labelpad=-2.0)
        ax_feat.set_ylabel(str(feature["label"]))
        ax_feat.tick_params(axis="x", labelbottom=True, pad=1)
        ax_feat.xaxis.set_label_coords(0.5, -0.085)
        ax_feat.grid(True, alpha=0.35)

    def _draw_bundle(self) -> None:
        if self.current_bundle is None:
            return

        self.figure.clear()
        self.figure.subplots_adjust(
            left=FIG_LEFT,
            right=FIG_RIGHT,
            bottom=FIG_BOTTOM,
            top=FIG_TOP,
            hspace=FIG_HSPACE,
        )
        gs = self.figure.add_gridspec(4, 1, height_ratios=GRID_HEIGHT_RATIOS)

        ax_amp = self.figure.add_subplot(gs[0, 0])
        ax_res = self.figure.add_subplot(gs[1, 0], sharex=ax_amp)
        ax_feat = self.figure.add_subplot(gs[2, 0], sharex=ax_amp)
        self.ax3d = self.figure.add_subplot(gs[3, 0], projection="3d")

        self._draw_compact_curves(ax_amp, ax_res, ax_feat)
        core.draw_combined_3d(
            self.ax3d,
            self.current_bundle,
            scatter_limit=int(core.MAX_SCATTER_POINTS),
            show_raw_points=bool(self.show_raw_cb.isChecked()),
            hide_purple_region_points=bool(self.hide_purple_raw_cb.isChecked()),
        )
        self._apply_default_view()
        try:
            self.ax3d.set_box_aspect(AX3D_BOX_ASPECT, zoom=AX3D_ZOOM)
        except TypeError:
            self.ax3d.set_box_aspect(AX3D_BOX_ASPECT)
        except Exception:
            pass
        pos = self.ax3d.get_position()
        self.ax3d.set_position([
            pos.x0 + AX3D_X_SHIFT,
            pos.y0 + AX3D_Y_SHIFT,
            pos.width + AX3D_W_GROW,
            pos.height + AX3D_H_GROW,
        ])
        ax_amp.set_title("")
        self.ax3d.set_title("")
        self.ax3d.set_xlabel("Pulse voltage (V)", labelpad=6)
        self.ax3d.set_ylabel("mean_y (Ohm)", labelpad=7)
        self.ax3d.set_zlabel("dR/dt (Ohm/s)", labelpad=5)
        legend = self.ax3d.get_legend()
        if legend is not None:
            legend.remove()
        self._update_view_angle_text()
        self.canvas.draw_idle()

    def _apply_default_view(self) -> None:
        if self.ax3d is None:
            return
        try:
            self.ax3d.view_init(
                elev=float(DEFAULT_VIEW_ELEV),
                azim=float(DEFAULT_VIEW_AZIM),
                roll=float(DEFAULT_VIEW_ROLL),
            )
        except TypeError:
            self.ax3d.view_init(
                elev=float(DEFAULT_VIEW_ELEV),
                azim=float(DEFAULT_VIEW_AZIM),
            )

    def _zoom_limits(self, lim: tuple, scale: float) -> tuple:
        lo, hi = float(lim[0]), float(lim[1])
        center = 0.5 * (lo + hi)
        half = 0.5 * (hi - lo)
        half2 = max(1e-12, half * float(scale))
        return center - half2, center + half2

    def _on_scroll_zoom(self, event) -> None:
        if getattr(self.toolbar, "mode", ""):
            return
        if self.ax3d is None:
            return
        if event.inaxes != self.ax3d:
            return

        step = getattr(event, "step", 0.0) or 0.0
        if step == 0:
            button = str(getattr(event, "button", ""))
            if button == "up":
                step = 1.0
            elif button == "down":
                step = -1.0
        if step == 0:
            return

        scale = 0.90 if step > 0 else 1.10
        self.ax3d.set_xlim3d(*self._zoom_limits(self.ax3d.get_xlim3d(), scale))
        self.ax3d.set_ylim3d(*self._zoom_limits(self.ax3d.get_ylim3d(), scale))
        self.ax3d.set_zlim3d(*self._zoom_limits(self.ax3d.get_zlim3d(), scale))
        self.canvas.draw_idle()

    def _current_view_message(self) -> str:
        if self.ax3d is None:
            return "Current 3D view: N/A"
        elev = float(getattr(self.ax3d, "elev", float("nan")))
        azim = float(getattr(self.ax3d, "azim", float("nan")))
        roll = getattr(self.ax3d, "roll", None)
        if roll is None:
            return f"Current 3D view: elev={elev:.1f}, azim={azim:.1f}"
        return f"Current 3D view: elev={elev:.1f}, azim={azim:.1f}, roll={float(roll):.1f}"

    def _update_view_angle_text(self) -> None:
        self.last_view_text = self._current_view_message()

    def _publish_view_angle(self) -> None:
        self._update_view_angle_text()
        message = self.last_view_text
        if self.current_bundle is not None and self.current_series is not None:
            self._set_summary_text(self._build_info_text())
        else:
            self._set_summary_text(message)
        self._set_status(message, timeout_ms=3000)

    def _on_mouse_release(self, event) -> None:
        if self.ax3d is None:
            return
        if event.inaxes != self.ax3d:
            return
        self._publish_view_angle()

    def on_log_view_angle(self) -> None:
        self._publish_view_angle()

    def _current_selected_experiment_id(self) -> Optional[int]:
        indexes = self.list_view.selectionModel().selectedIndexes()
        if not indexes:
            return None
        return int(self.exp_model.data(indexes[0], QtCore.Qt.UserRole))

    def run_fit_for_selected_experiment(self) -> None:
        if self.conn is None:
            QtWidgets.QMessageBox.warning(self, "Fit", "No database is loaded.")
            return
        if self.worker is not None:
            return

        exp_id = self._current_selected_experiment_id()
        if exp_id is None:
            QtWidgets.QMessageBox.warning(self, "Fit", "Select an experiment first.")
            return

        config_id = self._selected_rate_config_id()
        self._set_summary_text(
            f"Running fit for experiment_id={exp_id} with switching config_id={config_id} ..."
        )
        self._set_status(f"Running fit for experiment_id={exp_id} with config_id={config_id} ...", timeout_ms=0)

        self.worker = FitWorker(self.db_path, exp_id, config_id)
        self.worker.ok.connect(self._on_fit_ok)
        self.worker.fail.connect(self._on_fit_fail)
        self.worker.finished.connect(self._on_fit_finished)
        self._set_busy(True)
        self.worker.start()

    def on_replot(self) -> None:
        if self.current_bundle is None:
            return
        self._draw_bundle()
        self._set_summary_text(self._build_info_text())
        self._set_status("Replotted current fit", timeout_ms=3000)

    def on_save_png(self) -> None:
        if self.current_bundle is None:
            return

        default_name = f"feature_switching_exp{self.current_bundle.exp_id}_cfg{self.current_bundle.cfg_id}.png"
        default_path = str(core.OUT_DIR / default_name)
        save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save figure",
            default_path,
            "PNG (*.png);;All files (*.*)",
        )
        if not save_path:
            return

        self.figure.savefig(save_path, dpi=220)
        self._set_status(f"Saved: {save_path}", timeout_ms=4000)

    def _on_fit_ok(self, bundle, series) -> None:
        self.current_bundle = bundle
        self.current_series = series
        self._draw_bundle()
        self._set_summary_text(self._build_info_text())
        self._set_status(
            f"Done. exp_id={bundle.exp_id}, cfg_id={bundle.cfg_id}, "
            f"POS R2={bundle.fit_pos.r2:.4f}, NEG R2={bundle.fit_neg.r2:.4f}.",
            timeout_ms=6000,
        )

    def _on_fit_fail(self, message: str) -> None:
        self._set_summary_text(f"Fit failed:\n{message}")
        self._set_status(f"Fit failed: {message}", timeout_ms=6000)
        if self.current_bundle is None:
            self._show_plot_message("Fit failed. See summary panel for details.")

    def _on_fit_finished(self) -> None:
        self.worker = None
        self._set_busy(False)

    def load_metadata(self, experiment_id: int) -> None:
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
        self._append_rate_config_metadata()

    def _append_rate_config_metadata(self) -> None:
        row = self._selected_rate_config_row()
        if not row:
            self._append_meta_section("Switching Rate Config", "No config selected.")
            return
        self._append_meta_section("Switching Rate Config")
        self._append_metadata_fields(row, self.RATE_CONFIG_FIELDS)

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

        link_col = function_link_column(function_table, self.table_cols)
        if not link_col:
            self._append_meta("(function row)", "Link column not found")
            return

        link_value = row["function_config_id"] if link_col == "function_config_id" else experiment_id
        if link_value is None:
            self._append_meta("(function row)", "Not found")
            return

        function_row = None
        if link_col == "function_config_id":
            function_row = self.function_row_cache.get((row["function_type"], int(link_value)))

        if function_row is None:
            try:
                function_row = fetch_single_row_by_link(
                    conn=self.conn,
                    table_name=function_table,
                    link_col=link_col,
                    link_value=link_value,
                )
            except Exception as exc:
                self._append_meta("(function query error)", str(exc))
                return

        if not function_row:
            self._append_meta("(function row)", "Not found")
            return

        items = function_row.items() if isinstance(function_row, dict) else function_row
        for key, value in items:
            if key in ("id", "experiment_id", "function_config_id"):
                continue
            self._append_meta(key, value)

    def _append_meta(self, field: str, value: Any) -> None:
        row = self.meta_table.rowCount()
        self.meta_table.insertRow(row)
        self.meta_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(field)))
        self.meta_table.setItem(row, 1, QtWidgets.QTableWidgetItem("" if value is None else str(value)))


__all__ = ["MainWindow"]
