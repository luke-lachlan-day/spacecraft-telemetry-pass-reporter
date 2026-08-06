from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from telemetry_report.data import load_telemetry_pass
from telemetry_report.presentation import render_report
from telemetry_report.services import analyse_pass

pytestmark = pytest.mark.browser


def _report_html(name: str) -> str:
    root = Path(__file__).parents[2]
    sample_name = "nominal" if name == "long-identifiers" else name
    telemetry_pass = load_telemetry_pass(root / "sample-data" / f"{sample_name}-pass.json")
    if name == "long-identifiers":
        telemetry_pass = replace(
            telemetry_pass,
            pass_id="PASS-" + "IDENTIFIER-" * 10,
            spacecraft="DEMONSTRATION-SPACECRAFT-" * 4,
        )
    return render_report(analyse_pass(telemetry_pass))


def _new_page(browser: Any, width: int) -> tuple[Any, list[str]]:
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    return page, errors


@pytest.mark.parametrize("report_name", ["nominal", "anomalous", "long-identifiers"])
@pytest.mark.parametrize("width", [280, 320, 375, 1440])
def test_report_layout_is_contained_and_accessible(
    chromium_browser: Any,
    browser_artifacts: Path,
    report_name: str,
    width: int,
) -> None:
    page, errors = _new_page(chromium_browser, width)
    artifact_name = f"report-{report_name}-{width}.png"
    try:
        page.set_content(_report_html(report_name), wait_until="load")
        measurements = page.evaluate(
            """() => {
              const root = document.documentElement;
              const wrapper = document.querySelector('.table-wrapper');
              const bounds = wrapper.getBoundingClientRect();
              return {
                documentWidth: root.scrollWidth,
                viewportWidth: window.innerWidth,
                wrapperLeft: bounds.left,
                wrapperRight: bounds.right,
                wrapperClientWidth: wrapper.clientWidth,
                wrapperScrollWidth: wrapper.scrollWidth,
              };
            }"""
        )
        assert measurements["documentWidth"] <= measurements["viewportWidth"] + 1
        assert measurements["wrapperLeft"] >= -1
        assert measurements["wrapperRight"] <= measurements["viewportWidth"] + 1
        if width < 820:
            assert measurements["wrapperScrollWidth"] > measurements["wrapperClientWidth"]
        else:
            assert measurements["wrapperScrollWidth"] <= measurements["wrapperClientWidth"] + 1

        for heading in (
            "Pass summary",
            "Metric statistics and limits",
            "Out-of-limit occurrences",
            "Chronological telemetry",
        ):
            assert page.get_by_role("heading", name=heading).is_visible()
        assert page.locator("footer").is_visible()
        for severity in ("Nominal", "Warning", "Critical"):
            assert page.locator(".legend strong", has_text=severity).is_visible()
        assert page.locator(".metric-status").count() > 0
        assert (
            page.locator(".status-badge").get_attribute("aria-label").startswith("Overall status:")
        )
        assert errors == []
    except Exception:
        page.screenshot(path=browser_artifacts / artifact_name, full_page=True)
        raise
    finally:
        page.close()


def test_report_print_rules_and_pdf_output(chromium_browser: Any, browser_artifacts: Path) -> None:
    page, errors = _new_page(chromium_browser, 1440)
    pdf_path = browser_artifacts / "anomalous-report-print.pdf"
    try:
        page.set_content(_report_html("anomalous"), wait_until="load")
        page.emulate_media(media="print")
        print_styles = page.evaluate(
            """() => {
              const reportPage = getComputedStyle(document.querySelector('.page'));
              const wrapper = getComputedStyle(document.querySelector('.table-wrapper'));
              return {
                margin: reportPage.margin,
                borderWidth: reportPage.borderTopWidth,
                boxShadow: reportPage.boxShadow,
                overflowX: wrapper.overflowX,
              };
            }"""
        )
        assert print_styles == {
            "margin": "0px",
            "borderWidth": "0px",
            "boxShadow": "none",
            "overflowX": "visible",
        }
        pdf = page.pdf(path=pdf_path, format="A4", print_background=True)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 10_000
        assert errors == []
    except Exception:
        page.screenshot(path=browser_artifacts / "report-print-failure.png", full_page=True)
        raise
    finally:
        page.close()
