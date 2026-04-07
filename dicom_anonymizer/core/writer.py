"""Anonymized DICOM output writer.

Writes anonymized DICOM datasets to an output directory,
preserving the relative directory structure from the source.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import ExplicitVRLittleEndian


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def write_anonymized(
    ds: Dataset,
    source_path: Path,
    source_root: Path,
    output_root: Path,
) -> tuple[Path, str]:
    """Write an anonymized DICOM dataset to the output directory.

    Preserves the relative directory structure from source_root.
    Uses write_like_original=True to preserve the original transfer syntax
    and byte-level encoding of pixel data — only the anonymized tag values
    change.  This ensures maximum viewer compatibility (Horos, OsiriX, etc.).

    Args:
        ds: Anonymized pydicom Dataset.
        source_path: Original file path.
        source_root: Root of the source directory tree.
        output_root: Root of the output directory tree.

    Returns:
        Tuple of (output_path, sha256_hash).
    """
    # Compute relative path from source root
    relative = source_path.relative_to(source_root)
    output_path = output_root / relative

    # Create parent directories
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure file meta info exists with valid entries
    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        ds.file_meta = pydicom.dataset.FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    # Keep the original TransferSyntaxUID — do NOT override it.
    # Changing the transfer syntax without re-encoding pixel data
    # produces corrupt files that viewers cannot read.

    # Update MediaStorage UIDs to match the (possibly replaced) dataset UIDs
    if hasattr(ds, "SOPClassUID"):
        ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    if hasattr(ds, "SOPInstanceUID"):
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # Ensure preamble exists (required for Part 10 DICOM)
    if not hasattr(ds, "preamble") or ds.preamble is None:
        ds.preamble = b"\x00" * 128

    # Write with original encoding preserved — only anonymized tag values change
    ds.save_as(str(output_path), write_like_original=True)

    # Compute hash of output file
    file_hash = compute_file_hash(output_path)

    return output_path, file_hash
