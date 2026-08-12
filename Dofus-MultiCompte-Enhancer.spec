# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


# RapidOCR supports several optional inference backends. The application uses
# its default ONNX Runtime backend only; collecting every RapidOCR submodule
# also pulled unrelated PyTorch, pandas, openpyxl, and pytest modules into the
# executable. Static imports cover the OCR pipeline while this explicit hidden
# import keeps the dynamically selected ONNX engine available.
rapidocr_datas = collect_data_files("rapidocr")
rapidocr_hiddenimports = ["rapidocr.inference_engine.onnxruntime"]
excluded_modules = [
    "pandas",  # optional tqdm integration; not used by the application
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
    binaries=[],
    datas=[("app/assets", "assets"), *rapidocr_datas],
    hiddenimports=[
        "ankama_launcher",
        "chat_vision",
        "dofus_character_login",
        "localization",
        "panel_settings",
        *rapidocr_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
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
    # Keep the executable unpacked. UPX compression saves little for this
    # bundle and makes heuristic antivirus analysis less transparent.
    upx=False,
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
