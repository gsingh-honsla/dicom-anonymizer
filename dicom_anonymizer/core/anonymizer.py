"""DICOM tag anonymization engine.

Applies the PS3.15 Annex E Basic Profile to strip/replace PHI from DICOM datasets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset

from .hash_map import HashMapper
from .tag_profile import TAG_PROFILE, PHI_SOURCE_TAGS, Action
from .uid_generator import UIDMap
from ..utils.config import AnonymizationConfig


@dataclass
class AnonymizationResult:
    """Result of anonymizing a single DICOM file."""

    source_path: Path
    tags_modified: list[str] = field(default_factory=list)
    tags_removed: list[str] = field(default_factory=list)
    uids_replaced: list[str] = field(default_factory=list)
    private_tags_removed: int = 0
    original_phi: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    success: bool = True
    error: str = ""


# Regex patterns that suggest PHI in "clean" (C action) tags
_PHI_PATTERNS = [
    re.compile(r"\b[A-Z][a-z]+\^[A-Z]", re.ASCII),  # Name format: Last^First
    re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),     # Phone numbers
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),              # SSN
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+"),  # Email
    re.compile(r"\b(MRN|mrn|ID|id)[\s:=-]*\d+\b"),    # Medical record numbers
]


def _looks_like_phi(value: str) -> bool:
    """Heuristic check if a string value might contain PHI."""
    return any(pattern.search(value) for pattern in _PHI_PATTERNS)


class Anonymizer:
    """Anonymizes DICOM datasets by applying the tag profile."""

    def __init__(self, config: AnonymizationConfig):
        self.config = config
        self.uid_map = UIDMap(uid_root=config.uid_root)
        self.hasher = HashMapper(prefix=config.hash_prefix, salt=config.hash_salt)

    def anonymize_dataset(
        self,
        ds: Dataset,
        source_path: Path,
    ) -> AnonymizationResult:
        """Anonymize a single DICOM dataset in-place.

        Args:
            ds: The pydicom Dataset to anonymize (modified in-place).
            source_path: Original file path (for logging).

        Returns:
            AnonymizationResult with details of what was modified.
        """
        result = AnonymizationResult(source_path=source_path)

        # Collect original PHI values for cross-referencing
        for tag in PHI_SOURCE_TAGS:
            if tag in ds:
                value = str(ds[tag].value)
                if value:
                    tag_name = TAG_PROFILE.get(tag, (None, str(tag)))[1]
                    result.original_phi[tag_name] = value

        # Apply tag profile
        for tag, (action, tag_name) in TAG_PROFILE.items():
            if tag not in ds:
                continue

            try:
                self._apply_action(ds, tag, action, tag_name, result)
            except Exception as e:
                result.warnings.append(f"Error processing {tag_name} {tag}: {e}")

        # Strip private tags
        if self.config.strip_private_tags:
            result.private_tags_removed = self._remove_private_tags(ds)

        # Update MediaStorageSOPInstanceUID in file meta to match new SOPInstanceUID
        if hasattr(ds, "file_meta") and (0x0002, 0x0003) in ds.file_meta:
            if (0x0008, 0x0018) in ds:
                ds.file_meta[0x0002, 0x0003].value = ds[0x0008, 0x0018].value
                result.uids_replaced.append("MediaStorageSOPInstanceUID")

        return result

    def _apply_action(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        action: Action,
        tag_name: str,
        result: AnonymizationResult,
    ):
        """Apply the specified action to a DICOM tag."""
        if action == Action.D:
            self._action_dummy(ds, tag, tag_name, result)
        elif action == Action.Z:
            self._action_zero(ds, tag, tag_name, result)
        elif action == Action.X:
            self._action_remove(ds, tag, tag_name, result)
        elif action == Action.U:
            self._action_replace_uid(ds, tag, tag_name, result)
        elif action == Action.C:
            self._action_clean(ds, tag, tag_name, result)
        # Action.K = Keep — do nothing

    def _action_dummy(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        tag_name: str,
        result: AnonymizationResult,
    ):
        """Replace with a pseudonymous value."""
        original = str(ds[tag].value)
        ds[tag].value = self.hasher.hash_id(original)
        result.tags_modified.append(tag_name)

    def _action_zero(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        tag_name: str,
        result: AnonymizationResult,
    ):
        """Replace with zero-length value."""
        ds[tag].value = ""
        result.tags_modified.append(tag_name)

    def _action_remove(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        tag_name: str,
        result: AnonymizationResult,
    ):
        """Remove the tag entirely."""
        del ds[tag]
        result.tags_removed.append(tag_name)

    def _action_replace_uid(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        tag_name: str,
        result: AnonymizationResult,
    ):
        """Replace UID with a new generated UID, maintaining consistency."""
        original_uid = str(ds[tag].value)
        ds[tag].value = self.uid_map.get_replacement(original_uid)
        result.uids_replaced.append(tag_name)

    def _action_clean(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        tag_name: str,
        result: AnonymizationResult,
    ):
        """Remove if the value looks like it contains PHI, otherwise keep."""
        value = str(ds[tag].value)

        # Check PatientAge specifically for HIPAA age cap
        if tag == (0x0010, 0x1010):
            self._clean_patient_age(ds, tag, tag_name, value, result)
            return

        if _looks_like_phi(value):
            del ds[tag]
            result.tags_removed.append(f"{tag_name} (contained PHI)")
        # else: keep as-is

    def _clean_patient_age(
        self,
        ds: Dataset,
        tag: tuple[int, int],
        tag_name: str,
        value: str,
        result: AnonymizationResult,
    ):
        """Handle PatientAge per HIPAA Safe Harbor: cap at 89."""
        # PatientAge format is typically "045Y", "089Y", etc.
        match = re.match(r"(\d{3})([YMWD])", value)
        if match and match.group(2) == "Y":
            age = int(match.group(1))
            if age > self.config.max_age:
                ds[tag].value = f"{self.config.max_age + 1:03d}Y"
                result.tags_modified.append(f"{tag_name} (age capped)")
                return
        # Keep as-is if not years or within range

    def _remove_private_tags(self, ds: Dataset) -> int:
        """Remove all private tags (odd group numbers)."""
        private_tags = [
            elem.tag for elem in ds
            if elem.tag.group % 2 != 0
        ]
        for tag in private_tags:
            del ds[tag]
        return len(private_tags)

    def anonymize_file(self, source_path: Path) -> tuple[Dataset, AnonymizationResult]:
        """Read and anonymize a single DICOM file.

        Returns:
            Tuple of (anonymized Dataset, AnonymizationResult).
        """
        try:
            ds = pydicom.dcmread(str(source_path), force=self.config.force_read)
            result = self.anonymize_dataset(ds, source_path)
            return ds, result
        except Exception as e:
            result = AnonymizationResult(
                source_path=source_path,
                success=False,
                error=str(e),
            )
            return None, result
