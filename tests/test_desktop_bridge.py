from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from telemetry_report.desktop.bridge import DesktopBridge, safe_filename_stem
from telemetry_report.desktop.launcher import main as desktop_main
from telemetry_report.metrics import METRICS


@dataclass
class FakeDialogs:
    open_path: Path | None = None
    json_path: Path | None = None
    report_path: Path | None = None
    suggested_json: str | None = None
    suggested_report: str | None = None

    def open_json(self) -> Path | None:
        return self.open_path

    def save_json(self, suggested_name: str) -> Path | None:
        self.suggested_json = suggested_name
        return self.json_path

    def save_report(self, suggested_name: str) -> Path | None:
        self.suggested_report = suggested_name
        return self.report_path


def _payload_json(payload: dict[str, object]) -> str:
    return json.dumps(payload)


def test_bridge_configuration_serializes_the_shared_metric_catalog() -> None:
    result = DesktopBridge().get_configuration()

    assert result == {
        "metrics": [
            {
                "key": definition.metric.value,
                "slug": definition.slug,
                "label": definition.label,
                "unit": definition.unit,
                "report_decimals": definition.report_decimals,
                "average_note": definition.average_note,
                "quick": {
                    "default": definition.quick.default,
                    "minimum": definition.quick.minimum,
                    "maximum": definition.quick.maximum,
                    "step": definition.quick.step,
                    "decimals": definition.quick.decimals,
                },
                "limit": {
                    "direction": definition.default_limit.direction.value,
                    "warning": definition.default_limit.warning,
                    "critical": definition.default_limit.critical,
                },
            }
            for definition in METRICS
        ]
    }


def test_bridge_analysis_returns_summary_preview_and_opaque_id(
    valid_payload: dict[str, object],
) -> None:
    result = DesktopBridge().analyse(_payload_json(valid_payload))

    assert result["ok"] is True
    assert isinstance(result["analysis_id"], str)
    assert len(result["analysis_id"]) >= 24
    assert "<!doctype html>" in str(result["report_html"])
    summary = result["summary"]
    assert isinstance(summary, dict)
    assert summary["overall_status"] == "nominal"
    assert summary["counts"] == {"nominal": 2, "warning": 0, "critical": 0}
    assert summary["first_reading_metrics"] == {
        "battery_voltage": "nominal",
        "temperature_c": "nominal",
        "signal_strength_dbm": "nominal",
    }


def test_bridge_validation_returns_field_issues_and_invalidates_previous_result(
    valid_payload: dict[str, object], tmp_path: Path
) -> None:
    dialogs = FakeDialogs(report_path=tmp_path / "report.html")
    bridge = DesktopBridge(dialogs)
    successful = bridge.analyse(_payload_json(valid_payload))
    analysis_id = successful["analysis_id"]
    readings = valid_payload["readings"]
    assert isinstance(readings, list)
    assert isinstance(readings[0], dict)
    readings[0]["battery_voltage"] = "invalid"

    failed = bridge.analyse(_payload_json(valid_payload))

    assert failed["ok"] is False
    issues = failed["issues"]
    assert isinstance(issues, list)
    assert issues[0]["path"] == "readings.0.battery_voltage"
    assert bridge.save_report(str(analysis_id)) == {
        "ok": False,
        "error": "analysis result is missing or stale",
    }


def test_bridge_saves_only_latest_normalized_json_and_report(
    valid_payload: dict[str, object], tmp_path: Path
) -> None:
    json_path = tmp_path / "saved.json"
    report_path = tmp_path / "saved.html"
    dialogs = FakeDialogs(json_path=json_path, report_path=report_path)
    bridge = DesktopBridge(dialogs)
    result = bridge.analyse(_payload_json(valid_payload))
    analysis_id = str(result["analysis_id"])

    json_result = bridge.save_input_json(analysis_id)
    report_result = bridge.save_report(analysis_id)

    assert json_result["ok"] is True
    assert report_result["ok"] is True
    assert json_path.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(json_path.read_text(encoding="utf-8"))["pass_id"] == "PASS-TEST"
    assert "Telemetry Pass Report" in report_path.read_text(encoding="utf-8")
    assert dialogs.suggested_json == "PASS-TEST.json"
    assert dialogs.suggested_report == "PASS-TEST-report.html"


def test_bridge_dialog_cancellation_is_not_an_error(valid_payload: dict[str, object]) -> None:
    bridge = DesktopBridge(FakeDialogs())

    assert bridge.open_input_json() == {"ok": True, "cancelled": True}
    analysis = bridge.analyse(_payload_json(valid_payload))
    analysis_id = str(analysis["analysis_id"])
    assert bridge.save_input_json(analysis_id) == {"ok": True, "cancelled": True}
    assert bridge.save_report(analysis_id) == {"ok": True, "cancelled": True}


def test_bridge_rejects_file_operations_without_native_dialogs(
    valid_payload: dict[str, object],
) -> None:
    bridge = DesktopBridge()

    assert bridge.open_input_json() == {
        "ok": False,
        "error": "native file dialogs are unavailable",
        "issues": [],
    }
    analysis_id = str(bridge.analyse(_payload_json(valid_payload))["analysis_id"])
    assert bridge.save_input_json(analysis_id) == {
        "ok": False,
        "error": "native file dialogs are unavailable",
    }
    assert bridge.save_report(analysis_id) == {
        "ok": False,
        "error": "native file dialogs are unavailable",
    }


def test_bridge_rejects_wrong_analysis_id(valid_payload: dict[str, object]) -> None:
    bridge = DesktopBridge(FakeDialogs())
    bridge.analyse(_payload_json(valid_payload))

    assert bridge.save_report("another-analysis") == {
        "ok": False,
        "error": "analysis result is missing or stale",
    }


def test_bridge_reports_atomic_save_failure(
    valid_payload: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "blocked.json"
    bridge = DesktopBridge(FakeDialogs(json_path=destination))
    analysis_id = str(bridge.analyse(_payload_json(valid_payload))["analysis_id"])

    def fail_write(_path: Path, _content: str) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("telemetry_report.desktop.bridge.write_text_atomically", fail_write)

    result = bridge.save_input_json(analysis_id)

    assert result["ok"] is False
    assert str(destination) in str(result["error"])
    assert "simulated disk failure" in str(result["error"])


def test_bridge_opens_and_normalizes_valid_json(
    valid_payload: dict[str, object], tmp_path: Path
) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(_payload_json(valid_payload), encoding="utf-8")

    result = DesktopBridge(FakeDialogs(open_path=input_path)).open_input_json()

    assert result["ok"] is True
    assert result["cancelled"] is False
    assert json.loads(str(result["payload_json"]))["spacecraft"] == "TEST-CRAFT"


def test_bridge_reports_invalid_opened_json(tmp_path: Path) -> None:
    input_path = tmp_path / "invalid.json"
    input_path.write_text("{}", encoding="utf-8")

    result = DesktopBridge(FakeDialogs(open_path=input_path)).open_input_json()

    assert result["ok"] is False
    assert result["issues"]


@pytest.mark.parametrize("name", ["nominal", "anomalous"])
def test_packaged_examples_match_repository_samples(name: str) -> None:
    root = Path(__file__).parents[1]
    repository_payload = json.loads(
        (root / "sample-data" / f"{name}-pass.json").read_text(encoding="utf-8")
    )

    result = DesktopBridge().load_example(name)

    assert result["ok"] is True
    assert json.loads(str(result["payload_json"])) == repository_payload


def test_bridge_rejects_unknown_example() -> None:
    result = DesktopBridge().load_example("missing")

    assert result == {"ok": False, "error": "unknown example 'missing'", "issues": []}


@pytest.mark.parametrize(
    ("pass_id", "expected"),
    [
        (" PASS:01?/AUX. ", "PASS_01__AUX"),
        ("CON", "CON_"),
        ("CON.report", "CON_.report"),
        ("." * 100, "telemetry-pass"),
        ("A" * 100, "A" * 80),
    ],
)
def test_safe_filename_stem_handles_windows_rules(pass_id: str, expected: str) -> None:
    assert safe_filename_stem(pass_id) == expected


def test_safe_filename_stem_stays_bounded_after_reserved_name_fixup() -> None:
    stem = safe_filename_stem("CON." + "a" * 100)

    assert stem.startswith("CON_.")
    assert len(stem) == 80


def test_desktop_self_test_exercises_packaged_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert desktop_main(["--self-test"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Desktop self-test passed\n"
    assert captured.err == ""
