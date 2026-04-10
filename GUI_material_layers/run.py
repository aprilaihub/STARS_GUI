from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from GUI_material_layers.bootstrap.config import AppConfig, DEFAULT_BIG_DATABASE_NAME
from GUI_material_layers.bootstrap.container import build_container
from GUI_material_layers.ui.main_window import MainWindow

BIG_DB_FILE_FILTER = "SQLite Database Files (*.db *.sqlite *.sqlite3);;All Files (*)"
BIG_DB_REQUIRED_TABLES = ("Experiment", "Device", "Wafer", "Recipe")


def _validate_big_database(db_path: str | Path) -> Path:
    path = Path(db_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        table_names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()

    missing = [table_name for table_name in BIG_DB_REQUIRED_TABLES if table_name not in table_names]
    if missing:
        raise RuntimeError(
            "Selected file does not look like the main Database_NEW_V2.db. "
            f"Missing tables: {', '.join(missing)}"
        )
    return path


def _prompt_big_database(default_path: Path) -> Path | None:
    start_path = default_path if default_path.exists() else default_path.parent
    if not start_path.exists():
        start_path = PROJECT_ROOT

    file_path, _ = QFileDialog.getOpenFileName(
        None,
        f"Open Big Database ({DEFAULT_BIG_DATABASE_NAME})",
        str(start_path),
        BIG_DB_FILE_FILTER,
    )
    if not file_path:
        return None
    return Path(file_path)


def _choose_big_database(default_path: Path, cli_db_path: str | None) -> Path | None:
    candidate = Path(cli_db_path).expanduser() if cli_db_path else None

    while True:
        if candidate is None:
            candidate = _prompt_big_database(default_path)
            if candidate is None:
                return None

        try:
            return _validate_big_database(candidate)
        except Exception as exc:
            button = QMessageBox.warning(
                None,
                "Open Big Database",
                "Failed to open the main experiment database.\n\n"
                f"Expected file: {DEFAULT_BIG_DATABASE_NAME}\n"
                f"Path:\n{candidate}\n\n"
                f"Reason:\n{exc}\n\n"
                "Choose another database?",
                QMessageBox.Retry | QMessageBox.Cancel,
                QMessageBox.Retry,
            )
            if button != QMessageBox.Retry:
                return None
            candidate = None


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    base_font = QFont("Arial")
    if app.font().pointSize() > 0:
        base_font.setPointSize(app.font().pointSize())
    app.setFont(base_font)

    base_config = AppConfig.default(BASE_DIR)
    cli_db_path = sys.argv[1] if len(sys.argv) > 1 else None
    recipe_db_path = _choose_big_database(base_config.recipe_db_path, cli_db_path)
    if recipe_db_path is None:
        return 0

    while True:
        try:
            container = build_container(base_config.with_recipe_db_path(recipe_db_path))
            break
        except Exception as exc:
            button = QMessageBox.critical(
                None,
                "Open Big Database",
                "The selected big database could be read, but the GUI could not initialize it.\n\n"
                f"Path:\n{recipe_db_path}\n\n"
                f"Reason:\n{exc}\n\n"
                "Choose another database?",
                QMessageBox.Retry | QMessageBox.Cancel,
                QMessageBox.Retry,
            )
            if button != QMessageBox.Retry:
                return 1
            recipe_db_path = _choose_big_database(base_config.recipe_db_path, None)
            if recipe_db_path is None:
                return 0

    window = MainWindow(
        process_service=container.process_service,
        recipe_service=container.recipe_service,
    )
    app.aboutToQuit.connect(container.close)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
