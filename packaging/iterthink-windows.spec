# -*- mode: python -*-
# One-folder Windows build: uv run pyinstaller packaging/iterthink-windows.spec --noconfirm
import sys

sys.path.insert(0, SPECPATH)
from build_common import ENTRY, EXCLUDES, NAME, ROOT, collected, datas  # noqa: E402

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
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=NAME)
