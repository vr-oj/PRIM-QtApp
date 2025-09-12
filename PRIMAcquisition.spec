# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for Bladder Pressure Tracker.

This spec collects the application icons and stylesheet so the GUI has a
consistent, polished look across all platforms.
"""

import os
import sys
import pathlib

source_script = os.path.join("prim_app", "prim_app.py")
icons_dir = os.path.join("prim_app", "ui", "icons")
icon_ico = os.path.join(icons_dir, "PRIM.ico")
# Optional macOS icon (provide prim_app/ui/icons/app.icns to use)
icon_icns = os.path.join(icons_dir, "app.icns") if os.path.exists(os.path.join(icons_dir, "app.icns")) else None

data_files = [
    (os.path.join("prim_app", "ui", "icons", "*"), os.path.join("prim_app", "ui", "icons")),
    (os.path.join("prim_app", "ui", "style.qss"), os.path.join("prim_app", "ui")),
    (os.path.join("prim_app", "docs", "*"), os.path.join("prim_app", "docs")),
]

hidden = [
    # Be explicit about common Qt/Matplotlib bits when freezing
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_qtagg",
    "matplotlib.backends.backend_agg",
    "PyQt5.QtPrintSupport",
]

a = Analysis(
    [source_script],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe_name = "Bladder Pressure Tracker v1"
is_macos = sys.platform == "darwin"
is_windows = sys.platform.startswith("win")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=exe_name,
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
    icon=(icon_ico if is_windows else None),
)
target = exe

if is_macos:
    # Create a proper .app bundle on macOS
    app_name = f"{exe_name}.app"
    target = BUNDLE(
        exe,
        name=app_name,
        icon=icon_icns,  # Requires an .icns file; else None
        bundle_identifier="com.example.bladder-pressure-tracker",
        info_plist=None,
    )

coll = COLLECT(
    target,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Bladder Pressure Tracker",
)
