from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from telemetry_report.data import (
    TelemetryDataError,
    load_telemetry_pass,
    validate_telemetry_json,
)
from telemetry_report.data.json_repository import _MAX_INPUT_BYTES
from telemetry_report.data.schemas import _MAX_READINGS
from telemetry_report.domain import LimitDirection


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_padded_payload(path: Path, payload: dict[str, object], size: int) -> None:
    encoded_payload = json.dumps(payload).encode("utf-8")
    assert len(encoded_payload) <= size
    path.write_bytes(encoded_payload + b" " * (size - len(encoded_payload)))


def _payload_with_reading_count(payload: dict[str, object], count: int) -> dict[str, object]:
    result = copy.deepcopy(payload)
    started_at_value = result["started_at"]
    readings = result["readings"]
    assert isinstance(started_at_value, str)
    assert isinstance(readings, list)
    assert readings
    assert isinstance(readings[0], dict)
    started_at = datetime.fromisoformat(started_at_value)
    first_reading = readings[0]
    result["readings"] = [
        {
            **first_reading,
            "timestamp": (started_at + timedelta(seconds=index)).isoformat(),
        }
        for index in range(count)
    ]
    return result


def test_load_maps_valid_json_to_domain(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    input_path = tmp_path / "pass.json"
    _write_payload(input_path, valid_payload)

    telemetry_pass = load_telemetry_pass(input_path)

    assert telemetry_pass.pass_id == "PASS-TEST"
    assert telemetry_pass.started_at.utcoffset() is not None
    assert len(telemetry_pass.readings) == 2
    assert telemetry_pass.limits.battery_voltage.direction is LimitDirection.MINIMUM


def test_in_memory_validation_returns_normalized_payload(
    valid_payload: dict[str, object],
) -> None:
    valid_payload["pass_id"] = "  PASS-TEST  "

    validated = validate_telemetry_json(json.dumps(valid_payload))

    assert validated.telemetry_pass.pass_id == "PASS-TEST"
    assert validated.payload["pass_id"] == "PASS-TEST"


def test_in_memory_validation_exposes_structured_field_issues(
    valid_payload: dict[str, object],
) -> None:
    readings = valid_payload["readings"]
    assert isinstance(readings, list)
    assert isinstance(readings[0], dict)
    readings[0]["temperature_c"] = "not-a-number"

    with pytest.raises(TelemetryDataError) as caught:
        validate_telemetry_json(json.dumps(valid_payload))

    assert caught.value.issues
    assert caught.value.issues[0].path == "readings.0.temperature_c"
    assert "number" in caught.value.issues[0].message
    assert "readings.0.temperature_c" in str(caught.value)


def test_load_reports_missing_file_without_leaking_os_exception(tmp_path: Path) -> None:
    with pytest.raises(TelemetryDataError, match="could not read"):
        load_telemetry_pass(tmp_path / "missing.json")


def test_load_reports_invalid_utf8_as_data_error(tmp_path: Path) -> None:
    input_path = tmp_path / "invalid-encoding.json"
    input_path.write_bytes(b"\xff\xfe")

    with pytest.raises(TelemetryDataError, match="file must be UTF-8 encoded"):
        load_telemetry_pass(input_path)


def test_load_accepts_file_at_input_size_limit(
    tmp_path: Path, valid_payload: dict[str, object]
) -> None:
    input_path = tmp_path / "maximum-size.json"
    _write_padded_payload(input_path, valid_payload, _MAX_INPUT_BYTES)

    telemetry_pass = load_telemetry_pass(input_path)

    assert telemetry_pass.pass_id == "PASS-TEST"


def test_load_rejects_file_over_input_size_limit(
    tmp_path: Path, valid_payload: dict[str, object]
) -> None:
    input_path = tmp_path / "oversized.json"
    _write_padded_payload(input_path, valid_payload, _MAX_INPUT_BYTES + 1)

    with pytest.raises(TelemetryDataError, match="file exceeds the 5 MiB input limit"):
        load_telemetry_pass(input_path)


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


def test_load_accepts_maximum_reading_count(
    tmp_path: Path, valid_payload: dict[str, object]
) -> None:
    payload = _payload_with_reading_count(valid_payload, _MAX_READINGS)
    input_path = tmp_path / "maximum-readings.json"
    _write_payload(input_path, payload)

    telemetry_pass = load_telemetry_pass(input_path)

    assert len(telemetry_pass.readings) == _MAX_READINGS


def test_load_rejects_excessive_reading_count(
    tmp_path: Path, valid_payload: dict[str, object]
) -> None:
    payload = _payload_with_reading_count(valid_payload, _MAX_READINGS + 1)
    input_path = tmp_path / "too-many-readings.json"
    _write_payload(input_path, payload)

    with pytest.raises(TelemetryDataError, match="at most 10000 items"):
        load_telemetry_pass(input_path)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_load_rejects_non_finite_measurements(
    tmp_path: Path, valid_payload: dict[str, object], bad_value: float
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


@pytest.mark.parametrize("mutation", ["boolean", "numeric_string", "string_limit", "epoch"])
def test_load_rejects_coerced_json_types(
    tmp_path: Path, valid_payload: dict[str, object], mutation: str
) -> None:
    payload = copy.deepcopy(valid_payload)
    readings = payload["readings"]
    limits = payload["limits"]
    assert isinstance(readings, list)
    assert isinstance(readings[0], dict)
    assert isinstance(limits, dict)
    assert isinstance(limits["battery_voltage"], dict)

    if mutation == "boolean":
        readings[0]["battery_voltage"] = True
    elif mutation == "numeric_string":
        readings[0]["temperature_c"] = "27.5"
    elif mutation == "string_limit":
        limits["battery_voltage"]["warning"] = "3.6"
    else:
        payload["started_at"] = 1_785_886_200
        readings[0]["timestamp"] = 1_785_886_200

    input_path = tmp_path / "coerced-value.json"
    _write_payload(input_path, payload)

    with pytest.raises(TelemetryDataError, match="invalid telemetry data"):
        load_telemetry_pass(input_path)


def test_load_accepts_integer_json_numbers(
    tmp_path: Path, valid_payload: dict[str, object]
) -> None:
    readings = valid_payload["readings"]
    assert isinstance(readings, list)
    assert isinstance(readings[0], dict)
    readings[0]["temperature_c"] = 27
    input_path = tmp_path / "integer-value.json"
    _write_payload(input_path, valid_payload)

    telemetry_pass = load_telemetry_pass(input_path)

    assert telemetry_pass.readings[0].values.temperature_c == 27.0


def test_load_rejects_unknown_fields(tmp_path: Path, valid_payload: dict[str, object]) -> None:
    valid_payload["unexpected"] = True
    input_path = tmp_path / "extra.json"
    _write_payload(input_path, valid_payload)

    with pytest.raises(TelemetryDataError, match="Extra inputs are not permitted"):
        load_telemetry_pass(input_path)
