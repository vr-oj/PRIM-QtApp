# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for PRIMAcquisition.

This spec collects the application icons and stylesheet so the GUI has a
consistent, polished look across all platforms.
"""

import os

from PyInstaller.utils.hooks import collect_all

source_script = os.path.join("prim_app", "prim_app.py")
icon_file = os.path.join("prim_app", "ui", "icons", "PRIM.ico")
ic4_datas, ic4_binaries, ic4_hiddenimports = collect_all("imagingcontrol4")

data_files = [
    (os.path.join("prim_app", "ui", "icons", "*"), os.path.join("prim_app", "ui", "icons")),
    (os.path.join("prim_app", "ui", "style.qss"), os.path.join("prim_app", "ui")),
    (os.path.join("prim_app", "docs", "*"), os.path.join("prim_app", "docs")),
]
data_files += ic4_datas

a = Analysis(
    [source_script],
    pathex=[],
    binaries=ic4_binaries,
    datas=data_files,
    hiddenimports=["imagingcontrol4"] + ic4_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PRIMA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PRIMA",
)
