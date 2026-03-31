#!/bin/bash
# Build script for DICOM Anonymizer — Globus Medical
#
# Usage:
#   ./build.sh              Build .app bundle
#   ./build.sh --sign       Build + code sign (requires Apple Developer cert)
#   ./build.sh --dmg        Build + create DMG installer
#   ./build.sh --sign --dmg Build + sign + DMG
#   ./build.sh --clean      Remove build artifacts only

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="DICOM Anonymizer"
SPEC_FILE="$SCRIPT_DIR/dicom_anonymizer.spec"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
APP_PATH="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/DICOM_Anonymizer.dmg"

SIGN=false
DMG=false
CLEAN_ONLY=false

for arg in "$@"; do
    case $arg in
        --sign)  SIGN=true ;;
        --dmg)   DMG=true ;;
        --clean) CLEAN_ONLY=true ;;
        *)       echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── Clean ────────────────────────────────────────────────────
echo "==> Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR"

if $CLEAN_ONLY; then
    echo "==> Clean complete."
    exit 0
fi

# ── Build ────────────────────────────────────────────────────
echo "==> Building $APP_NAME..."
echo "    Spec: $SPEC_FILE"
echo "    Python: $(python3 --version)"

cd "$SCRIPT_DIR"
python3 -m PyInstaller "$SPEC_FILE" --noconfirm

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: Build failed — $APP_PATH not found"
    exit 1
fi

APP_SIZE=$(du -sh "$APP_PATH" | cut -f1)
echo "==> Build complete: $APP_PATH ($APP_SIZE)"

# ── Code Sign (optional) ─────────────────────────────────────
if $SIGN; then
    echo "==> Signing $APP_NAME..."

    # Find signing identity
    IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | sed 's/.*"\(.*\)".*/\1/')

    if [ -z "$IDENTITY" ]; then
        echo "WARNING: No 'Developer ID Application' certificate found."
        echo "         Trying any available signing identity..."
        IDENTITY=$(security find-identity -v -p codesigning | grep -v "0 valid" | head -1 | sed 's/.*"\(.*\)".*/\1/')
    fi

    if [ -z "$IDENTITY" ]; then
        echo "ERROR: No code signing identity found."
        echo "       Install an Apple Developer certificate or skip --sign"
        exit 1
    fi

    echo "    Identity: $IDENTITY"

    # Sign all binaries inside the app bundle
    codesign --deep --force --options runtime \
        --sign "$IDENTITY" \
        "$APP_PATH"

    echo "==> Verifying signature..."
    codesign --verify --deep --strict "$APP_PATH"
    echo "==> Signature valid."

    # Notarize (requires Apple Developer account + app-specific password)
    echo ""
    echo "NOTE: To notarize for Gatekeeper, run:"
    echo "  xcrun notarytool submit '$DMG_PATH' --apple-id YOUR_APPLE_ID --team-id YOUR_TEAM_ID --password YOUR_APP_SPECIFIC_PASSWORD --wait"
    echo "  xcrun stapler staple '$DMG_PATH'"
fi

# ── Create DMG (optional) ────────────────────────────────────
if $DMG; then
    echo "==> Creating DMG installer..."

    # Remove old DMG
    rm -f "$DMG_PATH"

    # Create DMG with hdiutil
    STAGING_DIR=$(mktemp -d)
    cp -R "$APP_PATH" "$STAGING_DIR/"

    # Create Applications symlink for drag-to-install
    ln -s /Applications "$STAGING_DIR/Applications"

    hdiutil create -volname "$APP_NAME" \
        -srcfolder "$STAGING_DIR" \
        -ov -format UDZO \
        "$DMG_PATH"

    rm -rf "$STAGING_DIR"

    DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
    echo "==> DMG created: $DMG_PATH ($DMG_SIZE)"
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Build Summary"
echo "============================================"
echo "  App:  $APP_PATH"
echo "  Size: $APP_SIZE"
if $DMG; then
    echo "  DMG:  $DMG_PATH ($DMG_SIZE)"
fi
if $SIGN; then
    echo "  Signed: Yes ($IDENTITY)"
else
    echo "  Signed: No (use --sign to code sign)"
fi
echo "============================================"
echo ""
echo "To test: open '$APP_PATH'"
