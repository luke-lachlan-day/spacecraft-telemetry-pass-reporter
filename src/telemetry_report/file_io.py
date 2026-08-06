"""Shared, defensive UTF-8 text output helpers."""

from __future__ import annotations

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import TextIO

_TEMPORARY_FILE_ATTEMPTS = 10


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


def write_text_atomically(output_path: Path, text: str) -> None:
    """Write UTF-8 text by replacing ``output_path`` only after a complete write."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = _existing_regular_mode(output_path)
    temporary_path: Path | None = None
    try:
        temporary_path, temporary_file = _open_temporary_output(output_path)
        with temporary_file:
            temporary_file.write(text)
        if existing_mode is not None:
            temporary_path.chmod(existing_mode)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
