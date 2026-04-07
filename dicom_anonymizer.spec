# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DICOM Anonymizer — Globus Medical.

Builds a standalone macOS .app bundle with all dependencies.
Pixel scrubbing (easyocr + torch) is included if available.

Usage:
    pyinstaller dicom_anonymizer.spec
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Paths ────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))
CASCADE_MODEL = os.path.join(
    PROJECT_ROOT,
    "CaseAnonymizer-R", "bin", "models",
    "RGB-FaceDetection", "haarcascade_frontalface_alt.xml",
)
EASYOCR_MODELS = os.path.join(os.path.expanduser("~"), ".EasyOCR", "model")

# ── Data files to bundle ─────────────────────────────────────
datas = []

# Haar cascade model for face detection
if os.path.isfile(CASCADE_MODEL):
    datas.append((CASCADE_MODEL, os.path.join(
        "CaseAnonymizer-R", "bin", "models", "RGB-FaceDetection"
    )))

# easyocr pre-downloaded models (avoids download on first run)
if os.path.isdir(EASYOCR_MODELS):
    datas.append((EASYOCR_MODELS, os.path.join(".EasyOCR", "model")))

# easyocr character data
try:
    import easyocr
    easyocr_pkg = os.path.dirname(easyocr.__file__)
    char_dir = os.path.join(easyocr_pkg, "character")
    if os.path.isdir(char_dir):
        datas.append((char_dir, os.path.join("easyocr", "character")))
except ImportError:
    pass

# pydicom data files (charset files, etc.)
datas += collect_data_files("pydicom")

# ── Hidden imports ───────────────────────────────────────────
hiddenimports = [
    "pydicom.encoders.gdcm",
    "pydicom.encoders.pylibjpeg",
    "pydicom.encoders.native",
    "pylibjpeg",
    "pylibjpeg.utils",
    # JPEG codec native modules — import names differ from pip package names
    "libjpeg",
    "openjpeg",
]

# Optional: easyocr + torch (for pixel scrubbing)
try:
    import easyocr
    hiddenimports += collect_submodules("easyocr")
    hiddenimports += ["easyocr"]
except ImportError:
    pass

try:
    import torch
    # Collect ALL torch submodules — torch uses heavy dynamic imports that
    # PyInstaller's static analysis misses, causing ImportError on target Macs.
    hiddenimports += collect_submodules("torch")
    datas += collect_data_files("torch")
except ImportError:
    pass

try:
    import torchvision
    hiddenimports += collect_submodules("torchvision")
    datas += collect_data_files("torchvision")
except ImportError:
    pass

# ── Analysis ─────────────────────────────────────────────────
a = Analysis(
    [os.path.join(PROJECT_ROOT, "run_app.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary heavy packages to reduce size
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter",
        "test",
        # NOTE: do NOT exclude "unittest" — torch/easyocr import it internally
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DICOM Anonymizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DICOM Anonymizer",
)

app = BUNDLE(
    coll,
    name="DICOM Anonymizer.app",
    icon=os.path.join(PROJECT_ROOT, "app_icon.icns"),
    bundle_identifier="com.globusmedical.dicom-anonymizer",
    info_plist={
        "CFBundleDisplayName": "DICOM Anonymizer",
        "CFBundleShortVersionString": "1.0.2",
        "CFBundleVersion": "1.0.2",
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [],
        "LSMinimumSystemVersion": "10.15.0",
        "NSHumanReadableCopyright": "© 2026 Globus Medical, Inc.",
    },
)
