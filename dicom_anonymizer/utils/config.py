"""Application configuration defaults."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AnonymizationConfig:
    """Settings for an anonymization run."""

    source_dir: Path = field(default_factory=lambda: Path.home())
    output_dir: Path = field(default_factory=lambda: Path.home() / "dicom_anon_output")

    # Anonymization options
    strip_private_tags: bool = True
    pixel_scrub: bool = False  # Phase 3
    keep_dates: bool = False  # False = zero mode (max safety)
    auto_verify: bool = True

    # Hashing
    hash_prefix: str = "ANON_"
    hash_salt: str = ""  # Optional salt for SHA-256

    # UID generation
    uid_root: str = "1.2.826.0.1.3680043.8.498"  # Registered UID root for anonymization

    # Age cap per HIPAA Safe Harbor
    max_age: int = 89  # Ages >= 90 are grouped as 090Y

    # Processing
    force_read: bool = True  # Use pydicom force=True for pre-Part 10 DICOM


APP_NAME = "DICOM Anonymizer"
APP_VERSION = "1.0.0"
APP_ORG = "Globus Medical"
