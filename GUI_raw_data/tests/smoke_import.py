from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from GUI_raw_data.ui.main_window import MainWindow
except ModuleNotFoundError as exc:
    missing_name = exc.name or str(exc)
    raise SystemExit(
        f"Missing dependency while importing GUI_raw_data: {missing_name}. "
        "Install GUI_raw_data/requirements.txt first."
    ) from exc


def main():
    print(MainWindow.__name__)


if __name__ == "__main__":
    main()
