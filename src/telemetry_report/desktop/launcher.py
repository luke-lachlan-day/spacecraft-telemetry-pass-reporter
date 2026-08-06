"""Launch and self-test the optional Windows desktop application."""

from __future__ import annotations

import argparse
import ctypes
import sys
import webbrowser
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

from telemetry_report import __version__
from telemetry_report.data import validate_telemetry_json
from telemetry_report.desktop.bridge import DesktopBridge, DesktopDialogs, _example_text
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass

_WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
_WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


class PywebviewDialogs(DesktopDialogs):
    """Native file-dialog adapter backed by a pywebview window."""

    def __init__(self, window: Any, webview_module: Any) -> None:
        self._window = window
        self._webview = webview_module

    def open_json(self) -> Path | None:
        result = self._window.create_file_dialog(
            self._webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=("Telemetry JSON (*.json)",),
        )
        return self._selected_path(result)

    def save_json(self, suggested_name: str) -> Path | None:
        return self._save_path(suggested_name, ("Telemetry JSON (*.json)",))

    def save_report(self, suggested_name: str) -> Path | None:
        return self._save_path(suggested_name, ("HTML report (*.html)",))

    def _save_path(self, suggested_name: str, file_types: tuple[str, ...]) -> Path | None:
        result = self._window.create_file_dialog(
            self._webview.FileDialog.SAVE,
            save_filename=suggested_name,
            file_types=file_types,
        )
        return self._selected_path(result)

    @staticmethod
    def _selected_path(result: tuple[str, ...] | None) -> Path | None:
        if not result:
            return None
        return Path(result[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telemetry-report-gui",
        description="Open the portable Spacecraft Telemetry Pass Reporter interface.",
    )
    parser.add_argument("--self-test", action="store_true", help="validate packaged resources")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def run_self_test() -> None:
    """Exercise packaged data, validation, analysis, and rendering without a window."""
    expected = {
        "nominal": ("nominal", (8, 0, 0)),
        "anomalous": ("critical", (4, 3, 3)),
    }
    for name, (status, counts) in expected.items():
        validated = validate_telemetry_json(_example_text(name), source=f"example:{name}")
        analysis = analyse_pass(validated.telemetry_pass)
        html = render_report(analysis)
        actual_counts = (
            analysis.counts.nominal,
            analysis.counts.warning,
            analysis.counts.critical,
        )
        if analysis.overall_status.value != status or actual_counts != counts:
            raise RuntimeError(f"packaged {name} example produced unexpected analysis")
        if "<!doctype html>" not in html or validated.telemetry_pass.pass_id not in html:
            raise RuntimeError(f"packaged {name} example did not render correctly")


def _webview2_runtime_version() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    locations = (
        (
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            rf"Software\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_ID}",
        ),
    )
    for hive, key_path in locations:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if isinstance(version, str) and version not in {"", "0.0.0.0"}:
            return version
    return None


def _native_message(message: str, *, question: bool = False) -> bool:
    flags = 0x30 | (0x04 if question else 0x00)
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise RuntimeError("native Windows message dialogs are unavailable")
    result = windll.user32.MessageBoxW(None, message, "Telemetry Reporter", flags)
    return bool(question and result == 6)


def _launch_gui() -> int:
    if sys.platform != "win32":
        print("error: the desktop application currently supports Windows x64 only", file=sys.stderr)
        return 2
    if _webview2_runtime_version() is None:
        should_open = _native_message(
            "Microsoft Edge WebView2 Runtime is required. Open the official download page?",
            question=True,
        )
        if should_open:
            webbrowser.open(_WEBVIEW2_DOWNLOAD_URL)
        return 2

    try:
        import webview
    except ImportError:
        print('error: install the desktop dependencies with pip install -e ".[desktop]"')
        return 2

    app_resource = files("telemetry_report.desktop").joinpath("assets", "app.html")
    bridge = DesktopBridge()
    try:
        with as_file(app_resource) as app_path:
            window = webview.create_window(
                "Spacecraft Telemetry Pass Reporter",
                url=app_path.as_uri(),
                js_api=bridge,
                width=1180,
                height=780,
                min_size=(720, 640),
                background_color="#edf2f6",
                text_select=True,
                zoomable=True,
            )
            bridge.bind_dialogs(PywebviewDialogs(window, webview))
            webview.start(gui="edgechromium", private_mode=True)
    except Exception as error:
        _native_message(f"The desktop application could not start:\n\n{error}")
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the self-test or launch the desktop application."""
    arguments = build_parser().parse_args(argv)
    if arguments.self_test:
        try:
            run_self_test()
        except Exception as error:
            print(f"Desktop self-test failed: {error}", file=sys.stderr)
            return 1
        print("Desktop self-test passed")
        return 0
    return _launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
