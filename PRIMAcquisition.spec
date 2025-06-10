# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['prim_app\\prim_app.py'],
    pathex=[],
    binaries=[],
    datas=[('.primenv/Lib/site-packages/imagingcontrol4/*', 'imagingcontrol4'), ('prim_app/ui/icons/*', 'prim_app/ui/icons'), ('prim_app/ui/style.qss', 'prim_app/ui')],
    hiddenimports=['imagingcontrol4'],
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
    name='PRIMAcquisition',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['prim_app\\ui\\icons\\PRIM.ico'],
)
