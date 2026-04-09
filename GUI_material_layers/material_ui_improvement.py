# -*- coding: utf-8 -*-
"""
material_ui_improvement.py

UI 主题与组件库（无业务依赖）：
- 设计 Tokens（明/暗主题）
- 通用样式（按钮/分割条/滚动区/表格/卡片）
- 可复用组件：ToolChip（两行紧凑信息块）

本文件不依赖数据库与业务逻辑，便于单独维护/测试。
"""

from PyQt5.QtCore import Qt, QRect, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QGraphicsDropShadowEffect, QFrame, QLabel, QSizePolicy, QWidget
)

# =========================
#  Design Tokens & Themes
# =========================
class _Color:
    def __init__(self, **kw):
        self.__dict__.update(kw)

class _Tokens:
    def __init__(self, color, radius, space, font, elev):
        self.color = color
        self.radius = radius
        self.space = space
        self.font = font
        self.elev = elev

LIGHT_COLOR = _Color(
    bg="#FFFFFF", fg="#333333", muted="#757575",
    primary="#BFD7EA", primary_hover="#8CBED6", primary_pressed="#6FA6C1",
    warning="#FFF3B0", warning_hover="#FFD166", warning_pressed="#E9B949",
    danger="#F8B4B4", danger_hover="#F98080", danger_pressed="#E74646",
    border="#DADADA", selection_bg="#BFD7EA", selection_fg="#0B3954",
    scrollbar_track="rgba(0,112,186,0.20)", scrollbar_thumb="rgba(0,88,155,0.80)"
)

DARK_COLOR = _Color(
    bg="#1E1E1E", fg="#EAEAEA", muted="#AAAAAA",
    primary="#2F6CAD", primary_hover="#3C7DC4", primary_pressed="#2A5C92",
    warning="#6B5E27", warning_hover="#8A7731", warning_pressed="#A98F3B",
    danger="#8E3B3B", danger_hover="#A64B4B", danger_pressed="#BF5A5A",
    border="#3A3A3A", selection_bg="#2F6CAD", selection_fg="#FFFFFF",
    scrollbar_track="rgba(255,255,255,0.12)", scrollbar_thumb="rgba(255,255,255,0.35)"
)

LIGHT_TOKENS = _Tokens(
    color=LIGHT_COLOR,
    radius={"sm": 4, "md": 8, "lg": 10},
    space={"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24},
    font={"family": "Arial", "size_base": 16, "size_label": 18, "size_title": 16},
    elev={"shadow_color": "#808080", "blur": 8, "x": 3, "y": 3}
)

DARK_TOKENS = _Tokens(
    color=DARK_COLOR,
    radius={"sm": 4, "md": 8, "lg": 10},
    space={"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24},
    font={"family": "Arial", "size_base": 16, "size_label": 18, "size_title": 16},
    elev={"shadow_color": "#000000", "blur": 8, "x": 3, "y": 3}
)

def _build_qss(t: _Tokens) -> str:
    """生成全局 QSS。注意按钮的 variant 值通过 dynamic property 控制。"""
    c, r, s, f = t.color, t.radius, t.space, t.font
    return f"""
    QWidget {{
        background-color: {c.bg};
        color: {c.fg};
        font-size: {f['size_base']}px;
        font-family: {f['family']};
    }}

    QPushButton {{
        background-color: {c.primary};
        color: #0B3954;
        border-radius: {r['md']}px;
        padding: {s['xs']}px {s['sm']}px;
        font-weight: 600;
        border: none;
    }}
    QPushButton:hover {{ background-color: {c.primary_hover}; }}
    QPushButton:pressed {{ background-color: {c.primary_pressed}; }}

    /* Variants */
    QPushButton[variant="warning"] {{
        background-color: #FFF176;
        color: #8A6D00;
        border: 1px solid #FBC02D;
    }}
    QPushButton[variant="warning"]:hover {{ background-color: #FFEE58; }}
    QPushButton[variant="warning"]:pressed {{ background-color: #FDD835; }}
    QPushButton[variant="warning"]:disabled {{
        background-color: #FFF9C4; color: #9E9E9E; border: 1px solid #F0E68C;
    }}

    QPushButton[variant="danger"] {{
        background-color: #F87171; color: #FFFFFF; border: 1px solid #DC2626;
    }}
    QPushButton[variant="danger"]:hover {{ background-color: #EF4444; }}
    QPushButton[variant="danger"]:pressed {{ background-color: #B91C1C; }}
    QPushButton[variant="danger"]:disabled {{
        background-color: #FCA5A5; color: #7F1D1D; border: 1px solid #FECACA;
    }}

    QGroupBox {{
        border: 1px solid {c.border};
        border-radius: {r['lg']}px;
        margin-top: {s['md']}px;
        padding: {s['sm']}px;
        background: transparent;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 3px 8px;
        background-color: #F3F6FA;
        color: #1F2D3D;
        border: 1px solid {c.border};
        border-radius: 6px;
        font-size: {f['size_title']}px;
        font-weight: 700;
    }}

    QLabel {{ font-weight: 600; font-size: {f['size_label']}px; color: {c.fg}; }}

    QLineEdit, QComboBox {{
        border: 1px solid {c.muted};
        border-radius: {r['sm']}px;
        padding: {s['xs']}px;
        background-color: #FFFFFF;
        color: {c.fg};
        min-height: 28px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {c.primary_hover}; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: {c.scrollbar_track}; width: 10px; margin: 2px 0; border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {c.scrollbar_thumb}; border-radius: 5px; min-height: 20px;
    }}

    QSplitter::handle {{ background: {c.muted}; border-radius: 5px; width: 3px; }}
    QSplitter::handle:hover {{ background: {c.primary_hover}; }}

    QTableView {{
        background-color: #FFFFFF;
        color: #000000;
        gridline-color: #DDDDDD;
        font-size: 12pt;
        border: 1px solid #CCCCCC;
        alternate-background-color: #F8F8F8;
        selection-background-color: {c.selection_bg};
        selection-color: {c.selection_fg};
    }}
    QHeaderView::section {{
        background-color: #F0F0F0;
        color: #000000;
        padding: 6px;
        font-size: 14pt;
        font-weight: bold;
        border: 1px solid #DDDDDD;
    }}
    """

# =========================
#  UIImprovement (Public API)
# =========================
class UIImprovement:
    """
    工程化 UI 辅助：主题注入、语义变体、卡片样式、阴影等。
    与现有业务代码兼容：保留 set_global_style()/add_shadow() 等接口。
    """
    _tokens = LIGHT_TOKENS  # 默认浅色

    # ---- 主题 ----
    @staticmethod
    def apply_theme(widget: QWidget, dark: bool = False):
        """应用主题并缓存 tokens。"""
        UIImprovement._tokens = DARK_TOKENS if dark else LIGHT_TOKENS
        widget.setStyleSheet(_build_qss(UIImprovement._tokens))

    @staticmethod
    def set_global_style(widget: QWidget):
        """兼容旧调用：内部转到浅色主题。"""
        UIImprovement.apply_theme(widget, dark=False)

    # ---- 按钮语义变体 ----
    @staticmethod
    def set_button_variant(btn: QWidget, variant: str):
        """variant: 'warning' / 'danger' / (可扩展 'ghost' 等)"""
        btn.setProperty("variant", variant)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    # ---- Layer 容器样式（右侧卡片 + 左侧竖标）----
    @staticmethod
    def _layer_palette(layer_type: str):
        palettes = {
            "Top":       {"bg": "#E3F2FD", "border": "#64B5F6", "accent": "#1565C0"},
            "Insulator": {"bg": "#FFF8E1", "border": "#FFD54F", "accent": "#F57F17"},
            "Bottom":    {"bg": "#FFEBEE", "border": "#E57373", "accent": "#B71C1C"},
        }
        return palettes.get(layer_type, {"bg": "#F5F5F5", "border": "#BDBDBD", "accent": "#374151"})

    @staticmethod
    def style_layer_section(side_label: QLabel, container_frame: QFrame, layer_type: str):
        p = UIImprovement._layer_palette(layer_type)

        side_label.setMinimumWidth(40)
        side_label.setMaximumWidth(40)
        side_label.setStyleSheet(f"""
            QLabel {{
                background: {p['accent']};
                color: white;
                border-radius: 10px;
                padding: 8px 0;
                font-weight: 700;
                letter-spacing: 1px;
                qproperty-alignment: AlignCenter;
            }}
        """)

        # 关键：容器自身保留彩色背景
        container_frame.setObjectName("layerContainer")
        container_frame.setAttribute(Qt.WA_StyledBackground, True)  # ✅ 允许按样式绘制背景
        container_frame.setStyleSheet(f"""
            QFrame#layerContainer {{
                background: {p['bg']};                 /* 保留你的蓝/黄/粉底 */
                border: 2px solid {p['border']};
                border-radius: 12px;
            }}
            /* 关键：所有后代都透明 —— 注意：Qt QSS 不支持 '>'，要用空格后代选择器 */
            QFrame#layerContainer * {{
                background: transparent;
            }}
        """)

    # ---- SubLayer 卡片 ----
    @staticmethod
    def style_sublayer_card(card: QFrame):
        """sub-layer 卡片：淡色背景 + 圆角 + 轻阴影"""
        card.setStyleSheet("""
            QFrame {
                background: #F7FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
        """)
        try:
            UIImprovement.add_shadow_new(card)  # 如果你后来扩展了 add_shadow_new
        except Exception:
            UIImprovement.add_shadow(card)

    @staticmethod
    def style_sublayer_header(bar: QWidget, title: QLabel):
        """卡片标题栏：左 Title + 右侧操作（删除/折叠）"""
        bar.setStyleSheet("""
            QWidget {
                background: #EDF2F7;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                border: none;
            }
        """)
        title.setText(title.text().replace("sub_layer_", "Sub-layer "))
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        title.setStyleSheet("""
            QLabel {
                font-weight: 700;
                color: #1F2937;
                padding-left: 10px;
                font-size: 14px;
            }
        """)

    # ---- 工具条按钮样式（可选）----
    @staticmethod
    def style_tool_button(btn: QWidget):
        btn.setStyleSheet("""
            QPushButton {
                background: #F3F6FA;
                color: #223344;
                border: 1px solid #D6DFEA;
                border-radius: 8px;
                padding: 6px 10px;
                text-align: left;
                font-weight: 600;
            }
            QPushButton:hover { background: #E7EFF8; }
            QPushButton:pressed { background: #DBE8F5; }
        """)

    # ---- Material 标签（Chip 文本 HTML）----
    @staticmethod
    def set_material_label_style(label: QLabel):
        label.setStyleSheet("""
            QLabel { background: transparent; color: #2F6CAD; font-weight: 600; padding: 0px; }
        """)
        label.setAlignment(Qt.AlignLeft)

    @staticmethod
    def format_chip(text: str) -> str:
        return f"""
            <span style="
                background-color:#EAF2FA;
                color:#1E4976;
                border:1px solid #D0E2F2;
                border-radius:12px;
                padding:2px 8px;
                font-size:14px;
                font-weight:600;">
                {text}
            </span>
        """

    # ---- 分割条 / 滚动区 / 表格 ----
    @staticmethod
    def set_vertical_splitter_style(splitter):
        splitter.setStyleSheet("""
            QSplitter::handle { background: #757575; border-radius: 5px; width: 3px; }
            QSplitter::handle:hover { background: #8CBED6; }
        """)

    @staticmethod
    def set_horizontal_splitter_style(splitter):
        splitter.setStyleSheet("""
            QSplitter::handle { background-color: #757575; height: 5px; }
        """)

    @staticmethod
    def set_scroll_area_style(scroll_area):
        scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical {
                background: rgba(0, 112, 186, 0.20);
                width: 10px; margin: 2px 0; border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 88, 155, 0.80);
                border-radius: 5px; min-height: 20px;
            }
        """)
        # ✅ 这一句非常关键
        scroll_area.viewport().setStyleSheet("background: transparent;")

    @staticmethod
    def set_table_style(table):
        table.setStyleSheet("""
            QTableView {
                background-color: #FFFFFF;
                color: #000000;
                gridline-color: #DDDDDD;
                font-size: 12pt;
                border: 1px solid #CCCCCC;
                alternate-background-color: #F0F0F0;
                selection-background-color: #BFD7EA;
                selection-color: #0B3954;
            }
            QHeaderView::section {
                background-color: #F0F0F0;
                color: #000000;
                padding: 6px;
                font-size: 14pt;
                font-weight: bold;
                border: 1px solid #DDDDDD;
            }
            QTableView::item:hover { background-color: #EAF2FA; }
        """)

    # ---- 阴影 ----
    @staticmethod
    def add_shadow(widget: QWidget):
        """
        给组件添加阴影。读取 tokens（未初始化主题时回退默认值）。
        """
        eff = QGraphicsDropShadowEffect()
        try:
            t = getattr(UIImprovement, "_tokens", LIGHT_TOKENS).elev
            blur, x, y = t["blur"], t["x"], t["y"]
            color = t["shadow_color"]
        except Exception:
            blur, x, y, color = 8, 3, 3, "#808080"

        if isinstance(color, str):
            color = QColor(color)

        eff.setBlurRadius(blur)
        eff.setXOffset(x)
        eff.setYOffset(y)
        eff.setColor(color)
        widget.setGraphicsEffect(eff)

    # ---- 小工具 ----
    @staticmethod
    def darken_color(hex_color: str, factor: float = 0.2) -> str:
        """暗化颜色（0~1）"""
        hex_color = hex_color.lstrip("#")
        r, g, b = [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return f"#{r:02X}{g:02X}{b:02X}"


# =========================
#  ToolChip 组件
# =========================
class ToolChip(QFrame):
    """
    两行紧凑 Chip：标题(大/粗) + 副标题(小/常规)。
    - 支持自定义字号：title_size / subtitle_size（pt）
    - 自动根据字号计算最小高度，避免裁切
    - 文本与背景均自绘，hover 变色
    """
    clicked = pyqtSignal()

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent=None,
        *,
        title_size: int = None,     # None -> 基准 +2
        subtitle_size: int = None,  # None -> 基准 -1
        hpad: int = 12,
        vpad: int = 10,
        line_gap: int = 4
    ):
        super().__init__(parent)
        self._title = title or ""
        self._subtitle = subtitle or ""
        self._hover = False

        self._title_size = title_size
        self._subtitle_size = subtitle_size
        self._hpad = hpad
        self._vpad = vpad
        self._gap = line_gap

        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setContentsMargins(0, 0, 0, 0)
        self.setMinimumHeight(40)

    # —— 公共 API —— #
    def setTexts(self, title: str, subtitle: str = ""):
        self._title = title or ""
        self._subtitle = subtitle or ""
        self.update()

    def setSizes(self, *, title_size: int = None, subtitle_size: int = None):
        self._title_size = title_size
        self._subtitle_size = subtitle_size
        self.update()

    # —— 交互 —— #
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    # —— 尺寸建议 —— #
    def sizeHint(self) -> QSize:
        base_pt = self.font().pointSize() if self.font().pointSize() > 0 else 10
        t_pt = self._title_size if self._title_size is not None else max(12, base_pt + 2)
        s_pt = self._subtitle_size if self._subtitle_size is not None else max(9, base_pt - 1)
        approx_h = t_pt + (s_pt if self._subtitle else 0) + self._gap + self._vpad * 2
        return QSize(220, max(approx_h, self.minimumHeight()))

    # —— 绘制 —— #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # 主题 / 颜色
        try:
            t = getattr(UIImprovement, "_tokens", LIGHT_TOKENS)
            c = t.color
            radius = t.radius["md"]
            bg = QColor(c.primary_hover if self._hover else c.primary)
            border = QColor(c.border)
            title_color = QColor("#0B3954")
            subtitle_color = QColor("#374151")
        except Exception:
            radius = 8
            bg = QColor("#BFD7EA")
            border = QColor("#D0D7DE")
            title_color = QColor("#0B3954")
            subtitle_color = QColor("#374151")

        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(border, 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(rect, radius, radius)

        base_pt = self.font().pointSize() if self.font().pointSize() > 0 else 10
        t_pt = self._title_size if self._title_size is not None else max(12, base_pt + 2)
        s_pt = self._subtitle_size if self._subtitle_size is not None else max(9, base_pt - 1)

        title_font = QFont(self.font()); title_font.setPointSize(t_pt); title_font.setBold(True)
        sub_font = QFont(self.font());   sub_font.setPointSize(s_pt);   sub_font.setBold(False)

        fm_t = QFontMetrics(title_font)
        fm_s = QFontMetrics(sub_font)

        title_h = fm_t.height()
        sub_h = fm_s.height() if self._subtitle else 0
        total_text_h = title_h + (self._gap if self._subtitle else 0) + sub_h
        needed_h = self._vpad * 2 + total_text_h

        if self.height() < needed_h:
            self.setMinimumHeight(needed_h)

        content = rect.adjusted(self._hpad, self._vpad, -self._hpad, -self._vpad)
        y = content.y() + (content.height() - total_text_h) // 2
        w = content.width()
        x = content.x()

        # 标题
        p.setFont(title_font); p.setPen(title_color)
        title_rect = QRect(x, y, w, title_h)
        t_text = fm_t.elidedText(self._title, Qt.ElideRight, w)
        p.drawText(title_rect, Qt.AlignHCenter | Qt.AlignVCenter, t_text)
        y += title_h

        # 副标题
        if self._subtitle:
            y += self._gap
            p.setFont(sub_font); p.setPen(subtitle_color)
            sub_rect = QRect(x, y, w, sub_h)
            s_text = fm_s.elidedText(self._subtitle, Qt.ElideRight, w)
            p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignVCenter, s_text)

        p.end()
