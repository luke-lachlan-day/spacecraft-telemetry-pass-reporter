"""Launch and self-test the optional Windows desktop application."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import webbrowser
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from typing import Any

from telemetry_report import __version__
from telemetry_report.data import validate_telemetry_json
from telemetry_report.desktop.bridge import DesktopBridge, DesktopDialogs, _example_text
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass

_WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
_WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_UI_SMOKE_TIMEOUT_SECONDS = 20.0
_CHROMIUM_LOG_ENVIRONMENT = "CHROME_LOG_FILE"
_UI_SMOKE_SCRIPT = """
(async () => {
  await initializeApp();
  const battery = metricDefinitions.find((metric) => metric.key === "battery_voltage");
  if (!battery) throw new Error("battery metric configuration is unavailable");
  const input = document.getElementById(`quick-${battery.slug}`);
  input.value = String(battery.limit.critical);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await analyseCurrent();
  const resultVisible = !document.getElementById("result-panel").hidden;
  const criticalStatus = document.getElementById("overall-status").classList.contains("critical");
  const previewReady = (document.getElementById("report-preview").srcdoc || "")
    .includes("<!doctype html>");
  const saveReady = !document.getElementById("save-report").disabled;
  input.value = String(battery.quick.default);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return {
    result_visible: resultVisible,
    critical_status: criticalStatus,
    preview_ready: previewReady,
    save_ready: saveReady,
    stale_result_cleared: document.getElementById("result-panel").hidden,
    stale_save_disabled: document.getElementById("save-report").disabled,
  };
})()
"""


@dataclass(slots=True)
class UiSmokeResult:
    """Result shared between pywebview's smoke thread and the launcher."""

    error: str | None = None


@contextmanager
def _temporary_chromium_log() -> Iterator[None]:
    """Keep incidental Chromium logging out of the launch directory."""
    if _CHROMIUM_LOG_ENVIRONMENT in os.environ:
        yield
        return

    with TemporaryDirectory(
        prefix="telemetry-reporter-webview-",
        ignore_cleanup_errors=True,
    ) as temporary_directory:
        os.environ[_CHROMIUM_LOG_ENVIRONMENT] = str(Path(temporary_directory) / "chromium.log")
        try:
            yield
        finally:
            os.environ.pop(_CHROMIUM_LOG_ENVIRONMENT, None)


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
    diagnostics = parser.add_mutually_exclusive_group()
    diagnostics.add_argument("--self-test", action="store_true", help="validate packaged resources")
    diagnostics.add_argument(
        "--ui-smoke-test",
        action="store_true",
        help="exercise the off-screen Windows WebView2 application path",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def run_self_test() -> None:
    """Exercise packaged data, validation, analysis, and rendering without a window."""
    _validate_packaged_static_files()
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


def _validate_packaged_static_files() -> None:
    """Ensure files promised beside a frozen executable were collected by PyInstaller."""
    if not getattr(sys, "frozen", False):
        return
    executable_directory = Path(sys.executable).resolve().parent
    missing = [
        name
        for name in ("LICENSE", "README.txt", "Telemetry Reporter.exe.config")
        if not (executable_directory / name).is_file()
    ]
    if missing:
        raise RuntimeError(f"packaged static files are missing: {', '.join(missing)}")


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


def _run_ui_smoke(window: Any, result: UiSmokeResult) -> None:
    """Exercise the loaded desktop page through the real pywebview bridge."""
    callback_complete = Event()
    callback_result: dict[str, object] = {}

    def receive(value: object) -> None:
        callback_result["value"] = value
        callback_complete.set()

    try:
        if not window.events.loaded.wait(_UI_SMOKE_TIMEOUT_SECONDS):
            raise TimeoutError("the desktop page did not finish loading")
        window.evaluate_js(_UI_SMOKE_SCRIPT, callback=receive)
        if not callback_complete.wait(_UI_SMOKE_TIMEOUT_SECONDS):
            raise TimeoutError("the desktop smoke script did not complete")
        value = callback_result.get("value")
        if not isinstance(value, dict):
            raise RuntimeError(f"the desktop smoke script returned {value!r}")
        failures = [name for name, passed in value.items() if passed is not True]
        if failures:
            raise RuntimeError(f"desktop smoke assertions failed: {', '.join(failures)}")
    except Exception as error:
        result.error = str(error)
    finally:
        try:
            window.destroy()
        except Exception as error:
            if result.error is None:
                result.error = f"could not close the smoke-test window: {error}"


def _launch_gui(*, smoke_test: bool = False) -> int:
    if sys.platform != "win32":
        print("error: the desktop application currently supports Windows x64 only", file=sys.stderr)
        return 2
    if _webview2_runtime_version() is None:
        if smoke_test:
            print("error: Microsoft Edge WebView2 Runtime is required", file=sys.stderr)
            return 2
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
    smoke_result = UiSmokeResult()
    window: Any | None = None
    try:
        with as_file(app_resource) as app_path:
            window = webview.create_window(
                "Spacecraft Telemetry Pass Reporter",
                url=app_path.as_uri(),
                js_api=bridge,
                width=1180,
                height=780,
                x=-32000 if smoke_test else None,
                y=-32000 if smoke_test else None,
                min_size=(720, 640),
                background_color="#edf2f6",
                text_select=True,
                zoomable=True,
                focus=not smoke_test,
            )
            if window is None:
                raise RuntimeError("pywebview did not create a desktop window")
            bridge.bind_dialogs(PywebviewDialogs(window, webview))
            with _temporary_chromium_log():
                if smoke_test:
                    webview.start(
                        _run_ui_smoke,
                        (window, smoke_result),
                        gui="edgechromium",
                        private_mode=True,
                    )
                else:
                    webview.start(gui="edgechromium", private_mode=True)
    except Exception as error:
        if smoke_test:
            message = f"Desktop UI smoke test could not start: {error}"
            if window is not None:
                try:
                    window.destroy()
                except Exception as cleanup_error:
                    message = f"{message}; could not close the window: {cleanup_error}"
            print(message, file=sys.stderr)
        else:
            _native_message(f"The desktop application could not start:\n\n{error}")
        return 3
    if smoke_test and smoke_result.error is not None:
        print(f"Desktop UI smoke test failed: {smoke_result.error}", file=sys.stderr)
        return 1
    if smoke_test:
        print("Desktop UI smoke test passed")
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
    if arguments.ui_smoke_test:
        return _launch_gui(smoke_test=True)
    return _launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
