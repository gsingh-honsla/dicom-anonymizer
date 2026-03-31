"""Anonymized DICOM output writer.

Writes anonymized DICOM datasets to an output directory,
preserving the relative directory structure from the source.
"""

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
    Saves as Explicit VR Little Endian (uncompressed) for maximum compatibility.

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

    # Ensure file meta info exists
    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        ds.file_meta = pydicom.dataset.FileMetaDataset()

    # Set transfer syntax to Explicit VR Little Endian
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = getattr(
        ds, "SOPClassUID", "1.2.840.10008.5.1.4.1.1.2"
    )
    if hasattr(ds, "SOPInstanceUID"):
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # Ensure preamble
    ds.preamble = b"\x00" * 128

    # Write
    ds.save_as(str(output_path), write_like_original=False)

    # Compute hash of output file
    file_hash = compute_file_hash(output_path)

    return output_path, file_hash
