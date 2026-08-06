"""Load and validate telemetry passes from JSON files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from telemetry_report.data.schemas import TelemetryPassSchema
from telemetry_report.domain.models import TelemetryPass

_MAX_INPUT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TelemetryValidationIssue:
    """One field-specific problem found at the untrusted JSON boundary."""

    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidatedTelemetry:
    """Validated domain data plus its normalized JSON-compatible payload."""

    telemetry_pass: TelemetryPass
    payload: dict[str, object]


class TelemetryDataError(Exception):
    """An expected, user-actionable failure while loading telemetry data."""

    def __init__(self, message: str, *, issues: tuple[TelemetryValidationIssue, ...] = ()) -> None:
        super().__init__(message)
        self.issues = issues


def _validation_issues(error: ValidationError) -> tuple[TelemetryValidationIssue, ...]:
    problems: list[TelemetryValidationIssue] = []
    for detail in error.errors(include_url=False):
        location = ".".join(str(part) for part in detail["loc"])
        problems.append(
            TelemetryValidationIssue(path=location or "input", message=str(detail["msg"]))
        )
    return tuple(problems)


def _validation_message(issues: tuple[TelemetryValidationIssue, ...]) -> str:
    return "; ".join(f"{issue.path}: {issue.message}" for issue in issues)


def read_telemetry_json(path: Path) -> str:
    """Read a bounded UTF-8 telemetry document without validating its contents."""
    try:
        with path.open("rb") as input_file:
            encoded_input = input_file.read(_MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise TelemetryDataError(f"could not read '{path}': {error}") from error

    if len(encoded_input) > _MAX_INPUT_BYTES:
        raise TelemetryDataError(
            f"invalid telemetry data in '{path}': file exceeds the 5 MiB input limit"
        )

    try:
        return encoded_input.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TelemetryDataError(
            f"invalid telemetry data in '{path}': file must be UTF-8 encoded"
        ) from error


def validate_telemetry_json(raw_input: str, *, source: str = "input") -> ValidatedTelemetry:
    """Validate in-memory JSON and return normalized input plus immutable domain data."""
    try:
        schema = TelemetryPassSchema.model_validate_json(raw_input)
    except ValidationError as error:
        issues = _validation_issues(error)
        raise TelemetryDataError(
            f"invalid telemetry data in '{source}': {_validation_message(issues)}", issues=issues
        ) from error

    payload = cast(dict[str, object], schema.model_dump(mode="json"))
    return ValidatedTelemetry(telemetry_pass=schema.to_domain(), payload=payload)


def load_telemetry_pass(path: Path) -> TelemetryPass:
    """Read ``path``, validate its JSON, and return immutable domain data."""
    raw_input = read_telemetry_json(path)
    return validate_telemetry_json(raw_input, source=str(path)).telemetry_pass
