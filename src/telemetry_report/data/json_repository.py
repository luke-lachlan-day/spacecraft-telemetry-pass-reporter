"""Load and validate telemetry passes from JSON files."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from telemetry_report.data.schemas import TelemetryPassSchema
from telemetry_report.domain.models import TelemetryPass


class TelemetryDataError(Exception):
    """An expected, user-actionable failure while loading telemetry data."""


def _validation_message(error: ValidationError) -> str:
    problems: list[str] = []
    for detail in error.errors(include_url=False):
        location = ".".join(str(part) for part in detail["loc"])
        problems.append(f"{location or 'input'}: {detail['msg']}")
    return "; ".join(problems)


def load_telemetry_pass(path: Path) -> TelemetryPass:
    """Read ``path``, validate its JSON, and return immutable domain data."""
    try:
        raw_input = path.read_text(encoding="utf-8")
    except OSError as error:
        raise TelemetryDataError(f"could not read '{path}': {error}") from error

    try:
        schema = TelemetryPassSchema.model_validate_json(raw_input)
    except ValidationError as error:
        raise TelemetryDataError(
            f"invalid telemetry data in '{path}': {_validation_message(error)}"
        ) from error

    return schema.to_domain()
