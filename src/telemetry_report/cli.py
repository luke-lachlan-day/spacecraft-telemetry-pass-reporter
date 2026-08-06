"""Command-line dependency wiring and user-facing error handling."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from jinja2 import TemplateError

from telemetry_report import __version__
from telemetry_report.data import TelemetryDataError, load_telemetry_pass
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass

_TEMPORARY_FILE_ATTEMPTS = 10


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


def _existing_regular_mode(output_path: Path) -> int | None:
    if os.name != "posix":
        return None

    try:
        output_stat = output_path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(output_stat.st_mode):
        return None
    return stat.S_IMODE(output_stat.st_mode)


def _open_temporary_output(output_path: Path) -> tuple[Path, TextIO]:
    for _ in range(_TEMPORARY_FILE_ATTEMPTS):
        token = secrets.token_hex(8)
        temporary_path = output_path.with_name(f".{output_path.name}.{token}.tmp")
        try:
            return temporary_path, temporary_path.open(mode="x", encoding="utf-8")
        except FileExistsError:
            continue
    raise OSError(f"could not create a temporary file beside '{output_path}'")


def _write_report_atomically(output_path: Path, html: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = _existing_regular_mode(output_path)
    temporary_path: Path | None = None
    try:
        temporary_path, temporary_file = _open_temporary_output(output_path)
        with temporary_file:
            temporary_file.write(html)
        if existing_mode is not None:
            temporary_path.chmod(existing_mode)
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
