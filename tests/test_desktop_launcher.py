from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

import telemetry_report.desktop.launcher as launcher
from telemetry_report.desktop.bridge import DesktopBridge


class FakeWindow:
    def __init__(self, responses: list[tuple[str, ...] | None] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[tuple[object, dict[str, object]]] = []

    def create_file_dialog(self, dialog_type: object, **kwargs: object) -> tuple[str, ...] | None:
        self.calls.append((dialog_type, kwargs))
        return self.responses.pop(0) if self.responses else None


def _fake_webview(window: FakeWindow, *, fail_start: bool = False) -> ModuleType:
    module = ModuleType("webview")
    module.FileDialog = SimpleNamespace(OPEN="open", SAVE="save")
    module.created = []
    module.started = []

    def create_window(title: str, **kwargs: object) -> FakeWindow:
        module.created.append((title, kwargs))
        return window

    def start(**kwargs: object) -> None:
        module.started.append(kwargs)
        if fail_start:
            raise RuntimeError("simulated WebView startup failure")

    module.create_window = create_window
    module.start = start
    return module


def test_pywebview_dialog_adapter_maps_native_results(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    json_path = tmp_path / "saved.json"
    report_path = tmp_path / "saved.html"
    window = FakeWindow([(str(input_path),), (str(json_path),), (str(report_path),), None])
    module = _fake_webview(window)
    dialogs = launcher.PywebviewDialogs(window, module)

    assert dialogs.open_json() == input_path
    assert dialogs.save_json("suggested.json") == json_path
    assert dialogs.save_report("suggested.html") == report_path
    assert dialogs.open_json() is None
    assert window.calls == [
        (
            "open",
            {"allow_multiple": False, "file_types": ("Telemetry JSON (*.json)",)},
        ),
        (
            "save",
            {
                "save_filename": "suggested.json",
                "file_types": ("Telemetry JSON (*.json)",),
            },
        ),
        (
            "save",
            {
                "save_filename": "suggested.html",
                "file_types": ("HTML report (*.html)",),
            },
        ),
        (
            "open",
            {"allow_multiple": False, "file_types": ("Telemetry JSON (*.json)",)},
        ),
    ]


def test_runtime_detection_skips_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "linux")

    assert launcher._webview2_runtime_version() is None


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([OSError("not installed"), "123.4.5.6"], "123.4.5.6"),
        (["0.0.0.0", ""], None),
    ],
)
def test_runtime_detection_uses_documented_registry_locations(
    monkeypatch: pytest.MonkeyPatch,
    versions: list[object],
    expected: str | None,
) -> None:
    fake_winreg = ModuleType("winreg")
    fake_winreg.HKEY_LOCAL_MACHINE = "machine"
    fake_winreg.HKEY_CURRENT_USER = "user"
    opened: list[tuple[object, str]] = []

    class Key:
        def __init__(self, value: object) -> None:
            self.value = value

        def __enter__(self) -> Key:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def open_key(hive: object, path: str) -> Key:
        opened.append((hive, path))
        value = versions[len(opened) - 1]
        if isinstance(value, OSError):
            raise value
        return Key(value)

    def query_value(key: Key, _name: str) -> tuple[object, int]:
        return key.value, 0

    fake_winreg.OpenKey = open_key
    fake_winreg.QueryValueEx = query_value
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(launcher.sys, "platform", "win32")

    assert launcher._webview2_runtime_version() == expected
    assert all(launcher._WEBVIEW2_CLIENT_ID in path for _, path in opened)


def test_native_message_uses_question_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    class User32:
        @staticmethod
        def MessageBoxW(*args: object) -> int:
            calls.append(args)
            return 6

    monkeypatch.setattr(launcher.ctypes, "windll", SimpleNamespace(user32=User32()), raising=False)

    assert launcher._native_message("Open the page?", question=True) is True
    assert calls[0][-1] == 0x34


def test_launch_gui_rejects_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "linux")

    assert launcher._launch_gui() == 2
    assert "supports Windows x64 only" in capsys.readouterr().err


def test_launch_gui_offers_webview2_download(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_webview2_runtime_version", lambda: None)
    monkeypatch.setattr(launcher, "_native_message", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    assert launcher._launch_gui() == 2
    assert opened == [launcher._WEBVIEW2_DOWNLOAD_URL]


def test_launch_gui_reports_missing_desktop_dependency(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def blocking_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "webview":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_webview2_runtime_version", lambda: "123")
    monkeypatch.setattr(builtins, "__import__", blocking_import)

    assert launcher._launch_gui() == 2
    assert ".[desktop]" in capsys.readouterr().out


def test_launch_gui_forces_edgechromium_and_binds_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = FakeWindow()
    module = _fake_webview(window)
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_webview2_runtime_version", lambda: "123")
    monkeypatch.setitem(sys.modules, "webview", module)

    assert launcher._launch_gui() == 0
    assert module.started == [{"gui": "edgechromium", "private_mode": True}]
    title, options = module.created[0]
    assert title == "Spacecraft Telemetry Pass Reporter"
    assert options["min_size"] == (720, 640)
    assert isinstance(options["js_api"], DesktopBridge)


def test_launch_gui_surfaces_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _fake_webview(FakeWindow(), fail_start=True)
    messages: list[str] = []
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "_webview2_runtime_version", lambda: "123")
    monkeypatch.setattr(
        launcher, "_native_message", lambda message, **_kwargs: messages.append(message) or False
    )
    monkeypatch.setitem(sys.modules, "webview", module)

    assert launcher._launch_gui() == 3
    assert "simulated WebView startup failure" in messages[0]


def test_desktop_main_reports_self_test_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail() -> None:
        raise RuntimeError("simulated self-test failure")

    monkeypatch.setattr(launcher, "run_self_test", fail)

    assert launcher.main(["--self-test"]) == 1
    assert "simulated self-test failure" in capsys.readouterr().err


def test_desktop_main_delegates_normal_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "_launch_gui", lambda: 7)

    assert launcher.main([]) == 7
