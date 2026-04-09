from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QMimeData, QPoint, Qt
from PyQt5.QtGui import QDrag, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...sql import db_ops
from ..style import UIImprovement

MIME_KIND = "application/x-nmlc-kind"
MIME_NODE_ID = "application/x-nmlc-node-id"
KIND_CYCLE = "cycle"
KIND_MATERIAL = "material"
KIND_GAS = "gas"
REL_TABLE = "Tool_ALD_Material_Gas_Cycle_Relation"
CYCLE_TABLE = "Tool_ALD_Cycle"
MATERIAL_TABLE = "Tool_ALD_Material"
GAS_TABLE = "Tool_ALD_Gas"
NODE_REF_COL = "MGCR_id"
ORDER_COL = '"order"'

LAYER_THEMES: dict[str, dict[str, str]] = {
    "Top": {
        "accent": "#2563EB",
        "text": "#0F355C",
        "cycle_bg": "#EAF3FF",
        "cycle_bg_selected": "#DCEBFF",
        "material_bg": "#EFF6FF",
        "material_bg_selected": "#DBEAFE",
        "gas_bg": "#E8FFF5",
        "gas_bg_selected": "#D1FAE5",
        "canvas_border": "#BFDBFE",
        "canvas_bg": "#F8FBFF",
        "hint": "#475569",
    },
    "Insulator": {
        "accent": "#D97706",
        "text": "#7C4700",
        "cycle_bg": "#FFF4D6",
        "cycle_bg_selected": "#FFE7B3",
        "material_bg": "#FFF8E1",
        "material_bg_selected": "#FFECB3",
        "gas_bg": "#F3FFE1",
        "gas_bg_selected": "#E7F9C0",
        "canvas_border": "#F5CC7A",
        "canvas_bg": "#FFFDF5",
        "hint": "#7A5A21",
    },
    "Bottom": {
        "accent": "#DC2626",
        "text": "#7F1D1D",
        "cycle_bg": "#FFE6EA",
        "cycle_bg_selected": "#FFD6DE",
        "material_bg": "#FFEEF1",
        "material_bg_selected": "#FFDDE4",
        "gas_bg": "#E7FFF7",
        "gas_bg_selected": "#CFF7EA",
        "canvas_border": "#F2B6C3",
        "canvas_bg": "#FFF7F9",
        "hint": "#7E3140",
    },
}


def _normalize_layer_name(layer_name: str | None) -> str:
    text = str(layer_name or "").strip().lower()
    if text.startswith("top"):
        return "Top"
    if text.startswith("insulator"):
        return "Insulator"
    if text.startswith("bottom"):
        return "Bottom"
    return "Top"


def _make_delete_button(on_click) -> QPushButton:
    btn = QPushButton("×")
    btn.setFixedSize(24, 24)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip("Delete")
    btn.setStyleSheet(
        "QPushButton{border:none;color:#9F1239;font-weight:800;font-size:14px;padding:0;}"
        "QPushButton:hover{color:#BE123C;background:rgba(190,24,60,0.08);border-radius:6px;}"
    )
    btn.clicked.connect(on_click)
    return btn


def _table_exists(conn, table: str) -> bool:
    return db_ops.table_exists(conn, table)


def _col_exists(conn, table: str, col: str) -> bool:
    return db_ops.column_exists(conn, table, col)


def _kind_from_db_type(db_type: str) -> str:
    t = (db_type or "").strip().lower()
    if t in {"loop", "cycle"}:
        return KIND_CYCLE
    if t == "gas":
        return KIND_GAS
    return KIND_MATERIAL


def _db_type_from_kind(kind: str) -> str:
    if kind == KIND_CYCLE:
        return "cycle"
    if kind == KIND_GAS:
        return "gas"
    return "material"


class _PaletteDragButton(QPushButton):
    def __init__(self, text: str, kind: str):
        super().__init__(text)
        self.kind = kind
        self._start_pos = QPoint()
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_KIND, self.kind.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)


class _NodeDragHandle(QPushButton):
    def __init__(self, node_widget: "_BaseNodeWidget"):
        super().__init__("⋮⋮")
        self.node_widget = node_widget
        self._start_pos = QPoint()
        self.setFixedWidth(24)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag to move")
        self.setStyleSheet(
            "QPushButton{border:none;color:#4B5563;font-weight:700;}"
            "QPushButton:hover{color:#111827;}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self.node_widget.start_drag()


class _BaseNodeWidget(QWidget):
    def __init__(self, dialog: "NestedMaterialCycleDialog", node_kind: str):
        super().__init__()
        self.dialog = dialog
        self.node_kind = node_kind
        self.mgcr_id: int | None = None
        self.ald_id: int | None = None
        self.parent_area: NmlcDropArea | None = None
        self._selected = False
        self._tree_depth = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)

    def start_drag(self) -> None:
        if self.mgcr_id is None:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_KIND, self.node_kind.encode("utf-8"))
        mime.setData(MIME_NODE_ID, str(int(self.mgcr_id)).encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def set_tree_depth(self, depth: int) -> None:
        self._tree_depth = max(0, int(depth))
        self._apply_tree_depth_visual()

    def _apply_tree_depth_visual(self) -> None:
        pass

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


class MaterialNodeWidget(_BaseNodeWidget):
    def __init__(self, dialog: "NestedMaterialCycleDialog"):
        super().__init__(dialog, KIND_MATERIAL)
        self.desired = ""
        self.precursor = ""
        self.dep_rate_value: float | None = None
        self.dep_rate_unit = "nm/cycle"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 1, 0, 1)
        root.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("nmlcNodeCard")
        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("nmlcMaterialHeader")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.lbl_nested = QLabel("↳")
        self.lbl_nested.setFixedWidth(16)
        self.lbl_nested.setAlignment(Qt.AlignCenter)
        self.lbl_nested.hide()
        row.addWidget(self.lbl_nested, 0)

        self.drag_handle = _NodeDragHandle(self)
        row.addWidget(self.drag_handle, 0)

        text_host = QWidget()
        text_col = QVBoxLayout(text_host)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        self.lbl_material = QLabel("Material")
        self.lbl_material.setStyleSheet("color:#0F355C;font-weight:700;")
        self.lbl_material.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(self.lbl_material)

        self.lbl_material_meta = QLabel("")
        self.lbl_material_meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(self.lbl_material_meta)
        row.addWidget(text_host, 1)

        self.btn_del = _make_delete_button(lambda: self.dialog.delete_node(self))
        row.addWidget(self.btn_del, 0)

        self.header.mousePressEvent = lambda _e: self.dialog.select_node(self)
        self.lbl_material.mousePressEvent = lambda _e: self.dialog.select_node(self)

        card_lay.addWidget(self.header)
        root.addWidget(self.card)
        self._apply_selection_style()
        self.update_display()

    def _apply_selection_style(self) -> None:
        theme = self.dialog.layer_theme()
        border = f"2px solid {theme['accent']}" if self._selected else "1px solid transparent"
        bg = theme["material_bg_selected"] if self._selected else theme["material_bg"]
        self.card.setStyleSheet("QFrame#nmlcNodeCard{background:transparent;border:none;}")
        self.header.setStyleSheet(
            "QFrame#nmlcMaterialHeader{"
            f"background:{bg};"
            f"border:{border};"
            "border-radius:10px;"
            "}"
        )
        self.lbl_material.setStyleSheet(f"color:{theme['text']};font-weight:700;")
        self.lbl_material_meta.setStyleSheet(f"color:{theme['hint']};font-size:11px;font-weight:600;")
        self.lbl_nested.setStyleSheet(f"color:{theme['accent']};font-weight:900;font-size:13px;")

    def set_selected(self, selected: bool) -> None:
        super().set_selected(selected)
        self._apply_selection_style()

    def _apply_tree_depth_visual(self) -> None:
        self.lbl_nested.setVisible(self._tree_depth > 0)

    def update_display(self) -> None:
        shown = (self.desired or "").strip()
        self.lbl_material.setText(f"Material: {shown}" if shown else "Material")
        meta_parts: list[str] = []
        precursor = (self.precursor or "").strip()
        if precursor:
            meta_parts.append(f"Precursor: {precursor}")
        if self.dep_rate_value is not None:
            meta_parts.append(f"{self.dep_rate_value:g} {self.dep_rate_unit or 'nm/cycle'}")
        self.lbl_material_meta.setText("  |  ".join(meta_parts))
        self.lbl_material_meta.setVisible(bool(meta_parts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": KIND_MATERIAL,
            "mgcr_id": self.mgcr_id,
            "ald_id": self.ald_id,
            "desired_material": self.desired,
            "precursor_name": self.precursor,
            "dep_rate_value": self.dep_rate_value,
            "dep_rate_unit": self.dep_rate_unit,
        }


class GasNodeWidget(_BaseNodeWidget):
    def __init__(self, dialog: "NestedMaterialCycleDialog"):
        super().__init__(dialog, KIND_GAS)
        self.gas_type = ""
        self.flow_value: float | None = None
        self.flow_unit = "sccm"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 1, 0, 1)
        root.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("nmlcNodeCard")
        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("nmlcGasHeader")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.lbl_nested = QLabel("↳")
        self.lbl_nested.setFixedWidth(16)
        self.lbl_nested.setAlignment(Qt.AlignCenter)
        self.lbl_nested.hide()
        row.addWidget(self.lbl_nested, 0)

        self.drag_handle = _NodeDragHandle(self)
        row.addWidget(self.drag_handle, 0)

        text_host = QWidget()
        text_col = QVBoxLayout(text_host)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        self.lbl_gas = QLabel("Gas")
        self.lbl_gas.setStyleSheet("color:#0F355C;font-weight:700;")
        self.lbl_gas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(self.lbl_gas)

        self.lbl_gas_meta = QLabel("")
        self.lbl_gas_meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_col.addWidget(self.lbl_gas_meta)
        row.addWidget(text_host, 1)

        self.btn_del = _make_delete_button(lambda: self.dialog.delete_node(self))
        row.addWidget(self.btn_del, 0)

        self.header.mousePressEvent = lambda _e: self.dialog.select_node(self)
        self.lbl_gas.mousePressEvent = lambda _e: self.dialog.select_node(self)

        card_lay.addWidget(self.header)
        root.addWidget(self.card)
        self._apply_selection_style()
        self.update_display()

    def _apply_selection_style(self) -> None:
        theme = self.dialog.layer_theme()
        border = f"2px solid {theme['accent']}" if self._selected else "1px solid transparent"
        bg = theme["gas_bg_selected"] if self._selected else theme["gas_bg"]
        self.card.setStyleSheet("QFrame#nmlcNodeCard{background:transparent;border:none;}")
        self.header.setStyleSheet(
            "QFrame#nmlcGasHeader{"
            f"background:{bg};"
            f"border:{border};"
            "border-radius:10px;"
            "}"
        )
        self.lbl_gas.setStyleSheet(f"color:{theme['text']};font-weight:700;")
        self.lbl_gas_meta.setStyleSheet(f"color:{theme['hint']};font-size:11px;font-weight:600;")
        self.lbl_nested.setStyleSheet(f"color:{theme['accent']};font-weight:900;font-size:13px;")

    def set_selected(self, selected: bool) -> None:
        super().set_selected(selected)
        self._apply_selection_style()

    def _apply_tree_depth_visual(self) -> None:
        self.lbl_nested.setVisible(self._tree_depth > 0)

    def update_display(self) -> None:
        shown = (self.gas_type or "").strip()
        self.lbl_gas.setText(f"Gas: {shown}" if shown else "Gas")
        if self.flow_value is None:
            self.lbl_gas_meta.clear()
            self.lbl_gas_meta.hide()
            return
        unit = (self.flow_unit or "sccm").strip() or "sccm"
        self.lbl_gas_meta.setText(f"{self.flow_value:g} {unit}")
        self.lbl_gas_meta.show()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": KIND_GAS,
            "mgcr_id": self.mgcr_id,
            "ald_id": self.ald_id,
            "gas_type": self.gas_type,
            "flow_value": self.flow_value,
            "flow_unit": self.flow_unit,
        }


class CycleNodeWidget(_BaseNodeWidget):
    def __init__(self, dialog: "NestedMaterialCycleDialog"):
        super().__init__(dialog, KIND_CYCLE)
        self.cycles = 1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 1, 0, 1)
        root.setSpacing(1)

        self.card = QFrame()
        self.card.setObjectName("nmlcNodeCard")
        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(2)

        self.header = QFrame()
        self.header.setObjectName("nmlcCycleHeader")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)
        self.lbl_nested = QLabel("↳")
        self.lbl_nested.setFixedWidth(16)
        self.lbl_nested.setAlignment(Qt.AlignCenter)
        self.lbl_nested.hide()
        row.addWidget(self.lbl_nested, 0)

        self.drag_handle = _NodeDragHandle(self)
        row.addWidget(self.drag_handle, 0)

        self.lbl_cycles = QLabel("Cycles: 1")
        self.lbl_cycles.setStyleSheet("color:#0F355C;font-weight:700;")
        self.lbl_cycles.mousePressEvent = lambda _e: self.dialog.select_node(self)
        row.addWidget(self.lbl_cycles, 0)
        row.addStretch(1)

        self.btn_del = _make_delete_button(lambda: self.dialog.delete_node(self))
        row.addWidget(self.btn_del, 0)

        self.header.mousePressEvent = lambda _e: self.dialog.select_node(self)

        card_lay.addWidget(self.header)

        self.child_area = NmlcDropArea(dialog, owner_cycle=self)
        child_wrap = QWidget()
        child_lay = QVBoxLayout(child_wrap)
        child_lay.setContentsMargins(32, 0, 0, 0)
        child_lay.setSpacing(2)
        child_lay.addWidget(self.child_area)
        card_lay.addWidget(child_wrap)

        root.addWidget(self.card)
        self._apply_selection_style()
        self.update_display()

    def _apply_selection_style(self) -> None:
        theme = self.dialog.layer_theme()
        border = f"2px solid {theme['accent']}" if self._selected else "1px solid transparent"
        header_bg = theme["cycle_bg_selected"] if self._selected else theme["cycle_bg"]
        self.card.setStyleSheet("QFrame#nmlcNodeCard{background:transparent;border:none;}")
        self.header.setStyleSheet(
            "QFrame#nmlcCycleHeader{"
            f"background:{header_bg};"
            f"border:{border};"
            "border-radius:10px;"
            "}"
        )
        self.lbl_cycles.setStyleSheet(f"color:{theme['text']};font-weight:700;")
        self.lbl_nested.setStyleSheet(f"color:{theme['accent']};font-weight:900;font-size:13px;")

    def set_selected(self, selected: bool) -> None:
        super().set_selected(selected)
        self._apply_selection_style()

    def _apply_tree_depth_visual(self) -> None:
        self.lbl_nested.setVisible(self._tree_depth > 0)

    def update_display(self) -> None:
        self.lbl_cycles.setText(f"Cycles: {self.cycles}")

    def set_cycles(self, cycles: int) -> None:
        self.cycles = max(1, int(cycles))
        self.update_display()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": KIND_CYCLE,
            "mgcr_id": self.mgcr_id,
            "ald_id": self.ald_id,
            "cycle_num": self.cycles,
            "children": self.child_area.to_list(),
        }

class NmlcDropArea(QFrame):
    def __init__(self, dialog: "NestedMaterialCycleDialog", owner_cycle: CycleNodeWidget | None = None):
        super().__init__()
        self.dialog = dialog
        self.owner_cycle = owner_cycle
        self._is_root_area = owner_cycle is None
        self.items: list[_BaseNodeWidget] = []
        self.accepts = {KIND_CYCLE, KIND_MATERIAL, KIND_GAS}

        self.setAcceptDrops(True)
        self.setObjectName("nmlcDropArea")
        if self._is_root_area:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.setMinimumHeight(480)
        else:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self.setMinimumHeight(36)

        self.v = QVBoxLayout(self)
        self.v.setAlignment(Qt.AlignTop)
        if self._is_root_area:
            self.v.setContentsMargins(8, 8, 8, 8)
            self.v.setSpacing(6)
        else:
            self.v.setContentsMargins(4, 2, 2, 2)
            self.v.setSpacing(4)

        hint_text = "Drop cycle/material/gas here"
        self.hint = QLabel(hint_text if self._is_root_area else hint_text)
        self.v.addWidget(self.hint)

        self._indicator = QLabel("")
        self._indicator.setMinimumHeight(10)
        self._indicator.setMaximumHeight(10)
        self._indicator.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._indicator.hide()
        self._drop_index = -1
        self.apply_theme(self.dialog.layer_theme())
        self._update_item_widths()

    def apply_theme(self, theme: dict[str, str]) -> None:
        if self._is_root_area:
            self.setStyleSheet(
                "QFrame#nmlcDropArea{"
                f"border:1px solid {theme['canvas_border']};"
                "border-radius:10px;"
                f"background:{theme['canvas_bg']};"
                "}"
            )
        else:
            self.setStyleSheet("QFrame#nmlcDropArea{border:none;background:transparent;}")
        self.hint.setStyleSheet(f"color:{theme['hint']};font-size:12px;")
        self._indicator.setStyleSheet(
            "QLabel{"
            f"background:{theme['accent']};"
            f"border:1px solid {theme['accent']};"
            "border-radius:5px;"
            "}"
        )

    @property
    def parent_mgcr_id(self) -> int | None:
        return None if self.owner_cycle is None else self.owner_cycle.mgcr_id

    def clear(self) -> None:
        for item in list(self.items):
            self.remove_item(item, delete_widget=True)
        self.items.clear()
        self._clear_indicator()
        self.hint.setVisible(True)

    def _content_width(self) -> int:
        m = self.v.contentsMargins()
        return max(180, self.width() - m.left() - m.right())

    def _target_item_width(self) -> int:
        content_w = self._content_width()
        return max(220, min(760, int(content_w)))

    def _update_item_widths(self) -> None:
        for item in self.items:
            item.setMinimumWidth(0)
            item.setMaximumWidth(16_777_215)

    def add_item(self, item: _BaseNodeWidget, index: int | None = None) -> None:
        if index is None:
            index = len(self.items)
        index = max(0, min(int(index), len(self.items)))
        self.items.insert(index, item)
        item.parent_area = self
        item.setParent(self)
        self.v.insertWidget(index, item)
        self.dialog._refresh_hierarchy_for_subtree(item)
        self._update_item_widths()
        self.hint.setVisible(False)

    def remove_item(self, item: _BaseNodeWidget, delete_widget: bool) -> None:
        if item in self.items:
            self.items.remove(item)
        self.v.removeWidget(item)
        if delete_widget:
            item.deleteLater()
        else:
            item.setParent(None)
        if not self.items:
            self.hint.setVisible(True)
        else:
            self._update_item_widths()

    def _index_from_pos(self, y: int) -> int:
        if not self.items:
            return 0
        for idx, w in enumerate(self.items):
            if y < (w.y() + w.height() // 2):
                return idx
        return len(self.items)

    def _show_indicator(self, index: int) -> None:
        index = max(0, min(int(index), len(self.items)))
        self._drop_index = index
        self._indicator.setText("")
        self.v.removeWidget(self._indicator)
        target_w = self._target_item_width()
        self._indicator.setFixedWidth(target_w)
        self.v.insertWidget(index, self._indicator)
        self._indicator.show()

    def _clear_indicator(self) -> None:
        self._drop_index = -1
        self.v.removeWidget(self._indicator)
        self._indicator.hide()

    def _drop_index_from_event(self, event) -> int:
        return self._drop_index if self._drop_index >= 0 else self._index_from_pos(event.pos().y())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_item_widths()
        if self._indicator.isVisible():
            self._indicator.setFixedWidth(self._target_item_width())

    def _is_inside_cycle(self, cycle_widget: CycleNodeWidget) -> bool:
        cur = self.owner_cycle
        while cur is not None:
            if cur is cycle_widget:
                return True
            pa = cur.parent_area
            cur = None if pa is None else pa.owner_cycle
        return False

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if not md.hasFormat(MIME_KIND):
            event.ignore(); return
        try:
            kind = bytes(md.data(MIME_KIND)).decode("utf-8", errors="ignore")
        except Exception:
            kind = ""
        if kind in self.accepts:
            event.acceptProposedAction(); return
        event.ignore()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if not md.hasFormat(MIME_KIND):
            event.ignore(); return
        try:
            kind = bytes(md.data(MIME_KIND)).decode("utf-8", errors="ignore")
        except Exception:
            kind = ""
        if kind not in self.accepts:
            event.ignore(); return
        self._show_indicator(self._index_from_pos(event.pos().y()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._clear_indicator()
        event.accept()

    def dropEvent(self, event):
        md = event.mimeData()
        if not md.hasFormat(MIME_KIND):
            self._clear_indicator(); event.ignore(); return

        try:
            kind = bytes(md.data(MIME_KIND)).decode("utf-8", errors="ignore")
        except Exception:
            kind = ""
        idx = self._drop_index_from_event(event)
        self._clear_indicator()

        node_id = None
        if md.hasFormat(MIME_NODE_ID):
            try:
                node_id = int(bytes(md.data(MIME_NODE_ID)).decode("utf-8", errors="ignore"))
            except Exception:
                node_id = None

        if node_id is not None:
            node = self.dialog.widget_by_mgcr(node_id)
            if node is None:
                event.ignore(); return
            if node.node_kind == KIND_CYCLE and self._is_inside_cycle(node):
                QMessageBox.warning(self, "Invalid Move", "Cannot move a cycle into its own child area.")
                event.ignore(); return
            self.dialog.move_existing_node(node, self, idx)
            event.acceptProposedAction(); return

        if kind in self.accepts:
            self.dialog.create_new_node(kind, self, idx)
            event.acceptProposedAction(); return

        event.ignore()

    def to_list(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self.items]


class NmlcInfoPanel(QFrame):
    def __init__(self, dialog: "NestedMaterialCycleDialog"):
        super().__init__()
        self.dialog = dialog
        self._target: _BaseNodeWidget | None = None
        self._widgets: dict[str, QWidget] = {}

        self.setObjectName("nmlcInfoPanel")
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(8)

        self.title = QLabel("Information")
        self.title.setFont(QFont("Arial", 10, QFont.Bold))
        col.addWidget(self.title)

        self.host = QWidget()
        self.form = QFormLayout(self.host)
        self.form.setContentsMargins(4, 4, 4, 4)
        self.form.setSpacing(8)
        col.addWidget(self.host)
        col.addStretch(1)

    def _clear_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets.clear()

    def set_target(self, node: _BaseNodeWidget | None) -> None:
        self._target = node
        self._clear_form()
        if node is None:
            self.title.setText("Information")
            return

        if isinstance(node, MaterialNodeWidget):
            self.title.setText("Material Information")
            btn_d = QPushButton(node.desired or "Select Material")
            btn_d.selected_material = node.desired or ""
            btn_d.clicked.connect(lambda: self._open_selector(btn_d, "desired_material"))
            self.form.addRow("Desired material:", btn_d)
            self._widgets["desired"] = btn_d

            btn_p = QPushButton(node.precursor or "Select Precursor")
            btn_p.selected_material = node.precursor or ""
            btn_p.clicked.connect(lambda: self._open_selector(btn_p, "precursor_name"))
            self.form.addRow("Precursor name:", btn_p)
            self._widgets["precursor"] = btn_p

            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(0.0, 1e9)
            spin.setSingleStep(0.05)
            spin.setValue(0.0 if node.dep_rate_value is None else float(node.dep_rate_value))
            unit = QComboBox(); unit.addItems(["nm/cycle", "A/cycle"])
            unit.setCurrentText(node.dep_rate_unit if node.dep_rate_unit in {"nm/cycle", "A/cycle"} else "nm/cycle")
            spin.valueChanged.connect(lambda _v: self._apply_material())
            unit.currentIndexChanged.connect(lambda _i: self._apply_material())
            row = QHBoxLayout(); row.addWidget(spin, 2); row.addWidget(unit, 1)
            holder = QWidget(); holder.setLayout(row)
            self.form.addRow("Deposition rate:", holder)
            self._widgets["rate_spin"] = spin; self._widgets["rate_unit"] = unit
            return

        if isinstance(node, GasNodeWidget):
            self.title.setText("Gas Information")
            gas_type = QPushButton(node.gas_type or "Select Gas")
            gas_type.selected_material = node.gas_type or ""
            gas_type.clicked.connect(lambda: self._open_selector(gas_type, "gas"))
            self.form.addRow("Gas type:", gas_type)
            self._widgets["gas_type"] = gas_type

            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(0.0, 1e9)
            spin.setSingleStep(0.1)
            spin.setValue(0.0 if node.flow_value is None else float(node.flow_value))
            unit = QComboBox(); unit.addItems(["sccm", "slm"])
            unit.setCurrentText(node.flow_unit if node.flow_unit in {"sccm", "slm"} else "sccm")
            spin.valueChanged.connect(lambda _v: self._apply_gas())
            unit.currentIndexChanged.connect(lambda _i: self._apply_gas())
            row = QHBoxLayout(); row.addWidget(spin, 2); row.addWidget(unit, 1)
            holder = QWidget(); holder.setLayout(row)
            self.form.addRow("Flow:", holder)
            self._widgets["flow_spin"] = spin; self._widgets["flow_unit"] = unit
            return

        if isinstance(node, CycleNodeWidget):
            self.title.setText("Cycle Information")
            spin = QSpinBox(); spin.setRange(1, 10_000_000); spin.setValue(node.cycles)
            spin.valueChanged.connect(lambda v: self._apply_cycle(v))
            self.form.addRow("Cycle number:", spin)
            self._widgets["cycles"] = spin
            return

        self.title.setText("Information")

    def _open_selector(self, btn: QPushButton, material_type: str) -> None:
        selector_cls = self.dialog.selector_cls
        if selector_cls is None or self._target is None:
            return
        dlg = selector_cls(
            parent=self.dialog,
            selected_materials=[getattr(btn, "selected_material", "")],
            conn=self.dialog.db_conn,
            tool_name="ALD",
            material_type=material_type,
            desired_material=None,
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        picked = getattr(dlg, "selected_material", "") or ""
        btn.selected_material = picked
        if material_type == "precursor_name":
            empty_text = "Select Precursor"
        elif material_type == "gas":
            empty_text = "Select Gas"
        else:
            empty_text = "Select Material"
        btn.setText(picked if picked else empty_text)

        if isinstance(self._target, MaterialNodeWidget):
            if material_type == "desired_material":
                self._target.desired = picked
            else:
                self._target.precursor = picked
            self._target.update_display()
            self.dialog.apply_material_edits(self._target)
        elif isinstance(self._target, GasNodeWidget) and material_type == "gas":
            self._target.gas_type = picked
            self._target.update_display()
            self.dialog.apply_gas_edits(self._target)

    def _apply_material(self) -> None:
        if not isinstance(self._target, MaterialNodeWidget):
            return
        rate_spin = self._widgets.get("rate_spin")
        rate_unit = self._widgets.get("rate_unit")
        if not isinstance(rate_spin, QDoubleSpinBox) or not isinstance(rate_unit, QComboBox):
            return
        self._target.dep_rate_value = float(rate_spin.value())
        self._target.dep_rate_unit = rate_unit.currentText()
        self._target.update_display()
        self.dialog.apply_material_edits(self._target)

    def _apply_gas(self) -> None:
        if not isinstance(self._target, GasNodeWidget):
            return
        gas_type = self._widgets.get("gas_type")
        flow_spin = self._widgets.get("flow_spin")
        flow_unit = self._widgets.get("flow_unit")
        if not isinstance(gas_type, QPushButton) or not isinstance(flow_spin, QDoubleSpinBox) or not isinstance(flow_unit, QComboBox):
            return
        self._target.gas_type = str(getattr(gas_type, "selected_material", "") or "").strip()
        self._target.flow_value = float(flow_spin.value())
        self._target.flow_unit = flow_unit.currentText()
        self._target.update_display()
        self.dialog.apply_gas_edits(self._target)

    def _apply_cycle(self, value: int) -> None:
        if not isinstance(self._target, CycleNodeWidget):
            return
        self._target.set_cycles(int(value))
        self.dialog.apply_cycle_edits(self._target)

class NestedMaterialCycleDialog(QDialog):
    def __init__(self, parent=None, db_conn=None, selector_cls=None, ald_id=None, layer_name: str | None = None):
        super().__init__(parent)
        self.db_conn = db_conn
        self.selector_cls = selector_cls
        self.active_ald_id = int(ald_id) if ald_id is not None else None
        self.layer_name = _normalize_layer_name(layer_name)

        self._registry: dict[int, _BaseNodeWidget] = {}
        self._selected: _BaseNodeWidget | None = None
        self.canvas: NmlcDropArea | None = None
        self.info: NmlcInfoPanel | None = None
        self._base_qss = ""

        self._init_window()
        self._init_ui()
        if self.active_ald_id is not None:
            self._load_from_db()

    def _init_window(self) -> None:
        self.setWindowTitle("Nested Material Cycle")
        self.resize(1120, 700)
        try:
            UIImprovement.apply_theme(self, dark=False)
        except Exception:
            pass
        self._base_qss = self.styleSheet()
        self._apply_dialog_theme()

    def layer_theme(self) -> dict[str, str]:
        return dict(LAYER_THEMES.get(self.layer_name, LAYER_THEMES["Top"]))

    def _apply_dialog_theme(self) -> None:
        theme = self.layer_theme()
        self.setStyleSheet(
            self._base_qss
            + f"""
            QDialog {{ background: #F3F6FA; }}
            QFrame#nmlcPalette, QFrame#nmlcInfoPanel, QFrame#nmlcCanvasWrap {{
                background: #FFFFFF;
                border: 1px solid {theme['canvas_border']};
                border-radius: 12px;
            }}
            """
        )

    def _apply_tree_theme(self) -> None:
        theme = self.layer_theme()
        if self.canvas is None:
            return
        self._apply_area_theme_recursive(self.canvas, theme)
        for node in list(self._registry.values()):
            node.set_selected(node is self._selected)

    def _apply_area_theme_recursive(self, area: NmlcDropArea, theme: dict[str, str]) -> None:
        area.apply_theme(theme)
        for item in area.items:
            if isinstance(item, CycleNodeWidget):
                self._apply_area_theme_recursive(item.child_area, theme)

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Horizontal)
        UIImprovement.set_vertical_splitter_style(splitter)
        root.addWidget(splitter)

        splitter.addWidget(self._build_palette_panel())

        canvas_wrap = QFrame(); canvas_wrap.setObjectName("nmlcCanvasWrap")
        canvas_layout = QVBoxLayout(canvas_wrap)
        canvas_layout.setContentsMargins(8, 8, 8, 8); canvas_layout.setSpacing(8)
        lbl = QLabel("Cycle Tree"); lbl.setFont(QFont("Arial", 10, QFont.Bold)); canvas_layout.addWidget(lbl)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); UIImprovement.set_scroll_area_style(scroll)
        inner = QWidget(); inner_layout = QVBoxLayout(inner); inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        self.canvas = NmlcDropArea(self, owner_cycle=None)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inner_layout.addWidget(self.canvas, 1)
        scroll.setWidget(inner)
        canvas_layout.addWidget(scroll)
        splitter.addWidget(canvas_wrap)

        self.info = NmlcInfoPanel(self)
        splitter.addWidget(self.info)
        splitter.setSizes([190, 640, 290])
        self._apply_tree_theme()

    def _build_palette_panel(self) -> QFrame:
        theme = self.layer_theme()
        panel = QFrame(); panel.setObjectName("nmlcPalette")
        lay = QVBoxLayout(panel); lay.setContentsMargins(10, 10, 10, 10); lay.setSpacing(10)
        title = QLabel("Drag Sources"); title.setFont(QFont("Arial", 10, QFont.Bold)); lay.addWidget(title)

        button_styles = {
            KIND_CYCLE: (theme["cycle_bg"], theme["cycle_bg_selected"]),
            KIND_MATERIAL: (theme["material_bg"], theme["material_bg_selected"]),
            KIND_GAS: (theme["gas_bg"], theme["gas_bg_selected"]),
        }
        for b in (
            _PaletteDragButton("Cycle", KIND_CYCLE),
            _PaletteDragButton("Material", KIND_MATERIAL),
            _PaletteDragButton("Gas", KIND_GAS),
        ):
            base_bg, hover_bg = button_styles.get(b.kind, (theme["canvas_bg"], theme["material_bg"]))
            b.setMinimumHeight(38)
            b.setStyleSheet(
                f"QPushButton{{border:1px solid {theme['canvas_border']};border-radius:10px;"
                f"background:{base_bg};padding:6px;font-weight:700;color:{theme['text']};}}"
                f"QPushButton:hover{{background:{hover_bg};}}"
            )
            lay.addWidget(b)

        tip = QLabel("Tip: drag existing nodes with ⋮⋮ handle")
        tip.setWordWrap(True); tip.setStyleSheet(f"color:{theme['hint']};font-size:12px;")
        lay.addWidget(tip); lay.addStretch(1)
        return panel

    def set_active_ald(self, ald_id: int):
        self.active_ald_id = int(ald_id)
        self._load_from_db()

    def set_active_context(self, ald_id: int, layer_name: str | None = None) -> None:
        if layer_name is not None:
            self.layer_name = _normalize_layer_name(layer_name)
            self._apply_dialog_theme()
            self._apply_tree_theme()
        self.set_active_ald(ald_id)

    def widget_by_mgcr(self, mgcr_id: int) -> _BaseNodeWidget | None:
        return self._registry.get(int(mgcr_id))

    def _node_depth(self, node: _BaseNodeWidget) -> int:
        depth = 0
        area = node.parent_area
        while area is not None and area.owner_cycle is not None:
            depth += 1
            area = area.owner_cycle.parent_area
        return depth

    def _refresh_hierarchy_for_subtree(self, node: _BaseNodeWidget) -> None:
        node.set_tree_depth(self._node_depth(node))
        if isinstance(node, CycleNodeWidget):
            for child in node.child_area.items:
                self._refresh_hierarchy_for_subtree(child)

    def _register_node(self, node: _BaseNodeWidget) -> None:
        if node.mgcr_id is not None:
            self._registry[int(node.mgcr_id)] = node

    def _unregister_subtree(self, node: _BaseNodeWidget) -> None:
        if node.mgcr_id is not None:
            self._registry.pop(int(node.mgcr_id), None)
        if isinstance(node, CycleNodeWidget):
            for child in list(node.child_area.items):
                self._unregister_subtree(child)

    def select_node(self, node: _BaseNodeWidget | None) -> None:
        if self._selected is not None:
            self._selected.set_selected(False)
        self._selected = node
        if self._selected is not None:
            self._selected.set_selected(True)
        if self.info is not None:
            self.info.set_target(node)

    def create_new_node(self, kind: str, target_area: NmlcDropArea, index: int) -> None:
        if kind not in {KIND_CYCLE, KIND_MATERIAL, KIND_GAS}:
            return
        created = self._create_db_node(kind, target_area.parent_mgcr_id, index)
        if created is None:
            return

        if kind == KIND_CYCLE:
            node = CycleNodeWidget(self)
        elif kind == KIND_GAS:
            node = GasNodeWidget(self)
        else:
            node = MaterialNodeWidget(self)
        if isinstance(node, CycleNodeWidget):
            node.set_cycles(1)

        node.mgcr_id = int(created["mgcr_id"]); node.ald_id = int(created["ald_id"])
        target_area.add_item(node, index)
        self._register_node(node)
        self.select_node(node)

    def move_existing_node(self, node: _BaseNodeWidget, target_area: NmlcDropArea, index: int) -> None:
        src_area = node.parent_area
        if src_area is None:
            return
        if node.node_kind == KIND_CYCLE and target_area._is_inside_cycle(node):
            QMessageBox.warning(self, "Invalid Move", "Cannot move a cycle into its own child area.")
            return

        src_index = src_area.items.index(node)
        if src_area is target_area and src_index < index:
            index -= 1
        if src_area is target_area and src_index == index:
            return

        old_parent = src_area.parent_mgcr_id
        new_parent = target_area.parent_mgcr_id
        src_area.remove_item(node, delete_widget=False)
        target_area.add_item(node, index)

        if node.mgcr_id is not None:
            self._move_db_node(int(node.mgcr_id), old_parent, new_parent, index)
        self.select_node(node)

    def delete_node(self, node: _BaseNodeWidget) -> None:
        if node.mgcr_id is None or node.parent_area is None:
            return
        if QMessageBox.question(self, "Confirm Delete", "Delete selected node and its children?") != QMessageBox.Yes:
            return

        selected_inside = self._contains(node, self._selected)
        self._delete_db_node(int(node.mgcr_id))
        node.parent_area.remove_item(node, delete_widget=True)
        self._unregister_subtree(node)
        if selected_inside:
            self.select_node(None)

    @staticmethod
    def _contains(root: _BaseNodeWidget, target: _BaseNodeWidget | None) -> bool:
        if target is None:
            return False
        if root is target:
            return True
        if isinstance(root, CycleNodeWidget):
            return any(NestedMaterialCycleDialog._contains(ch, target) for ch in root.child_area.items)
        return False

    def _require_ald(self) -> bool:
        if self.active_ald_id is None:
            QMessageBox.warning(self, "ALD Required", "Active ALD row is not set.")
            return False
        return True

    def _next_ord(self, parent_mgcr_id: int | None) -> int:
        if self.db_conn is None or not self._require_ald():
            return 0
        return db_ops.nmlc_next_order(self.db_conn, self.active_ald_id, parent_mgcr_id)

    def _create_db_node(self, kind: str, parent_mgcr_id: int | None, ord_value: int | None) -> dict[str, int] | None:
        if self.db_conn is None or not self._require_ald():
            return None
        return db_ops.nmlc_create_node(
            self.db_conn,
            ald_id=int(self.active_ald_id),
            kind=kind,
            parent_mgcr_id=parent_mgcr_id,
            order_value=ord_value,
        )

    def _delete_db_node(self, mgcr_id: int) -> None:
        if self.db_conn is None or not self._require_ald():
            return
        db_ops.nmlc_delete_node(self.db_conn, mgcr_id=int(mgcr_id))

    def _move_db_node(self, mgcr_id: int, old_parent_id: int | None, new_parent_id: int | None, new_ord: int) -> None:
        if self.db_conn is None or not self._require_ald():
            return
        db_ops.nmlc_move_node(
            self.db_conn,
            ald_id=int(self.active_ald_id),
            mgcr_id=int(mgcr_id),
            old_parent_id=old_parent_id,
            new_parent_id=new_parent_id,
            new_order=int(new_ord),
        )

    def _reorder_siblings(self, parent_mgcr_id: int | None) -> None:
        if self.db_conn is None or not self._require_ald():
            return
        db_ops.nmlc_reorder_siblings(self.db_conn, ald_id=int(self.active_ald_id), parent_mgcr_id=parent_mgcr_id)

    def apply_material_edits(self, node: MaterialNodeWidget) -> None:
        if self.db_conn is None or node.mgcr_id is None:
            return
        dm = (node.desired or "").strip(); pc = (node.precursor or "").strip(); val = node.dep_rate_value
        unit = node.dep_rate_unit or "nm/cycle"
        db_ops.nmlc_upsert_material(
            self.db_conn,
            mgcr_id=int(node.mgcr_id),
            ald_id=None if node.ald_id is None else int(node.ald_id),
            desired_material=dm,
            precursor_name=pc,
            dep_rate_value=val,
            dep_rate_unit=unit,
        )

    def apply_gas_edits(self, node: GasNodeWidget) -> None:
        if self.db_conn is None or node.mgcr_id is None:
            return
        gas_type = (node.gas_type or "").strip()
        flow_value = node.flow_value
        flow_unit = node.flow_unit or "sccm"
        db_ops.nmlc_upsert_gas(
            self.db_conn,
            mgcr_id=int(node.mgcr_id),
            gas_type=gas_type,
            flow_value=flow_value,
            flow_unit=flow_unit,
        )

    def apply_cycle_edits(self, node: CycleNodeWidget) -> None:
        if self.db_conn is None or node.mgcr_id is None:
            return
        db_ops.nmlc_upsert_cycle(self.db_conn, mgcr_id=int(node.mgcr_id), cycle_number=int(node.cycles))

    def _load_from_db(self) -> None:
        if self.canvas is None:
            return
        self._registry.clear()
        self.select_node(None)

        if self.db_conn is None or self.active_ald_id is None:
            self.canvas.clear(); return
        roots = db_ops.nmlc_load_tree(self.db_conn, int(self.active_ald_id))
        if not roots:
            self.canvas.clear(); return

        self.canvas.clear()
        for node in roots:
            self._build_widget_recursive(self.canvas, node)

        if self.canvas.items:
            self.select_node(self.canvas.items[0])
        self._apply_tree_theme()

    def _loadFromDB(self):
        self._load_from_db()

    def _build_widget_recursive(self, area: NmlcDropArea, node: dict[str, Any]) -> _BaseNodeWidget:
        kind = (node.get("type") or "").strip().lower()
        if kind == KIND_CYCLE:
            w = CycleNodeWidget(self)
            w.set_cycles(int(node.get("cycle_num", 1) or 1))
        elif kind == KIND_GAS:
            w = GasNodeWidget(self)
            w.gas_type = str(node.get("gas_type", "") or "")
            flow_value = node.get("flow_value", None)
            w.flow_value = None if flow_value is None else float(flow_value)
            w.flow_unit = str(node.get("flow_unit", "sccm") or "sccm")
            w.update_display()
        else:
            w = MaterialNodeWidget(self)
            w.desired = str(node.get("desired_material", "") or "")
            w.precursor = str(node.get("precursor_name", "") or "")
            val = node.get("dep_rate_value", None)
            w.dep_rate_value = None if val is None else float(val)
            w.dep_rate_unit = str(node.get("dep_rate_unit", "nm/cycle") or "nm/cycle")
            w.update_display()

        w.mgcr_id = int(node.get("mgcr_id")) if node.get("mgcr_id") is not None else None
        w.ald_id = int(node.get("ald_id")) if node.get("ald_id") is not None else None

        area.add_item(w, len(area.items))
        self._register_node(w)

        if isinstance(w, CycleNodeWidget):
            for child in node.get("children", []) or []:
                self._build_widget_recursive(w.child_area, child)

        return w

    def get_structure(self):
        if self.canvas is None:
            return []
        return self.canvas.to_list()

    def get_first_material(self):
        def _dfs(nodes: list[dict[str, Any]]):
            for n in nodes:
                t = (n.get("type") or "").strip().lower()
                if t == KIND_MATERIAL:
                    return (n.get("desired_material") or "", n.get("precursor_name") or "")
                if t == KIND_CYCLE:
                    got = _dfs(n.get("children") or [])
                    if got:
                        return got
            return None

        found = _dfs(self.get_structure() or [])
        return found if found else ("", "")


# Backward compatibility for callers still using the old class name.
NestedMaterialLoopChipDialog = NestedMaterialCycleDialog
