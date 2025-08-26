import json
from datetime import datetime
from typing import List, Dict

from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtWidgets import QWidget, QListWidget, QVBoxLayout, QListWidgetItem


class StartupHome(QWidget):
    """Home screen showing recent notebooks."""

    open_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.settings = QSettings("YourCompany", "PRIMApp")
        self._recent: List[Dict] = []

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)

        self._load_recent()

    # ------------------------------------------------------------------
    def _load_recent(self) -> None:
        """Load recent notebooks from persistent settings."""
        raw = self.settings.value("recent/notebooks", "[]")
        if isinstance(raw, list):
            data = raw
        else:
            try:
                data = json.loads(raw)
            except Exception:
                data = []
        if not isinstance(data, list):
            data = []
        self._recent = data
        self._render_recent()

    def _save_recent(self) -> None:
        """Persist current recent list to settings."""
        self.settings.setValue("recent/notebooks", json.dumps(self._recent))

    def _render_recent(self) -> None:
        """Render the recent list into the widget."""
        self.list.clear()
        for entry in self._recent:
            title = entry.get("title", "")
            path = entry.get("path", "")
            item = QListWidgetItem(f"{title} — {path}")
            item.setData(Qt.UserRole, entry.get("id"))
            self.list.addItem(item)

    # ------------------------------------------------------------------
    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Emit open_requested with the notebook id on double-click."""
        notebook_id = item.data(Qt.UserRole)
        if notebook_id is not None:
            self.open_requested.emit(str(notebook_id))

    # ------------------------------------------------------------------
    def record_recent(self, notebook_id: str, title: str, path: str) -> None:
        """Update recent list with the given notebook details.

        Moves existing entry to top, deduplicates and keeps at most 10 items.
        """
        # remove existing entry with same id
        self._recent = [r for r in self._recent if r.get("id") != notebook_id]

        self._recent.insert(
            0,
            {
                "id": notebook_id,
                "title": title,
                "path": path,
                "last_opened": datetime.utcnow().isoformat(),
            },
        )
        self._recent = self._recent[:10]
        self._save_recent()
        self._render_recent()
