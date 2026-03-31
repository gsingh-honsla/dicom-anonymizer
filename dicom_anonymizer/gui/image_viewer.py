"""DICOM image viewer widget with window/level controls and series scrolling."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QScrollBar,
    QGroupBox,
)

import pydicom


def _apply_window_level(pixels: np.ndarray, window: float, level: float) -> np.ndarray:
    """Apply window/level transform to raw pixel data.

    Maps a range of pixel values to 0-255 for display.

    Args:
        pixels: Raw pixel array (any dtype).
        window: Width of the display range.
        level: Center of the display range.

    Returns:
        uint8 array suitable for display.
    """
    lower = level - window / 2
    upper = level + window / 2
    result = np.clip((pixels.astype(np.float64) - lower) / max(window, 1) * 255, 0, 255)
    return result.astype(np.uint8)


def _numpy_to_qimage(arr: np.ndarray) -> QImage:
    """Convert a 2D uint8 numpy array to a QImage."""
    if arr.ndim == 2:
        h, w = arr.shape
        bytes_per_line = w
        return QImage(arr.data, w, h, bytes_per_line, QImage.Format_Grayscale8)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        h, w, _ = arr.shape
        bytes_per_line = 3 * w
        return QImage(arr.data, w, h, bytes_per_line, QImage.Format_RGB888)
    else:
        # Fallback: take first channel
        h, w = arr.shape[:2]
        flat = arr.reshape(h, w) if arr.ndim == 2 else arr[:, :, 0]
        return QImage(flat.data, w, h, w, QImage.Format_Grayscale8)


class ImageViewer(QWidget):
    """DICOM image viewer with window/level sliders and series scrolling.

    Signals:
        file_changed(int): Emitted when the displayed file index changes.
    """

    file_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._files: list[Path] = []
        self._current_index: int = 0
        self._pixels: np.ndarray | None = None
        self._ds: pydicom.Dataset | None = None
        self._window: float = 256
        self._level: float = 128

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Image display
        self.lbl_image = QLabel("No image loaded")
        self.lbl_image.setAlignment(Qt.AlignCenter)
        self.lbl_image.setMinimumSize(256, 256)
        self.lbl_image.setStyleSheet("background: #000; color: #666;")
        layout.addWidget(self.lbl_image, stretch=1)

        # Info label
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.lbl_info)

        # Window/Level controls
        wl_group = QGroupBox("Window / Level")
        wl_layout = QVBoxLayout(wl_group)

        # Window slider
        row_w = QHBoxLayout()
        row_w.addWidget(QLabel("W:"))
        self.slider_window = QSlider(Qt.Horizontal)
        self.slider_window.setRange(1, 4096)
        self.slider_window.setValue(256)
        self.slider_window.valueChanged.connect(self._on_window_changed)
        row_w.addWidget(self.slider_window)
        self.lbl_window = QLabel("256")
        self.lbl_window.setFixedWidth(50)
        row_w.addWidget(self.lbl_window)
        wl_layout.addLayout(row_w)

        # Level slider
        row_l = QHBoxLayout()
        row_l.addWidget(QLabel("L:"))
        self.slider_level = QSlider(Qt.Horizontal)
        self.slider_level.setRange(-1024, 4096)
        self.slider_level.setValue(128)
        self.slider_level.valueChanged.connect(self._on_level_changed)
        row_l.addWidget(self.slider_level)
        self.lbl_level = QLabel("128")
        self.lbl_level.setFixedWidth(50)
        row_l.addWidget(self.lbl_level)
        wl_layout.addLayout(row_l)

        layout.addWidget(wl_group)

        # Series scroll bar
        scroll_row = QHBoxLayout()
        scroll_row.addWidget(QLabel("Slice:"))
        self.scrollbar = QScrollBar(Qt.Horizontal)
        self.scrollbar.setRange(0, 0)
        self.scrollbar.valueChanged.connect(self._on_scroll)
        scroll_row.addWidget(self.scrollbar)
        self.lbl_slice = QLabel("0 / 0")
        self.lbl_slice.setFixedWidth(70)
        scroll_row.addWidget(self.lbl_slice)
        layout.addLayout(scroll_row)

    # ── Public API ────────────────────────────────────────────

    def load_files(self, files: list[Path]):
        """Load a list of DICOM file paths for viewing.

        Args:
            files: List of DICOM file paths (sorted order is preserved).
        """
        self._files = list(files)
        if self._files:
            self.scrollbar.setRange(0, len(self._files) - 1)
            self.scrollbar.setValue(0)
            self._load_index(0)
        else:
            self._pixels = None
            self._ds = None
            self.lbl_image.setText("No image loaded")
            self.lbl_info.setText("")
            self.scrollbar.setRange(0, 0)
            self.lbl_slice.setText("0 / 0")

    def load_single(self, file_path: Path):
        """Load a single DICOM file for viewing."""
        self.load_files([file_path])

    def current_dataset(self) -> pydicom.Dataset | None:
        """Return the currently displayed DICOM dataset."""
        return self._ds

    # ── Internal ──────────────────────────────────────────────

    def _load_index(self, index: int):
        """Load and display the file at the given index."""
        if not 0 <= index < len(self._files):
            return

        self._current_index = index
        file_path = self._files[index]

        try:
            ds = pydicom.dcmread(str(file_path), force=True)
            self._ds = ds

            if hasattr(ds, "pixel_array"):
                pixels = ds.pixel_array

                # Apply rescale slope/intercept if present
                slope = float(getattr(ds, "RescaleSlope", 1))
                intercept = float(getattr(ds, "RescaleIntercept", 0))
                pixels = pixels.astype(np.float64) * slope + intercept

                self._pixels = pixels

                # Auto window/level on first load from pixel stats
                pmin, pmax = float(pixels.min()), float(pixels.max())
                auto_window = pmax - pmin
                auto_level = (pmax + pmin) / 2

                self.slider_window.blockSignals(True)
                self.slider_level.blockSignals(True)
                self.slider_window.setRange(1, max(int(auto_window * 2), 4096))
                self.slider_window.setValue(int(auto_window))
                self.slider_level.setRange(int(pmin), int(pmax))
                self.slider_level.setValue(int(auto_level))
                self.slider_window.blockSignals(False)
                self.slider_level.blockSignals(False)

                self._window = auto_window
                self._level = auto_level
                self.lbl_window.setText(str(int(auto_window)))
                self.lbl_level.setText(str(int(auto_level)))

                self._update_display()

                # Info
                rows = getattr(ds, "Rows", "?")
                cols = getattr(ds, "Columns", "?")
                modality = getattr(ds, "Modality", "?")
                bits = getattr(ds, "BitsStored", "?")
                self.lbl_info.setText(
                    f"{modality} | {cols}x{rows} | {bits}-bit | {file_path.name}"
                )
            else:
                self._pixels = None
                self.lbl_image.setText("No pixel data")
                self.lbl_info.setText(file_path.name)

        except Exception as e:
            self._pixels = None
            self._ds = None
            self.lbl_image.setText(f"Error: {e}")
            self.lbl_info.setText(file_path.name)

        self.lbl_slice.setText(f"{index + 1} / {len(self._files)}")
        self.file_changed.emit(index)

    def _update_display(self):
        """Re-render the current pixel data with current window/level."""
        if self._pixels is None:
            return

        display = _apply_window_level(self._pixels, self._window, self._level)

        # Handle multi-frame: take first frame for 3D arrays
        if display.ndim == 3 and display.shape[2] not in (3, 4):
            display = display[0] if display.shape[0] > 1 else display.squeeze()

        # Ensure contiguous for QImage
        display = np.ascontiguousarray(display)
        qimg = _numpy_to_qimage(display)

        # Scale to fit the label while maintaining aspect ratio
        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(
            self.lbl_image.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.lbl_image.setPixmap(scaled)

    def _on_window_changed(self, value: int):
        self._window = float(value)
        self.lbl_window.setText(str(value))
        self._update_display()

    def _on_level_changed(self, value: int):
        self._level = float(value)
        self.lbl_level.setText(str(value))
        self._update_display()

    def _on_scroll(self, value: int):
        self._load_index(value)

    def resizeEvent(self, event):
        """Re-render on resize to fill available space."""
        super().resizeEvent(event)
        self._update_display()
