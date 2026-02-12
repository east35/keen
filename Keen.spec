# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['kindle_menubar.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Menu bar template icons must be in Contents/Resources for runtime lookup.
        ('iconTemplate.png', '.'),
        ('iconTemplate@2x.png', '.'),
        # Keep source assets in the bundle for debugging / future use.
        ('assets/app-icon.png', 'assets'),
        ('assets/menubar-icon.svg', 'assets'),
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='Keen',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['AppIcon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Keen',
)
app = BUNDLE(
    coll,
    name='Keen.app',
    icon='AppIcon.icns',
    bundle_identifier='com.keen.app',
)
