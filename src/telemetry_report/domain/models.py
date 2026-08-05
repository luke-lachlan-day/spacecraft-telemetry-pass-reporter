"""Immutable application concepts used by the telemetry reporter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar


class Status(StrEnum):
    """Severity assigned to a metric, reading, or complete pass."""

    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Return the ordering value used to compare severities."""
        return {
            Status.NOMINAL: 0,
            Status.WARNING: 1,
            Status.CRITICAL: 2,
        }[self]


class LimitDirection(StrEnum):
    """Whether values become unsafe below or above a threshold."""

    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class TelemetryMetric(StrEnum):
    """Metrics supported by the demonstration input format."""

    BATTERY_VOLTAGE = "battery_voltage"
    TEMPERATURE_C = "temperature_c"
    SIGNAL_STRENGTH_DBM = "signal_strength_dbm"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MetricValues(Generic[T]):
    """A typed value for each supported telemetry metric."""

    battery_voltage: T
    temperature_c: T
    signal_strength_dbm: T

    def items(self) -> tuple[tuple[TelemetryMetric, T], ...]:
        """Return values in the stable order used by reports and events."""
        return (
            (TelemetryMetric.BATTERY_VOLTAGE, self.battery_voltage),
            (TelemetryMetric.TEMPERATURE_C, self.temperature_c),
            (TelemetryMetric.SIGNAL_STRENGTH_DBM, self.signal_strength_dbm),
        )

    def for_metric(self, metric: TelemetryMetric) -> T:
        """Return the value associated with ``metric``."""
        if metric is TelemetryMetric.BATTERY_VOLTAGE:
            return self.battery_voltage
        if metric is TelemetryMetric.TEMPERATURE_C:
            return self.temperature_c
        return self.signal_strength_dbm


@dataclass(frozen=True, slots=True)
class OperatingLimit:
    """Warning and critical thresholds for one metric."""

    direction: LimitDirection
    warning: float
    critical: float


@dataclass(frozen=True, slots=True)
class TelemetryReading:
    """One timestamped set of telemetry measurements."""

    timestamp: datetime
    values: MetricValues[float]


@dataclass(frozen=True, slots=True)
class TelemetryPass:
    """Validated pass metadata, limits, and chronological readings."""

    pass_id: str
    spacecraft: str
    started_at: datetime
    limits: MetricValues[OperatingLimit]
    readings: tuple[TelemetryReading, ...]


@dataclass(frozen=True, slots=True)
class MetricStatistics:
    """Descriptive values calculated across a pass."""

    minimum: float
    maximum: float
    average: float


@dataclass(frozen=True, slots=True)
class ReadingAnalysis:
    """Per-metric and aggregate severity for a telemetry reading."""

    reading: TelemetryReading
    metric_statuses: MetricValues[Status]
    status: Status


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    """A warning or critical metric occurrence in chronological order."""

    timestamp: datetime
    metric: TelemetryMetric
    value: float
    status: Status


@dataclass(frozen=True, slots=True)
class StatusCounts:
    """Counts of readings at each severity."""

    nominal: int
    warning: int
    critical: int

    @property
    def total(self) -> int:
        """Return the total number of analysed readings."""
        return self.nominal + self.warning + self.critical


@dataclass(frozen=True, slots=True)
class PassAnalysis:
    """Complete deterministic result produced for a telemetry pass."""

    telemetry_pass: TelemetryPass
    overall_status: Status
    readings: tuple[ReadingAnalysis, ...]
    events: tuple[TelemetryEvent, ...]
    statistics: MetricValues[MetricStatistics]
    counts: StatusCounts
    operational_summary: str
