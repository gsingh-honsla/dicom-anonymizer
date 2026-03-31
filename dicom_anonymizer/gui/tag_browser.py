"""DICOM tag browser widget with PHI highlighting."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel,
    QLineEdit,
    QPushButton,
)

import pydicom

from ..core.tag_profile import TAG_PROFILE, Action


# Colors
_RED = QBrush(QColor("#dc3545"))       # PHI tags that should be anonymized
_GREEN = QBrush(QColor("#28a745"))     # Successfully anonymized
_ORANGE = QBrush(QColor("#fd7e14"))    # Warnings (e.g. private tags present)
_GRAY = QBrush(QColor("#6c757d"))      # Removed tags (shown in profile-only mode)


class TagBrowser(QWidget):
    """DICOM tag tree viewer with PHI-aware color coding.

    Color coding:
    - Red: Tag is in the anonymization profile and value looks like original PHI
    - Green: Tag is in the profile and appears properly anonymized
    - Orange: Private tag still present
    - Default: Non-profiled tag (not a PHI concern)
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._ds: pydicom.Dataset | None = None
        self._file_path: Path | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header with file info
        self.lbl_file = QLabel("No file loaded")
        self.lbl_file.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.lbl_file)

        # Search / filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("Search tags by name, number, or value...")
        self.txt_filter.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.txt_filter)
        self.btn_phi_only = QPushButton("PHI Only")
        self.btn_phi_only.setCheckable(True)
        self.btn_phi_only.toggled.connect(self._apply_filter)
        filter_row.addWidget(self.btn_phi_only)
        layout.addLayout(filter_row)

        # Tag tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tag", "Name", "VR", "Value", "Profile"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.resizeSection(0, 120)   # Tag
        header.resizeSection(1, 200)   # Name
        header.resizeSection(2, 40)    # VR
        header.resizeSection(3, 300)   # Value
        header.resizeSection(4, 60)    # Profile
        layout.addWidget(self.tree, stretch=1)

        # Summary
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.lbl_summary)

    # ── Public API ────────────────────────────────────────────

    def load_dataset(self, ds: pydicom.Dataset, file_path: Path | None = None):
        """Load a DICOM dataset into the tag browser.

        Args:
            ds: pydicom Dataset to display.
            file_path: Optional file path for the header label.
        """
        self._ds = ds
        self._file_path = file_path
        self.lbl_file.setText(str(file_path.name) if file_path else "In-memory dataset")
        self._populate_tree()

    def load_file(self, file_path: Path):
        """Load a DICOM file into the tag browser."""
        try:
            ds = pydicom.dcmread(str(file_path), force=True)
            self.load_dataset(ds, file_path)
        except Exception as e:
            self.tree.clear()
            self.lbl_file.setText(f"Error loading {file_path.name}: {e}")

    # ── Internal ──────────────────────────────────────────────

    def _populate_tree(self):
        """Fill the tree widget from the current dataset."""
        self.tree.clear()
        if self._ds is None:
            return

        profiled_count = 0
        private_count = 0
        total = 0

        for elem in self._ds:
            total += 1
            tag = elem.tag
            tag_str = f"({tag.group:04X},{tag.element:04X})"
            name = elem.keyword or elem.name or "Unknown"
            vr = str(elem.VR)

            # Truncate long values for display
            try:
                value = str(elem.value)
                if len(value) > 200:
                    value = value[:200] + "..."
            except Exception:
                value = "<cannot display>"

            # Determine profile action
            tag_tuple = (tag.group, tag.element)
            profile_info = TAG_PROFILE.get(tag_tuple)
            profile_str = ""
            if profile_info:
                profile_str = profile_info[0].value
                profiled_count += 1

            is_private = tag.group % 2 != 0
            if is_private:
                private_count += 1

            item = QTreeWidgetItem([tag_str, name, vr, value, profile_str])
            item.setData(0, Qt.UserRole, tag_tuple)  # Store tag for filtering

            # Color coding
            if profile_info:
                action = profile_info[0]
                if action in (Action.D, Action.Z, Action.X):
                    # This is a PHI tag — check if it looks properly handled
                    if action == Action.X:
                        # Should have been removed — if we see it, it's bad
                        item.setForeground(0, _RED)
                        item.setForeground(1, _RED)
                        item.setForeground(3, _RED)
                    elif action == Action.D and value.startswith("ANON_"):
                        item.setForeground(0, _GREEN)
                        item.setForeground(1, _GREEN)
                        item.setForeground(3, _GREEN)
                    elif action == Action.Z and not value.strip():
                        item.setForeground(0, _GREEN)
                        item.setForeground(1, _GREEN)
                    else:
                        # Tag present with unexpected value
                        item.setForeground(0, _RED)
                        item.setForeground(1, _RED)
                        item.setForeground(3, _RED)
            elif is_private:
                item.setForeground(0, _ORANGE)
                item.setForeground(1, _ORANGE)

            self.tree.addTopLevelItem(item)

        self.lbl_summary.setText(
            f"{total} tags | {profiled_count} in profile | "
            f"{private_count} private"
        )

    def _apply_filter(self, _=None):
        """Show/hide tree items based on current filter."""
        filter_text = self.txt_filter.text().lower()
        phi_only = self.btn_phi_only.isChecked()

        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            tag_tuple = item.data(0, Qt.UserRole)
            profile_str = item.text(4)

            visible = True

            # PHI filter
            if phi_only and not profile_str:
                visible = False

            # Text filter
            if visible and filter_text:
                searchable = " ".join(
                    item.text(col).lower() for col in range(5)
                )
                if filter_text not in searchable:
                    visible = False

            item.setHidden(not visible)
