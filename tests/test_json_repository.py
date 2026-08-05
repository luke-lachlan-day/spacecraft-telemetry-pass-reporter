from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from telemetry_report.data import TelemetryDataError, load_telemetry_pass
from telemetry_report.domain import LimitDirection


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_maps_valid_json_to_domain(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    input_path = tmp_path / "pass.json"
    _write_payload(input_path, valid_payload)

    telemetry_pass = load_telemetry_pass(input_path)

    assert telemetry_pass.pass_id == "PASS-TEST"
    assert telemetry_pass.started_at.utcoffset() is not None
    assert len(telemetry_pass.readings) == 2
    assert telemetry_pass.limits.battery_voltage.direction is LimitDirection.MINIMUM


def test_load_reports_missing_file_without_leaking_os_exception(tmp_path: Path) -> None:
    with pytest.raises(TelemetryDataError, match="could not read"):
        load_telemetry_pass(tmp_path / "missing.json")


@pytest.mark.parametrize("content", ["{not json", "[]", "{}"])
def test_load_reports_malformed_or_wrongly_shaped_json(tmp_path: Path, content: str) -> None:
    input_path = tmp_path / "invalid.json"
    input_path.write_text(content, encoding="utf-8")

    with pytest.raises(TelemetryDataError, match="invalid telemetry data"):
        load_telemetry_pass(input_path)


@pytest.mark.parametrize(
    ("direction", "warning", "critical", "message"),
    [
        ("minimum", 3.4, 3.4, "warning to be greater"),
        ("minimum", 3.3, 3.4, "warning to be greater"),
        ("maximum", 50.0, 50.0, "warning to be less"),
        ("maximum", 51.0, 50.0, "warning to be less"),
    ],
)
def test_load_rejects_invalid_threshold_order(
    tmp_path: Path,
    valid_payload: dict[str, object],
    direction: str,
    warning: float,
    critical: float,
    message: str,
) -> None:
    payload = copy.deepcopy(valid_payload)
    limits = payload["limits"]
    assert isinstance(limits, dict)
    limits["battery_voltage"] = {
        "direction": direction,
        "warning": warning,
        "critical": critical,
    }
    input_path = tmp_path / "invalid-limits.json"
    _write_payload(input_path, payload)

    with pytest.raises(TelemetryDataError, match=message):
        load_telemetry_pass(input_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("empty", "at least 1 item"),
        ("duplicate", "unique"),
        ("reversed", "chronological"),
        ("wrong_start", "started_at must equal"),
        ("naive_start", "timezone"),
        ("naive_reading", "timezone"),
    ],
)
def test_load_rejects_invalid_timelines(
    tmp_path: Path,
    valid_payload: dict[str, object],
    mutation: str,
    message: str,
) -> None:
    payload = copy.deepcopy(valid_payload)
    readings = payload["readings"]
    assert isinstance(readings, list)
    if mutation == "empty":
        readings.clear()
    elif mutation == "duplicate":
        assert isinstance(readings[1], dict)
        assert isinstance(readings[0], dict)
        readings[1]["timestamp"] = readings[0]["timestamp"]
    elif mutation == "reversed":
        readings.reverse()
        payload["started_at"] = "2026-08-05T09:31:00+09:30"
    elif mutation == "wrong_start":
        payload["started_at"] = "2026-08-05T09:29:00+09:30"
    elif mutation == "naive_start":
        payload["started_at"] = "2026-08-05T09:30:00"
    else:
        assert isinstance(readings[0], dict)
        readings[0]["timestamp"] = "2026-08-05T09:30:00"
    input_path = tmp_path / "invalid-time.json"
    _write_payload(input_path, payload)

    with pytest.raises(TelemetryDataError, match=message):
        load_telemetry_pass(input_path)


@pytest.mark.parametrize("bad_value", ["NaN", "Infinity", "-Infinity"])
def test_load_rejects_non_finite_measurements(
    tmp_path: Path, valid_payload: dict[str, object], bad_value: str
) -> None:
    payload = copy.deepcopy(valid_payload)
    readings = payload["readings"]
    assert isinstance(readings, list)
    assert isinstance(readings[0], dict)
    readings[0]["temperature_c"] = bad_value
    input_path = tmp_path / "non-finite.json"
    _write_payload(input_path, payload)

    with pytest.raises(TelemetryDataError, match="finite number"):
        load_telemetry_pass(input_path)


def test_load_rejects_unknown_fields(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    valid_payload["unexpected"] = True
    input_path = tmp_path / "extra.json"
    _write_payload(input_path, valid_payload)

    with pytest.raises(TelemetryDataError, match="Extra inputs are not permitted"):
        load_telemetry_pass(input_path)
