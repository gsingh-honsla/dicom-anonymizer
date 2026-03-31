"""UID replacement with consistency mapping.

DICOM UIDs must be globally unique and follow the format:
  root.suffix where each component is a numeric string.

We generate replacement UIDs using:
  <uid_root>.<hash_of_original_uid>

The mapping is maintained per session so the same original UID
always maps to the same replacement UID.
"""

from __future__ import annotations

import hashlib
import uuid


class UIDMap:
    """Maintains a consistent mapping from original UIDs to replacement UIDs."""

    def __init__(self, uid_root: str = "1.2.826.0.1.3680043.8.498"):
        self.uid_root = uid_root
        self._map: dict[str, str] = {}

    def get_replacement(self, original_uid: str) -> str:
        """Get or create a replacement UID for the given original UID.

        The replacement is deterministic within a session — same input
        always produces the same output.
        """
        if original_uid in self._map:
            return self._map[original_uid]

        # Generate a new UID based on UUID4 to ensure global uniqueness
        # Format: root.uuid_as_decimal
        new_uuid = uuid.uuid4()
        # Convert UUID to a decimal string (DICOM UIDs only allow digits and dots)
        uid_suffix = str(int(new_uuid.hex, 16))
        new_uid = f"{self.uid_root}.{uid_suffix}"

        # DICOM UIDs have a max length of 64 characters
        if len(new_uid) > 64:
            new_uid = new_uid[:64]

        self._map[original_uid] = new_uid
        return new_uid

    @property
    def mapping(self) -> dict[str, str]:
        """Return a copy of the current UID mapping."""
        return dict(self._map)

    def clear(self):
        """Reset the mapping for a new session."""
        self._map.clear()
