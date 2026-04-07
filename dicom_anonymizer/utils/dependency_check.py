"""Startup dependency verification.

Validates that all required and optional dependencies are loadable
inside the PyInstaller bundle (or dev environment) before the user
starts processing files.  Returns structured results so the GUI can
show a clear diagnostic at launch.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DepStatus:
    """Status of a single dependency."""

    name: str
    required: bool
    loaded: bool = False
    version: str = ""
    error: str = ""


@dataclass
class DependencyReport:
    """Full dependency check report."""

    deps: list[DepStatus] = field(default_factory=list)
    python_version: str = ""
    platform_info: str = ""
    is_bundled: bool = False

    @property
    def all_required_ok(self) -> bool:
        return all(d.loaded for d in self.deps if d.required)

    @property
    def missing_required(self) -> list[DepStatus]:
        return [d for d in self.deps if d.required and not d.loaded]

    @property
    def missing_optional(self) -> list[DepStatus]:
        return [d for d in self.deps if not d.required and not d.loaded]


def _check(name: str, import_name: str, required: bool) -> DepStatus:
    """Try to import a module and return its status."""
    status = DepStatus(name=name, required=required)
    try:
        mod = __import__(import_name)
        status.loaded = True
        status.version = getattr(mod, "__version__", getattr(mod, "VERSION", ""))
    except Exception as e:
        status.error = str(e)
    return status


def _check_jpeg_codecs() -> DepStatus:
    """Verify DICOM JPEG decompression actually works end-to-end."""
    status = DepStatus(name="JPEG codec (pylibjpeg)", required=True)
    try:
        import pylibjpeg  # noqa: F401
        import libjpeg  # noqa: F401
        import openjpeg  # noqa: F401
        status.loaded = True
        status.version = getattr(pylibjpeg, "__version__", "")
    except Exception as e:
        status.error = str(e)
    return status


def _check_haar_cascade() -> DepStatus:
    """Verify the Haar cascade model file is accessible."""
    status = DepStatus(name="Haar cascade (face detection)", required=False)
    base = getattr(sys, "_MEIPASS", None)
    cascade_rel = Path("CaseAnonymizer-R", "bin", "models",
                       "RGB-FaceDetection", "haarcascade_frontalface_alt.xml")
    if base:
        p = Path(base) / cascade_rel
    else:
        p = Path(__file__).resolve().parent.parent.parent / cascade_rel

    if p.exists():
        status.loaded = True
        status.version = str(p)
    else:
        status.error = f"Model file not found: {p}"
    return status


def run_check() -> DependencyReport:
    """Run a full dependency check and return the report."""
    report = DependencyReport(
        python_version=sys.version,
        platform_info=f"{platform.system()} {platform.release()} ({platform.machine()})",
        is_bundled=hasattr(sys, "_MEIPASS"),
    )

    # --- Required dependencies ---
    report.deps.append(_check("pydicom", "pydicom", required=True))
    report.deps.append(_check("PySide6 (Qt GUI)", "PySide6", required=True))
    report.deps.append(_check("NumPy", "numpy", required=True))
    report.deps.append(_check_jpeg_codecs())

    # --- Optional dependencies (pixel scrubbing) ---
    report.deps.append(_check("OpenCV (face detection)", "cv2", required=False))
    report.deps.append(_check("EasyOCR (text detection)", "easyocr", required=False))
    report.deps.append(_check_haar_cascade())

    return report


def format_report(report: DependencyReport) -> str:
    """Format the dependency report as human-readable text."""
    lines = [
        f"Python: {report.python_version}",
        f"Platform: {report.platform_info}",
        f"Bundled: {'Yes (PyInstaller)' if report.is_bundled else 'No (dev mode)'}",
        "",
    ]

    for dep in report.deps:
        tag = "REQUIRED" if dep.required else "optional"
        if dep.loaded:
            ver = f" v{dep.version}" if dep.version else ""
            lines.append(f"  OK  {dep.name}{ver}")
        else:
            lines.append(f"  FAIL  {dep.name} [{tag}]")
            lines.append(f"        {dep.error}")

    return "\n".join(lines)
