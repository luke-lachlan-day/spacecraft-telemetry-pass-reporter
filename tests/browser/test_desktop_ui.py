from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.browser


def _stub_script(payload: dict[str, object]) -> str:
    payload_json = json.dumps(payload)
    report_html = "<!doctype html><html><body><h1>Generated report</h1></body></html>"
    return f"""
      window.__forceValidationError = false;
      window.__bridgeCalls = [];
      const examplePayload = {payload_json};
      window.pywebview = {{ api: {{
        load_example: async (name) => {{
          window.__bridgeCalls.push(['load_example', name]);
          return {{ ok: true, cancelled: false, payload_json: JSON.stringify(examplePayload) }};
        }},
        open_input_json: async () => ({{ ok: true, cancelled: true }}),
        analyse: async (raw) => {{
          window.__bridgeCalls.push(['analyse', JSON.parse(raw)]);
          if (window.__forceValidationError) return {{
            ok: false,
            error: 'invalid telemetry',
            issues: [{{
              path: 'readings.0.temperature_c',
              message: 'Input should be a valid number'
            }}]
          }};
          return {{
            ok: true,
            analysis_id: 'analysis-token',
            report_html: {json.dumps(report_html)},
            summary: {{
              overall_status: 'warning',
              overall_status_label: 'Warning',
              operational_summary: 'One fictional warning reading requires review.',
              counts: {{ nominal: 0, warning: 1, critical: 0 }},
              first_reading_metrics: {{
                battery_voltage: 'warning',
                temperature_c: 'nominal',
                signal_strength_dbm: 'nominal'
              }}
            }}
          }};
        }},
        save_input_json: async (id) => ({{
          ok: true, cancelled: false, path: 'C:\\\\Reports\\\\input.json', id
        }}),
        save_report: async (id) => ({{
          ok: true, cancelled: false, path: 'C:\\\\Reports\\\\report.html', id
        }})
      }} }};
    """


def _open_app(browser: Any, payload: dict[str, object], width: int = 1180) -> tuple[Any, list[str]]:
    app_path = (
        Path(__file__).parents[2] / "src" / "telemetry_report" / "desktop" / "assets" / "app.html"
    )
    page = browser.new_page(viewport={"width": width, "height": 820})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    page.add_init_script(_stub_script(payload))
    page.goto(app_path.as_uri(), wait_until="load")
    return page, errors


def test_quick_experiment_analysis_preview_and_stale_invalidation(
    chromium_browser: Any,
    browser_artifacts: Path,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#result-panel").wait_for(state="visible")
        assert page.locator("#overall-status").inner_text() == "▲ Warning"
        assert page.locator("#quick-statuses .metric-chip").count() == 3
        assert page.locator("#report-preview").get_attribute("sandbox") == ""
        assert page.get_by_role("button", name="Save HTML report…").is_enabled()

        page.locator("#quick-battery").fill("3.3")

        assert page.locator("#result-panel").is_hidden()
        assert page.locator("#save-report").is_disabled()
        assert "Validate again" in page.locator("#bridge-status").inner_text()
        assert errors == []
    except Exception:
        page.screenshot(path=browser_artifacts / "desktop-quick-failure.png", full_page=True)
        raise
    finally:
        page.close()


def test_full_editor_examples_rows_errors_and_keyboard_tabs(
    chromium_browser: Any,
    browser_artifacts: Path,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload, width=720)
    try:
        page.locator("#quick-tab").focus()
        page.keyboard.press("ArrowRight")
        assert page.locator("#full-tab").get_attribute("aria-selected") == "true"
        page.locator("#readings-body tr").first.wait_for()
        assert page.locator("#readings-body tr").count() == 2

        page.locator("#readings-body .duplicate").first.click()
        assert page.locator("#readings-body tr").count() == 3
        page.locator("#readings-body .delete").first.click()
        assert page.locator("#readings-body tr").count() == 2

        page.evaluate("window.__forceValidationError = true")
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#error-summary").wait_for(state="visible")
        assert "readings.0.temperature_c" in page.locator("#error-summary").inner_text()
        assert page.locator("#reading-0-temperature-c").get_attribute("aria-invalid") == "true"

        document_width = page.evaluate("document.documentElement.scrollWidth")
        overflowing = page.evaluate(
            """() => [...document.querySelectorAll('*')]
              .filter(element => element.getBoundingClientRect().right > innerWidth + 1)
              .map(element => `${element.tagName.toLowerCase()}#${element.id}.${element.className}`)
              .slice(0, 10)"""
        )
        assert document_width <= 721, overflowing
        assert page.locator(".readings-wrapper").evaluate(
            "element => element.scrollWidth > element.clientWidth"
        )
        assert errors == []
    except Exception:
        page.screenshot(path=browser_artifacts / "desktop-full-failure.png", full_page=True)
        raise
    finally:
        page.close()


def test_desktop_ui_loads_only_packaged_local_resources(
    chromium_browser: Any, valid_payload: dict[str, object]
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        resource_urls = page.evaluate(
            """() => [...document.querySelectorAll('link[href], script[src]')]
              .map(element => element.href || element.src)"""
        )
        assert resource_urls
        assert all(url.startswith("file:") for url in resource_urls)
        assert errors == []
    finally:
        page.close()
