from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from GUI_material_layers.bootstrap.config import AppConfig
from GUI_material_layers.bootstrap.container import build_container
from GUI_material_layers.ui.main_window import MainWindow


def main() -> int:
    config = AppConfig.default(BASE_DIR)
    container = build_container(config)

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    base_font = QFont("Arial")
    if app.font().pointSize() > 0:
        base_font.setPointSize(app.font().pointSize())
    app.setFont(base_font)
    window = MainWindow(
        process_service=container.process_service,
        recipe_service=container.recipe_service,
    )
    app.aboutToQuit.connect(container.close)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
