"""DICOM tag constants and magic bytes."""

# DICOM file identification
DICM_MAGIC = b"DICM"
DICM_MAGIC_OFFSET = 128

# DICOM tag groups
PRIVATE_TAG_GROUP_MASK = 0x0001  # Odd group numbers are private tags
