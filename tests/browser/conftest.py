from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="session")
def chromium_browser() -> Iterator[Any]:
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(scope="session")
def browser_artifacts() -> Path:
    path = Path(__file__).parents[2] / ".browser-artifacts"
    path.mkdir(exist_ok=True)
    return path
