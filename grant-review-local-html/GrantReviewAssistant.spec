# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)

datas = [
    (str(project_root / "ui"), "ui"),
    (str(project_root / "examples"), "examples"),
]
binaries = []
hiddenimports = []

for package in ("webview", "pypdf", "openpyxl", "openai", "cryptography"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    [str(project_root / "desktop_app.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["streamlit", "pandas", "matplotlib", "numpy.testing"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="GrantReviewAssistant",
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
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GrantReviewAssistant",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="基金评审助手.app",
        icon=None,
        bundle_identifier="cn.local.grant-review-assistant",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleDisplayName": "基金评审助手",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
        },
    )
