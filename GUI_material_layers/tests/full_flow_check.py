from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from GUI_material_layers.bootstrap.container import build_container
from GUI_material_layers.bootstrap.config import AppConfig
from GUI_material_layers.ui.main_window import MainWindow, ToolItemWidget


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec_()


def _first_tool_widget(window: MainWindow) -> ToolItemWidget | None:
    sl = window.top_drop_area.sublayers[0]
    for i in range(sl.tool_layout.count()):
        w = sl.tool_layout.itemAt(i).widget()
        if isinstance(w, ToolItemWidget):
            return w
    return None


def run_full_flow_check() -> int:
    with tempfile.TemporaryDirectory(prefix="material_gui_fullflow_") as td:
        root = Path(td)
        cfg = AppConfig(
            base_dir=root,
            working_db_path=root / "working.db",
            recipe_db_path=root / "recipe.db",
        )
        container = build_container(cfg)

        app = QApplication.instance() or QApplication([])
        win = MainWindow(
            process_service=container.process_service,
            recipe_service=container.recipe_service,
        )
        win.show()
        _wait(150)

        # 1) Add process steps for all layers.
        win.top_drop_area.sublayers[0].addTool("ALD")
        win.insulator_drop_area.sublayers[0].addTool("Sputter")
        win.bottom_drop_area.sublayers[0].addTool("Furnace")
        _wait(150)
        steps = container.process_service.list_steps()
        assert len(steps) >= 3, "Expected at least 3 steps after adding tools"

        # 2) Verify autosave flow on ALD step.
        tw = _first_tool_widget(win)
        assert tw is not None, "Top layer ALD tool was not created"
        win.updateToolInfo(tw)
        _wait(80)

        win.thickness_input.setText("42.5")
        w_inst = win.parameter_widgets.get("instrument_name")
        if isinstance(w_inst, QLineEdit):
            w_inst.setText("AUTO-TOOL-01")
        w_mat = win.parameter_widgets.get("desired_material")
        if isinstance(w_mat, QPushButton):
            w_mat.selected_material = "Al2O3"
            w_mat.setText("Al2O3")
        _wait(950)  # > autosave delay

        updated = container.process_service.get_step(tw.tool_id)
        assert updated is not None, "Updated step not found"
        assert updated.thickness_nm is not None and abs(updated.thickness_nm - 42.5) < 1e-6, "Thickness autosave failed"
        assert (updated.parameters.get("instrument_name") or "") == "AUTO-TOOL-01", "Parameter autosave failed"

        # 3) Regression check: remove and add again should not crash.
        win._removeTool(tw)
        _wait(120)
        win.top_drop_area.sublayers[0].addTool("ALD")
        _wait(150)

        # 4) Save and load full data flow.
        recipe_id = container.recipe_service.save_current_as_recipe("fullflow_recipe")
        assert recipe_id > 0, "Failed to save recipe"

        loaded_count = container.recipe_service.load_recipe_into_working(recipe_id)
        assert loaded_count > 0, "Failed to load recipe into working DB"

        win.close()
        container.close()
        print(
            f"FULL_FLOW_CHECK_OK recipe_id={recipe_id} "
            f"steps={loaded_count}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(run_full_flow_check())
