# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules


ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "app.py"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "data" / "corpus_version.json"), "data"),
    (str(ROOT / "data" / "knowledge_pages"), "data/knowledge_pages"),
    (str(ROOT / "data" / "raw" / "local_corpus.json"), "data/raw"),
]
binaries = []
hiddenimports = collect_submodules("evidence_assistant")

streamlit_datas, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
datas += streamlit_datas
binaries += streamlit_binaries
hiddenimports += streamlit_hidden
datas += collect_data_files("certifi")

a = Analysis(
    [str(ROOT / "src" / "evidence_assistant" / "desktop.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "pymupdf",
        "pytest",
        "sentence_transformers",
        "torch",
        "transformers",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClinicalEvidenceAssistant",
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
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ClinicalEvidenceAssistant",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="Clinical Evidence Assistant.app",
        icon=None,
        bundle_identifier="io.github.xiaoxiaomugong.clinical-evidence-assistant",
        version=os.getenv("CEA_VERSION", "0.1.0"),
        info_plist={
            "CFBundleDisplayName": "循证知问",
            "NSHighResolutionCapable": True,
            "LSBackgroundOnly": False,
        },
    )
