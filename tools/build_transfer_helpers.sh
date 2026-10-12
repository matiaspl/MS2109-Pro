#!/bin/sh
# Compile only; no device access. Native capture needs a camera-declared app.
set -eu
cd "$(dirname "$0")/.."
clang -fobjc-arc -framework Cocoa -I/opt/homebrew/include -L/opt/homebrew/lib -luvc tools/transfer_capture.m -o /private/tmp/transfer_capture
clang -I/opt/homebrew/include -L/opt/homebrew/lib -luvc tools/transfer_controls.c -o /private/tmp/transfer_controls
clang -fobjc-arc -framework Cocoa -framework AVFoundation -framework CoreMedia -framework CoreVideo tools/transfer_native_metadata.m -o /private/tmp/transfer_native_metadata
python3 - <<'PY'
from pathlib import Path
import plistlib
import shutil
app=Path('/private/tmp/TransferMetadataProbe.app')
(app/'Contents/MacOS').mkdir(parents=True,exist_ok=True)
shutil.copy2('/private/tmp/transfer_native_metadata',app/'Contents/MacOS/TransferMetadataProbe')
info={'CFBundleExecutable':'TransferMetadataProbe',
      'CFBundleIdentifier':'com.codex.local.TransferMetadataProbe',
      'CFBundleName':'Transfer Metadata Probe','CFBundlePackageType':'APPL',
      'LSMinimumSystemVersion':'14.0',
      'NSCameraUsageDescription':'Read native MS2109 video color attachments for the requested metadata calibration. Frames remain in memory.'}
(app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
PY
codesign --force --sign - /private/tmp/TransferMetadataProbe.app
