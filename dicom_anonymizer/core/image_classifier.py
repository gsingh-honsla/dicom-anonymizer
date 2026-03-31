"""Classify DICOM images by burned-in PHI risk level.

Identifies dose reports, protocol summaries, scout localizers, and
other secondary capture images that typically contain patient
demographics rendered directly into the pixel data.

These images cannot be safely anonymized by tag stripping alone —
they must be either quarantined (excluded) or pixel-scrubbed.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass

from pydicom.dataset import Dataset


class PHIRisk(str, Enum):
    """Risk level for burned-in PHI in pixel data."""

    SAFE = "safe"              # Normal imaging — no burned-in PHI expected
    SUSPECT = "suspect"        # May contain burned-in PHI (check BurnedInAnnotation)
    DANGEROUS = "dangerous"    # Almost certainly contains burned-in PHI


# Secondary Capture SOP Class UIDs
_SC_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.7",      # Secondary Capture Image Storage
    "1.2.840.10008.5.1.4.1.1.7.1",    # Multi-frame Single Bit SC
    "1.2.840.10008.5.1.4.1.1.7.2",    # Multi-frame Grayscale Byte SC
    "1.2.840.10008.5.1.4.1.1.7.3",    # Multi-frame Grayscale Word SC
    "1.2.840.10008.5.1.4.1.1.7.4",    # Multi-frame True Color SC
    "1.2.840.10008.5.1.4.1.1.88.11",  # Basic Text SR (structured report)
    "1.2.840.10008.5.1.4.1.1.88.22",  # Enhanced SR
    "1.2.840.10008.5.1.4.1.1.88.33",  # Comprehensive SR
}

# Modalities where burned-in text is very common
_HIGH_RISK_MODALITIES = {"SC", "OT"}

# Modalities where burned-in text sometimes appears
_MEDIUM_RISK_MODALITIES = {"US", "CR", "DX", "XA", "RF", "ES", "MG"}


@dataclass
class ImageClassification:
    """Classification result for a single DICOM image."""

    risk: PHIRisk
    reason: str
    is_secondary_capture: bool = False
    is_derived: bool = False
    has_burned_annotation: bool = False
    modality: str = ""
    image_type: str = ""


def classify_dataset(ds: Dataset) -> ImageClassification:
    """Classify a DICOM dataset by its risk of containing burned-in PHI.

    Args:
        ds: pydicom Dataset to classify.

    Returns:
        ImageClassification with risk level and reasoning.
    """
    modality = str(getattr(ds, "Modality", ""))
    sop_uid = str(getattr(ds, "SOPClassUID", ""))
    image_type = [s.upper() for s in getattr(ds, "ImageType", [])]
    burned = str(getattr(ds, "BurnedInAnnotation", "")).upper()
    conv_type = str(getattr(ds, "ConversionType", "")).upper()

    is_sc = sop_uid in _SC_SOP_CLASSES
    is_derived = "DERIVED" in image_type
    is_secondary = "SECONDARY" in image_type
    has_burned = burned == "YES"
    image_type_str = "\\".join(image_type)

    # ── Definite dangerous: BurnedInAnnotation = YES ──
    if has_burned:
        return ImageClassification(
            risk=PHIRisk.DANGEROUS,
            reason="BurnedInAnnotation tag explicitly set to YES",
            is_secondary_capture=is_sc,
            is_derived=is_derived,
            has_burned_annotation=True,
            modality=modality,
            image_type=image_type_str,
        )

    # ── Secondary Capture + DERIVED/SECONDARY = dose report / screenshot ──
    if is_sc and is_derived and is_secondary:
        return ImageClassification(
            risk=PHIRisk.DANGEROUS,
            reason=f"Secondary Capture with DERIVED\\SECONDARY image type (dose report / protocol summary)",
            is_secondary_capture=True,
            is_derived=True,
            has_burned_annotation=False,
            modality=modality,
            image_type=image_type_str,
        )

    # ── Secondary Capture SOP class alone ──
    if is_sc:
        return ImageClassification(
            risk=PHIRisk.SUSPECT,
            reason=f"Secondary Capture SOP class — may contain burned-in text",
            is_secondary_capture=True,
            is_derived=is_derived,
            modality=modality,
            image_type=image_type_str,
        )

    # ── WSD (Workstation Display) conversion type ──
    if conv_type == "WSD":
        return ImageClassification(
            risk=PHIRisk.DANGEROUS,
            reason="ConversionType=WSD (Workstation Display screenshot)",
            is_secondary_capture=is_sc,
            is_derived=is_derived,
            modality=modality,
            image_type=image_type_str,
        )

    # ── High-risk modality ──
    if modality in _HIGH_RISK_MODALITIES:
        return ImageClassification(
            risk=PHIRisk.SUSPECT,
            reason=f"Modality {modality} frequently contains burned-in text",
            modality=modality,
            image_type=image_type_str,
        )

    # ── Medium-risk modality without BurnedInAnnotation ──
    if modality in _MEDIUM_RISK_MODALITIES:
        return ImageClassification(
            risk=PHIRisk.SUSPECT,
            reason=f"Modality {modality} sometimes contains burned-in text",
            modality=modality,
            image_type=image_type_str,
        )

    # ── Normal imaging ──
    return ImageClassification(
        risk=PHIRisk.SAFE,
        reason="Standard imaging modality, no burned-in PHI indicators",
        modality=modality,
        image_type=image_type_str,
    )


def classify_file(file_path) -> ImageClassification:
    """Classify a DICOM file by its risk of containing burned-in PHI."""
    import pydicom
    ds = pydicom.dcmread(str(file_path), force=True, specific_tags=[
        "Modality", "SOPClassUID", "ImageType",
        "BurnedInAnnotation", "ConversionType",
    ])
    return classify_dataset(ds)
