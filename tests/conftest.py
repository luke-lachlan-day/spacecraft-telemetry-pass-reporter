from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

from telemetry_report.domain import (
    LimitDirection,
    MetricValues,
    OperatingLimit,
    TelemetryPass,
    TelemetryReading,
)


@pytest.fixture
def pass_factory() -> Callable[[tuple[tuple[float, float, float], ...], str, str], TelemetryPass]:
    def create(
        measurements: tuple[tuple[float, float, float], ...],
        pass_id: str = "PASS-TEST",
        spacecraft: str = "TEST-CRAFT",
    ) -> TelemetryPass:
        started_at = datetime(2026, 8, 5, 9, 30, tzinfo=timezone(timedelta(hours=9.5)))
        limits = MetricValues(
            battery_voltage=OperatingLimit(LimitDirection.MINIMUM, 3.6, 3.4),
            temperature_c=OperatingLimit(LimitDirection.MAXIMUM, 40.0, 50.0),
            signal_strength_dbm=OperatingLimit(LimitDirection.MINIMUM, -90.0, -105.0),
        )
        readings = tuple(
            TelemetryReading(
                timestamp=started_at + timedelta(minutes=index),
                values=MetricValues(
                    battery_voltage=battery,
                    temperature_c=temperature,
                    signal_strength_dbm=signal,
                ),
            )
            for index, (battery, temperature, signal) in enumerate(measurements)
        )
        return TelemetryPass(pass_id, spacecraft, started_at, limits, readings)

    return create


@pytest.fixture
def valid_payload() -> dict[str, object]:
    return {
        "pass_id": "PASS-TEST",
        "spacecraft": "TEST-CRAFT",
        "started_at": "2026-08-05T09:30:00+09:30",
        "limits": {
            "battery_voltage": {"direction": "minimum", "warning": 3.6, "critical": 3.4},
            "temperature_c": {"direction": "maximum", "warning": 40.0, "critical": 50.0},
            "signal_strength_dbm": {
                "direction": "minimum",
                "warning": -90.0,
                "critical": -105.0,
            },
        },
        "readings": [
            {
                "timestamp": "2026-08-05T09:30:00+09:30",
                "battery_voltage": 3.8,
                "temperature_c": 27.5,
                "signal_strength_dbm": -82.0,
            },
            {
                "timestamp": "2026-08-05T09:31:00+09:30",
                "battery_voltage": 3.7,
                "temperature_c": 29.5,
                "signal_strength_dbm": -85.0,
            },
        ],
    }
