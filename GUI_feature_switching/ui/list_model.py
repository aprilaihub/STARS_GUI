"""Virtualized experiment list model."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5 import QtCore


class ExperimentListModel(QtCore.QAbstractListModel):
    """Virtual list model backed by experiment ids and preloaded metadata."""

    def __init__(self, meta_by_eid: Dict[int, Dict[str, Any]], eid_list: Optional[List[int]] = None, parent=None):
        super().__init__(parent)
        self.meta_by_eid = meta_by_eid
        self.eids: List[int] = list(eid_list) if eid_list else []
        self._label_cache: Dict[int, str] = {}

    def set_eids(self, new_eids: List[int]) -> None:
        self.beginResetModel()
        self.eids = list(new_eids)
        self._label_cache.clear()
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.eids)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self.eids):
            return None

        eid = self.eids[row]
        if role == QtCore.Qt.UserRole:
            return eid

        if role == QtCore.Qt.DisplayRole:
            if eid in self._label_cache:
                return self._label_cache[eid]

            data = self.meta_by_eid.get(eid, {})
            dev_id = data.get("device_id", "")
            name = data.get("experiment_name") or ""
            function_type = data.get("function_type") or ""
            recipe = data.get("recipe_name") or ""
            die = data.get("die_number", "")
            area = data.get("cross_sectional_area_um2", "")
            wordline = data.get("wordline", "")
            bitline = data.get("bitline", "")
            label = (
                f"{eid} | dev={dev_id} | {function_type} | {name} | "
                f"recipe={recipe} die={die} area={area} wl={wordline} bl={bitline}"
            )
            self._label_cache[eid] = label
            return label

        return None
