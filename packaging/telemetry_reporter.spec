"""PyInstaller definition for the portable Windows x64 desktop application."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


repository_root = Path(SPEC).resolve().parent.parent

datas = collect_data_files("telemetry_report")
datas.extend(
    [
        (str(repository_root / "LICENSE"), "."),
        (str(repository_root / "packaging" / "release" / "README.txt"), "."),
    ]
)

analysis = Analysis(
    [str(repository_root / "src" / "telemetry_report" / "desktop" / "launcher.py")],
    pathex=[str(repository_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["webview.platforms.edgechromium"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cefpython3",
        "gi",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "qtpy",
        "webview.platforms.cef",
        "webview.platforms.gtk",
        "webview.platforms.qt",
    ],
    noarchive=False,
    optimize=1,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Telemetry Reporter",
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

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Telemetry Reporter",
)
