from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    try:
        from PyQt5.QtWidgets import QApplication

        from GUI_feature_switching.bootstrap.qt_app import apply_global_fonts, enable_qt_high_dpi
        from GUI_feature_switching.ui.main_window import MainWindow
    except ImportError as exc:
        print(
            "Missing GUI dependency. Install packages from "
            "GUI_feature_switching/requirements.txt and try again.\n"
            f"Original error: {exc}",
            file=sys.stderr,
        )
        return 1

    enable_qt_high_dpi()
    app = QApplication(sys.argv)
    apply_global_fonts(app, base_pt=10.0)

    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(db_path)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
