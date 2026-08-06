"""Transform completed analysis results into an escaped HTML report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import cache

from jinja2 import Environment, PackageLoader, StrictUndefined, Template, select_autoescape

from telemetry_report.domain.models import (
    LimitDirection,
    OperatingLimit,
    PassAnalysis,
)
from telemetry_report.metrics import METRICS, METRICS_BY_METRIC, MetricDefinition


@dataclass(frozen=True, slots=True)
class MetricSummaryView:
    label: str
    unit: str
    minimum: str
    maximum: str
    average: str
    direction: str
    threshold_description: str
    average_note: str | None


@dataclass(frozen=True, slots=True)
class MetricCellView:
    unit: str
    value: str
    status: str
    status_label: str


@dataclass(frozen=True, slots=True)
class ReadingRowView:
    timestamp: str
    status: str
    status_label: str
    metrics: tuple[MetricCellView, ...]


@dataclass(frozen=True, slots=True)
class OccurrenceView:
    timestamp: str
    metric_label: str
    value: str
    unit: str
    status: str
    status_label: str


@dataclass(frozen=True, slots=True)
class ReportView:
    pass_id: str
    spacecraft: str
    started_at: str
    overall_status: str
    overall_status_label: str
    operational_summary: str
    total_readings: int
    nominal_count: int
    warning_count: int
    critical_count: int
    metric_summaries: tuple[MetricSummaryView, ...]
    occurrences: tuple[OccurrenceView, ...]
    readings: tuple[ReadingRowView, ...]


def _format_number(value: float, decimals: int) -> str:
    representation = str(value)
    if "e" in representation.lower():
        return f"{value:.{decimals}e}"

    formatted = f"{value:.{decimals}f}"
    if value != 0.0 and float(formatted) == 0.0:
        return f"{value:.{decimals}e}"
    return formatted


def _format_measurement(value: float, minimum_decimals: int) -> str:
    representation = str(value)
    if "e" in representation.lower():
        return representation

    exponent = Decimal(representation).as_tuple().exponent
    if not isinstance(exponent, int):
        return _format_number(value, minimum_decimals)
    return _format_number(value, max(minimum_decimals, -exponent))


def _format_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="auto")


def _threshold_description(limit: OperatingLimit, metric: MetricDefinition) -> str:
    warning = _format_measurement(limit.warning, metric.report_decimals)
    critical = _format_measurement(limit.critical, metric.report_decimals)
    if limit.direction is LimitDirection.MINIMUM:
        return (
            f"Warning at or below {warning} {metric.unit}; "
            f"critical at or below {critical} {metric.unit}"
        )
    return (
        f"Warning at or above {warning} {metric.unit}; "
        f"critical at or above {critical} {metric.unit}"
    )


def _build_view(analysis: PassAnalysis) -> ReportView:
    telemetry_pass = analysis.telemetry_pass
    metric_summaries: list[MetricSummaryView] = []
    for metric in METRICS:
        statistics = analysis.statistics.for_metric(metric.metric)
        limit = telemetry_pass.limits.for_metric(metric.metric)
        metric_summaries.append(
            MetricSummaryView(
                label=metric.label,
                unit=metric.unit,
                minimum=_format_measurement(statistics.minimum, metric.report_decimals),
                maximum=_format_measurement(statistics.maximum, metric.report_decimals),
                average=_format_number(statistics.average, metric.report_decimals),
                direction=limit.direction.value,
                threshold_description=_threshold_description(limit, metric),
                average_note=metric.average_note,
            )
        )

    reading_rows: list[ReadingRowView] = []
    for result in analysis.readings:
        cells = tuple(
            MetricCellView(
                unit=metric.unit,
                value=_format_measurement(
                    result.reading.values.for_metric(metric.metric), metric.report_decimals
                ),
                status=result.metric_statuses.for_metric(metric.metric).value,
                status_label=result.metric_statuses.for_metric(metric.metric).value.title(),
            )
            for metric in METRICS
        )
        reading_rows.append(
            ReadingRowView(
                timestamp=_format_timestamp(result.reading.timestamp),
                status=result.status.value,
                status_label=result.status.value.title(),
                metrics=cells,
            )
        )

    occurrences: list[OccurrenceView] = []
    for occurrence in analysis.occurrences:
        metric = METRICS_BY_METRIC[occurrence.metric]
        occurrences.append(
            OccurrenceView(
                timestamp=_format_timestamp(occurrence.timestamp),
                metric_label=metric.label,
                value=_format_measurement(occurrence.value, metric.report_decimals),
                unit=metric.unit,
                status=occurrence.status.value,
                status_label=occurrence.status.value.title(),
            )
        )

    return ReportView(
        pass_id=telemetry_pass.pass_id,
        spacecraft=telemetry_pass.spacecraft,
        started_at=_format_timestamp(telemetry_pass.started_at),
        overall_status=analysis.overall_status.value,
        overall_status_label=analysis.overall_status.value.title(),
        operational_summary=analysis.operational_summary,
        total_readings=analysis.counts.total,
        nominal_count=analysis.counts.nominal,
        warning_count=analysis.counts.warning,
        critical_count=analysis.counts.critical,
        metric_summaries=tuple(metric_summaries),
        occurrences=tuple(occurrences),
        readings=tuple(reading_rows),
    )


@cache
def _report_template() -> Template:
    environment = Environment(
        loader=PackageLoader("telemetry_report", "presentation/templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "jinja"), default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template("report.html.jinja")


def render_report(analysis: PassAnalysis) -> str:
    """Render ``analysis`` as a self-contained, auto-escaped HTML document."""
    return _report_template().render(report=_build_view(analysis))
