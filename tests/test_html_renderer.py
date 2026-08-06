from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from telemetry_report.data import load_telemetry_pass
from telemetry_report.domain import Status, TelemetryPass
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass


def test_report_contains_key_analysis_content(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    analysis = analyse_pass(pass_factory(((3.8, 25.0, -80.0), (3.4, 50.0, -105.0))))

    html = render_report(analysis)

    assert "<!doctype html>" in html
    assert "Spacecraft Telemetry Pass Report" in html
    assert "Overall: Critical" in html
    assert "Metric statistics and limits" in html
    assert "Out-of-limit occurrences" in html
    assert "Chronological telemetry" in html
    assert "3.40 V" in html
    assert "50.0 °C" in html
    assert "arithmetic mean of dBm samples" in html
    assert "not equivalent to averaging received power" in html
    assert "not intended for mission use" in html
    assert "https://" not in html


def test_report_escapes_untrusted_spacecraft_and_pass_identifiers(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    telemetry_pass = pass_factory(
        ((3.8, 25.0, -80.0),),
        '<img src=x onerror="alert(1)">',
        "<script>alert('spacecraft')</script>",
    )

    html = render_report(analyse_pass(telemetry_pass))

    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert" in html
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in html


def test_nominal_report_explains_empty_occurrence_list(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    html = render_report(analyse_pass(pass_factory(((3.8, 25.0, -80.0),))))

    assert "Overall: Nominal" in html
    assert "No out-of-limit metric occurrences were recorded" in html
    assert "The single reading remained" in html


def test_report_preserves_additional_measurement_and_threshold_precision(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    telemetry_pass = pass_factory(((3.6005, 25.0, -80.0), (3.4005, 26.0, -81.0)))
    battery_limit = replace(
        telemetry_pass.limits.battery_voltage,
        warning=3.6004,
        critical=3.4004,
    )
    telemetry_pass = replace(
        telemetry_pass,
        limits=replace(telemetry_pass.limits, battery_voltage=battery_limit),
    )

    analysis = analyse_pass(telemetry_pass)
    html = render_report(analysis)

    assert analysis.readings[0].metric_statuses.battery_voltage is Status.NOMINAL
    assert analysis.readings[1].metric_statuses.battery_voltage is Status.WARNING
    assert "3.6005 V" in html
    assert "3.4005 V" in html
    assert "Warning at or below 3.6004 V; critical at or below 3.4004 V" in html
    assert "<dt>Minimum</dt><dd>3.4005</dd>" in html
    assert "<dt>Average</dt><dd>3.50</dd>" in html
    assert "<dt>Maximum</dt><dd>3.6005</dd>" in html


def test_report_preserves_fractional_timestamps_across_all_sections(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    telemetry_pass = pass_factory(((3.6, 25.0, -80.0), (3.4, 25.0, -80.0)))
    first_timestamp = telemetry_pass.started_at + timedelta(microseconds=100_000)
    second_timestamp = telemetry_pass.started_at + timedelta(microseconds=900_000)
    readings = (
        replace(telemetry_pass.readings[0], timestamp=first_timestamp),
        replace(telemetry_pass.readings[1], timestamp=second_timestamp),
    )
    telemetry_pass = replace(telemetry_pass, started_at=first_timestamp, readings=readings)

    html = render_report(analyse_pass(telemetry_pass))

    assert html.count("2026-08-05T09:30:00.100000+09:30") == 3
    assert html.count("2026-08-05T09:30:00.900000+09:30") == 2


@pytest.mark.parametrize(
    ("value", "measurement", "average"),
    [
        (1e308, "1e+308 V", "1.00e+308"),
        (1e-308, "1e-308 V", "1.00e-308"),
    ],
)
def test_report_uses_compact_scientific_notation_for_extreme_values(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
    value: float,
    measurement: str,
    average: str,
) -> None:
    html = render_report(analyse_pass(pass_factory(((value, 25.0, -80.0),))))

    assert measurement in html
    assert f"<dt>Average</dt><dd>{average}</dd>" in html


@pytest.mark.parametrize(
    ("sample_name", "example_name"),
    [
        ("nominal-pass.json", "nominal-pass-report.html"),
        ("anomalous-pass.json", "anomalous-pass-report.html"),
    ],
)
def test_checked_in_example_matches_fresh_render(sample_name: str, example_name: str) -> None:
    root = Path(__file__).parents[1]
    analysis = analyse_pass(load_telemetry_pass(root / "sample-data" / sample_name))

    assert render_report(analysis) == (root / "examples" / example_name).read_text(encoding="utf-8")
