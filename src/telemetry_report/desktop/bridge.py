"""Typed bridge between the local desktop UI and the authoritative Python pipeline."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Protocol

from telemetry_report.data import (
    TelemetryDataError,
    read_telemetry_json,
    validate_telemetry_json,
)
from telemetry_report.file_io import write_text_atomically
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass

_EXAMPLE_FILES = {
    "nominal": "nominal-pass.json",
    "anomalous": "anomalous-pass.json",
}
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_UNSAFE_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DesktopDialogs(Protocol):
    """Native dialog operations used by the desktop bridge."""

    def open_json(self) -> Path | None: ...

    def save_json(self, suggested_name: str) -> Path | None: ...

    def save_report(self, suggested_name: str) -> Path | None: ...


@dataclass(frozen=True, slots=True)
class GeneratedAnalysis:
    analysis_id: str
    normalized_json: str
    report_html: str
    json_filename: str
    report_filename: str


def safe_filename_stem(pass_id: str) -> str:
    """Return a Windows-safe filename stem derived from a pass identifier."""
    stem = _UNSAFE_FILENAME_CHARACTERS.sub("_", pass_id).strip().rstrip(". ")
    stem = stem[:80].rstrip(". ")
    if not stem:
        return "telemetry-pass"
    filename_prefix, separator, remainder = stem.partition(".")
    if filename_prefix.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"{filename_prefix}_{separator}{remainder}"
        return stem[:80].rstrip(". ")
    return stem


def _error_result(error: TelemetryDataError) -> dict[str, object]:
    return {
        "ok": False,
        "error": str(error),
        "issues": [{"path": issue.path, "message": issue.message} for issue in error.issues],
    }


def _example_text(name: str) -> str:
    try:
        filename = _EXAMPLE_FILES[name]
    except KeyError as error:
        raise ValueError(f"unknown example '{name}'") from error
    resource = files("telemetry_report.desktop").joinpath("examples", filename)
    return resource.read_text(encoding="utf-8")


class DesktopBridge:
    """Expose safe, JSON-compatible operations to the desktop JavaScript UI."""

    def __init__(self, dialogs: DesktopDialogs | None = None) -> None:
        self._dialogs = dialogs
        self._latest: GeneratedAnalysis | None = None

    def bind_dialogs(self, dialogs: DesktopDialogs) -> None:
        """Attach native dialogs after pywebview has created its window."""
        self._dialogs = dialogs

    def load_example(self, name: str) -> dict[str, object]:
        """Return one packaged, validated example as normalized JSON."""
        self._latest = None
        try:
            validated = validate_telemetry_json(_example_text(name), source=f"example:{name}")
        except (TelemetryDataError, ValueError) as error:
            if isinstance(error, TelemetryDataError):
                return _error_result(error)
            return {"ok": False, "error": str(error), "issues": []}
        return {
            "ok": True,
            "cancelled": False,
            "payload_json": json.dumps(validated.payload, indent=2, ensure_ascii=False) + "\n",
        }

    def open_input_json(self) -> dict[str, object]:
        """Open and validate a telemetry JSON document selected by the user."""
        self._latest = None
        if self._dialogs is None:
            return {"ok": False, "error": "native file dialogs are unavailable", "issues": []}
        path = self._dialogs.open_json()
        if path is None:
            return {"ok": True, "cancelled": True}
        try:
            raw_input = read_telemetry_json(path)
            validated = validate_telemetry_json(raw_input, source=str(path))
        except TelemetryDataError as error:
            return _error_result(error)
        return {
            "ok": True,
            "cancelled": False,
            "payload_json": json.dumps(validated.payload, indent=2, ensure_ascii=False) + "\n",
        }

    def analyse(self, payload_json: str) -> dict[str, object]:
        """Validate, analyse, and render the supplied telemetry JSON."""
        self._latest = None
        try:
            validated = validate_telemetry_json(payload_json)
        except TelemetryDataError as error:
            return _error_result(error)

        analysis = analyse_pass(validated.telemetry_pass)
        report_html = render_report(analysis)
        normalized_json = json.dumps(validated.payload, indent=2, ensure_ascii=False) + "\n"
        filename_stem = safe_filename_stem(validated.telemetry_pass.pass_id)
        analysis_id = secrets.token_urlsafe(24)
        self._latest = GeneratedAnalysis(
            analysis_id=analysis_id,
            normalized_json=normalized_json,
            report_html=report_html,
            json_filename=f"{filename_stem}.json",
            report_filename=f"{filename_stem}-report.html",
        )
        first_reading = analysis.readings[0]
        return {
            "ok": True,
            "analysis_id": analysis_id,
            "report_html": report_html,
            "summary": {
                "overall_status": analysis.overall_status.value,
                "overall_status_label": analysis.overall_status.value.title(),
                "operational_summary": analysis.operational_summary,
                "counts": {
                    "nominal": analysis.counts.nominal,
                    "warning": analysis.counts.warning,
                    "critical": analysis.counts.critical,
                },
                "first_reading_metrics": {
                    metric.value: status.value
                    for metric, status in first_reading.metric_statuses.items()
                },
            },
        }

    def save_input_json(self, analysis_id: str) -> dict[str, object]:
        """Save the latest validated JSON through a native dialog."""
        latest_or_error = self._latest_for(analysis_id)
        if isinstance(latest_or_error, dict):
            return latest_or_error
        if self._dialogs is None:
            return {"ok": False, "error": "native file dialogs are unavailable"}
        path = self._dialogs.save_json(latest_or_error.json_filename)
        return self._save(path, latest_or_error.normalized_json)

    def save_report(self, analysis_id: str) -> dict[str, object]:
        """Save the latest generated HTML report through a native dialog."""
        latest_or_error = self._latest_for(analysis_id)
        if isinstance(latest_or_error, dict):
            return latest_or_error
        if self._dialogs is None:
            return {"ok": False, "error": "native file dialogs are unavailable"}
        path = self._dialogs.save_report(latest_or_error.report_filename)
        return self._save(path, latest_or_error.report_html)

    def _latest_for(self, analysis_id: str) -> GeneratedAnalysis | dict[str, object]:
        if self._latest is None or not secrets.compare_digest(
            self._latest.analysis_id, analysis_id
        ):
            return {"ok": False, "error": "analysis result is missing or stale"}
        return self._latest

    @staticmethod
    def _save(path: Path | None, content: str) -> dict[str, object]:
        if path is None:
            return {"ok": True, "cancelled": True}
        try:
            write_text_atomically(path, content)
        except OSError as error:
            return {"ok": False, "error": f"could not save '{path}': {error}"}
        return {"ok": True, "cancelled": False, "path": str(path.resolve())}
