from __future__ import annotations

import json
from pathlib import Path

from telemetry_report.cli import main


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cli_generates_report_and_creates_output_directory(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: object,
) -> None:
    input_path = tmp_path / "pass.json"
    output_path = tmp_path / "nested" / "report.html"
    _write_payload(input_path, valid_payload)

    exit_code = main([str(input_path), "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.is_file()
    assert "PASS-TEST" in output_path.read_text(encoding="utf-8")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
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


def test_cli_reports_invalid_input_without_traceback(tmp_path: Path, capsys: object) -> None:
    input_path = tmp_path / "broken.json"
    input_path.write_text("not-json", encoding="utf-8")

    exit_code = main([str(input_path)])

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert exit_code == 2
    assert captured.out == ""
    assert "error: invalid telemetry data" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_output_failure(
    tmp_path: Path,
    valid_payload: dict[str, object],
    capsys: object,
) -> None:
    input_path = tmp_path / "pass.json"
    blocked_parent = tmp_path / "not-a-directory"
    _write_payload(input_path, valid_payload)
    blocked_parent.write_text("file", encoding="utf-8")

    exit_code = main([str(input_path), "--output", str(blocked_parent / "report.html")])

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert exit_code == 3
    assert "could not generate" in captured.err
    assert "Traceback" not in captured.err
