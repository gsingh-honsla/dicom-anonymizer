"""Pixel-level PHI scrubbing: OCR burned-in text detection and face detection.

Detects and redacts:
1. Burned-in text (patient names, MRNs, dates) via easyocr
2. Faces in applicable modalities via OpenCV Haar cascade
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

try:
    import easyocr
    _HAS_EASYOCR = True
except ImportError:
    _HAS_EASYOCR = False

from pydicom.dataset import Dataset


# Default Haar cascade path — checks PyInstaller bundle first, then dev layout
def _find_cascade() -> Path:
    """Locate the Haar cascade model file."""
    # PyInstaller bundle path
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "CaseAnonymizer-R" / "bin" / "models" / "RGB-FaceDetection" / "haarcascade_frontalface_alt.xml"
        if p.exists():
            return p

    # Development layout (relative to this source file)
    p = (Path(__file__).resolve().parent.parent.parent
         / "CaseAnonymizer-R" / "bin" / "models" / "RGB-FaceDetection"
         / "haarcascade_frontalface_alt.xml")
    return p


_DEFAULT_CASCADE = _find_cascade()

# Modalities where face detection is relevant
_FACE_MODALITIES = {"CT", "MR", "PT", "NM", "XA"}

# Modalities where burned-in text is common
_TEXT_MODALITIES = {"US", "CR", "DX", "XA", "RF", "MG", "SC", "OT"}

# Padding (pixels) around detected regions for redaction
_REDACT_PADDING = 5


@dataclass
class DetectedRegion:
    """A rectangular region detected as containing PHI."""

    x: int
    y: int
    width: int
    height: int
    category: str           # "text" or "face"
    confidence: float       # 0.0 - 1.0
    detail: str = ""        # Detected text content or detection info


@dataclass
class ScrubResult:
    """Result of pixel scrubbing a single DICOM image."""

    regions_found: list[DetectedRegion] = field(default_factory=list)
    regions_redacted: int = 0
    text_detected: list[str] = field(default_factory=list)
    faces_detected: int = 0
    phi_text_matches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scrubbed: bool = False    # True if any pixels were modified

    @property
    def has_detections(self) -> bool:
        return len(self.regions_found) > 0


# Lazy-initialized singleton reader
_ocr_reader: easyocr.Reader | None = None


def _get_ocr_reader() -> easyocr.Reader:
    """Get or create the easyocr reader (lazy init, heavy on first call)."""
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _ocr_reader


def _pixels_to_uint8(pixels: np.ndarray) -> np.ndarray:
    """Convert raw DICOM pixels to uint8 for OCR/face detection.

    Applies window/level normalization to map the full dynamic range
    to 0-255.
    """
    pmin = float(pixels.min())
    pmax = float(pixels.max())
    if pmax == pmin:
        return np.zeros(pixels.shape[:2], dtype=np.uint8)

    normalized = (pixels.astype(np.float64) - pmin) / (pmax - pmin) * 255
    return normalized.astype(np.uint8)


def _build_phi_patterns(known_phi: dict[str, str]) -> list[re.Pattern]:
    """Build regex patterns from known PHI values for text matching."""
    patterns = []
    for tag_name, value in known_phi.items():
        cleaned = value.strip()
        if not cleaned or len(cleaned) < 3:
            continue
        # Split DICOM name format and match individual components
        for part in re.split(r"[\^\s,]+", cleaned):
            part = part.strip()
            if len(part) >= 3:
                patterns.append(re.compile(re.escape(part), re.IGNORECASE))
    return patterns


def check_availability() -> dict[str, bool]:
    """Check which pixel scrubbing features are available.

    Returns:
        Dict with 'ocr' and 'face_detection' availability flags.
    """
    cascade_exists = _DEFAULT_CASCADE.exists() if _DEFAULT_CASCADE else False
    return {
        "ocr": _HAS_EASYOCR,
        "face_detection": _HAS_CV2 and cascade_exists,
        "opencv": _HAS_CV2,
        "cascade_path": str(_DEFAULT_CASCADE) if cascade_exists else None,
    }


def scrub_dataset(
    ds: Dataset,
    known_phi: dict[str, str] | None = None,
    detect_text: bool = True,
    detect_faces: bool = True,
    redact: bool = True,
    cascade_path: Path | None = None,
) -> ScrubResult:
    """Scan and optionally redact PHI from DICOM pixel data.

    Args:
        ds: pydicom Dataset with pixel data.
        known_phi: Dict of tag_name -> original_value for cross-referencing
                   detected text against actual patient PHI.
        detect_text: Run OCR text detection.
        detect_faces: Run face detection.
        redact: If True, black out detected regions in the pixel data.
                If False, only detect (dry run).
        cascade_path: Override path to Haar cascade XML.

    Returns:
        ScrubResult with detection details.
    """
    result = ScrubResult()

    if not hasattr(ds, "pixel_array"):
        result.warnings.append("No pixel data in dataset")
        return result

    try:
        pixels = ds.pixel_array.copy()
    except Exception as e:
        result.warnings.append(f"Cannot read pixel data: {e}")
        return result

    # Apply rescale for proper visualization
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    if slope != 1 or intercept != 0:
        pixels = pixels.astype(np.float64) * slope + intercept

    # Handle multi-frame: process each frame
    modality = str(getattr(ds, "Modality", ""))
    frames = []
    if pixels.ndim == 3 and getattr(ds, "NumberOfFrames", 1) > 1:
        frames = [pixels[i] for i in range(pixels.shape[0])]
    elif pixels.ndim == 2:
        frames = [pixels]
    elif pixels.ndim == 3 and pixels.shape[2] in (3, 4):
        # RGB image
        frames = [pixels]
    else:
        frames = [pixels]

    phi_patterns = _build_phi_patterns(known_phi or {})

    for frame_idx, frame in enumerate(frames):
        img_uint8 = _pixels_to_uint8(frame)

        # ── OCR text detection ──
        if detect_text and _HAS_EASYOCR:
            _detect_text_regions(
                img_uint8, result, phi_patterns, frame_idx, known_phi or {}
            )

        # ── Face detection ──
        if detect_faces and _HAS_CV2:
            _detect_face_regions(
                img_uint8, result, modality, frame_idx,
                cascade_path or _DEFAULT_CASCADE,
            )

    # ── Redact detected regions ──
    if redact and result.regions_found:
        _apply_redaction(ds, result)

    return result


def _detect_text_regions(
    img: np.ndarray,
    result: ScrubResult,
    phi_patterns: list[re.Pattern],
    frame_idx: int,
    known_phi: dict[str, str],
):
    """Run OCR and cross-reference against known PHI."""
    try:
        reader = _get_ocr_reader()
        detections = reader.readtext(img, detail=1, paragraph=False)
    except Exception as e:
        result.warnings.append(f"OCR error on frame {frame_idx}: {e}")
        return

    for bbox, text, confidence in detections:
        if confidence < 0.3:
            continue

        result.text_detected.append(text)

        # Cross-reference against known PHI
        is_phi = False
        for pattern in phi_patterns:
            if pattern.search(text):
                is_phi = True
                result.phi_text_matches.append(text)
                break

        if is_phi:
            # Convert bbox to rectangle
            xs = [int(pt[0]) for pt in bbox]
            ys = [int(pt[1]) for pt in bbox]
            x = max(0, min(xs) - _REDACT_PADDING)
            y = max(0, min(ys) - _REDACT_PADDING)
            w = max(xs) - min(xs) + 2 * _REDACT_PADDING
            h = max(ys) - min(ys) + 2 * _REDACT_PADDING

            result.regions_found.append(DetectedRegion(
                x=x, y=y, width=w, height=h,
                category="text",
                confidence=confidence,
                detail=text,
            ))


def _detect_face_regions(
    img: np.ndarray,
    result: ScrubResult,
    modality: str,
    frame_idx: int,
    cascade_path: Path,
):
    """Run Haar cascade face detection on applicable modalities."""
    if modality and modality not in _FACE_MODALITIES:
        return

    if not cascade_path.exists():
        result.warnings.append(f"Haar cascade not found at {cascade_path}")
        return

    try:
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            result.warnings.append("Failed to load Haar cascade classifier")
            return

        # Ensure grayscale
        if img.ndim == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        for (x, y, w, h) in faces:
            result.faces_detected += 1
            result.regions_found.append(DetectedRegion(
                x=max(0, x - _REDACT_PADDING),
                y=max(0, y - _REDACT_PADDING),
                width=w + 2 * _REDACT_PADDING,
                height=h + 2 * _REDACT_PADDING,
                category="face",
                confidence=1.0,
                detail=f"Face detected in frame {frame_idx}",
            ))

    except Exception as e:
        result.warnings.append(f"Face detection error on frame {frame_idx}: {e}")


def _apply_redaction(ds: Dataset, result: ScrubResult):
    """Black out all detected regions in the pixel data."""
    try:
        pixels = ds.pixel_array
    except Exception:
        return

    modified = pixels.copy()

    for region in result.regions_found:
        y1 = max(0, region.y)
        y2 = min(modified.shape[-2] if modified.ndim >= 2 else modified.shape[0],
                 region.y + region.height)
        x1 = max(0, region.x)
        x2 = min(modified.shape[-1] if modified.ndim >= 2 else modified.shape[1],
                 region.x + region.width)

        if modified.ndim == 2:
            modified[y1:y2, x1:x2] = 0
        elif modified.ndim == 3:
            modified[:, y1:y2, x1:x2] = 0

        result.regions_redacted += 1

    # Write modified pixels back to the dataset
    ds.PixelData = modified.tobytes()
    result.scrubbed = True
