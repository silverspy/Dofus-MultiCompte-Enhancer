# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all


rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_all("rapidocr")

a = Analysis(
    ["app/dofus_panel.pyw"],
    pathex=["app"],
    binaries=rapidocr_binaries,
    datas=[("app/assets", "assets"), *rapidocr_datas],
    hiddenimports=[
        "ankama_launcher",
        "chat_vision",
        "dofus_character_login",
        *rapidocr_hiddenimports,
    ],
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
    name="Dofus-MultiCompte-Enhancer",
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
    icon=["app/assets/dofus-multicompteenhancer.ico"],
)
