# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

project_root = os.path.abspath('.')

a = Analysis(
    ['prim_app/prim_app.py'],
    pathex=[project_root],
    binaries=[
        # Add Imaging Control 4 DLLs here if needed, e.g. ('path/to/ic4.dll', '.')
    ],
    datas=[
        ('prim_app/ui/icons/*', 'prim_app/ui/icons'),
        ('prim_app/ui/style.qss', 'prim_app/ui'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PRIMAcquisition',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='prim_app/ui/icons/PRIM.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PRIMAcquisition',
)
