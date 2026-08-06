"""Shared metric presentation and desktop experiment configuration."""

from __future__ import annotations

from dataclasses import dataclass

from telemetry_report.domain.models import LimitDirection, OperatingLimit, TelemetryMetric


@dataclass(frozen=True, slots=True)
class QuickControl:
    """Input behaviour for one Quick Experiment measurement."""

    default: float
    minimum: float
    maximum: float
    step: float
    decimals: int


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One supported metric's shared labels, limits, and display behaviour."""

    metric: TelemetryMetric
    label: str
    unit: str
    report_decimals: int
    quick: QuickControl
    default_limit: OperatingLimit
    average_note: str | None = None

    @property
    def slug(self) -> str:
        """Return the stable HTML identifier fragment for this metric."""
        return self.metric.value.replace("_", "-")


METRICS = (
    MetricDefinition(
        metric=TelemetryMetric.BATTERY_VOLTAGE,
        label="Battery voltage",
        unit="V",
        report_decimals=2,
        quick=QuickControl(default=3.8, minimum=3.0, maximum=4.2, step=0.01, decimals=2),
        default_limit=OperatingLimit(
            direction=LimitDirection.MINIMUM,
            warning=3.6,
            critical=3.4,
        ),
    ),
    MetricDefinition(
        metric=TelemetryMetric.TEMPERATURE_C,
        label="Temperature",
        unit="°C",
        report_decimals=1,
        quick=QuickControl(default=25.0, minimum=-20.0, maximum=80.0, step=0.1, decimals=1),
        default_limit=OperatingLimit(
            direction=LimitDirection.MAXIMUM,
            warning=40.0,
            critical=50.0,
        ),
    ),
    MetricDefinition(
        metric=TelemetryMetric.SIGNAL_STRENGTH_DBM,
        label="Signal strength",
        unit="dBm",
        report_decimals=1,
        quick=QuickControl(default=-80.0, minimum=-120.0, maximum=-40.0, step=1.0, decimals=0),
        default_limit=OperatingLimit(
            direction=LimitDirection.MINIMUM,
            warning=-90.0,
            critical=-105.0,
        ),
        average_note=(
            "Average is the arithmetic mean of dBm samples; it is not equivalent to averaging "
            "received power."
        ),
    ),
)

METRICS_BY_METRIC = {definition.metric: definition for definition in METRICS}
