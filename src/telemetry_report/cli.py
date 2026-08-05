"""Command-line dependency wiring and user-facing error handling."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from jinja2 import TemplateError

from telemetry_report import __version__
from telemetry_report.data import TelemetryDataError, load_telemetry_pass
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser used by the reporter CLI."""
    parser = argparse.ArgumentParser(
        prog="telemetry-report",
        description="Generate an HTML report from fictional spacecraft-pass telemetry.",
    )
    parser.add_argument("input", type=Path, help="path to the telemetry JSON file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="report path (default: <input-name>-report.html beside the input)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _default_output(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}-report.html")


def _paths_refer_to_same_file(input_path: Path, output_path: Path) -> bool:
    try:
        if input_path.resolve() == output_path.resolve():
            return True
    except (OSError, RuntimeError):
        pass

    try:
        return input_path.samefile(output_path)
    except OSError:
        return False


def _write_report_atomically(output_path: Path, html: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(html)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the report pipeline and return a process exit code."""
    arguments = build_parser().parse_args(argv)
    output_path = arguments.output or _default_output(arguments.input)

    if _paths_refer_to_same_file(arguments.input, output_path):
        print("error: input and output paths must refer to different files", file=sys.stderr)
        return 2

    try:
        telemetry_pass = load_telemetry_pass(arguments.input)
        analysis = analyse_pass(telemetry_pass)
        html = render_report(analysis)
        _write_report_atomically(output_path, html)
    except TelemetryDataError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (OSError, TemplateError) as error:
        print(f"error: could not generate '{output_path}': {error}", file=sys.stderr)
        return 3

    print(f"Generated telemetry report: {output_path.resolve()}")
    return 0
