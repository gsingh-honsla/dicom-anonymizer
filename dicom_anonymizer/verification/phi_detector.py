"""Regex-based PHI pattern detection for post-anonymization verification.

Scans string values for patterns matching HIPAA Safe Harbor's 18 identifiers.
Used as a defense-in-depth layer to catch any PHI the anonymizer missed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PHIMatch:
    """A single detected PHI pattern match."""

    category: str       # e.g. "name", "date", "phone"
    matched_text: str   # The actual text that matched
    pattern_name: str   # Human-readable pattern description


@dataclass
class PHIScanResult:
    """Result of scanning a single string value."""

    value: str
    matches: list[PHIMatch] = field(default_factory=list)

    @property
    def has_phi(self) -> bool:
        return len(self.matches) > 0


# ── Pattern definitions ──────────────────────────────────────

# Each entry: (category, pattern_name, compiled_regex)
_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # Names (DICOM format Last^First^Middle)
    ("name", "DICOM name format",
     re.compile(r"[A-Z][a-z]+\^[A-Z][a-z]+", re.ASCII)),

    # Dates (various formats)
    ("date", "DICOM date YYYYMMDD",
     re.compile(r"\b(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b")),
    ("date", "Date with slashes",
     re.compile(r"\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}\b")),
    ("date", "Date with dashes",
     re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")),

    # Phone / fax numbers
    ("phone", "US phone number",
     re.compile(r"\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),

    # SSN
    ("ssn", "Social Security Number",
     re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),

    # Email
    ("email", "Email address",
     re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")),

    # Medical record numbers (common patterns)
    ("mrn", "Medical record number",
     re.compile(r"\b(MRN|mrn|MR#|PatientId|PATID)[\s:=#-]*[A-Z0-9]{4,}\b")),

    # IP addresses
    ("ip", "IPv4 address",
     re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")),

    # URLs (can contain identifying info)
    ("url", "URL",
     re.compile(r"https?://[^\s,;]+", re.ASCII)),

    # Street addresses (basic US pattern)
    ("address", "Street address",
     re.compile(r"\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place)\b")),

    # ZIP codes (5 or 5+4)
    ("zip", "ZIP code",
     re.compile(r"\b\d{5}(?:-\d{4})?\b")),
]

# Known safe values that commonly match patterns but aren't PHI
_SAFE_VALUES = frozenset({
    "",
    "ANON",
    "ANONYMOUS",
    "UNKNOWN",
    "NONE",
    "NA",
    "N/A",
})


class PHIDetector:
    """Detects potential PHI in string values using regex patterns.

    Can optionally cross-reference against known original PHI values
    from the source file to reduce false positives.
    """

    def __init__(self, known_phi: dict[str, str] | None = None):
        """Initialize detector.

        Args:
            known_phi: Optional dict of tag_name -> original_value from the
                       anonymizer. When provided, exact-match scanning is also
                       performed against these known values.
        """
        self._known_phi = known_phi or {}
        # Build set of known PHI substrings for exact matching
        self._known_values: set[str] = set()
        for value in self._known_phi.values():
            cleaned = value.strip().upper()
            if cleaned and cleaned not in _SAFE_VALUES:
                self._known_values.add(cleaned)
                # Also add individual name components (split on ^ and space)
                for part in re.split(r"[\^\s,]+", cleaned):
                    part = part.strip()
                    if len(part) >= 3:  # Skip very short fragments
                        self._known_values.add(part)

    def scan_value(self, value: str) -> PHIScanResult:
        """Scan a single string value for PHI patterns.

        Args:
            value: The string to scan.

        Returns:
            PHIScanResult with any matches found.
        """
        result = PHIScanResult(value=value)

        if not value or value.strip().upper() in _SAFE_VALUES:
            return result

        # Pattern-based detection
        for category, pattern_name, pattern in _PATTERNS:
            for match in pattern.finditer(value):
                result.matches.append(PHIMatch(
                    category=category,
                    matched_text=match.group(),
                    pattern_name=pattern_name,
                ))

        # Known PHI exact-match detection
        value_upper = value.upper()
        for known in self._known_values:
            if known in value_upper:
                result.matches.append(PHIMatch(
                    category="known_phi",
                    matched_text=known,
                    pattern_name="Exact match against source PHI",
                ))

        return result

    def scan_all_values(self, tag_values: dict[str, str]) -> dict[str, PHIScanResult]:
        """Scan multiple tag values and return only those with matches.

        Args:
            tag_values: Dict of tag_name -> string_value.

        Returns:
            Dict of tag_name -> PHIScanResult, only for tags with detected PHI.
        """
        results = {}
        for tag_name, value in tag_values.items():
            scan = self.scan_value(value)
            if scan.has_phi:
                results[tag_name] = scan
        return results
