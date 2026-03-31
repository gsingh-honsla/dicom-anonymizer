"""DICOMDIR parsing and regeneration for anonymized output.

The original DICOMDIR should never be copied — it references original UIDs
and paths. This module regenerates a new DICOMDIR from the anonymized output
files so the media can be imported into PACS systems.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pydicom
from pydicom.fileset import FileSet

from .scanner import scan_directory, is_dicomdir


# Tags that FileSet requires but anonymization may have zeroed.
_REQUIRED_PLACEHOLDERS = {
    "StudyDate": "19000101",
    "StudyTime": "000000",
    "SeriesDate": "19000101",
    "SeriesTime": "000000",
    "ContentDate": "19000101",
    "ContentTime": "000000",
    "AcquisitionDate": "19000101",
    "AcquisitionTime": "000000",
}


def has_dicomdir(source_dir: Path) -> bool:
    """Check if the source directory contains a DICOMDIR file."""
    dicomdir_path = source_dir / "DICOMDIR"
    return dicomdir_path.exists() and is_dicomdir(dicomdir_path)


def parse_dicomdir(source_dir: Path) -> dict:
    """Parse the original DICOMDIR for summary information.

    Args:
        source_dir: Directory containing the DICOMDIR.

    Returns:
        Dict with patient/study/series/image counts from the DICOMDIR.
    """
    dicomdir_path = source_dir / "DICOMDIR"
    if not dicomdir_path.exists():
        return {"exists": False}

    try:
        ds = pydicom.dcmread(str(dicomdir_path))
        records = ds.DirectoryRecordSequence

        counts = {}
        for r in records:
            rtype = r.DirectoryRecordType
            counts[rtype] = counts.get(rtype, 0) + 1

        return {
            "exists": True,
            "path": str(dicomdir_path),
            "patients": counts.get("PATIENT", 0),
            "studies": counts.get("STUDY", 0),
            "series": counts.get("SERIES", 0),
            "images": counts.get("IMAGE", 0),
            "total_records": len(records),
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}


def _fill_required_placeholders(ds: pydicom.Dataset):
    """Fill placeholder values for tags FileSet requires.

    Modifies dataset in-place. Only used on temporary copies for
    DICOMDIR generation — never on the actual output files.
    """
    for attr_name, placeholder in _REQUIRED_PLACEHOLDERS.items():
        if hasattr(ds, attr_name):
            val = getattr(ds, attr_name)
            if val is None or (isinstance(val, str) and not val.strip()):
                setattr(ds, attr_name, placeholder)


def generate_dicomdir(
    output_dir: Path,
    progress_callback: callable | None = None,
) -> Path:
    """Generate a new DICOMDIR from anonymized DICOM files.

    Uses a temporary staging directory to build the FileSet, then
    copies only the DICOMDIR file back to the output directory.
    This avoids FileSet.write() overwriting our anonymized files.

    Args:
        output_dir: Root directory of anonymized DICOM files.
        progress_callback: Optional callback(current, total, message).

    Returns:
        Path to the generated DICOMDIR file.

    Raises:
        RuntimeError: If no DICOM files found or generation fails.
    """
    scan = scan_directory(output_dir)
    if scan.file_count == 0:
        raise RuntimeError("No DICOM files found in output directory")

    # Build FileSet in a temp directory to avoid overwriting output files
    staging_dir = Path(tempfile.mkdtemp(prefix="dicomdir_staging_"))

    try:
        fs = FileSet()
        total = scan.file_count
        added = 0
        errors = []

        for i, file_path in enumerate(scan.dicom_files):
            if progress_callback:
                progress_callback(i + 1, total, file_path.name)

            try:
                ds = pydicom.dcmread(str(file_path))
                _fill_required_placeholders(ds)
                fs.add(ds)
                added += 1
            except Exception as e:
                errors.append((file_path.name, str(e)))

        if added == 0:
            raise RuntimeError(
                f"Could not add any files to DICOMDIR. "
                f"Errors: {errors[:5]}"
            )

        # Write FileSet to staging directory
        fs.write(staging_dir)

        # Copy only the DICOMDIR file to the output directory
        staged_dicomdir = staging_dir / "DICOMDIR"
        output_dicomdir = output_dir / "DICOMDIR"

        if staged_dicomdir.exists():
            shutil.copy2(str(staged_dicomdir), str(output_dicomdir))
        else:
            raise RuntimeError("FileSet.write() did not produce a DICOMDIR file")

        return output_dicomdir

    finally:
        # Clean up staging directory
        shutil.rmtree(staging_dir, ignore_errors=True)
