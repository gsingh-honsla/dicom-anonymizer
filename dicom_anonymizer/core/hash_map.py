"""Patient ID and accession number hashing for pseudonymous replacement."""

import hashlib


class HashMapper:
    """Generate deterministic pseudonymous IDs using SHA-256.

    Same input always produces the same output, enabling consistent
    patient identification across files and sessions.
    """

    def __init__(self, prefix: str = "ANON_", salt: str = ""):
        self.prefix = prefix
        self.salt = salt

    def hash_id(self, original: str) -> str:
        """Generate a pseudonymous ID from the original.

        Returns: e.g. "ANON_a3f8b2c1"
        """
        value = f"{self.salt}{original}".encode("utf-8")
        digest = hashlib.sha256(value).hexdigest()[:8]
        return f"{self.prefix}{digest}"
