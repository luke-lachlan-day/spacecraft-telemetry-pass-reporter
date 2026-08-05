from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from telemetry_report.domain import (
    LimitDirection,
    MetricValues,
    OperatingLimit,
    Status,
    TelemetryMetric,
    TelemetryPass,
)
from telemetry_report.services import analyse_pass, evaluate_metric


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3.61, Status.NOMINAL),
        (3.60, Status.WARNING),
        (3.50, Status.WARNING),
        (3.40, Status.CRITICAL),
        (3.20, Status.CRITICAL),
    ],
)
def test_minimum_thresholds_are_inclusive(value: float, expected: Status) -> None:
    assert evaluate_metric(value, OperatingLimit(LimitDirection.MINIMUM, 3.6, 3.4)) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (39.9, Status.NOMINAL),
        (40.0, Status.WARNING),
        (45.0, Status.WARNING),
        (50.0, Status.CRITICAL),
        (51.0, Status.CRITICAL),
    ],
)
def test_maximum_thresholds_are_inclusive(value: float, expected: Status) -> None:
    assert evaluate_metric(value, OperatingLimit(LimitDirection.MAXIMUM, 40.0, 50.0)) is expected


def test_analysis_selects_worst_status_and_counts_readings(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    telemetry_pass = pass_factory(
        (
            (3.8, 25.0, -80.0),
            (3.6, 41.0, -85.0),
            (3.3, 35.0, -110.0),
        )
    )

    result = analyse_pass(telemetry_pass)

    assert result.overall_status is Status.CRITICAL
    assert [reading.status for reading in result.readings] == [
        Status.NOMINAL,
        Status.WARNING,
        Status.CRITICAL,
    ]
    assert result.counts.nominal == 1
    assert result.counts.warning == 1
    assert result.counts.critical == 1
    assert result.counts.total == 3
    assert "1 of 3 readings" in result.operational_summary


def test_analysis_calculates_summary_statistics(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    result = analyse_pass(
        pass_factory(((3.8, 20.0, -70.0), (3.6, 30.0, -80.0), (3.4, 40.0, -90.0)))
    )

    battery = result.statistics.battery_voltage
    temperature = result.statistics.temperature_c
    assert battery.minimum == pytest.approx(3.4)
    assert battery.maximum == pytest.approx(3.8)
    assert battery.average == pytest.approx(3.6)
    assert temperature.average == pytest.approx(30.0)


def test_occurrences_are_chronological_and_use_stable_metric_order(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    result = analyse_pass(pass_factory(((3.8, 40.0, -91.0), (3.4, 50.0, -105.0))))

    assert [(occurrence.metric, occurrence.status) for occurrence in result.occurrences] == [
        (TelemetryMetric.TEMPERATURE_C, Status.WARNING),
        (TelemetryMetric.SIGNAL_STRENGTH_DBM, Status.WARNING),
        (TelemetryMetric.BATTERY_VOLTAGE, Status.CRITICAL),
        (TelemetryMetric.TEMPERATURE_C, Status.CRITICAL),
        (TelemetryMetric.SIGNAL_STRENGTH_DBM, Status.CRITICAL),
    ]
    assert list(result.occurrences) == sorted(
        result.occurrences, key=lambda occurrence: occurrence.timestamp
    )


def test_nominal_and_warning_summaries_are_deterministic(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    nominal = analyse_pass(pass_factory(((3.8, 25.0, -80.0),)))
    warning = analyse_pass(pass_factory(((3.6, 25.0, -80.0),)))

    assert nominal.operational_summary == (
        "The single reading remained within the configured nominal operating ranges."
    )
    assert warning.operational_summary == (
        "No critical conditions were detected. 1 of 1 reading entered warning ranges, "
        "producing 1 warning metric occurrence."
    )


def test_analysis_rejects_empty_domain_pass(
    pass_factory: Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass],
) -> None:
    with pytest.raises(ValueError, match="at least one"):
        analyse_pass(pass_factory(()))


def test_metric_values_can_be_addressed_by_metric() -> None:
    values = MetricValues(battery_voltage=1, temperature_c=2, signal_strength_dbm=3)

    assert values.for_metric(TelemetryMetric.BATTERY_VOLTAGE) == 1
    assert values.for_metric(TelemetryMetric.TEMPERATURE_C) == 2
    assert values.for_metric(TelemetryMetric.SIGNAL_STRENGTH_DBM) == 3


def test_metric_values_reject_unknown_metric_at_runtime() -> None:
    values = MetricValues(battery_voltage=1, temperature_c=2, signal_strength_dbm=3)

    with pytest.raises(AssertionError):
        values.for_metric(cast(TelemetryMetric, "unsupported"))
