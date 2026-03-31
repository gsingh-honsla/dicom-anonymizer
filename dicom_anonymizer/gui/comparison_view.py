"""Side-by-side comparison view: original vs anonymized DICOM (images + tags)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QScrollBar,
    QPushButton,
)

import pydicom

from .image_viewer import ImageViewer
from ..core.tag_profile import TAG_PROFILE, Action


_RED_BG = QBrush(QColor("#fff0f0"))
_GREEN_BG = QBrush(QColor("#f0fff0"))
_YELLOW_BG = QBrush(QColor("#fffde0"))
_RED_FG = QBrush(QColor("#dc3545"))
_GREEN_FG = QBrush(QColor("#28a745"))


class ComparisonView(QWidget):
    """Side-by-side original vs anonymized DICOM comparison.

    Provides two tabs:
    1. Image comparison — synchronized image viewers
    2. Tag diff — color-coded tag-by-tag comparison
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._original_files: list[Path] = []
        self._anon_files: list[Path] = []
        self._file_pairs: list[tuple[Path, Path]] = []
        self._current_index: int = 0

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header
        header = QHBoxLayout()
        self.lbl_title = QLabel("Comparison View")
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(self.lbl_title)
        header.addStretch()
        self.lbl_pair_info = QLabel("")
        self.lbl_pair_info.setStyleSheet("color: #666;")
        header.addWidget(self.lbl_pair_info)
        layout.addLayout(header)

        # Tabs for image vs tag comparison
        self.tabs = QTabWidget()

        # ── Tab 1: Image comparison ──
        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)

        image_splitter = QSplitter(Qt.Horizontal)

        # Left: Original
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        lbl_orig = QLabel("ORIGINAL")
        lbl_orig.setStyleSheet(
            "font-weight: bold; color: #dc3545; padding: 4px; "
            "background: #fff0f0; border-radius: 3px;"
        )
        lbl_orig.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(lbl_orig)
        self.viewer_original = ImageViewer()
        left_layout.addWidget(self.viewer_original)
        image_splitter.addWidget(left_container)

        # Right: Anonymized
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        lbl_anon = QLabel("ANONYMIZED")
        lbl_anon.setStyleSheet(
            "font-weight: bold; color: #28a745; padding: 4px; "
            "background: #f0fff0; border-radius: 3px;"
        )
        lbl_anon.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(lbl_anon)
        self.viewer_anonymized = ImageViewer()
        right_layout.addWidget(self.viewer_anonymized)
        image_splitter.addWidget(right_container)

        image_layout.addWidget(image_splitter)
        self.tabs.addTab(image_tab, "Images")

        # ── Tab 2: Tag diff ──
        tag_tab = QWidget()
        tag_layout = QVBoxLayout(tag_tab)

        self.tag_diff_tree = QTreeWidget()
        self.tag_diff_tree.setHeaderLabels([
            "Tag", "Name", "Original Value", "Anonymized Value", "Action",
        ])
        self.tag_diff_tree.setAlternatingRowColors(True)
        self.tag_diff_tree.setRootIsDecorated(False)
        header = self.tag_diff_tree.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 120)
        header.resizeSection(1, 180)
        header.resizeSection(2, 220)
        header.resizeSection(3, 220)
        header.resizeSection(4, 60)
        tag_layout.addWidget(self.tag_diff_tree)

        self.lbl_diff_summary = QLabel("")
        self.lbl_diff_summary.setStyleSheet("color: #666; font-size: 11px;")
        tag_layout.addWidget(self.lbl_diff_summary)

        self.tabs.addTab(tag_tab, "Tag Diff")
        layout.addWidget(self.tabs, stretch=1)

        # File navigation
        nav_row = QHBoxLayout()
        self.btn_prev = QPushButton("< Prev")
        self.btn_prev.clicked.connect(self._go_prev)
        nav_row.addWidget(self.btn_prev)

        self.scrollbar = QScrollBar(Qt.Horizontal)
        self.scrollbar.setRange(0, 0)
        self.scrollbar.valueChanged.connect(self._on_scroll)
        nav_row.addWidget(self.scrollbar)

        self.btn_next = QPushButton("Next >")
        self.btn_next.clicked.connect(self._go_next)
        nav_row.addWidget(self.btn_next)

        self.lbl_nav = QLabel("0 / 0")
        self.lbl_nav.setFixedWidth(70)
        nav_row.addWidget(self.lbl_nav)
        layout.addLayout(nav_row)

    # ── Public API ────────────────────────────────────────────

    def load_comparison(
        self,
        source_dir: Path,
        output_dir: Path,
        original_files: list[Path],
        anon_files: list[Path],
    ):
        """Load file pairs for comparison.

        Matches original → anonymized by relative path within their
        respective root directories.

        Args:
            source_dir: Root of the original DICOM files.
            output_dir: Root of the anonymized DICOM files.
            original_files: List of original DICOM file paths.
            anon_files: List of anonymized DICOM file paths.
        """
        # Build lookup from relative path → absolute path
        anon_lookup: dict[str, Path] = {}
        for f in anon_files:
            try:
                rel = str(f.relative_to(output_dir))
                anon_lookup[rel] = f
            except ValueError:
                continue

        self._file_pairs = []
        for orig in original_files:
            try:
                rel = str(orig.relative_to(source_dir))
                if rel in anon_lookup:
                    self._file_pairs.append((orig, anon_lookup[rel]))
            except ValueError:
                continue

        if self._file_pairs:
            self.scrollbar.setRange(0, len(self._file_pairs) - 1)
            self.scrollbar.setValue(0)
            self.lbl_pair_info.setText(f"{len(self._file_pairs)} file pairs matched")
            self._load_pair(0)
        else:
            self.lbl_pair_info.setText("No matching file pairs found")
            self.lbl_nav.setText("0 / 0")

    # ── Internal ──────────────────────────────────────────────

    def _load_pair(self, index: int):
        """Load and display the file pair at the given index."""
        if not 0 <= index < len(self._file_pairs):
            return

        self._current_index = index
        orig_path, anon_path = self._file_pairs[index]

        # Load images
        self.viewer_original.load_single(orig_path)
        self.viewer_anonymized.load_single(anon_path)

        # Load tag diff
        self._load_tag_diff(orig_path, anon_path)

        self.lbl_nav.setText(f"{index + 1} / {len(self._file_pairs)}")

    def _load_tag_diff(self, orig_path: Path, anon_path: Path):
        """Build the tag diff tree from two DICOM files."""
        self.tag_diff_tree.clear()

        try:
            ds_orig = pydicom.dcmread(str(orig_path), force=True)
            ds_anon = pydicom.dcmread(str(anon_path), force=True)
        except Exception as e:
            self.lbl_diff_summary.setText(f"Error loading files: {e}")
            return

        modified = 0
        removed = 0
        unchanged = 0

        # Collect all tags from both datasets
        all_tags = set()
        for elem in ds_orig:
            all_tags.add(elem.tag)
        for elem in ds_anon:
            all_tags.add(elem.tag)

        for tag in sorted(all_tags):
            tag_str = f"({tag.group:04X},{tag.element:04X})"
            tag_tuple = (tag.group, tag.element)

            in_orig = tag in ds_orig
            in_anon = tag in ds_anon

            if in_orig:
                elem_orig = ds_orig[tag]
                name = elem_orig.keyword or elem_orig.name or "Unknown"
                orig_val = self._safe_value(elem_orig)
            else:
                name = ds_anon[tag].keyword if in_anon else "Unknown"
                orig_val = "<not present>"

            anon_val = self._safe_value(ds_anon[tag]) if in_anon else "<removed>"

            profile = TAG_PROFILE.get(tag_tuple)
            action_str = profile[0].value if profile else ""

            item = QTreeWidgetItem([tag_str, name, orig_val, anon_val, action_str])

            # Color based on change status
            if in_orig and not in_anon:
                # Tag was removed
                removed += 1
                for col in range(5):
                    item.setBackground(col, _RED_BG)
                item.setForeground(2, _RED_FG)
                item.setText(3, "<REMOVED>")
                item.setForeground(3, _GREEN_FG)
            elif in_orig and in_anon and orig_val != anon_val:
                # Tag was modified
                modified += 1
                for col in range(5):
                    item.setBackground(col, _YELLOW_BG)
                item.setForeground(2, _RED_FG)
                item.setForeground(3, _GREEN_FG)
            elif not in_orig and in_anon:
                # Tag was added (unusual but possible with file_meta updates)
                for col in range(5):
                    item.setBackground(col, _GREEN_BG)
            else:
                unchanged += 1

            self.tag_diff_tree.addTopLevelItem(item)

        self.lbl_diff_summary.setText(
            f"{modified} modified | {removed} removed | {unchanged} unchanged"
        )

    def _safe_value(self, elem) -> str:
        """Safely extract a displayable string from a DICOM element."""
        try:
            val = str(elem.value)
            return val[:120] + "..." if len(val) > 120 else val
        except Exception:
            return "<cannot display>"

    def _go_prev(self):
        if self._current_index > 0:
            self.scrollbar.setValue(self._current_index - 1)

    def _go_next(self):
        if self._current_index < len(self._file_pairs) - 1:
            self.scrollbar.setValue(self._current_index + 1)

    def _on_scroll(self, value: int):
        self._load_pair(value)
