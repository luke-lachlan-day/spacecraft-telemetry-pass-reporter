from __future__ import annotations

import json
import os
from importlib.metadata import version
from pathlib import Path

import pytest

from telemetry_report import __version__
from telemetry_report.cli import main


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cli_generates_report_and_creates_output_directory(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "nested" / "report.html"
    _write_payload(input_path, valid_payload)

    exit_code = main([str(input_path), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.is_file()
    assert "PASS-TEST" in output_path.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert "Generated telemetry report" in captured.out
    assert str(output_path.resolve()) in captured.out
    assert captured.err == ""


def test_cli_uses_default_output_beside_input(
    tmp_path: Path, valid_payload: dict[str, object]
) -> None:
    input_path = tmp_path / "example.pass.json"
    _write_payload(input_path, valid_payload)

    assert main([str(input_path)]) == 0
    assert (tmp_path / "example.pass-report.html").is_file()


def test_cli_reports_invalid_input_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "broken.json"
    input_path.write_text("not-json", encoding="utf-8")

    exit_code = main([str(input_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "error: invalid telemetry data" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_output_failure(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "pass.json"
    blocked_parent = tmp_path / "not-a-directory"
    _write_payload(input_path, valid_payload)
    blocked_parent.write_text("file", encoding="utf-8")

    exit_code = main([str(input_path), "--output", str(blocked_parent / "report.html")])

    captured = capsys.readouterr()
    assert exit_code == 3
    assert "could not generate" in captured.err
    assert "Traceback" not in captured.err


def test_cli_rejects_identical_and_normalized_input_output_paths(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "pass.json"
    alias_parent = tmp_path / "alias"
    alias_parent.mkdir()
    _write_payload(input_path, valid_payload)
    original_content = input_path.read_bytes()

    for output_path in (input_path, alias_parent / ".." / input_path.name):
        assert main([str(input_path), "--output", str(output_path)]) == 2
        assert input_path.read_bytes() == original_content

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("input and output paths must refer to different files") == 2
    assert "Traceback" not in captured.err


def test_cli_rejects_hard_link_to_input(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "report.html"
    _write_payload(input_path, valid_payload)
    os.link(input_path, output_path)
    original_content = input_path.read_bytes()

    assert main([str(input_path), "--output", str(output_path)]) == 2
    assert input_path.read_bytes() == original_content
    assert output_path.read_bytes() == original_content
    assert "input and output paths must refer to different files" in capsys.readouterr().err


def test_cli_preserves_existing_report_when_atomic_replace_fails(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "report.html"
    _write_payload(input_path, valid_payload)
    output_path.write_text("existing report", encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("telemetry_report.cli.os.replace", fail_replace)

    assert main([str(input_path), "--output", str(output_path)]) == 3
    assert output_path.read_text(encoding="utf-8") == "existing report"
    assert list(tmp_path.glob(f".{output_path.name}.*.tmp")) == []
    captured = capsys.readouterr()
    assert "simulated replacement failure" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_invalid_utf8_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "invalid-encoding.json"
    input_path.write_bytes(b"\xff\xfe")

    assert main([str(input_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "file must be UTF-8 encoded" in captured.err
    assert "Traceback" not in captured.err


def test_package_version_comes_from_distribution_metadata() -> None:
    assert __version__ == version("spacecraft-telemetry-pass-reporter")
