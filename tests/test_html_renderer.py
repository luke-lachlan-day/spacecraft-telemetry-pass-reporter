from __future__ import annotations

from collections.abc import Callable

from telemetry_report.domain import TelemetryPass
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
    assert "Warning and critical events" in html
    assert "Chronological telemetry" in html
    assert "3.40 V" in html
    assert "50.0 °C" in html
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


def test_nominal_report_explains_empty_event_list(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    html = render_report(analyse_pass(pass_factory(((3.8, 25.0, -80.0),))))

    assert "Overall: Nominal" in html
    assert "No warning or critical metric events were recorded" in html
    assert "The single reading remained" in html
