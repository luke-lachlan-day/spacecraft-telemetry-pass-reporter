"""Pydantic schemas defining the untrusted JSON input boundary."""

from __future__ import annotations

from itertools import pairwise
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from telemetry_report.domain.models import (
    LimitDirection,
    MetricValues,
    OperatingLimit,
    TelemetryPass,
    TelemetryReading,
)


class InputModel(BaseModel):
    """Strict base configuration shared by all input schemas."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class LimitSchema(InputModel):
    """Validated external representation of one operating limit."""

    direction: LimitDirection
    warning: FiniteFloat
    critical: FiniteFloat

    @model_validator(mode="after")
    def thresholds_follow_direction(self) -> Self:
        """Ensure warning is encountered before critical in the unsafe direction."""
        if self.direction is LimitDirection.MINIMUM and self.warning <= self.critical:
            raise ValueError("minimum limit requires warning to be greater than critical")
        if self.direction is LimitDirection.MAXIMUM and self.warning >= self.critical:
            raise ValueError("maximum limit requires warning to be less than critical")
        return self

    def to_domain(self) -> OperatingLimit:
        """Map validated external data to an immutable domain value."""
        return OperatingLimit(
            direction=self.direction,
            warning=float(self.warning),
            critical=float(self.critical),
        )


class LimitsSchema(InputModel):
    """Operating limits for all required metrics."""

    battery_voltage: LimitSchema
    temperature_c: LimitSchema
    signal_strength_dbm: LimitSchema

    def to_domain(self) -> MetricValues[OperatingLimit]:
        """Map each validated limit to the domain representation."""
        return MetricValues(
            battery_voltage=self.battery_voltage.to_domain(),
            temperature_c=self.temperature_c.to_domain(),
            signal_strength_dbm=self.signal_strength_dbm.to_domain(),
        )


class ReadingSchema(InputModel):
    """Validated external representation of one telemetry reading."""

    timestamp: AwareDatetime
    battery_voltage: FiniteFloat
    temperature_c: FiniteFloat
    signal_strength_dbm: FiniteFloat

    def to_domain(self) -> TelemetryReading:
        """Map a validated reading to the domain representation."""
        return TelemetryReading(
            timestamp=self.timestamp,
            values=MetricValues(
                battery_voltage=float(self.battery_voltage),
                temperature_c=float(self.temperature_c),
                signal_strength_dbm=float(self.signal_strength_dbm),
            ),
        )


class TelemetryPassSchema(InputModel):
    """Complete validated representation of a telemetry pass JSON document."""

    pass_id: str = Field(min_length=1, max_length=100)
    spacecraft: str = Field(min_length=1, max_length=100)
    started_at: AwareDatetime
    limits: LimitsSchema
    readings: list[ReadingSchema] = Field(min_length=1)

    @model_validator(mode="after")
    def readings_form_valid_timeline(self) -> Self:
        """Require a unique, strictly chronological timeline beginning at pass start."""
        timestamps = [reading.timestamp for reading in self.readings]
        if len(set(timestamps)) != len(timestamps):
            raise ValueError("reading timestamps must be unique")
        if any(current <= previous for previous, current in pairwise(timestamps)):
            raise ValueError("readings must be in strictly chronological order")
        if timestamps[0] != self.started_at:
            raise ValueError("started_at must equal the first reading timestamp")
        return self

    def to_domain(self) -> TelemetryPass:
        """Map validated input into framework-independent domain objects."""
        return TelemetryPass(
            pass_id=self.pass_id,
            spacecraft=self.spacecraft,
            started_at=self.started_at,
            limits=self.limits.to_domain(),
            readings=tuple(reading.to_domain() for reading in self.readings),
        )
