"""Qt application setup helpers."""

from PyQt5 import QtCore, QtGui, QtWidgets

import matplotlib


def enable_qt_high_dpi() -> None:
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)


def apply_global_fonts(app: QtWidgets.QApplication, base_pt: float = 10.0) -> None:
    screen = app.primaryScreen()
    dpi = screen.logicalDotsPerInch() if screen else 96.0
    scale = dpi / 96.0
    scale = max(0.8, min(scale, 2.5))

    font = QtGui.QFont("Arial")
    font.setPointSizeF(base_pt * scale)
    app.setFont(font)

    mpl_base = base_pt * scale
    matplotlib.rcParams.update({
        "font.family": "Arial",
        "font.sans-serif": ["Arial"],
        "font.size": mpl_base,
        "axes.titlesize": mpl_base * 1.05,
        "axes.labelsize": mpl_base * 1.00,
        "xtick.labelsize": mpl_base * 0.90,
        "ytick.labelsize": mpl_base * 0.90,
        "legend.fontsize": mpl_base * 0.85,
    })
