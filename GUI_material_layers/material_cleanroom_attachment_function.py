from __future__ import annotations

import os

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .sql import db_ops

try:
    from .material_ui_improvement import UIImprovement  # type: ignore
except Exception:
    class UIImprovement:  # pragma: no cover - fallback only
        @staticmethod
        def apply_theme(*_args, **_kwargs):
            return None

        @staticmethod
        def set_button_variant(*_args, **_kwargs):
            return None


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class AttachmentDialog(QDialog):
    def __init__(self, parent_widget: "MaterialProcessWidget", tool_button: "ToolButton"):
        super().__init__(parent_widget)
        UIImprovement.apply_theme(self, dark=False)
        self.setWindowTitle("Tool Attachment")
        self.resize(700, 320)

        self.parent_widget = parent_widget
        self.tool_button = tool_button
        self.conn = parent_widget.conn
        self.current_type = self.tool_button.base_name
        self.layer_id = int(self.tool_button.tool_id)

        root = QVBoxLayout(self)

        header = QLabel(f"Tool ID: {self.layer_id}   |   {tool_button.tool_name}")
        header.setStyleSheet("font-weight:700; font-size:14px;")
        root.addWidget(header)

        self.info_table = QTableWidget(5, 2, self)
        self.info_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.info_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.info_table.setFocusPolicy(0)
        self.info_table.setAlternatingRowColors(True)
        self.info_table.setFixedHeight(210)
        for row, field in enumerate(["Status", "File", "Size", "SHA256", "Created"]):
            self.info_table.setItem(row, 0, QTableWidgetItem(field))
            self.info_table.setItem(row, 1, QTableWidgetItem("-"))
        root.addWidget(self.info_table)

        button_row = QHBoxLayout()
        self.btn_load = QPushButton("Load / Replace Attachment")
        self.btn_export = QPushButton("Export Attachment")
        self.btn_remove = QPushButton("Remove Attachment")
        self.btn_close = QPushButton("Close")

        UIImprovement.set_button_variant(self.btn_export, "warning")
        UIImprovement.set_button_variant(self.btn_remove, "danger")

        button_row.addWidget(self.btn_load)
        button_row.addWidget(self.btn_export)
        button_row.addWidget(self.btn_remove)
        button_row.addStretch(1)
        button_row.addWidget(self.btn_close)
        root.addLayout(button_row)

        self.btn_load.clicked.connect(self._load_or_replace_attachment)
        self.btn_export.clicked.connect(self._export_attachment)
        self.btn_remove.clicked.connect(self._remove_attachment)
        self.btn_close.clicked.connect(self.accept)

        self._reload_summary()

    def _current_summary(self) -> dict[str, object] | None:
        return db_ops.get_tool_attachment_summary(
            self.conn,
            tool_type=self.current_type,
            layer_id=self.layer_id,
        )

    def _reload_summary(self) -> None:
        summary = self._current_summary()
        if summary is None:
            values = [
                "No attachment linked",
                "-",
                "-",
                "-",
                "-",
            ]
            self.btn_export.setEnabled(False)
            self.btn_remove.setEnabled(False)
        else:
            hash_text = str(summary.get("content_hash") or "")
            values = [
                "One attachment linked",
                str(summary.get("file_name") or "-"),
                f"{summary.get('file_size') or 0} bytes",
                hash_text,
                str(summary.get("created_at") or "-"),
            ]
            self.btn_export.setEnabled(True)
            self.btn_remove.setEnabled(True)

        for row, value in enumerate(values):
            item = self.info_table.item(row, 1)
            if item is None:
                item = QTableWidgetItem("")
                self.info_table.setItem(row, 1, item)
            item.setText(value)

    def _load_or_replace_attachment(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose attachment", "", "All Files (*.*)")
        if not path:
            return

        try:
            raw = _read_file_bytes(path)
            result = db_ops.link_attachment_to_tool(
                self.conn,
                tool_type=self.current_type,
                layer_id=self.layer_id,
                file_name=os.path.basename(path),
                raw=raw,
            )
            self._reload_summary()
            msg = "Attachment linked to this tool."
            if bool(result.get("reused")):
                msg += " Reused existing Tool_Attachment row."
            else:
                msg += " Stored as a new Tool_Attachment row."
            QMessageBox.information(self, "Attachment Updated", msg)
        except Exception as exc:
            QMessageBox.critical(self, "Attachment Failed", str(exc))

    def _remove_attachment(self) -> None:
        summary = self._current_summary()
        if summary is None:
            QMessageBox.warning(self, "No Attachment", "This tool has no linked attachment.")
            return
        if QMessageBox.question(self, "Confirm", "Remove the attachment from this tool?") != QMessageBox.Yes:
            return

        try:
            removed = db_ops.detach_attachment_from_tool(
                self.conn,
                tool_type=self.current_type,
                layer_id=self.layer_id,
            )
            self._reload_summary()
            if removed:
                QMessageBox.information(self, "Attachment Removed", "Attachment detached from this tool.")
            else:
                QMessageBox.information(self, "No Change", "This tool had no attachment.")
        except Exception as exc:
            QMessageBox.critical(self, "Remove Failed", str(exc))

    def _export_attachment(self) -> None:
        summary = self._current_summary()
        if summary is None:
            QMessageBox.warning(self, "No Attachment", "This tool has no linked attachment.")
            return

        row = db_ops.fetch_attachment_export(self.conn, int(summary["attachment_id"]))
        if row is None:
            QMessageBox.warning(self, "Missing Attachment", "Attachment payload could not be loaded.")
            return

        file_name, raw = row
        out_path, _ = QFileDialog.getSaveFileName(self, "Export Attachment", file_name, "All Files (*.*)")
        if not out_path:
            return

        try:
            with open(out_path, "wb") as handle:
                handle.write(raw)
            QMessageBox.information(self, "Export Complete", "Attachment exported.")
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
