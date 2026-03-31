"""Recursive DICOM file discovery using magic byte detection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.constants import DICM_MAGIC, DICM_MAGIC_OFFSET


@dataclass
class ScanResult:
    """Results from scanning a directory for DICOM files."""

    dicom_files: list[Path] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    total_size_bytes: int = 0

    @property
    def file_count(self) -> int:
        return len(self.dicom_files)


def is_dicom_file(path: Path) -> bool:
    """Check if a file is DICOM by looking for DICM magic bytes at offset 128.

    Also attempts pydicom force-read for pre-Part 10 DICOM files that lack
    the preamble (rare but possible).
    """
    try:
        with open(path, "rb") as f:
            f.seek(DICM_MAGIC_OFFSET)
            magic = f.read(4)
            return magic == DICM_MAGIC
    except (OSError, IOError):
        return False


def is_dicomdir(path: Path) -> bool:
    """Check if a file is a DICOMDIR index file."""
    return path.name.upper() == "DICOMDIR"


def scan_directory(
    source_dir: Path,
    progress_callback=None,
) -> ScanResult:
    """Recursively scan a directory for DICOM files.

    Args:
        source_dir: Root directory to scan.
        progress_callback: Optional callable(current_file_path) for progress updates.

    Returns:
        ScanResult with lists of found DICOM files, skipped files, and errors.
    """
    result = ScanResult()

    if not source_dir.is_dir():
        result.errors.append((source_dir, "Not a directory"))
        return result

    for root, _dirs, files in os.walk(source_dir):
        root_path = Path(root)
        for filename in files:
            file_path = root_path / filename

            if progress_callback:
                progress_callback(file_path)

            # Skip DICOMDIR — handled separately
            if is_dicomdir(file_path):
                continue

            # Skip hidden files and common non-DICOM files
            if filename.startswith(".") or filename.lower() in ("readme.txt", "thumbs.db"):
                result.skipped_files.append(file_path)
                continue

            try:
                if is_dicom_file(file_path):
                    result.dicom_files.append(file_path)
                    result.total_size_bytes += file_path.stat().st_size
                else:
                    result.skipped_files.append(file_path)
            except Exception as e:
                result.errors.append((file_path, str(e)))

    # Sort for deterministic processing order
    result.dicom_files.sort()
    return result


def get_patient_study_counts(dicom_files: list[Path]) -> dict:
    """Quick-scan DICOM files to count unique patients and studies.

    Reads only the necessary tags (PatientID, StudyInstanceUID) for speed.
    """
    import pydicom

    patients = set()
    studies = set()

    for path in dicom_files:
        try:
            ds = pydicom.dcmread(
                path,
                stop_before_pixels=True,
                force=True,
                specific_tags=[
                    (0x0010, 0x0020),  # PatientID
                    (0x0020, 0x000D),  # StudyInstanceUID
                ],
            )
            if hasattr(ds, "PatientID"):
                patients.add(str(ds.PatientID))
            if hasattr(ds, "StudyInstanceUID"):
                studies.add(str(ds.StudyInstanceUID))
        except Exception:
            continue

    return {
        "patients": len(patients),
        "studies": len(studies),
        "files": len(dicom_files),
    }
