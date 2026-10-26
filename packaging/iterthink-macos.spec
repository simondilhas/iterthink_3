# -*- mode: python -*-
# One-folder macOS app: uv run pyinstaller packaging/iterthink-macos.spec --noconfirm
# Info.plist carries NSMicrophoneUsageDescription for voice input.
import plistlib
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from build_common import ENTRY, EXCLUDES, NAME, ROOT, collected, datas  # noqa: E402

macos = Path(SPECPATH) / "macos"
with (macos / "Info.plist").open("rb") as handle:
    info = plistlib.load(handle)

extra_datas, binaries, hidden = collected()
a = Analysis(
    [ENTRY],
    pathex=[str(ROOT)],
    datas=datas() + extra_datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=EXCLUDES,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    upx=False,
    entitlements_file=str(macos / "entitlements.plist"),
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=NAME)
app = BUNDLE(
    coll,
    name=f"{NAME}.app",
    bundle_identifier=info["CFBundleIdentifier"],
    info_plist=info,
)
