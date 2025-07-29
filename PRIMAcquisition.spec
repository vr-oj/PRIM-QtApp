# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for PRIMAcquisition.

This spec collects the application icons and stylesheet so the GUI has a
consistent, polished look across all platforms.
"""

import os
import sys
import importlib.util

source_script = os.path.join("prim_app", "prim_app.py")
icon_file = os.path.join("prim_app", "ui", "icons", "PRIM.ico")

data_files = [
    (
        os.path.join("prim_app", "ui", "icons", "*"),
        os.path.join("prim_app", "ui", "icons"),
    ),
    (os.path.join("prim_app", "ui", "style.qss"), os.path.join("prim_app", "ui")),
]

# Attempt to include imagingcontrol4 resources if the module is installed.
imaging_spec = importlib.util.find_spec("imagingcontrol4")
if imaging_spec is not None and imaging_spec.origin is not None:
    imaging_dir = os.path.dirname(imaging_spec.origin)
    data_files.append((os.path.join(imaging_dir, "*"), "imagingcontrol4"))

data_files.append(
    (os.path.join("prim_app", "docs", "*"), os.path.join("prim_app", "docs"))
)

a = Analysis(
    [source_script],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=["imagingcontrol4"],
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
    name="PRIMAcquisition 2.0",
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
    icon=icon_file
)


target = exe
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="PRIMAcquisition.app",
        icon=icon_file,
        bundle_identifier="com.example.PRIMAcquisition",
    )
    target = app

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PRIMAcquisition"
)

