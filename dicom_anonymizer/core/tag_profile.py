"""DICOM tag anonymization profile based on PS3.15 Annex E Basic Profile + HIPAA Safe Harbor.

Action codes:
    D = Replace with dummy/pseudonymous value
    Z = Replace with zero-length value
    X = Remove tag entirely
    K = Keep (required for DICOM validity or useful for ML)
    U = Replace UID with new generated UID (maintaining internal consistency)
    C = Clean (remove if contains PHI, otherwise keep)
"""

from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    D = "D"  # Dummy/pseudonymous
    Z = "Z"  # Zero-length
    X = "X"  # Remove
    K = "K"  # Keep
    U = "U"  # Replace UID
    C = "C"  # Clean


# Tag profile: (group, element) -> (Action, description)
# Organized by category for maintainability.

PATIENT_TAGS = {
    (0x0010, 0x0010): (Action.D, "PatientName"),
    (0x0010, 0x0020): (Action.D, "PatientID"),
    (0x0010, 0x0030): (Action.Z, "PatientBirthDate"),
    (0x0010, 0x0040): (Action.K, "PatientSex"),
    (0x0010, 0x1000): (Action.X, "OtherPatientIDs"),
    (0x0010, 0x1001): (Action.X, "OtherPatientNames"),
    (0x0010, 0x1010): (Action.C, "PatientAge"),
    (0x0010, 0x1020): (Action.K, "PatientSize"),
    (0x0010, 0x1030): (Action.K, "PatientWeight"),
    (0x0010, 0x1040): (Action.X, "PatientAddress"),
    (0x0010, 0x2154): (Action.X, "PatientTelephoneNumbers"),
    (0x0010, 0x2160): (Action.X, "EthnicGroup"),
    (0x0010, 0x2180): (Action.X, "Occupation"),
    (0x0010, 0x21B0): (Action.X, "AdditionalPatientHistory"),
    (0x0010, 0x4000): (Action.X, "PatientComments"),
}

STUDY_INSTITUTIONAL_TAGS = {
    (0x0008, 0x0020): (Action.Z, "StudyDate"),
    (0x0008, 0x0021): (Action.Z, "SeriesDate"),
    (0x0008, 0x0022): (Action.Z, "AcquisitionDate"),
    (0x0008, 0x0023): (Action.Z, "ContentDate"),
    (0x0008, 0x0030): (Action.Z, "StudyTime"),
    (0x0008, 0x0031): (Action.Z, "SeriesTime"),
    (0x0008, 0x0032): (Action.Z, "AcquisitionTime"),
    (0x0008, 0x0033): (Action.Z, "ContentTime"),
    (0x0008, 0x0050): (Action.D, "AccessionNumber"),
    (0x0008, 0x0080): (Action.X, "InstitutionName"),
    (0x0008, 0x0081): (Action.X, "InstitutionAddress"),
    (0x0008, 0x0090): (Action.X, "ReferringPhysicianName"),
    (0x0008, 0x0092): (Action.X, "ReferringPhysicianAddress"),
    (0x0008, 0x0094): (Action.X, "ReferringPhysicianTelephoneNumbers"),
    (0x0008, 0x1010): (Action.X, "StationName"),
    (0x0008, 0x1030): (Action.C, "StudyDescription"),
    (0x0008, 0x103E): (Action.C, "SeriesDescription"),
    (0x0008, 0x1040): (Action.X, "InstitutionalDepartmentName"),
    (0x0008, 0x1048): (Action.X, "PhysiciansOfRecord"),
    (0x0008, 0x1050): (Action.X, "PerformingPhysicianName"),
    (0x0008, 0x1060): (Action.X, "NameOfPhysiciansReadingStudy"),
    (0x0008, 0x1070): (Action.X, "OperatorsName"),
    (0x0008, 0x1080): (Action.X, "AdmittingDiagnosesDescription"),
    (0x0020, 0x0010): (Action.D, "StudyID"),
    (0x0020, 0x4000): (Action.X, "ImageComments"),
    (0x0032, 0x1032): (Action.X, "RequestingPhysician"),
    (0x0032, 0x1033): (Action.X, "RequestingService"),
    (0x0038, 0x0010): (Action.X, "AdmissionID"),
    (0x0038, 0x0500): (Action.X, "PatientState"),
    (0x0040, 0x0006): (Action.X, "ScheduledPerformingPhysicianName"),
    (0x0040, 0x0241): (Action.X, "PerformedStationAETitle"),
    (0x0040, 0x0242): (Action.X, "PerformedStationName"),
    (0x0040, 0x0243): (Action.X, "PerformedStationGeographicLocationCodeSequence"),
    (0x0040, 0x0244): (Action.Z, "PerformedProcedureStepStartDate"),
    (0x0040, 0x0245): (Action.Z, "PerformedProcedureStepStartTime"),
    (0x0040, 0x0253): (Action.X, "PerformedProcedureStepID"),
    (0x0040, 0x0254): (Action.C, "PerformedProcedureStepDescription"),
    (0x0040, 0x1001): (Action.X, "RequestedProcedureID"),
    (0x0040, 0x2016): (Action.X, "PlacerOrderNumberImagingServiceRequest"),
    (0x0040, 0x2017): (Action.X, "FillerOrderNumberImagingServiceRequest"),
    (0x0040, 0xA730): (Action.X, "ContentSequence"),
}

UID_TAGS = {
    (0x0008, 0x0018): (Action.U, "SOPInstanceUID"),
    (0x0020, 0x000D): (Action.U, "StudyInstanceUID"),
    (0x0020, 0x000E): (Action.U, "SeriesInstanceUID"),
    (0x0008, 0x0014): (Action.U, "InstanceCreatorUID"),
    (0x0020, 0x0052): (Action.U, "FrameOfReferenceUID"),
}

EQUIPMENT_TAGS = {
    (0x0008, 0x0070): (Action.K, "Manufacturer"),
    (0x0008, 0x1090): (Action.K, "ManufacturerModelName"),
    (0x0018, 0x1000): (Action.X, "DeviceSerialNumber"),
    (0x0018, 0x1002): (Action.U, "DeviceUID"),
    (0x0018, 0x1020): (Action.K, "SoftwareVersions"),
}

# Combined profile: all tags with their actions
TAG_PROFILE: dict[tuple[int, int], tuple[Action, str]] = {
    **PATIENT_TAGS,
    **STUDY_INSTITUTIONAL_TAGS,
    **UID_TAGS,
    **EQUIPMENT_TAGS,
}

# Tags whose original values should be collected for PHI cross-referencing
PHI_SOURCE_TAGS = {
    (0x0010, 0x0010),  # PatientName
    (0x0010, 0x0020),  # PatientID
    (0x0010, 0x0030),  # PatientBirthDate
    (0x0010, 0x1000),  # OtherPatientIDs
    (0x0010, 0x1001),  # OtherPatientNames
    (0x0008, 0x0080),  # InstitutionName
    (0x0008, 0x0081),  # InstitutionAddress
    (0x0008, 0x0090),  # ReferringPhysicianName
    (0x0008, 0x1050),  # PerformingPhysicianName
    (0x0008, 0x1060),  # NameOfPhysiciansReadingStudy
    (0x0008, 0x1070),  # OperatorsName
}
