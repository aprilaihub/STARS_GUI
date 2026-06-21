"""Matplotlib plot panel widget with axis dropdowns."""

from __future__ import annotations

from typing import Tuple

from PyQt5 import QtCore, QtWidgets

import matplotlib

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class MplPanel(QtWidgets.QWidget):
    def __init__(self, title: str, default_x: str, default_y: str, parent=None):
        super().__init__(parent)
        self.fig = Figure(figsize=(5, 2.3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)

        self.canvas.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        self.x_label = QtWidgets.QLabel("x-axis:")
        self.y_label = QtWidgets.QLabel("y-axis:")

        self.combo_x = QtWidgets.QComboBox()
        self.combo_y = QtWidgets.QComboBox()
        self.combo_x.addItems(["linear", "log10"])
        self.combo_y.addItems(["linear", "log10", "sqrt"])

        self.combo_x.setCurrentText(default_x if default_x in ("linear", "log10") else "linear")
        self.combo_y.setCurrentText(default_y if default_y in ("linear", "log10", "sqrt") else "linear")

        header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.x_label)
        header_layout.addWidget(self.combo_x)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.y_label)
        header_layout.addWidget(self.combo_y)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(header)
        layout.addWidget(self.canvas, stretch=1)

    def ensure_xlabel_visible(self, bottom: float = 0.22) -> None:
        self.fig.subplots_adjust(bottom=bottom)
        self.canvas.draw_idle()

    def clear_with_msg(self, msg: str) -> None:
        self.ax.clear()
        self.ax.text(0.03, 0.5, msg, transform=self.ax.transAxes)
        self.ax.grid(False)
        self.canvas.draw_idle()

    def get_modes(self) -> Tuple[str, str]:
        return self.combo_x.currentText(), self.combo_y.currentText()
