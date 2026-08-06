from __future__ import annotations

from telemetry_report.domain import LimitDirection, TelemetryMetric
from telemetry_report.metrics import METRICS, METRICS_BY_METRIC


def test_metric_catalog_is_complete_and_has_unique_stable_identifiers() -> None:
    assert {definition.metric for definition in METRICS} == set(TelemetryMetric)
    assert len({definition.metric.value for definition in METRICS}) == len(METRICS)
    assert len({definition.slug for definition in METRICS}) == len(METRICS)
    assert {definition.metric: definition for definition in METRICS} == METRICS_BY_METRIC


def test_metric_catalog_controls_and_limits_are_internally_consistent() -> None:
    for definition in METRICS:
        quick = definition.quick
        limit = definition.default_limit
        assert quick.minimum <= quick.default <= quick.maximum
        assert quick.step > 0
        assert quick.decimals >= 0
        assert definition.report_decimals >= 0
        if limit.direction is LimitDirection.MINIMUM:
            assert limit.critical < limit.warning
        else:
            assert limit.warning < limit.critical
