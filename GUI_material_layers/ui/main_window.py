from __future__ import annotations

from html import escape
import re
import sys
from pathlib import Path
from typing import List

from PyQt5.QtCore import QEvent, QMimeData, QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QDrag, QFont, QKeySequence, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..logic.enums import ToolType
from ..logic.models import ProcessStep
from ..logic.params import ParamSpec, specs_for
from ..logic.process_service import ProcessService
from ..logic.recipe_service import RecipeService
from ..sql import db_ops
from .style import UIImprovement


LAYER_RANK = {
    "Substrate": 1,
    "Source_Drain_Adhesion": 2,
    "Source_Drain_Electrode": 3,
    "Channel": 4,
    "Gate_Dielectric": 5,
    "Gate_Adhesion": 6,
    "Gate_Electrode": 7
}
ALL_LAYERS = ("Gate_Electrode", "Gate_Adhesion", "Gate_Dielectric", "Channel", "Source_Drain_Electrode", "Source_Drain_Adhesion", "Substrate")

MIME_ITEM_TYPE = "application/x-item-type"
MIME_TOOL_STEP_ID = "application/x-tool-step-id"


def _layer_badge(layer_name: str) -> str:
    return f"L{LAYER_RANK.get(layer_name, '?')} {layer_name}"


def _open_attachment_dialog(parent: QWidget, tool_button: "ToolItemWidget") -> None:
    """
    Lazy import avoids crashing the whole app at startup if attachment module has env issues.
    """
    try:
        from ..material_cleanroom_attachment_function import AttachmentDialog  # type: ignore
    except Exception as exc:
        QMessageBox.warning(parent, "Attachment Unavailable", f"Attachment dialog failed to import:\n{exc}")
        return
    AttachmentDialog(parent, tool_button).exec_()


class LayerCakeWidget(QWidget):
    """Small decorative layer stack to show bottom->top order with a pseudo 3D look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        self.layer_materials: dict[str, str] = {layer: "Select Material" for layer in ALL_LAYERS}
        self.layer_details: dict[str, list[str]] = {layer: ["Select Material"] for layer in ALL_LAYERS}
        self.layer_weights: dict[str, float] = {layer: 1.0 for layer in ALL_LAYERS}
        
        self.setToolTip("Layer stack: Gate / Gate_Dielectric / Channel / Source_Drain / Substrate")

    def _stack_font_point_sizes(self) -> tuple[int, int]:
        app = QApplication.instance()
        app_font = app.font() if app is not None else self.font()
        app_pt = app_font.pointSizeF()
        if app_pt <= 0:
            app_pt = float(max(10, self.font().pointSize()))

        # Keep the stack text tied to the global adaptive font, but bump it up
        # a little and let larger stack widgets breathe more.
        size_scale = min(max(min(self.width() / 340.0, self.height() / 240.0), 0.95), 1.20)
        title_pt = int(round(max(11.0, min(18.0, (app_pt + 2.0) * size_scale))))
        body_pt = max(10, title_pt - 1)
        return title_pt, body_pt

    def set_layer_materials(
        self,
        layer_materials: dict[str, str],
        layer_details: dict[str, list[str]] | None = None,
        layer_weights: dict[str, float] | None = None,
    ) -> None:
        for layer in ALL_LAYERS:
            text = (layer_materials.get(layer, "") or "").strip()
            self.layer_materials[layer] = text if text else ""
            details_raw = list(layer_details.get(layer, [])) if layer_details else []
            details_clean: list[str] = []
            for raw in details_raw:
                line = str(raw or "").rstrip()
                if line.strip():
                    details_clean.append(line)
            self.layer_details[layer] = details_clean
            weight = 0.0
            if layer_weights is not None:
                try:
                    weight = float(layer_weights.get(layer, 0.0) or 0.0)
                except Exception:
                    weight = 0.0
            self.layer_weights[layer] = max(0.0, weight)

        tip_lines: list[str] = []
        for layer in ALL_LAYERS:
            tip_lines.append(f"{layer}:")
            for line in self.layer_details[layer]:
                tip_lines.append(f"  {line}")
        self.setToolTip("Layer materials:\n" + "\n".join(tip_lines))
        self.update()

    @staticmethod
    def _short(text: str, max_len: int = 22) -> str:
        return text if len(text) <= max_len else (text[: max_len - 1] + "…")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.resetTransform()

        def get_dynamic_label(layer_name: str) -> str:
            mat = self.layer_materials.get(layer_name, "")
            if mat and mat not in ("", "No material", "Select Material") and not mat.startswith("+"):
                return mat
            role = layer_name.replace("_", " ")
            return role

        painter.setRenderHint(QPainter.Antialiasing, True)

        box = self.rect().adjusted(12, 10, -22, -10)
        if box.width() <= 0 or box.height() <= 0:
            return

        X0 = box.left()
        X1 = box.right()
        W = X1 - X0
        H = box.height()

        h_sub = H * 0.15
        h_sd_bot = H * 0.10
        h_sd_top = H * 0.10
        h_igzo_top = H * 0.05
        h_diel = H * 0.15
        h_gate_bot = H * 0.08
        h_gate_top = H * 0.10

        Y_sub_bottom = box.bottom() - H * 0.05
        Y_sub_top = Y_sub_bottom - h_sub
        Y_sd_mid = Y_sub_top - h_sd_bot
        Y_sd_top_edge = Y_sd_mid - h_sd_top

        S_right = X0 + W * 0.28
        D_left = X0 + W * 0.72
        Gap_center = (S_right + D_left) / 2.0

        c_sub = QColor("#4A90E2")
        c_ti = QColor("#9E9E9E")
        c_pt = QColor("#424242")
        c_igzo = QColor("#5C4033")
        c_diel = QColor("#1B5E20")

        def draw_rect_with_text(rect, color, text, text_color):
            painter.setPen(QPen(color.darker(130), 2))
            painter.setBrush(color)
            painter.drawRect(rect)

            font = painter.font()
            font.setPointSize(max(7, int(H * 0.030)))
            font.setBold(True)
            painter.setFont(font)

            painter.setPen(text_color)
            painter.drawText(rect, int(Qt.AlignCenter | Qt.TextWordWrap), text)

        def draw_poly_with_text(poly, color, text, text_color, text_rect):
            painter.setPen(QPen(color.darker(130), 2))
            painter.setBrush(color)
            painter.drawPolygon(poly)

            font = painter.font()
            font.setPointSize(max(7, int(H * 0.030)))
            font.setBold(True)
            painter.setFont(font)

            painter.setPen(text_color)
            painter.drawText(text_rect, int(Qt.AlignCenter | Qt.TextWordWrap), text)

        sub_rect = QRectF(X0, Y_sub_top, W, h_sub)
        draw_rect_with_text(sub_rect, c_sub, get_dynamic_label("Substrate"), QColor("#FFFFFF"))

        S_left = X0
        D_right = X1
        S_center_x = (S_left + S_right) / 2.0
        D_center_x = (D_left + D_right) / 2.0

        s_bot_rect = QRectF(S_left, Y_sd_mid, S_right - S_left, h_sd_bot)
        draw_rect_with_text(s_bot_rect, c_ti, get_dynamic_label("Source_Drain_Adhesion"), QColor("#000000"))
        s_top_rect = QRectF(S_left, Y_sd_top_edge, S_right - S_left, h_sd_top)
        draw_rect_with_text(s_top_rect, c_pt, get_dynamic_label("Source_Drain_Electrode"), QColor("#FFFFFF"))

        d_bot_rect = QRectF(D_left, Y_sd_mid, D_right - D_left, h_sd_bot)
        draw_rect_with_text(d_bot_rect, c_ti, get_dynamic_label("Source_Drain_Adhesion"), QColor("#000000"))
        d_top_rect = QRectF(D_left, Y_sd_top_edge, D_right - D_left, h_sd_top)
        draw_rect_with_text(d_top_rect, c_pt, get_dynamic_label("Source_Drain_Electrode"), QColor("#FFFFFF"))

        igzo_y_top = Y_sd_top_edge - h_igzo_top
        igzo_poly = QPolygonF([
            QPointF(S_center_x, Y_sd_top_edge),
            QPointF(S_center_x, igzo_y_top),
            QPointF(D_center_x, igzo_y_top),
            QPointF(D_center_x, Y_sd_top_edge),
            QPointF(D_left, Y_sd_top_edge),
            QPointF(D_left, Y_sub_top),
            QPointF(S_right, Y_sub_top),
            QPointF(S_right, Y_sd_top_edge)
        ])
        igzo_text_rect = QRectF(S_center_x, igzo_y_top + h_igzo_top * 0.25, D_center_x - S_center_x, h_igzo_top * 0.75)
        draw_poly_with_text(igzo_poly, c_igzo, get_dynamic_label("Channel"), QColor("#FFFFFF"), igzo_text_rect)

        diel_y_top = igzo_y_top - h_diel
        gap_width = D_left - S_right
        gate_w = gap_width
        diel_top_w = gate_w + W * 0.08
        diel_top_left = Gap_center - (diel_top_w / 2.0)
        diel_top_right = Gap_center + (diel_top_w / 2.0)
        diel_slope_x = W * 0.05

        diel_poly = QPolygonF([
            QPointF(S_center_x - diel_slope_x, Y_sd_top_edge),
            QPointF(S_center_x - W * 0.01, igzo_y_top - W * 0.01),
            QPointF(diel_top_left, diel_y_top),
            QPointF(diel_top_right, diel_y_top),
            QPointF(D_center_x + W * 0.01, igzo_y_top - W * 0.01),
            QPointF(D_center_x + diel_slope_x, Y_sd_top_edge),
            QPointF(D_center_x, Y_sd_top_edge),
            QPointF(D_center_x, igzo_y_top),
            QPointF(S_center_x, igzo_y_top),
            QPointF(S_center_x, Y_sd_top_edge)
        ])
        diel_text_rect = QRectF(diel_top_left, diel_y_top + h_diel * 0.30, diel_top_w, h_diel * 0.70)
        draw_poly_with_text(diel_poly, c_diel, get_dynamic_label("Gate_Dielectric"), QColor("#FFFFFF"), diel_text_rect)

        Gate_left = Gap_center - (gap_width / 2.0)
        gate_bot_y = diel_y_top - h_gate_bot
        gate_bot_rect = QRectF(Gate_left, gate_bot_y, gate_w, h_gate_bot)
        draw_rect_with_text(gate_bot_rect, c_ti, get_dynamic_label("Gate_Adhesion"), QColor("#000000"))

        gate_top_y = gate_bot_y - h_gate_top
        gate_top_rect = QRectF(Gate_left, gate_top_y, gate_w, h_gate_top)
        draw_rect_with_text(gate_top_rect, c_pt, get_dynamic_label("Gate_Electrode"), QColor("#FFFFFF"))


class DraggableButton(QPushButton):
    def __init__(self, text: str, button_type: str = "tool", payload: str | None = None):
        super().__init__(text)
        self.button_type = button_type
        self.payload = payload or text

    def mouseMoveEvent(self, event):
        if event.buttons() != Qt.LeftButton:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.payload)
        mime.setData(MIME_ITEM_TYPE, self.button_type.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)


class ToolCardWidget(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolCardWidget")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(52)

        self._hover = False
        self._pressed = False
        self._meta_font_pt = 10
        self._palette: dict[str, str] = {
            "bg": "#E3F2FD",
            "hover": "#D4EAFC",
            "pressed": "#C4E1FB",
            "border": "#64B5F6",
            "text": "#0E4A82",
        }

        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 4, 7, 4)
        lay.setSpacing(1)

        self.title_label = QLabel("")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setTextFormat(Qt.RichText)
        self.title_label.setWordWrap(False)
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.title_label)

        self.material_label = QLabel("")
        self.material_label.setAlignment(Qt.AlignCenter)
        self.material_label.setWordWrap(True)
        self.material_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.material_label)

        self._apply_style()

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = dict(palette or self._palette)
        self._apply_style()

    def set_meta_font_size_pt(self, pt: int) -> None:
        self._meta_font_pt = max(9, int(pt))
        self._apply_style()

    def set_texts(self, title_html: str, material_lines: list[str]) -> None:
        self.title_label.setText(title_html or "")
        has_material = bool(material_lines)
        self.material_label.setVisible(has_material)
        self.material_label.setText("\n".join(material_lines) if has_material else "")

        body_h = self.material_label.fontMetrics().lineSpacing() * len(material_lines) if has_material else 0
        gap = 2 if has_material else 0
        target_h = max(52, 28 + gap + body_h)
        self.setMinimumHeight(int(target_h))

    def _apply_style(self) -> None:
        p = self._palette
        if self._pressed:
            bg = p["pressed"]
        elif self._hover:
            bg = p["hover"]
        else:
            bg = p["bg"]

        self.setStyleSheet(
            f"""
            QFrame#toolCardWidget {{
                background: {bg};
                border: none;
                border-radius: 12px;
            }}
            """
        )
        self.title_label.setStyleSheet(
            f"QLabel{{color:{p['text']};font-weight:800;padding:0px;background:transparent;"
            "font-family:Arial;}}"
        )
        self.material_label.setStyleSheet(
            f"QLabel{{color:{p['text']};font-size:{self._meta_font_pt}pt;font-weight:600;"
            "padding:0px;background:transparent;font-family:Arial;}}"
        )

    def enterEvent(self, _e):
        self._hover = True
        self._apply_style()

    def leaveEvent(self, _e):
        self._hover = False
        self._pressed = False
        self._apply_style()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed = True
            self._apply_style()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        was_pressed = self._pressed
        self._pressed = False
        self._apply_style()
        if was_pressed and e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class ToolItemWidget(QWidget):
    _LAYER_CARD_PALETTES: dict[str, dict[str, str]] = {
        "Substrate": {
            "bg": "#EFEBE9",
            "hover": "#D7CCC8",
            "pressed": "#BCAAA4",
            "border": "#A1887F",
            "text": "#3E2723",
        },
        "Source_Drain_Adhesion": {
            "bg": "#FFF3E0",
            "hover": "#FFECB3",
            "pressed": "#FFE082",
            "border": "#FFCA28",
            "text": "#F57F17",
        },
        "Source_Drain_Electrode": {
            "bg": "#FFEBEE",
            "hover": "#FFCDD2",
            "pressed": "#EF9A9A",
            "border": "#E53935",
            "text": "#B71C1C",
        },
        "Channel": {
            "bg": "#F3E5F5",
            "hover": "#E1BEE7",
            "pressed": "#CE93D8",
            "border": "#AB47BC",
            "text": "#4A148C",
        },
        "Gate_Dielectric": {
            "bg": "#E8F5E9",
            "hover": "#C8E6C9",
            "pressed": "#A5D6A7",
            "border": "#66BB6A",
            "text": "#1B5E20",
        },
        "Gate_Adhesion": {
            "bg": "#FFF8E1",
            "hover": "#FFECB3",
            "pressed": "#FFE082",
            "border": "#FFC107",
            "text": "#FF8F00",
        },
        "Gate_Electrode": {
            "bg": "#E3F2FD",
            "hover": "#BBDEFB",
            "pressed": "#90CAF9",
            "border": "#42A5F5",
            "text": "#0D47A1",
        },
    }
    TOOL_FONT_DELTA_PT = 1
    META_FONT_DELTA_PT = 0

    def __init__(self, step: ProcessStep, main_window: 'MainWindow', sublayer_widget: 'SubLayerWidget'):
        super().__init__()
        self.step = step
        self.main_window = main_window
        self.sublayer_widget = sublayer_widget
        self._drag_start_pos = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(0)

        self.chip = ToolCardWidget()
        self.chip.setFocusPolicy(Qt.NoFocus)
        self.chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.chip.set_meta_font_size_pt(11)
        self.chip.clicked.connect(lambda: self.sublayer_widget.on_tool_click(self))

        try:
            UIImprovement.add_shadow(self.chip)
        except Exception:
            pass
        self.chip.installEventFilter(self)

        lay.addWidget(self.chip)
        self.updateMaterialDisplay()

    @property
    def tool_id(self) -> int:
        return int(self.step.step_id or 0)

    @property
    def tool_name(self) -> str:
        return self.step.tool_type.value

    @property
    def base_name(self) -> str:
        return self.step.tool_type.value

    @property
    def layer_name(self) -> str:
        return self.step.layer.value

    @staticmethod
    def _short_line(text: str, max_len: int = 34) -> str:
        s = (text or "").strip()
        if len(s) <= max_len:
            return s
        return s[: max_len - 1] + "…"

    def _palette_for_layer(self) -> dict[str, str]:
        return dict(self._LAYER_CARD_PALETTES.get(self.layer_name, self._LAYER_CARD_PALETTES["Gate_Electrode"]))

    def _apply_chip_style(self) -> None:
        self.chip.set_palette(self._palette_for_layer())

    def _font_sizes_pt(self) -> tuple[int, int]:
        app = QApplication.instance()
        base_pt = 10
        try:
            if app is not None and app.font().pointSize() > 0:
                base_pt = int(app.font().pointSize())
            elif self.font().pointSize() > 0:
                base_pt = int(self.font().pointSize())
        except Exception:
            base_pt = 10
        base_pt = max(10, base_pt)
        tool_pt = min(20, base_pt + self.TOOL_FONT_DELTA_PT)
        meta_pt = min(18, base_pt + self.META_FONT_DELTA_PT)
        return tool_pt, meta_pt

    def updateMaterialDisplay(self):
        include_target = self.step.tool_type != ToolType.SPUTTER
        mat_lines = [
            self._short_line(x)
            for x in self.main_window._tool_material_lines(
                self.step,
                max_lines=4,
                include_target_material=include_target,
            )
        ]
        stack_index = self.main_window.get_stack_index(self.tool_id)
        if stack_index is not None:
            badge = f"- Layer {stack_index}"
        else:
            badge = f"- {self.layer_name}"
        tool_pt, meta_pt = self._font_sizes_pt()

        title_html = (
            f"<span style='font-family:Arial;font-size:{tool_pt}pt;font-weight:800;'>{escape(self.base_name)}</span> "
            f"<span style='font-family:Arial;font-size:{meta_pt}pt;font-weight:700;'>{escape(badge)}</span>"
        )
        self._apply_chip_style()
        self.chip.set_meta_font_size_pt(meta_pt)
        self.chip.set_texts(title_html, mat_lines)

        tip_lines = [f"{self.base_name} {badge}"] + mat_lines
        self.chip.setToolTip("\n".join(tip_lines))

    def eventFilter(self, source, event):
        if source is self.chip and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self._drag_start_pos = event.pos()
            return False

        if source is self.chip and event.type() == QEvent.MouseMove:
            if event.buttons() & Qt.LeftButton:
                if self._drag_start_pos is None:
                    self._drag_start_pos = event.pos()
                    return False
                if (event.pos() - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                    self._start_drag()
                    return True
            return False

        if source is self.chip and event.type() == QEvent.MouseButtonRelease:
            self._drag_start_pos = None
            return False

        return super().eventFilter(source, event)

    def _start_drag(self) -> None:
        if not self.tool_id:
            return
        drag = QDrag(self.chip)
        mime = QMimeData()
        mime.setData(MIME_ITEM_TYPE, b"existing_tool")
        mime.setData(MIME_TOOL_STEP_ID, str(self.tool_id).encode("utf-8"))
        mime.setText(self.base_name)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)


class SubLayerWidget(QWidget):
    def __init__(self, drop_area: 'DropArea', sublayer_number: int):
        super().__init__()
        self.drop_area = drop_area
        # Sublayer concept is removed in UI; keep a fixed value for DB compatibility.
        self.sublayer_number = 1
        self.main_window = drop_area.main_window

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.card = QFrame()
        UIImprovement.style_sublayer_card(self.card)
        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.card.setStyleSheet(
            """
            QFrame {
                background: #F7FAFC;
                border: none;
                border-radius: 10px;
            }
            """
        )
        root.addWidget(self.card, 1)

        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 3)
        card_lay.setSpacing(3)

        header = QWidget()
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(6, 3, 6, 3)
        header_lay.setSpacing(4)

        self.label = QLabel("Tools")
        UIImprovement.style_sublayer_header(header, self.label)
        header_lay.addWidget(self.label, 1)

        card_lay.addWidget(header)

        self.tool_container = QWidget()
        self.tool_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tool_layout = QVBoxLayout(self.tool_container)
        self.tool_layout.setContentsMargins(6, 2, 6, 2)
        self.tool_layout.setSpacing(4)
        self.tool_layout.setAlignment(Qt.AlignTop)
        self.tool_container.setAcceptDrops(True)
        self.tool_container.installEventFilter(self)
        self._insert_line = QFrame(self.tool_container)
        self._insert_line.setFrameShape(QFrame.HLine)
        self._insert_line.setLineWidth(2)
        self._insert_line.setStyleSheet("background:#2D9CDB; min-height:2px; max-height:2px;")
        self._insert_line.hide()
        self._drop_index = -1

        card_lay.addWidget(self.tool_container, 1)
        self.updateRemoveButtonState()

    def tool_widgets(self) -> list[ToolItemWidget]:
        out: list[ToolItemWidget] = []
        for i in range(self.tool_layout.count()):
            w = self.tool_layout.itemAt(i).widget()
            if isinstance(w, ToolItemWidget):
                out.append(w)
        return out

    def _clamp_insert_index(self, idx: int) -> int:
        count = len(self.tool_widgets())
        return max(0, min(int(idx), count))

    def _insert_index_from_y(self, y: int) -> int:
        tools = self.tool_widgets()
        if not tools:
            return 0
        for i, w in enumerate(tools):
            mid_y = w.y() + (w.height() // 2)
            if y < mid_y:
                return i
        return len(tools)

    def _show_drop_indicator(self, idx: int) -> None:
        idx = self._clamp_insert_index(idx)
        self._drop_index = idx
        self.tool_layout.removeWidget(self._insert_line)
        self.tool_layout.insertWidget(idx, self._insert_line)
        self._insert_line.show()

    def _clear_drop_indicator(self) -> None:
        self._drop_index = -1
        self.tool_layout.removeWidget(self._insert_line)
        self._insert_line.hide()

    def _get_drop_index(self, event) -> int:
        if self._drop_index >= 0:
            return self._drop_index
        return self._insert_index_from_y(event.pos().y())

    @staticmethod
    def _mime_item_type(md) -> str:
        if not md.hasFormat(MIME_ITEM_TYPE):
            return ""
        return bytes(md.data(MIME_ITEM_TYPE)).decode("utf-8", errors="ignore")

    @staticmethod
    def _mime_step_id(md) -> int | None:
        if not md.hasFormat(MIME_TOOL_STEP_ID):
            return None
        try:
            return int(bytes(md.data(MIME_TOOL_STEP_ID)).decode("utf-8", errors="ignore").strip())
        except Exception:
            return None

    def _add_new_tool_at_index(self, tool_type_text: str, insert_index: int) -> None:
        count = len(self.tool_widgets())
        insert_index = self._clamp_insert_index(insert_index)
        new_position = (count + 1) - insert_index
        try:
            step = self.main_window.process_service.add_step(
                layer=self.drop_area.layer_name,
                tool_type=tool_type_text,
                position_in_layer=new_position,
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Add Tool Failed', str(exc))
            return
        self.addToolFromStep(step, insert_index=insert_index)
        self.main_window._refresh_tool_badges()
        self.main_window._refresh_layer_cake()
        self.main_window._set_status(
            f'Added {tool_type_text} tool {step.step_id} at #{step.position_in_layer} in {self.drop_area.layer_name}'
        )

    def _move_existing_tool_at_index(self, step_id: int, insert_index: int) -> None:
        step = self.main_window.process_service.get_step(step_id)
        if step is None:
            return

        src_widget = self.main_window.find_tool_widget(step_id)
        same_lane = src_widget is not None and src_widget.sublayer_widget is self
        src_index = self.tool_layout.indexOf(src_widget) if same_lane else -1

        target_count_before = len(self.tool_widgets())
        if same_lane and src_index >= 0 and src_index < insert_index:
            insert_index -= 1

        target_count_after = target_count_before if same_lane else (target_count_before + 1)
        if target_count_after <= 0:
            target_count_after = 1
        insert_index = max(0, min(insert_index, target_count_after - 1))
        new_position = target_count_after - insert_index

        try:
            updated = self.main_window.process_service.update_step(
                step_id=step_id,
                layer=self.drop_area.layer_name,
                thickness_raw='' if step.thickness_nm is None else str(step.thickness_nm),
                parameters=dict(step.parameters),
                position_in_layer=new_position,
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Move Tool Failed', str(exc))
            return

        self.main_window._refresh_from_db()
        self.main_window._set_status(
            f'Moved tool {updated.step_id} to #{updated.position_in_layer} in {self.drop_area.layer_name}'
        )

    def eventFilter(self, source, event):
        if source is self.tool_container and event.type() == QEvent.DragEnter:
            md = event.mimeData()
            item_type = self._mime_item_type(md)
            if item_type == 'tool' or self._mime_step_id(md) is not None:
                event.acceptProposedAction()
                return True
            return False

        if source is self.tool_container and event.type() == QEvent.DragMove:
            md = event.mimeData()
            item_type = self._mime_item_type(md)
            if item_type == 'tool' or self._mime_step_id(md) is not None:
                idx = self._insert_index_from_y(event.pos().y())
                self._show_drop_indicator(idx)
                event.acceptProposedAction()
                return True
            return False

        if source is self.tool_container and event.type() == QEvent.DragLeave:
            self._clear_drop_indicator()
            return False

        if source is self.tool_container and event.type() == QEvent.Drop:
            md = event.mimeData()
            item_type = self._mime_item_type(md)
            insert_index = self._get_drop_index(event)
            self._clear_drop_indicator()
            step_id = self._mime_step_id(md)
            if step_id is not None:
                self._move_existing_tool_at_index(step_id, insert_index)
                event.acceptProposedAction()
                return True
            if item_type == 'tool':
                # ACTION: Fix the Central Recipe Builder Drag & Drop Logic
                # Parse JSON if it's a string to strictly enforce robust tool addition
                import json
                tool_type_text = (md.text() or "").strip()
                try:
                    data = json.loads(tool_type_text)
                    tool_type_text = data.get("payload", tool_type_text)
                except (json.JSONDecodeError, AttributeError):
                    pass  # Not JSON, or not a dict; proceed with raw text.
                self._add_new_tool_at_index(tool_type_text, insert_index)
                event.acceptProposedAction()
                return True
            return False

        return super().eventFilter(source, event)

    def addTool(self, tool_type_text: str, insert_index: int | None = None):
        idx = 0 if insert_index is None else int(insert_index)
        self._add_new_tool_at_index(tool_type_text, idx)

    def addToolFromStep(self, step: ProcessStep, insert_index: int | None = None):
        btn = ToolItemWidget(step, self.main_window, self)
        idx = 0 if insert_index is None else self._clamp_insert_index(insert_index)
        self.tool_layout.insertWidget(idx, btn)
        self.updateRemoveButtonState()

    def on_tool_click(self, tool_widget: ToolItemWidget):
        self.main_window.updateToolInfo(tool_widget)

    def removeSubLayer(self):
        # Sublayer removal disabled: one fixed tool lane per layer.
        return

    def updateRemoveButtonState(self):
        # Kept for compatibility with existing calls.
        return


class LayerSection(QWidget):
    def __init__(self, main_window: 'MainWindow', layer_name: str):
        super().__init__()
        self.main_window = main_window
        self.layer_name = layer_name

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        display_name = layer_name.replace("_", " ")
        self.title = QLabel(display_name)
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title.setStyleSheet("""
            QLabel {
                font-weight: 600;
                font-size: 13px;
                color: #374151;
                padding: 3px 0px;
            }
        """)
        root.addWidget(self.title)

        self.container = QFrame()
        self.container.setStyleSheet("""
            QFrame {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
            }
        """)
        cont_lay = QVBoxLayout(self.container)
        cont_lay.setContentsMargins(8, 8, 8, 8)
        cont_lay.setSpacing(6)

        self.drop = DropArea(main_window, layer_name)
        cont_lay.addWidget(self.drop)

        root.addWidget(self.container, 1)


class DropArea(QFrame):
    def __init__(self, main_window: 'MainWindow', layer_name: str):
        super().__init__()
        self.main_window = main_window
        self.layer_name = layer_name
        self.setAcceptDrops(True)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(6)

        self.sublayer_wrap = QWidget()
        self.sublayer_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sublayer_vlay = QVBoxLayout(self.sublayer_wrap)
        self.sublayer_vlay.setContentsMargins(0, 0, 0, 0)
        self.sublayer_vlay.setSpacing(6)
        self.sublayer_vlay.setAlignment(Qt.AlignTop)
        self.layout.addWidget(self.sublayer_wrap, 1)

        self.sublayers: List[SubLayerWidget] = []
        self.addSubLayer(initial=True)

    def addSubLayer(self, initial: bool = False) -> SubLayerWidget:
        if self.sublayers:
            return self.sublayers[0]
        w = SubLayerWidget(self, 1)
        self.sublayer_vlay.addWidget(w, 1)
        self.sublayers = [w]
        return w

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(MIME_ITEM_TYPE):
            it = bytes(md.data(MIME_ITEM_TYPE)).decode("utf-8", errors="ignore")
            if it == 'tool':
                event.acceptProposedAction()
                return
        if md.hasFormat(MIME_TOOL_STEP_ID):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        md = event.mimeData()
        target = self.addSubLayer(initial=True)
        if md.hasFormat(MIME_TOOL_STEP_ID):
            try:
                step_id = int(bytes(md.data(MIME_TOOL_STEP_ID)).decode("utf-8", errors="ignore").strip())
            except Exception:
                step_id = None
            if step_id is not None:
                target._move_existing_tool_at_index(step_id, 0)
                event.acceptProposedAction()
                return
        if md.hasFormat(MIME_ITEM_TYPE):
            it = bytes(md.data(MIME_ITEM_TYPE)).decode("utf-8", errors="ignore")
            if it == 'tool':
                tool_type_text = (md.text() or "").strip()
                target.addTool(tool_type_text, insert_index=0)
                event.acceptProposedAction()
                return
        event.ignore()

    def canRemoveSubLayer(self, sublayer_number: int) -> bool:
        return False

    def removeSubLayer(self, sublayer_widget: SubLayerWidget):
        return

    def maxSublayerNumber(self) -> int:
        return 1

    def _renumber_descending(self):
        for w in self.sublayers:
            w.sublayer_number = 1
            w.label.setText('Tools')
            w.updateRemoveButtonState()

    def _updateSublayerNumbersInDB(self):
        for sl in self.sublayers:
            for tool in sl.tool_widgets():
                s = tool.step
                try:
                    tool.step = self.main_window.process_service.update_step(
                        step_id=tool.tool_id,
                        layer=self.layer_name,
                        thickness_raw='' if s.thickness_nm is None else str(s.thickness_nm),
                        parameters=dict(s.parameters),
                    )
                except Exception:
                    pass

    def getOrCreateSubLayer(self, sublayer_number: int) -> SubLayerWidget:
        return self.addSubLayer(initial=True)


class MaterialSelectorDialog(QDialog):
    def __init__(self, parent: 'MainWindow', tool_type: ToolType, param_key: str, selected: str):
        super().__init__(parent)
        UIImprovement.apply_theme(self, dark=False)
        self.process_service = parent.process_service
        self.tool_type = tool_type
        self.param_key = param_key
        self.material_type = 'gas' if 'gas' in str(param_key or '').lower() else 'material'
        self.selected_material = selected or ''

        thing = 'Gas' if self.material_type == 'gas' else 'Material'
        self.setWindowTitle(f'Select {thing} for {tool_type.value}')
        self.resize(620, 420)

        col = QVBoxLayout(self)
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.material_list = QListWidget()
        self.material_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.material_list.itemClicked.connect(self._selectMaterial)
        item_label = 'Available Gases - click to select' if self.material_type == 'gas' else 'Available Materials - click to select'
        left.addWidget(QLabel(item_label))
        left.addWidget(self.material_list)
        btm = QHBoxLayout()
        btn_add = QPushButton('Add')
        btn_del = QPushButton('Remove')
        UIImprovement.set_button_variant(btn_del, 'danger')
        btn_add.clicked.connect(self._addMaterial)
        btn_del.clicked.connect(self._removeMaterial)
        btm.addWidget(btn_add)
        btm.addWidget(btn_del)
        left.addLayout(btm)
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        right.addWidget(QLabel('Selected:'))
        self.selected_display = QLabel(self.selected_material)
        self.selected_display.setStyleSheet('font-weight: bold; font-size: 24px;')
        right.addWidget(self.selected_display)
        row.addLayout(left)
        row.addLayout(right)
        col.addLayout(row)

        self._loadMaterialsFromDB()

    def _loadMaterialsFromDB(self):
        vals = self.process_service.list_candidates_for(self.tool_type, self.param_key)
        self.material_list.clear()
        for v in vals:
            self.material_list.addItem(QListWidgetItem(v))

    def _selectMaterial(self, item: QListWidgetItem):
        self.selected_material = item.text()
        self.selected_display.setText(self.selected_material)
        self.accept()

    def _addMaterial(self):
        thing = 'gas' if self.material_type == 'gas' else 'material'
        name, ok = QInputDialog.getText(self, f'Add {thing.title()}', f'Enter {thing} name:')
        if not ok or not name.strip():
            return
        self.process_service.add_candidate(self.tool_type, self.param_key, name.strip())
        self._loadMaterialsFromDB()

    def _removeMaterial(self):
        items = self.material_list.selectedItems()
        if not items:
            QMessageBox.warning(self, 'Warning', 'Please select one item to remove.')
            return
        name = items[0].text().strip()
        thing = 'gas candidate' if self.material_type == 'gas' else 'material candidate'
        if QMessageBox.question(self, 'Confirm', f"Remove '{name}' from the shared {thing} list?") != QMessageBox.Yes:
            return
        self.process_service.remove_candidate(self.tool_type, self.param_key, name)
        self._loadMaterialsFromDB()


class NmlcMaterialSelectorDialog(QDialog):
    """
    Compatibility selector for nested material-cycle editor.
    Signature is intentionally aligned with the old selector class.
    """

    def __init__(
        self,
        parent=None,
        selected_materials=None,
        conn=None,
        tool_name=None,
        material_type=None,
        desired_material=None,
    ):
        super().__init__(parent)
        UIImprovement.apply_theme(self, dark=False)
        self.conn = conn
        self.tool_name = str(tool_name or "").strip()
        self.material_type = str(material_type or "").strip()
        _selected = ""
        if isinstance(selected_materials, list) and selected_materials:
            _selected = str(selected_materials[0] or "")
        self.selected_material = _selected

        title = f"Select {self.material_type or 'material'} for {self.tool_name or 'Tool'}"
        self.setWindowTitle(title)
        self.resize(620, 420)

        col = QVBoxLayout(self)
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.material_list = QListWidget()
        self.material_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.material_list.itemClicked.connect(self._selectMaterial)
        left.addWidget(QLabel('Available Materials - click to select'))
        left.addWidget(self.material_list)
        btm = QHBoxLayout()
        btn_add = QPushButton('Add')
        btn_del = QPushButton('Remove')
        UIImprovement.set_button_variant(btn_del, 'danger')
        btn_add.clicked.connect(self._addMaterial)
        btn_del.clicked.connect(self._removeMaterial)
        btm.addWidget(btn_add)
        btm.addWidget(btn_del)
        left.addLayout(btm)
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        right.addWidget(QLabel('Selected:'))
        self.selected_display = QLabel(self.selected_material)
        self.selected_display.setStyleSheet('font-weight: bold; font-size: 24px;')
        right.addWidget(self.selected_display)
        row.addLayout(left)
        row.addLayout(right)
        col.addLayout(row)

        self._loadMaterialsFromDB()

    def _execute_fetch(self, sql: str) -> list[str]:
        return db_ops.list_candidate_values(self.conn, self.tool_name, self.material_type)

    def _loadMaterialsFromDB(self):
        try:
            vals = self._execute_fetch("")
        except Exception:
            vals = []
        self.material_list.clear()
        for v in sorted(set(vals)):
            self.material_list.addItem(QListWidgetItem(v))

    def _selectMaterial(self, item: QListWidgetItem):
        self.selected_material = item.text()
        self.selected_display.setText(self.selected_material)
        self.accept()

    def _addMaterial(self):
        if self.conn is None:
            QMessageBox.warning(self, 'Warning', 'Database connection is not available.')
            return
        is_gas = self.material_type == 'gas'
        prompt = 'Enter gas name:' if is_gas else 'Enter material name:'
        title = 'Add Gas' if is_gas else 'Add Material'
        name, ok = QInputDialog.getText(self, title, prompt)
        name = (name or "").strip()
        if not ok or not name:
            return
        try:
            db_ops.add_candidate_value(self.conn, self.tool_name, self.material_type, name)
            self._loadMaterialsFromDB()
        except Exception as exc:
            QMessageBox.warning(self, 'Warning', f'Failed to add value: {exc}')

    def _removeMaterial(self):
        if self.conn is None:
            QMessageBox.warning(self, 'Warning', 'Database connection is not available.')
            return
        items = self.material_list.selectedItems()
        if not items:
            QMessageBox.warning(self, 'Warning', 'Please select one item to remove.')
            return
        name = (items[0].text() or "").strip()
        if not name:
            return
        thing = 'gas candidate' if self.material_type == 'gas' else 'material candidate'
        msg = f"Remove shared {thing} '{name}' from the selector list?\nThis does not delete the current saved node."
        if QMessageBox.question(self, 'Confirm', msg) != QMessageBox.Yes:
            return
        try:
            db_ops.remove_candidate_value(self.conn, self.tool_name, self.material_type, name)
            self._loadMaterialsFromDB()
        except Exception as exc:
            QMessageBox.warning(self, 'Warning', f'Failed to remove value: {exc}')


class SaveRecipeDialog(QDialog):
    def __init__(self, recipe_service: RecipeService, parent=None):
        super().__init__(parent)
        UIImprovement.apply_theme(self, dark=False)
        self.recipe_service = recipe_service
        self.setWindowTitle('Save Recipe')
        self.resize(420, 170)
        self.label = QLabel('Please enter your recipe name:')
        self.recipe_name_input = QLineEdit()
        btn_create = QPushButton('Create')
        btn_leave = QPushButton('Leave')
        btn_create.clicked.connect(self._create_recipe)
        btn_leave.clicked.connect(self.close)
        col = QVBoxLayout(self)
        col.addWidget(self.label)
        col.addWidget(self.recipe_name_input)
        row = QHBoxLayout()
        row.addWidget(btn_create)
        row.addWidget(btn_leave)
        col.addLayout(row)

    def _create_recipe(self):
        name = (self.recipe_name_input.text() or '').strip()
        if not name:
            self.label.setText('Recipe name cannot be empty!')
            return
        try:
            rid = self.recipe_service.save_current_as_recipe(name)
            QMessageBox.information(self, 'Success', f"Recipe '{name}' has been created with ID {rid}!")
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, 'Error', f'Failed to create recipe: {exc}')


class LoadRecipeDialog(QDialog):
    def __init__(self, recipe_service: RecipeService, parent=None):
        super().__init__(parent)
        UIImprovement.apply_theme(self, dark=False)
        self.recipe_service = recipe_service
        self.selected_recipe_id: int | None = None
        self.setWindowTitle('Recipe Operation')
        self.resize(620, 420)
        col = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['ID', 'Recipe Name', 'Created At'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        UIImprovement.set_table_style(self.table)
        col.addWidget(self.table)
        row = QHBoxLayout()
        self.load_button = QPushButton('Load Selected Recipe')
        self.load_button.clicked.connect(self._load_selected_recipe)
        row.addWidget(self.load_button)
        self.replace_button = QPushButton('Replace Selected Recipe')
        UIImprovement.set_button_variant(self.replace_button, 'warning')
        self.replace_button.clicked.connect(self._replace_selected_recipe)
        row.addWidget(self.replace_button)
        self.delete_button = QPushButton('Delete Selected Recipe')
        UIImprovement.set_button_variant(self.delete_button, 'danger')
        self.delete_button.clicked.connect(self._delete_selected_recipe)
        row.addWidget(self.delete_button)
        col.addLayout(row)
        self._load_data()

    def _load_data(self):
        recipes = self.recipe_service.list_recipes()
        self.table.setRowCount(len(recipes))
        for i, rec in enumerate(recipes):
            self.table.setItem(i, 0, QTableWidgetItem(str(rec.recipe_id)))
            self.table.setItem(i, 1, QTableWidgetItem(rec.recipe_name))
            self.table.setItem(i, 2, QTableWidgetItem(rec.created_at or '-'))
        self.table.resizeColumnsToContents()

    def _load_selected_recipe(self):
        selected = self._selected_recipe()
        if selected is None:
            return
        recipe_id, _recipe_name = selected
        self.selected_recipe_id = recipe_id
        self.accept()

    def _selected_recipe(self) -> tuple[int, str] | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            QMessageBox.warning(self, 'No Selection', 'Please select a recipe first.')
            return None
        row = rows[0].row()
        id_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        if not id_item:
            QMessageBox.warning(self, 'No Selection', 'Selected row is invalid.')
            return None
        recipe_name = (name_item.text() if name_item else '').strip()
        return int(id_item.text()), recipe_name

    def _delete_selected_recipe(self):
        selected = self._selected_recipe()
        if selected is None:
            return
        recipe_id, recipe_name = selected
        msg = (
            f"Delete recipe '{recipe_name}' (ID={recipe_id})?\n\n"
            "This will cascade delete all process steps and tool parameter rows under this recipe."
        )
        if QMessageBox.question(self, 'Confirm Delete', msg) != QMessageBox.Yes:
            return
        try:
            self.recipe_service.delete_recipe(recipe_id)
            self._load_data()
            QMessageBox.information(self, 'Deleted', f"Recipe {recipe_id} deleted.")
        except Exception as exc:
            QMessageBox.critical(self, 'Error', f'Failed to delete recipe: {exc}')

    def _replace_selected_recipe(self):
        selected = self._selected_recipe()
        if selected is None:
            return
        recipe_id, recipe_name = selected
        msg = (
            f"Replace recipe '{recipe_name}' (ID={recipe_id}) with the current working DB content?\n\n"
            "This keeps the same recipe ID and recipe name, but overwrites all saved steps, tool parameters, "
            "and ALD nested cycle/material data under that recipe."
        )
        if QMessageBox.question(self, 'Confirm Replace', msg) != QMessageBox.Yes:
            return
        try:
            count = self.recipe_service.replace_recipe_from_working(recipe_id)
            self._load_data()
            QMessageBox.information(
                self,
                'Replaced',
                f"Recipe {recipe_id} replaced from the current working DB ({count} tools).",
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Error', f'Failed to replace recipe: {exc}')


class MainWindow(QMainWindow):
    databaseRequested = pyqtSignal()

    def __init__(
        self,
        process_service: ProcessService,
        recipe_service: RecipeService,
        parent=None,
    ):
        super().__init__(parent)
        self.process_service = process_service
        self.recipe_service = recipe_service
        self.conn = getattr(self.process_service.working_repo, 'conn', None)

        self.info_group: QGroupBox | None = None
        self.parameter_widgets: dict[str, QWidget] = {}
        self.tool_button: ToolItemWidget | None = None
        self._status_label: QLabel | None = None
        self._autosave_timers: dict[QLineEdit, QTimer] = {}
        self._autosave_delay_ms = 700
        self._screen_adaptation_bound = False
        self._nmlc_dialog = None
        self._nmlc_active_step_id: int | None = None
        self._recipe_db_path: str | None = None

        UIImprovement.apply_theme(self, dark=False)
        # Keep typography consistent across widgets in this window.
        self.setStyleSheet(self.styleSheet() + "\nQWidget { font-family: Arial; }")
        self.setWindowTitle('Tool Selector with Database Integration')
        self.resize(1300, 760)
        self.setMinimumSize(1180, 760)

        self._build_file_menu()
        self._initUI()
        self._refresh_from_db()

    def _build_file_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_action = file_menu.addAction("Open Main Database...")
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.databaseRequested.emit)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

    def _initUI(self):
        left_top = QWidget()
        lt = QVBoxLayout(left_top)
        lt.setContentsMargins(0, 0, 0, 0)
        lt.setSpacing(6)

        layer_panel = QWidget()
        layer_lay = QVBoxLayout(layer_panel)
        layer_lay.setContentsMargins(0, 0, 0, 0)
        self.layer_cake = LayerCakeWidget()
        layer_lay.addWidget(self.layer_cake, 1)
        layer_panel.setMinimumHeight(int(self.layer_cake.minimumHeight() + 6))

        tools_panel = QWidget()
        tools_lay = QVBoxLayout(tools_panel)
        tools_lay.setAlignment(Qt.AlignTop)
        tools_lay.setContentsMargins(0, 0, 0, 0)
        tools_lay.addWidget(QLabel('Tools (Draggable)'))
        for tool in ['ALD', 'Sputter', 'E_beam', 'Furnace']:
            tools_lay.addWidget(DraggableButton(tool, button_type='tool', payload=tool))
        tools_lay.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))
        tools_panel.setMinimumHeight(130)

        top_splitter = QSplitter(Qt.Vertical)
        UIImprovement.set_horizontal_splitter_style(top_splitter)
        top_splitter.addWidget(layer_panel)
        top_splitter.addWidget(tools_panel)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.setCollapsible(0, False)
        top_splitter.setCollapsible(1, False)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setSizes([380, 200])
        lt.addWidget(top_splitter)

        left_bot = QWidget()
        lb = QVBoxLayout(left_bot)
        lb.setAlignment(Qt.AlignTop)
        lb.addWidget(QLabel('Recipe Details'))
        self.btn_save = QPushButton('Save Recipe')
        self.btn_load = QPushButton('Recipe Operation')
        UIImprovement.set_button_variant(self.btn_load, 'warning')
        self.btn_save.clicked.connect(self._open_save_dialog)
        self.btn_load.clicked.connect(self._open_load_dialog)
        lb.addWidget(self.btn_save)
        lb.addWidget(self.btn_load)
        self.global_status = QLabel('Ready')
        UIImprovement.set_material_label_style(self.global_status)
        lb.addWidget(self.global_status)
        lb.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        left_splitter = QSplitter(Qt.Vertical)
        UIImprovement.set_horizontal_splitter_style(left_splitter)
        left_splitter.addWidget(left_top)
        left_splitter.addWidget(left_bot)
        for i in range(2):
            left_splitter.setCollapsible(i, False)
        left_splitter.setSizes([500, 180])

        left_panel = QWidget()
        lpl = QVBoxLayout(left_panel)
        lpl.addWidget(left_splitter)
        left_panel.setMinimumWidth(280)
        UIImprovement.add_shadow(left_panel)

        dz_layout = QVBoxLayout()
        dz_layout.setContentsMargins(0, 0, 0, 0)
        dz_layout.setSpacing(10)

        self.gate_elec_section = LayerSection(self, 'Gate_Electrode')
        self.gate_adh_section = LayerSection(self, 'Gate_Adhesion')
        self.gate_diel_section = LayerSection(self, 'Gate_Dielectric')
        self.channel_section = LayerSection(self, 'Channel')
        self.sd_elec_section = LayerSection(self, 'Source_Drain_Electrode')
        self.sd_adh_section = LayerSection(self, 'Source_Drain_Adhesion')
        self.sub_section = LayerSection(self, 'Substrate')

        self.gate_elec_drop_area = self.gate_elec_section.drop
        self.gate_adh_drop_area = self.gate_adh_section.drop
        self.gate_diel_drop_area = self.gate_diel_section.drop
        self.channel_drop_area = self.channel_section.drop
        self.sd_elec_drop_area = self.sd_elec_section.drop
        self.sd_adh_drop_area = self.sd_adh_section.drop
        self.sub_drop_area = self.sub_section.drop

        self._all_drop_areas = (
            self.gate_elec_drop_area, self.gate_adh_drop_area, self.gate_diel_drop_area,
            self.channel_drop_area, self.sd_elec_drop_area, self.sd_adh_drop_area, self.sub_drop_area
        )

        dz_layout.addWidget(self.gate_elec_section)
        dz_layout.addWidget(self.gate_adh_section)
        dz_layout.addWidget(self.gate_diel_section)
        dz_layout.addWidget(self.channel_section)
        dz_layout.addWidget(self.sd_elec_section)
        dz_layout.addWidget(self.sd_adh_section)
        dz_layout.addWidget(self.sub_section)
        dz_layout.addStretch()

        container = QWidget()
        container.setLayout(dz_layout)

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(480)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: rgba(0, 112, 186, 0.20);
                width: 10px;
                margin: 2px 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 88, 155, 0.80);
                border-radius: 5px;
                min-height: 20px;
            }
        """)
        scroll.viewport().setStyleSheet("background: transparent;")
        UIImprovement.add_shadow(scroll)

        self.info_widget = QWidget()
        self.info_layout = QVBoxLayout(self.info_widget)
        self.info_widget.setMinimumWidth(620)
        UIImprovement.add_shadow(self.info_widget)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(scroll)
        splitter.addWidget(self.info_widget)
        for i in range(3):
            splitter.setCollapsible(i, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        UIImprovement.set_vertical_splitter_style(splitter)

        central = QWidget(self)
        self.setCentralWidget(central)
        main = QHBoxLayout(central)
        main.addWidget(splitter)

        for area in self._all_drop_areas:
            area.layout.removeWidget(area.title) if hasattr(area, 'title') else None
            area.title.setParent(None) if hasattr(area, 'title') else None

        self._set_recipe_database_context(None)

    def bind_recipe_service(self, recipe_service: RecipeService, recipe_db_path: str | Path) -> None:
        self.recipe_service = recipe_service
        self._set_recipe_database_context(str(recipe_db_path))

    def _set_recipe_database_context(self, recipe_db_path: str | None) -> None:
        self._recipe_db_path = str(recipe_db_path) if recipe_db_path else None
        if self._recipe_db_path:
            self.btn_save.setEnabled(True)
            self.btn_load.setEnabled(True)
            self.global_status.setText('Main database loaded')
            self.setWindowTitle(f"Tool Selector with Database Integration - {Path(self._recipe_db_path).name}")
        else:
            self.btn_save.setEnabled(False)
            self.btn_load.setEnabled(False)
            self.global_status.setText('Open the main database to load or save recipes')
            self.setWindowTitle('Tool Selector with Database Integration - No Database Loaded')

    def showEvent(self, event):
        super().showEvent(event)
        if not self._screen_adaptation_bound:
            self._screen_adaptation_bound = True
            handle = self.windowHandle()
            if handle is not None:
                handle.screenChanged.connect(self._on_screen_changed)
            self.apply_adaptive_geometry()

    def _on_screen_changed(self, _screen):
        self.apply_adaptive_geometry()

    def _current_screen(self):
        app = QApplication.instance()
        if app is None:
            return None
        screen = app.screenAt(QCursor.pos())
        if screen is not None:
            return screen
        if self.windowHandle() is not None and self.windowHandle().screen() is not None:
            return self.windowHandle().screen()
        return app.primaryScreen()

    def _apply_adaptive_font(self, screen) -> None:
        app = QApplication.instance()
        if app is None or screen is None:
            return
        geo = screen.availableGeometry()
        short_edge = max(720, min(2160, min(geo.width(), geo.height())))
        # 1080p-like screen -> around 11pt, larger screens scale up moderately.
        point_size = int(max(10, min(14, round(short_edge / 96))))
        f = app.font()
        changed = False
        if f.family() != "Arial":
            f.setFamily("Arial")
            changed = True
        if f.pointSize() != point_size:
            f.setPointSize(point_size)
            changed = True
        if changed:
            app.setFont(f)

    def apply_adaptive_geometry(self, ratio: float = 0.75) -> None:
        screen = self._current_screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        target_w = int(geo.width() * ratio)
        target_h = int(geo.height() * ratio)
        target_w = max(self.minimumWidth(), min(target_w, int(geo.width() * 0.95)))
        target_h = max(self.minimumHeight(), min(target_h, int(geo.height() * 0.95)))
        x = geo.x() + (geo.width() - target_w) // 2
        y = geo.y() + (geo.height() - target_h) // 2
        self.setGeometry(x, y, target_w, target_h)
        self._apply_adaptive_font(screen)
        # Regenerate tool card rich-text sizes after adaptive font changes.
        try:
            self._refresh_tool_badges()
        except Exception:
            pass
        try:
            self._refresh_layer_cake()
        except Exception:
            pass

    def _set_status(self, text: str):
        self.global_status.setText(text)
        if self._status_label is not None:
            try:
                self._status_label.setText(text)
            except Exception:
                # The right-side panel may already be deleted via deleteLater().
                self._status_label = None

    def _iter_tools_bottom_to_top(self) -> list[ToolItemWidget]:
        ordered: list[ToolItemWidget] = []
        for area in reversed(self._all_drop_areas):
            if not area.sublayers:
                continue
            lane = area.sublayers[0]
            # tool_layout is top-aligned; reverse it to interpret visual bottom->top.
            ordered.extend(reversed(lane.tool_widgets()))
        return ordered

    def get_stack_index(self, tool_id: int) -> int | None:
        for i, tool in enumerate(self._iter_tools_bottom_to_top(), start=1):
            if tool.tool_id == tool_id:
                return i
        return None

    def find_tool_widget(self, tool_id: int) -> ToolItemWidget | None:
        for area in self._all_drop_areas:
            if not area.sublayers:
                continue
            for tool in area.sublayers[0].tool_widgets():
                if tool.tool_id == tool_id:
                    return tool
        return None

    def _refresh_tool_badges(self) -> None:
        for tool in self._iter_tools_bottom_to_top():
            tool.updateMaterialDisplay()

    @staticmethod
    def _split_material_values(raw: str) -> list[str]:
        text = (raw or "").strip()
        if not text:
            return []
        parts = [p.strip() for p in re.split(r"[\n,;|，；、]+", text) if p.strip()]
        return parts

    @staticmethod
    def _dedupe_keep_order(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _table_exists(self, table_name: str) -> bool:
        return db_ops.table_exists(self.conn, str(table_name))

    def _ald_material_lines(self, step_id: int) -> list[str]:
        vals: list[str] = []
        for raw_mat in db_ops.list_ald_material_values(self.conn, int(step_id)):
            vals.extend(self._split_material_values(str(raw_mat or "")))
        return self._dedupe_keep_order(vals)

    def _tool_material_lines(
        self,
        step: ProcessStep,
        max_lines: int | None = None,
        include_target_material: bool = True,
    ) -> list[str]:
        vals: list[str] = []

        if step.tool_type == ToolType.ALD and step.step_id is not None:
            vals.extend(self._ald_material_lines(int(step.step_id)))

        if not vals:
            desired = str(step.parameters.get("desired_material", "") or "")
            vals.extend(self._split_material_values(desired))

        if include_target_material:
            target = str(step.parameters.get("target_material", "") or "")
            vals.extend(self._split_material_values(target))

        if not vals:
            for key, raw in (step.parameters or {}).items():
                if key in {"desired_material", "target_material"}:
                    continue
                if "material" not in str(key).lower():
                    continue
                vals.extend(self._split_material_values(str(raw or "")))

        vals = self._dedupe_keep_order(vals)
        if max_lines is not None and len(vals) > int(max_lines):
            keep = max(1, int(max_lines) - 1)
            vals = vals[:keep] + [f"+{len(vals) - keep} more"]
        return vals

    def _refresh_layer_cake(self) -> None:
        if not hasattr(self, "layer_cake"):
            return
        layer_steps: dict[str, list[ProcessStep]] = {layer: [] for layer in ALL_LAYERS}
        for step in self.process_service.list_steps():
            layer_name = step.layer.value
            if layer_name in layer_steps:
                layer_steps[layer_name].append(step)

        summary: dict[str, str] = {}
        layer_details: dict[str, list[str]] = {layer: [] for layer in ALL_LAYERS}
        layer_weights: dict[str, float] = {layer: 0.0 for layer in ALL_LAYERS}
        for layer in ALL_LAYERS:
            steps = sorted(layer_steps[layer], key=lambda s: int(s.position_in_layer or 0))
            if not steps:
                summary[layer] = ""
                layer_details[layer] = []
                layer_weights[layer] = 0.0
                continue

            layer_vals: list[str] = []
            details: list[str] = []
            thickness_sum = 0.0
            for step in steps:
                try:
                    t = float(step.thickness_nm or 0.0)
                except Exception:
                    t = 0.0
                if t > 0:
                    thickness_sum += t
                mats = self._tool_material_lines(
                    step,
                    max_lines=8,
                    include_target_material=False,
                )
                if not mats:
                    continue
                layer_vals.extend(mats)
                details.append(", ".join(mats))

            uniq = self._dedupe_keep_order(layer_vals)
            if not uniq:
                summary[layer] = ""
            elif len(uniq) <= 2:
                summary[layer] = ", ".join(uniq)
            else:
                summary[layer] = ", ".join(uniq[:2]) + f" +{len(uniq) - 2}"
            if len(details) > 6:
                hidden = len(details) - 5
                details = details[:5] + [f"+{hidden} more"]
            layer_details[layer] = details
            layer_weights[layer] = thickness_sum

        if sum(layer_weights.values()) <= 0.0:
            for layer in ALL_LAYERS:
                layer_weights[layer] = 1.0

        self.layer_cake.set_layer_materials(summary, layer_details, layer_weights)

    def _clear_autosave_timers(self):
        for t in list(self._autosave_timers.values()):
            try:
                t.stop()
                t.deleteLater()
            except Exception:
                pass
        self._autosave_timers.clear()

    def _bind_lineedit_autosave(self, line: QLineEdit):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(self._autosave_delay_ms)

        def on_text_changed(_):
            timer.stop()
            timer.start()
            self._set_status('Editing...')

        def on_timeout():
            self._autoSaveParams(silent=True)

        line.textChanged.connect(on_text_changed)
        timer.timeout.connect(on_timeout)
        self._autosave_timers[line] = timer

    def _wire_autosave_signals(self):
        # Data Binding Explanation:
        # We bind the 'textChanged' or 'currentIndexChanged' signals of the UI inputs
        # (thickness, material comboboxes, etc.) to the _autoSaveParams method.
        # This creates a real-time reactive loop: Input Change -> _autoSaveParams -> 
        # updates the database model -> calls _refresh_layer_cake -> calls LayerCakeWidget.update().
        if hasattr(self, 'thickness_input') and isinstance(self.thickness_input, QLineEdit):
            self._bind_lineedit_autosave(self.thickness_input)

        for w in (self.parameter_widgets or {}).values():
            if isinstance(w, QLineEdit):
                self._bind_lineedit_autosave(w)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(lambda _=None: self._autoSaveParams(silent=True))

    def _open_save_dialog(self):
        SaveRecipeDialog(self.recipe_service, self).exec_()

    def _open_load_dialog(self):
        dlg = LoadRecipeDialog(self.recipe_service, self)
        if dlg.exec_() == QDialog.Accepted and dlg.selected_recipe_id is not None:
            rid = dlg.selected_recipe_id
            try:
                count = self.recipe_service.load_recipe_into_working(rid)
                self._refresh_from_db()
                QMessageBox.information(self, 'Success', f'Recipe {rid} loaded ({count} tools).')
            except Exception as exc:
                QMessageBox.critical(self, 'Error', f'Failed to load recipe: {exc}')

    def _refresh_from_db(self):
        self._clear_autosave_timers()
        if self.info_group:
            self.info_layout.removeWidget(self.info_group)
            self.info_group.deleteLater()
            self.info_group = None
            self._status_label = None
            self.tool_button = None
            self.parameter_widgets = {}

        def clear_area(area: DropArea):
            for sl in list(area.sublayers):
                area.sublayer_vlay.removeWidget(sl)
                sl.deleteLater()
            area.sublayers.clear()
            area.addSubLayer(initial=True)

        for area in self._all_drop_areas:
            clear_area(area)
        self._loadToolsFromDB()
        self._refresh_tool_badges()
        self._refresh_layer_cake()

    def _loadToolsFromDB(self):
        drop_map = {
            'Gate_Electrode': self.gate_elec_drop_area,
            'Gate_Adhesion': self.gate_adh_drop_area,
            'Gate_Dielectric': self.gate_diel_drop_area,
            'Channel': self.channel_drop_area,
            'Source_Drain_Electrode': self.sd_elec_drop_area,
            'Source_Drain_Adhesion': self.sd_adh_drop_area,
            'Substrate': self.sub_drop_area,
        }
        for step in self.process_service.list_steps():
            drop = drop_map.get(step.layer.value)
            if drop:
                drop.getOrCreateSubLayer(1).addToolFromStep(step)

    def updateToolInfo(self, tool_button: ToolItemWidget):
        self._clear_autosave_timers()
        self.tool_button = tool_button
        step = self.process_service.get_step(tool_button.tool_id) or tool_button.step
        tool_button.step = step
        if self.info_group:
            self.info_layout.removeWidget(self.info_group)
            self.info_group.deleteLater()
            self.info_group = None
            self._status_label = None

        self.info_group = QGroupBox('Tool Configuration')
        self.info_group.setStyleSheet(
            """
            QGroupBox { font-weight: 800; }
            QGroupBox::title { font-weight: 900; }
            """
        )
        info_main_lay = QVBoxLayout(self.info_group)
        info_main_lay.setContentsMargins(8, 6, 8, 8)
        info_main_lay.setSpacing(8)
        self.info_layout.addWidget(self.info_group)

        # --- Header with Thickness and Material in compact row ---
        header_row = QHBoxLayout()
        info_main_lay.addLayout(header_row)

        display_layer = tool_button.layer_name.replace("_", " ")
        hdr = QLabel(f'{display_layer}: {tool_button.tool_name}')
        hdr.setStyleSheet('font-weight: 600; font-size: 14px;')
        header_row.addWidget(hdr, 1)

        header_row.addSpacing(12)
        header_row.addWidget(QLabel('Thickness (nm):'))
        self.thickness_input = QLineEdit('' if step.thickness_nm is None else str(step.thickness_nm))
        self.thickness_input.setMaximumWidth(100)
        header_row.addWidget(self.thickness_input)

        # --- Vertical Parameters Layout ---
        param_vlay = QVBoxLayout()
        param_vlay.setSpacing(10)
        info_main_lay.addLayout(param_vlay)

        self.parameter_widgets = {}
        is_ald = step.tool_type == ToolType.ALD
        ald_nmlc_button_added = False

        for spec in specs_for(step.tool_type):
            if is_ald and spec.key in {"desired_material", "precursor_name"}:
                if not ald_nmlc_button_added:
                    mat_row = QHBoxLayout()
                    btn_nmlc = QPushButton('Inserting material')
                    UIImprovement.set_button_variant(btn_nmlc, 'primary')
                    btn_nmlc.clicked.connect(self._open_nmlc_for_ald)
                    mat_row.addWidget(QLabel('Material:'), 0)
                    mat_row.addWidget(btn_nmlc, 1)
                    param_vlay.addLayout(mat_row)
                    self.parameter_widgets["__ald_nmlc_material__"] = btn_nmlc
                    ald_nmlc_button_added = True
                continue

            w = self._make_param_widget(spec, step)
            label = spec.label if spec.unit == '-' else f"{spec.label} ({spec.unit})"

            if spec.key == "desired_material":
                mat_row = QHBoxLayout()
                mat_row.addWidget(QLabel('Material:'), 0)
                mat_row.addWidget(w, 1)
                param_vlay.addLayout(mat_row)
                self.parameter_widgets[spec.key] = w
                continue

            param_row = QHBoxLayout()
            param_row.addWidget(QLabel(label + ':'), 0)
            param_row.addWidget(w, 1)
            param_vlay.addLayout(param_row)
            self.parameter_widgets[spec.key] = w

        param_vlay.addStretch(1)

        action_row = QHBoxLayout()

        if self.conn is not None:
            btn_link = QPushButton('Link...')
            btn_link.clicked.connect(lambda: _open_attachment_dialog(self, tool_button))
            action_row.addWidget(btn_link)

        btn_del = QPushButton('Remove Tool')
        UIImprovement.set_button_variant(btn_del, 'danger')
        btn_del.clicked.connect(lambda: self._removeTool(tool_button))
        action_row.addWidget(btn_del)
        action_row.addStretch(1)

        info_main_lay.addLayout(action_row)
        self._wire_autosave_signals()

    def _make_param_widget(self, spec: ParamSpec, step: ProcessStep) -> QWidget:
        curv = str(step.parameters.get(spec.key, '') or '')
        if spec.input_kind == 'material':
            btn = QPushButton('Select Gas' if 'gas' in spec.key else 'Select Material')
            if curv:
                btn.setText(curv)
            btn.selected_material = curv
            btn.clicked.connect(lambda _, key=spec.key, b=btn, tt=step.tool_type: self._openMaterialSelectionDialog(key, b, tt))
            return btn

        if spec.input_kind == 'combo':
            combo = QComboBox()
            combo.addItems(list(spec.choices))
            if curv and combo.findText(curv) < 0:
                combo.addItem(curv)
            if curv:
                combo.setCurrentText(curv)
            return combo

        edit = QLineEdit(curv)
        edit.setFont(QFont('Arial', 10))
        return edit

    def _openMaterialSelectionDialog(self, param_name: str, button: QPushButton, tool_type: ToolType):
        try:
            dlg = MaterialSelectorDialog(self, tool_type, param_name, getattr(button, 'selected_material', ''))
        except Exception as exc:
            QMessageBox.critical(self, 'Selector Open Failed', f'Failed to open selector: {exc}')
            return
        if dlg.exec_() == QDialog.Accepted:
            val = dlg.selected_material or ''
            button.selected_material = val
            button.setText(val if val else ('Select Gas' if 'gas' in param_name else 'Select Material'))
            self._autoSaveParams(silent=True)

    def _ensure_ald_row_and_get_id(self, tools_mps_id: int) -> int:
        if self.conn is None:
            raise RuntimeError("Database connection is not available")
        return db_ops.ensure_ald_row(self.conn, int(tools_mps_id))

    def _load_nmlc_dialog_class(self):
        try:
            from .dialogs.nested_cycle_dialog import NestedMaterialCycleDialog
            return NestedMaterialCycleDialog
        except Exception:
            pass

        QMessageBox.warning(self, "NMLC Unavailable", "Failed to import NMLC dialog modules.")
        return None

    def _open_nmlc_for_ald(self):
        tb = self.tool_button
        if tb is None or tb.step.tool_type != ToolType.ALD:
            QMessageBox.warning(self, "No ALD Tool", "Please select an ALD tool first.")
            return

        if self.conn is None:
            QMessageBox.warning(self, "DB Unavailable", "Database connection is not available.")
            return

        try:
            ald_id = self._ensure_ald_row_and_get_id(tb.tool_id)
        except Exception as exc:
            QMessageBox.critical(self, "ALD Init Failed", str(exc))
            return

        dialog_cls = self._load_nmlc_dialog_class()
        if dialog_cls is None:
            return

        if not self._nmlc_dialog_is_valid():
            self._nmlc_dialog = None

        self._nmlc_active_step_id = int(tb.tool_id)
        if self._nmlc_dialog is None:
            try:
                try:
                    self._nmlc_dialog = dialog_cls(
                        parent=self,
                        db_conn=self.conn,
                        selector_cls=NmlcMaterialSelectorDialog,
                        ald_id=ald_id,
                        layer_name=tb.layer_name,
                    )
                except TypeError:
                    self._nmlc_dialog = dialog_cls(
                        parent=self,
                        db_conn=self.conn,
                        selector_cls=NmlcMaterialSelectorDialog,
                        ald_id=ald_id,
                    )
                self._nmlc_dialog.finished.connect(self._on_nmlc_dialog_finished)
                self._nmlc_dialog.destroyed.connect(self._on_nmlc_dialog_destroyed)
            except Exception as exc:
                QMessageBox.critical(self, "NMLC Open Failed", str(exc))
                self._nmlc_dialog = None
                return
        else:
            try:
                if hasattr(self._nmlc_dialog, "set_active_context"):
                    self._nmlc_dialog.set_active_context(ald_id, tb.layer_name)
                else:
                    self._nmlc_dialog.set_active_ald(ald_id)
            except Exception as exc:
                QMessageBox.critical(self, "NMLC Reload Failed", str(exc))
                return

        self._nmlc_dialog.show()
        self._nmlc_dialog.raise_()
        self._nmlc_dialog.activateWindow()

    def _nmlc_dialog_is_valid(self) -> bool:
        if self._nmlc_dialog is None:
            return False
        try:
            _ = self._nmlc_dialog.isVisible()
            return True
        except RuntimeError:
            return False

    def _on_nmlc_dialog_destroyed(self, *_args) -> None:
        self._nmlc_dialog = None

    def _on_nmlc_dialog_finished(self, _result_code: int):
        step_id = self._nmlc_active_step_id
        if step_id is None or not self._nmlc_dialog_is_valid():
            return
        try:
            desired, precursor = self._nmlc_dialog.get_first_material()
        except Exception:
            return

        step = self.process_service.get_step(int(step_id))
        if step is None:
            return
        params = dict(step.parameters)
        params["desired_material"] = desired or ""
        params["precursor_name"] = precursor or ""

        try:
            updated = self.process_service.update_step(
                step_id=int(step.step_id or 0),
                layer=step.layer.value,
                thickness_raw="" if step.thickness_nm is None else str(step.thickness_nm),
                parameters=params,
                position_in_layer=step.position_in_layer,
            )
        except Exception:
            return

        w = self.find_tool_widget(int(step_id))
        if w is not None:
            w.step = updated
            w.updateMaterialDisplay()
            if self.tool_button is w:
                self.tool_button = w
        self._refresh_tool_badges()
        self._refresh_layer_cake()

    def closeEvent(self, event):
        dlg = self._nmlc_dialog if self._nmlc_dialog_is_valid() else None
        self._nmlc_dialog = None
        if dlg is not None:
            try:
                dlg.close()
                dlg.deleteLater()
            except RuntimeError:
                pass
        super().closeEvent(event)

    def _autoSaveParams(self, silent: bool = True):
        self._saveData(show_message=not silent)
        if silent:
            self._set_status('Auto-saved')

    def _saveData(self, show_message: bool = False):
        if not self.tool_button:
            return
        try:
            current = self.process_service.get_step(self.tool_button.tool_id) or self.tool_button.step
            params: dict[str, str] = {
                str(k): ("" if v is None else str(v))
                for k, v in (current.parameters or {}).items()
            }
            for key, w in self.parameter_widgets.items():
                if key.startswith("__"):
                    continue
                if isinstance(w, QLineEdit):
                    params[key] = (w.text() or '').strip()
                elif isinstance(w, QComboBox):
                    params[key] = (w.currentText() or '').strip()
                elif isinstance(w, QPushButton):
                    params[key] = (getattr(w, 'selected_material', '') or '').strip()
                else:
                    params[key] = ''

            updated = self.process_service.update_step(
                step_id=self.tool_button.tool_id,
                layer=self.tool_button.layer_name,
                thickness_raw=(self.thickness_input.text() or '').strip(),
                parameters=params,
                position_in_layer=current.position_in_layer,
            )
            self.tool_button.step = updated
            self.tool_button.updateMaterialDisplay()
            self._refresh_layer_cake()
            self._set_status(f'Saved tool {updated.step_id}')
            if show_message:
                QMessageBox.information(self, 'Success', 'Data saved successfully.')
        except Exception as exc:
            if show_message:
                QMessageBox.critical(self, 'Error', f'Failed to save data: {exc}')
            self._set_status('Save failed')

    def _removeTool(self, tool_button: ToolItemWidget):
        try:
            self.process_service.delete_step(tool_button.tool_id)
            sl = tool_button.sublayer_widget
            sl.tool_layout.removeWidget(tool_button)
            tool_button.deleteLater()
            if self.info_group:
                self.info_layout.removeWidget(self.info_group)
                self.info_group.deleteLater()
                self.info_group = None
                self._status_label = None
                self.parameter_widgets = {}
                self._clear_autosave_timers()
            if self.tool_button is tool_button:
                self.tool_button = None
            sl.updateRemoveButtonState()
            self._refresh_tool_badges()
            self._refresh_layer_cake()
            self._set_status(f'Removed tool {tool_button.tool_id}')
        except Exception as exc:
            QMessageBox.critical(self, 'Error', f'Failed to remove tool: {exc}')
