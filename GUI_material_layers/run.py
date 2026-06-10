from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from GUI_material_layers.bootstrap.config import AppConfig, DEFAULT_BIG_DATABASE_NAME
from GUI_material_layers.bootstrap.container import AppContainer, build_container
from GUI_material_layers.logic.recipe_service import RecipeService
from GUI_material_layers.sql.db_ops import SQLiteRecipeRepository, prepare_runtime_databases
from GUI_material_layers.ui.main_window import MainWindow

BIG_DB_FILE_FILTER = "SQLite Database Files (*.db *.sqlite *.sqlite3);;All Files (*)"
BIG_DB_REQUIRED_TABLES = ("Experiment", "Device", "Wafer", "Recipe")
WORKING_DB_DISPLAY = "In-memory only. Unsaved edits are discarded when the GUI closes."


def _default_database_picker_dir(default_path: Path) -> Path:
    candidates = []
    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        candidates.append(Path(userprofile) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    candidates.append(default_path.parent)
    candidates.append(PROJECT_ROOT)
    candidates.append(Path.home())

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return PROJECT_ROOT


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
            f"Selected file does not look like the main {DEFAULT_BIG_DATABASE_NAME}. "
            f"Missing tables: {', '.join(missing)}"
        )
    return path


def _prompt_big_database(parent: MainWindow | None, default_path: Path) -> Path | None:
    start_path = _default_database_picker_dir(default_path)

    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        f"Open Big Database ({DEFAULT_BIG_DATABASE_NAME})",
        str(start_path),
        BIG_DB_FILE_FILTER,
    )
    if not file_path:
        return None
    return Path(file_path)


def _choose_big_database(parent: MainWindow | None, default_path: Path, cli_db_path: str | None) -> Path | None:
    candidate = Path(cli_db_path).expanduser() if cli_db_path else None

    while True:
        if candidate is None:
            candidate = _prompt_big_database(parent, default_path)
            if candidate is None:
                return None

        try:
            return _validate_big_database(candidate)
        except Exception as exc:
            button = QMessageBox.warning(
                parent,
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


def _build_runtime_container(base_config: AppConfig) -> AppContainer:
    runtime_config = base_config.with_working_db_path(":memory:").with_recipe_db_path(":memory:")
    return build_container(runtime_config)


def _attach_big_database(container: AppContainer, recipe_db_path: Path) -> RecipeService:
    old_recipe_repo = container.recipe_repo
    new_recipe_repo = SQLiteRecipeRepository(recipe_db_path)
    try:
        prepare_runtime_databases(container.working_repo.conn, new_recipe_repo.conn)
        new_recipe_service = RecipeService(container.working_repo, new_recipe_repo)
    except Exception:
        new_recipe_repo.close()
        raise

    container.recipe_repo = new_recipe_repo
    container.recipe_service = new_recipe_service
    try:
        old_recipe_repo.close()
    except Exception:
        pass
    return new_recipe_service


def _open_big_database(
    window: MainWindow,
    container: AppContainer,
    base_config: AppConfig,
    cli_db_path: str | None,
) -> bool:
    recipe_db_path = _choose_big_database(window, base_config.recipe_db_path, cli_db_path)
    if recipe_db_path is None:
        return False

    while True:
        try:
            recipe_service = _attach_big_database(container, recipe_db_path)
            window.bind_recipe_service(recipe_service, recipe_db_path)
            return True
        except Exception as exc:
            button = QMessageBox.critical(
                window,
                "Open Big Database",
                "The selected big database could be read, but the GUI could not initialize it.\n\n"
                f"Selected big database:\n{recipe_db_path}\n\n"
                f"Working database:\n{WORKING_DB_DISPLAY}\n\n"
                f"Reason:\n{exc}\n\n"
                "Choose another database?",
                QMessageBox.Retry | QMessageBox.Cancel,
                QMessageBox.Retry,
            )
            if button != QMessageBox.Retry:
                return False
            recipe_db_path = _choose_big_database(window, base_config.recipe_db_path, None)
            if recipe_db_path is None:
                return False


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
    container = _build_runtime_container(base_config)

    window = MainWindow(
        process_service=container.process_service,
        recipe_service=container.recipe_service,
    )
    window.databaseRequested.connect(lambda: _open_big_database(window, container, base_config, None))
    app.aboutToQuit.connect(container.close)
    window.show()
    QTimer.singleShot(75, lambda: _open_big_database(window, container, base_config, cli_db_path))
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
