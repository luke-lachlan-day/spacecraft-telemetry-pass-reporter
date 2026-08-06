from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from telemetry_report.data import validate_telemetry_json
from telemetry_report.desktop.bridge import DesktopBridge
from telemetry_report.metrics import METRICS

pytestmark = pytest.mark.browser


def _stub_script(
    payload: dict[str, object],
    *,
    configuration_error: bool = False,
    missing_configuration_method: bool = False,
) -> str:
    payload_json = json.dumps(payload)
    configuration_json = json.dumps(DesktopBridge().get_configuration())
    report_html = "<!doctype html><html><body><h1>Generated report</h1></body></html>"
    return f"""
      window.__forceValidationError = false;
      window.__validationIssues = [{{
        path: 'readings.0.temperature_c',
        message: 'Input should be a valid number'
      }}];
      window.__holdAnalysis = false;
      window.__releaseAnalysis = null;
      window.__importCancelled = true;
      window.__importFailure = false;
      window.__holdImport = false;
      window.__releaseImport = null;
      window.__heldExampleNames = [];
      window.__releaseExamples = {{}};
      window.__bridgeCalls = [];
      const examplePayload = {payload_json};
      const desktopConfiguration = {configuration_json};
      window.pywebview = {{ api: {{
        get_configuration: {str(missing_configuration_method).lower()} ? undefined : async () => {{
          if ({str(configuration_error).lower()}) {{
            throw new Error('simulated configuration failure');
          }}
          return desktopConfiguration;
        }},
        load_example: async (name) => {{
          window.__bridgeCalls.push(['load_example', name]);
          if (window.__heldExampleNames.includes(name)) await new Promise((resolve) => {{
            window.__releaseExamples[name] = resolve;
          }});
          return {{
            ok: true,
            cancelled: false,
            payload_json: JSON.stringify({{ ...examplePayload, pass_id: name.toUpperCase() }})
          }};
        }},
        open_input_json: async () => {{
          if (window.__holdImport) await new Promise((resolve) => {{
            window.__releaseImport = resolve;
          }});
          if (window.__importFailure) return {{
            ok: false,
            error: 'invalid imported telemetry',
            issues: [{{
              path: 'readings.0.temperature_c',
              message: 'Input should be a valid number'
            }}]
          }};
          return window.__importCancelled
            ? {{ ok: true, cancelled: true }}
            : {{
                ok: true,
                cancelled: false,
                payload_json: JSON.stringify({{ ...examplePayload, pass_id: 'IMPORTED' }})
              }};
        }},
        analyse: async (raw) => {{
          window.__bridgeCalls.push(['analyse', JSON.parse(raw)]);
          if (window.__holdAnalysis) await new Promise((resolve) => {{
            window.__releaseAnalysis = resolve;
          }});
          if (window.__forceValidationError) return {{
            ok: false,
            error: 'invalid telemetry',
            issues: window.__validationIssues
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
        save_input_json: async (id) => {{
          window.__bridgeCalls.push(['save_input_json', id]);
          return {{ ok: true, cancelled: false, path: 'C:\\\\Reports\\\\input.json', id }};
        }},
        save_report: async (id) => {{
          window.__bridgeCalls.push(['save_report', id]);
          return {{ ok: true, cancelled: false, path: 'C:\\\\Reports\\\\report.html', id }};
        }}
      }} }};
    """


def _open_app(
    browser: Any,
    payload: dict[str, object],
    width: int = 1180,
    *,
    configuration_error: bool = False,
    missing_configuration_method: bool = False,
) -> tuple[Any, list[str]]:
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
    page.add_init_script(
        _stub_script(
            payload,
            configuration_error=configuration_error,
            missing_configuration_method=missing_configuration_method,
        )
    )
    page.goto(app_path.as_uri(), wait_until="load")
    if not configuration_error and not missing_configuration_method:
        page.wait_for_function("!document.querySelector('#analyse-button').disabled")
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

        submitted_payload = page.evaluate("window.__bridgeCalls[0][1]")
        validate_telemetry_json(json.dumps(submitted_payload), source="quick experiment")
        assert submitted_payload["limits"] == valid_payload["limits"]
        desktop_metrics = page.evaluate(
            """metricDefinitions.map(
              ({ key, label, unit, report_decimals }) =>
              ({ key, label, unit, report_decimals }))"""
        )
        assert desktop_metrics == [
            {
                "key": metric.metric.value,
                "label": metric.label,
                "unit": metric.unit,
                "report_decimals": metric.report_decimals,
            }
            for metric in METRICS
        ]
        assert page.locator("#quick-grid .control-card").count() == len(METRICS)
        for metric in METRICS:
            control = page.locator(f"#quick-{metric.slug}")
            assert page.get_by_role("heading", name=metric.label, exact=True).count() == 1
            assert float(control.input_value()) == metric.quick.default
            assert float(control.get_attribute("min")) == metric.quick.minimum
            assert float(control.get_attribute("max")) == metric.quick.maximum
            assert float(control.get_attribute("step")) == metric.quick.step

        page.locator("#quick-battery-voltage").fill("3.3")

        assert page.locator("#result-panel").is_hidden()
        assert page.locator("#save-report").is_disabled()
        assert "Validate again" in page.locator("#bridge-status").inner_text()
        assert errors == []
    except Exception:
        page.screenshot(path=browser_artifacts / "desktop-quick-failure.png", full_page=True)
        raise
    finally:
        page.close()


@pytest.mark.parametrize("mutation", ["edit", "mode"])
def test_inflight_analysis_is_discarded_after_inputs_change(
    chromium_browser: Any,
    browser_artifacts: Path,
    valid_payload: dict[str, object],
    mutation: str,
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.evaluate("window.__holdAnalysis = true")
        page.get_by_role("button", name="Validate & Analyze").click()
        page.wait_for_function("window.__releaseAnalysis !== null")

        if mutation == "edit":
            page.locator("#quick-battery-voltage").fill("3.3")
        else:
            page.get_by_role("tab", name="Full Pass Editor").click()
            page.locator("#readings-body tr").first.wait_for()

        page.evaluate("window.__releaseAnalysis()")
        page.wait_for_function("!document.querySelector('#analyse-button').disabled")

        assert page.locator("#result-panel").is_hidden()
        assert page.locator("#save-json").is_disabled()
        assert page.locator("#save-report").is_disabled()
        assert "changed while analysis was running" in page.locator("#bridge-status").inner_text()
        assert errors == []
    except Exception:
        page.screenshot(
            path=browser_artifacts / f"desktop-stale-{mutation}-failure.png", full_page=True
        )
        raise
    finally:
        page.close()


def test_reanalysis_hides_previous_result_until_completion(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#result-panel").wait_for(state="visible")

        page.evaluate("window.__holdAnalysis = true")
        page.get_by_role("button", name="Validate & Analyze").click()
        page.wait_for_function("window.__releaseAnalysis !== null")

        assert page.locator("#result-panel").is_hidden()
        assert page.locator("#save-json").is_disabled()
        assert page.locator("#save-report").is_disabled()

        page.evaluate("window.__releaseAnalysis()")
        page.locator("#result-panel").wait_for(state="visible")
        assert page.locator("#save-report").is_enabled()
        assert errors == []
    finally:
        page.close()


def test_quick_reset_clears_validation_errors(
    chromium_browser: Any,
    browser_artifacts: Path,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.evaluate("window.__forceValidationError = true")
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#error-summary").wait_for(state="visible")
        assert page.locator("#quick-temperature-c").get_attribute("aria-invalid") == "true"

        page.get_by_role("button", name="Reset values").click()

        assert page.locator("#error-summary").is_hidden()
        assert page.locator('[aria-invalid="true"]').count() == 0
        assert errors == []
    except Exception:
        page.screenshot(path=browser_artifacts / "desktop-reset-failure.png", full_page=True)
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

        page.evaluate("window.__forceValidationError = false")
        page.get_by_role("button", name="Nominal example").click()
        page.locator("#error-summary").wait_for(state="hidden")
        assert page.locator('[aria-invalid="true"]').count() == 0

        page.evaluate("window.__forceValidationError = true")
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#error-summary").wait_for(state="visible")
        page.evaluate("window.__forceValidationError = false; window.__importCancelled = false")
        page.get_by_role("button", name="Import JSON…").click()
        page.locator("#error-summary").wait_for(state="hidden")
        assert page.locator('[aria-invalid="true"]').count() == 0

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


def test_cancelled_import_preserves_current_result_and_save_actions(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("tab", name="Full Pass Editor").click()
        page.locator("#readings-body tr").first.wait_for()
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#result-panel").wait_for(state="visible")
        preview = page.locator("#report-preview").get_attribute("srcdoc")

        page.get_by_role("button", name="Import JSON…").click()
        page.wait_for_function(
            "document.querySelector('#bridge-status').innerText.includes('remains available')"
        )

        assert page.locator("#result-panel").is_visible()
        assert page.locator("#report-preview").get_attribute("srcdoc") == preview
        assert page.locator("#save-json").is_enabled()
        assert page.locator("#save-report").is_enabled()

        page.get_by_role("button", name="Save input JSON…").click()
        page.wait_for_function(
            "document.querySelector('#bridge-status').innerText.includes('input.json')"
        )
        page.get_by_role("button", name="Save HTML report…").click()
        page.wait_for_function(
            "document.querySelector('#bridge-status').innerText.includes('report.html')"
        )
        save_calls = page.evaluate(
            "window.__bridgeCalls.filter(([method]) => method.startsWith('save_'))"
        )
        assert save_calls == [
            ["save_input_json", "analysis-token"],
            ["save_report", "analysis-token"],
        ]

        page.evaluate("window.__importCancelled = false")
        page.get_by_role("button", name="Import JSON…").click()
        page.wait_for_function("document.querySelector('#full-pass-id').value === 'IMPORTED'")
        assert page.locator("#result-panel").is_hidden()
        assert page.locator("#save-report").is_disabled()
        assert errors == []
    finally:
        page.close()


def test_invalid_import_preserves_current_editor_and_analysis(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("tab", name="Full Pass Editor").click()
        page.locator("#readings-body tr").first.wait_for()
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#result-panel").wait_for(state="visible")
        pass_id = page.locator("#full-pass-id").input_value()

        page.evaluate("window.__importFailure = true")
        page.get_by_role("button", name="Import JSON…").click()
        page.locator("#error-summary").wait_for(state="visible")

        assert page.locator("#error-title").inner_text() == (
            "The selected JSON could not be imported"
        )
        assert page.locator("#full-pass-id").input_value() == pass_id
        assert page.locator("#result-panel").is_visible()
        assert page.locator("#save-report").is_enabled()
        assert page.locator('[aria-invalid="true"]').count() == 0
        assert page.locator("#error-summary a").count() == 0
        assert errors == []
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


def test_configuration_failure_is_fatal_and_keeps_analysis_disabled(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(
        chromium_browser,
        valid_payload,
        configuration_error=True,
    )
    try:
        page.locator("#error-summary").wait_for(state="visible")
        assert page.locator("#analyse-button").is_disabled()
        assert page.locator("#quick-grid > *").count() == 0
        assert "initialization failed" in page.locator("#bridge-status").inner_text().lower()
        assert "simulated configuration failure" in page.locator("#error-summary").inner_text()
        assert errors == []
    finally:
        page.close()


def test_missing_configuration_bridge_method_is_fatal(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(
        chromium_browser,
        valid_payload,
        missing_configuration_method=True,
    )
    try:
        page.locator("#error-summary").wait_for(state="visible")
        assert page.locator("#analyse-button").is_disabled()
        assert "Python desktop bridge is unavailable" in page.locator("#error-summary").inner_text()
        assert errors == []
    finally:
        page.close()


def test_model_level_limit_error_marks_and_focuses_all_metric_controls(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("tab", name="Full Pass Editor").click()
        page.locator("#readings-body tr").first.wait_for()
        page.evaluate(
            """window.__forceValidationError = true;
               window.__validationIssues = [{
                 path: 'limits.battery_voltage',
                 message: 'Warning and critical limits are in the wrong order'
               }];"""
        )
        page.get_by_role("button", name="Validate & Analyze").click()
        page.locator("#error-summary").wait_for(state="visible")

        for suffix in ("direction", "warning", "critical"):
            assert (
                page.locator(f"#limit-battery-voltage-{suffix}").get_attribute("aria-invalid")
                == "true"
            )
        assert (
            page.locator("#error-summary a").get_attribute("href")
            == "#limit-battery-voltage-direction"
        )
        page.locator("#error-summary a").click()
        assert page.locator("#limit-battery-voltage-direction").evaluate(
            "element => element === document.activeElement"
        )
        assert errors == []
    finally:
        page.close()


def test_latest_delayed_example_response_wins(
    chromium_browser: Any,
    valid_payload: dict[str, object],
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("tab", name="Full Pass Editor").click()
        page.locator("#readings-body tr").first.wait_for()
        page.evaluate("window.__heldExampleNames = ['nominal', 'anomalous']")

        page.get_by_role("button", name="Nominal example").click()
        page.wait_for_function("window.__releaseExamples.nominal !== undefined")
        page.get_by_role("button", name="Anomalous example").click()
        page.wait_for_function("window.__releaseExamples.anomalous !== undefined")

        page.evaluate("window.__releaseExamples.anomalous()")
        page.wait_for_function("document.querySelector('#full-pass-id').value === 'ANOMALOUS'")
        page.evaluate("window.__releaseExamples.nominal()")
        page.wait_for_timeout(50)

        assert page.locator("#full-pass-id").input_value() == "ANOMALOUS"
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("mutation", ["edit", "mode"])
def test_pending_import_is_invalidated_by_editor_change(
    chromium_browser: Any,
    valid_payload: dict[str, object],
    mutation: str,
) -> None:
    page, errors = _open_app(chromium_browser, valid_payload)
    try:
        page.get_by_role("tab", name="Full Pass Editor").click()
        page.locator("#readings-body tr").first.wait_for()
        page.evaluate("window.__importCancelled = false; window.__holdImport = true")
        page.get_by_role("button", name="Import JSON…").click()
        page.wait_for_function("window.__releaseImport !== null")

        if mutation == "edit":
            page.locator("#full-pass-id").fill("USER-EDIT")
        else:
            page.get_by_role("tab", name="Quick Experiment").click()
        page.evaluate("window.__releaseImport()")
        page.wait_for_timeout(50)

        if mutation == "edit":
            assert page.locator("#full-pass-id").input_value() == "USER-EDIT"
        else:
            assert page.locator("#quick-tab").get_attribute("aria-selected") == "true"
        assert errors == []
    finally:
        page.close()
