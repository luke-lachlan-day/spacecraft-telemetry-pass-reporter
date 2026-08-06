from __future__ import annotations

import json
import os
import stat
from importlib.metadata import version
from pathlib import Path

import pytest

from telemetry_report import __version__
from telemetry_report.cli import main
from telemetry_report.data.json_repository import _MAX_INPUT_BYTES


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


def test_cli_rejects_oversized_input_without_writing_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "oversized.json"
    output_path = tmp_path / "report.html"
    input_path.write_bytes(b" " * (_MAX_INPUT_BYTES + 1))

    assert main([str(input_path), "--output", str(output_path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "file exceeds the 5 MiB input limit" in captured.err
    assert "Traceback" not in captured.err
    assert not output_path.exists()


def test_cli_generates_report_for_extreme_finite_values(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    readings = valid_payload["readings"]
    assert isinstance(readings, list)
    for reading in readings:
        assert isinstance(reading, dict)
        reading["battery_voltage"] = 1e308
    input_path = tmp_path / "extreme.json"
    output_path = tmp_path / "extreme-report.html"
    _write_payload(input_path, valid_payload)

    assert main([str(input_path), "--output", str(output_path)]) == 0

    html = output_path.read_text(encoding="utf-8")
    assert "1e+308 V" in html
    assert "<dt>Average</dt><dd>1.00e+308</dd>" in html
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Traceback" not in captured.out


def test_cli_retries_temporary_file_name_collision(
    tmp_path: Path,
    valid_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "report.html"
    collision_path = tmp_path / ".report.html.collision.tmp"
    _write_payload(input_path, valid_payload)
    collision_path.write_text("keep me", encoding="utf-8")
    tokens = iter(("collision", "available"))
    monkeypatch.setattr("telemetry_report.cli.secrets.token_hex", lambda _size: next(tokens))

    assert main([str(input_path), "--output", str(output_path)]) == 0

    assert collision_path.read_text(encoding="utf-8") == "keep me"
    assert not (tmp_path / ".report.html.available.tmp").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_cli_new_report_permissions_respect_umask(
    tmp_path: Path,
    valid_payload: dict[str, object],
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "report.html"
    _write_payload(input_path, valid_payload)
    previous_umask = os.umask(0o027)
    try:
        assert main([str(input_path), "--output", str(output_path)]) == 0
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_cli_existing_report_permissions_survive_replacement(
    tmp_path: Path,
    valid_payload: dict[str, object],
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "report.html"
    _write_payload(input_path, valid_payload)
    output_path.write_text("existing", encoding="utf-8")
    output_path.chmod(0o604)

    assert main([str(input_path), "--output", str(output_path)]) == 0

    assert stat.S_IMODE(output_path.stat().st_mode) == 0o604


def test_package_version_comes_from_distribution_metadata() -> None:
    assert __version__ == version("spacecraft-telemetry-pass-reporter")
