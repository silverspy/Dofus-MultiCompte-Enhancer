# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files
import sys
from pathlib import Path


# The installed edition uses the same application payload as the portable
# edition, but COLLECT keeps it unpacked on disk for near-instant startup.
rapidocr_datas = collect_data_files("rapidocr")
rapidocr_hiddenimports = ["rapidocr.inference_engine.onnxruntime"]
python_root = Path(sys.base_prefix)
tkinter_binaries = [
    (str(python_root / "DLLs" / "_tkinter.pyd"), "."),
    (str(python_root / "DLLs" / "tcl86t.dll"), "."),
    (str(python_root / "DLLs" / "tk86t.dll"), "."),
]
tkinter_datas = [
    (str(python_root / "tcl" / "tcl8.6"), "_tcl_data"),
    (str(python_root / "tcl" / "tk8.6"), "_tk_data"),
    (str(python_root / "tcl" / "tcl8"), "tcl8"),
]
excluded_modules = [
    "pandas",
    "pytest",
    "openpyxl",
    "rapidocr.inference_engine.mnn",
    "rapidocr.inference_engine.openvino",
    "rapidocr.inference_engine.paddle",
    "rapidocr.inference_engine.pytorch",
    "rapidocr.inference_engine.tensorrt",
]

a = Analysis(
    ["app/dofus_panel.pyw"],
    pathex=["app"],
    binaries=tkinter_binaries,
    datas=[("app/assets", "assets"), *rapidocr_datas, *tkinter_datas],
    hiddenimports=[
        "ankama_launcher",
        "chat_vision",
        "dofus_character_login",
        "localization",
        "panel_settings",
        "tkinter",
        "_tkinter",
        *rapidocr_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["app/runtime_tkinter.py"],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dofus-MultiCompte-Enhancer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Avoid executable packing so security products can inspect the payload
    # without first unpacking it heuristically.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["app/assets/dofus-multicompteenhancer.ico"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Dofus-MultiCompte-Enhancer",
)
