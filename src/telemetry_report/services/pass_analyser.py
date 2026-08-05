"""Pure, deterministic analysis rules for validated telemetry passes."""

from __future__ import annotations

from statistics import fmean

from telemetry_report.domain.models import (
    LimitDirection,
    MetricStatistics,
    MetricValues,
    OperatingLimit,
    OutOfLimitOccurrence,
    PassAnalysis,
    ReadingAnalysis,
    Status,
    StatusCounts,
    TelemetryMetric,
    TelemetryPass,
    TelemetryReading,
)


def evaluate_metric(value: float, limit: OperatingLimit) -> Status:
    """Classify one value using the configured inclusive threshold rules."""
    if limit.direction is LimitDirection.MINIMUM:
        if value <= limit.critical:
            return Status.CRITICAL
        if value <= limit.warning:
            return Status.WARNING
        return Status.NOMINAL

    if value >= limit.critical:
        return Status.CRITICAL
    if value >= limit.warning:
        return Status.WARNING
    return Status.NOMINAL


def _worst_status(statuses: MetricValues[Status]) -> Status:
    return max((status for _, status in statuses.items()), key=lambda status: status.rank)


def _analyse_reading(
    reading: TelemetryReading, limits: MetricValues[OperatingLimit]
) -> ReadingAnalysis:
    statuses = MetricValues(
        battery_voltage=evaluate_metric(reading.values.battery_voltage, limits.battery_voltage),
        temperature_c=evaluate_metric(reading.values.temperature_c, limits.temperature_c),
        signal_strength_dbm=evaluate_metric(
            reading.values.signal_strength_dbm, limits.signal_strength_dbm
        ),
    )
    return ReadingAnalysis(
        reading=reading, metric_statuses=statuses, status=_worst_status(statuses)
    )


def _statistics(readings: tuple[TelemetryReading, ...]) -> MetricValues[MetricStatistics]:
    def for_metric(metric: TelemetryMetric) -> MetricStatistics:
        values = [reading.values.for_metric(metric) for reading in readings]
        return MetricStatistics(minimum=min(values), maximum=max(values), average=fmean(values))

    return MetricValues(
        battery_voltage=for_metric(TelemetryMetric.BATTERY_VOLTAGE),
        temperature_c=for_metric(TelemetryMetric.TEMPERATURE_C),
        signal_strength_dbm=for_metric(TelemetryMetric.SIGNAL_STRENGTH_DBM),
    )


def _occurrences(readings: tuple[ReadingAnalysis, ...]) -> tuple[OutOfLimitOccurrence, ...]:
    occurrences: list[OutOfLimitOccurrence] = []
    for reading_result in readings:
        for metric, status in reading_result.metric_statuses.items():
            if status is not Status.NOMINAL:
                occurrences.append(
                    OutOfLimitOccurrence(
                        timestamp=reading_result.reading.timestamp,
                        metric=metric,
                        value=reading_result.reading.values.for_metric(metric),
                        status=status,
                    )
                )
    return tuple(occurrences)


def _counts(readings: tuple[ReadingAnalysis, ...]) -> StatusCounts:
    return StatusCounts(
        nominal=sum(reading.status is Status.NOMINAL for reading in readings),
        warning=sum(reading.status is Status.WARNING for reading in readings),
        critical=sum(reading.status is Status.CRITICAL for reading in readings),
    )


def _summary(counts: StatusCounts, occurrences: tuple[OutOfLimitOccurrence, ...]) -> str:
    critical_occurrences = sum(occurrence.status is Status.CRITICAL for occurrence in occurrences)
    warning_occurrences = sum(occurrence.status is Status.WARNING for occurrence in occurrences)
    reading_word = "reading" if counts.total == 1 else "readings"
    occurrence_word = "occurrence" if len(occurrences) == 1 else "occurrences"
    if counts.critical:
        return (
            f"Critical conditions occurred in {counts.critical} of {counts.total} {reading_word}. "
            f"The out-of-limit timeline contains {critical_occurrences} critical and "
            f"{warning_occurrences} warning metric {occurrence_word} for review."
        )
    if counts.warning:
        return (
            f"No critical conditions were detected. {counts.warning} of {counts.total} "
            f"{reading_word} entered warning ranges, producing {warning_occurrences} warning "
            f"metric {occurrence_word}."
        )
    if counts.total == 1:
        return "The single reading remained within the configured nominal operating ranges."
    return f"All {counts.total} readings remained within the configured nominal operating ranges."


def analyse_pass(telemetry_pass: TelemetryPass) -> PassAnalysis:
    """Analyse a validated pass without file, console, or rendering side effects."""
    if not telemetry_pass.readings:
        raise ValueError("a telemetry pass must contain at least one reading")

    reading_results = tuple(
        _analyse_reading(reading, telemetry_pass.limits) for reading in telemetry_pass.readings
    )
    occurrences = _occurrences(reading_results)
    counts = _counts(reading_results)
    overall_status = max(
        (reading.status for reading in reading_results), key=lambda status: status.rank
    )

    return PassAnalysis(
        telemetry_pass=telemetry_pass,
        overall_status=overall_status,
        readings=reading_results,
        occurrences=occurrences,
        statistics=_statistics(telemetry_pass.readings),
        counts=counts,
        operational_summary=_summary(counts, occurrences),
    )
