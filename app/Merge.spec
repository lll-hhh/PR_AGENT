# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

# Build against Windows and this interpreter only. A Conda installation on
# PATH can otherwise supply an incompatible ICU DLL for Qt's Windows ICU API.
if sys.platform == "win32":
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join([
        str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
        str(windows / "System32"), str(windows),
    ])

root = Path(SPECPATH)
assets = root / "merge_monitor" / "assets"
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(assets), "merge_monitor/assets"), (str(root / "THIRD_PARTY_NOTICES.md"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Contributions",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(assets / "merge.ico"),
    version=str(root / "version_info.txt"),
)
