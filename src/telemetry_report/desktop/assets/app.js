"use strict";

const metricDefinitions = [
  { key: "battery_voltage", slug: "battery-voltage", label: "Battery voltage", unit: "V", direction: "minimum", warning: 3.6, critical: 3.4 },
  { key: "temperature_c", slug: "temperature-c", label: "Temperature", unit: "°C", direction: "maximum", warning: 40, critical: 50 },
  { key: "signal_strength_dbm", slug: "signal-strength-dbm", label: "Signal strength", unit: "dBm", direction: "minimum", warning: -90, critical: -105 },
];

const quickDefaults = { battery: 3.8, temperature: 25, signal: -80 };
const state = {
  mode: "quick",
  analysisId: null,
  quickTimestamp: new Date().toISOString(),
  fullLoaded: false,
  inputRevision: 0,
};

const byId = (id) => document.getElementById(id);
const quickFields = {
  battery: { range: byId("quick-battery-range"), number: byId("quick-battery"), output: byId("quick-battery-output"), decimals: 2, unit: "V" },
  temperature: { range: byId("quick-temperature-range"), number: byId("quick-temperature"), output: byId("quick-temperature-output"), decimals: 1, unit: "°C" },
  signal: { range: byId("quick-signal-range"), number: byId("quick-signal"), output: byId("quick-signal-output"), decimals: 0, unit: "dBm" },
};

function bridgeApi() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

async function callBridge(method, ...args) {
  const api = bridgeApi();
  if (!api || typeof api[method] !== "function") throw new Error("The Python desktop bridge is unavailable.");
  return api[method](...args);
}

function setBridgeStatus(message) { byId("bridge-status").textContent = message; }

function setBusy(isBusy, message) {
  byId("analyse-button").disabled = isBusy;
  byId("analyse-button").textContent = isBusy ? "Analyzing…" : "Validate & Analyze";
  if (message) setBridgeStatus(message);
}

function clearResult() {
  state.analysisId = null;
  byId("result-panel").hidden = true;
  byId("report-preview").removeAttribute("srcdoc");
  byId("save-json").disabled = true;
  byId("save-report").disabled = true;
}

function discardStaleAnalysis() {
  clearResult();
  setBridgeStatus(
    "Inputs changed while analysis was running. Validate again to analyze the current telemetry."
  );
}

function invalidateResult(message = "Inputs changed. Validate again to refresh the report.") {
  state.inputRevision += 1;
  if (state.analysisId) setBridgeStatus(message);
  clearResult();
}

function valueOrRaw(value) {
  const trimmed = String(value).trim();
  if (!trimmed) return "";
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : trimmed;
}

function updateQuickOutput(name) {
  const field = quickFields[name];
  const value = Number(field.number.value);
  const formatted = Number.isFinite(value) ? value.toFixed(field.decimals).replace("-", "−") : field.number.value;
  field.output.textContent = `${formatted} ${field.unit}`;
}

function pairQuickControl(name) {
  const field = quickFields[name];
  field.range.addEventListener("input", () => {
    field.number.value = field.range.value;
    updateQuickOutput(name);
  });
  field.number.addEventListener("input", () => {
    const value = Number(field.number.value);
    if (Number.isFinite(value)) field.range.value = field.number.value;
    updateQuickOutput(name);
  });
}

function resetQuick() {
  clearErrors();
  state.quickTimestamp = new Date().toISOString();
  Object.entries(quickDefaults).forEach(([name, value]) => {
    quickFields[name].range.value = String(value);
    quickFields[name].number.value = String(value);
    updateQuickOutput(name);
  });
  invalidateResult("Quick Experiment reset. Validate when ready.");
}

function quickPayload() {
  return {
    pass_id: "QUICK-EXPERIMENT",
    spacecraft: "DEMO-CRAFT",
    started_at: state.quickTimestamp,
    limits: {
      battery_voltage: { direction: "minimum", warning: 3.6, critical: 3.4 },
      temperature_c: { direction: "maximum", warning: 40, critical: 50 },
      signal_strength_dbm: { direction: "minimum", warning: -90, critical: -105 },
    },
    readings: [{
      timestamp: state.quickTimestamp,
      battery_voltage: valueOrRaw(quickFields.battery.number.value),
      temperature_c: valueOrRaw(quickFields.temperature.number.value),
      signal_strength_dbm: valueOrRaw(quickFields.signal.number.value),
    }],
  };
}

function renderLimitEditors() {
  const grid = byId("limits-grid");
  grid.replaceChildren();
  metricDefinitions.forEach((metric) => {
    const card = document.createElement("article");
    card.className = "limit-card";
    card.innerHTML = `
      <h3>${metric.label} <span class="field-help">(${metric.unit})</span></h3>
      <div class="limit-fields">
        <div class="direction-field"><label for="limit-${metric.slug}-direction">Unsafe direction</label><select id="limit-${metric.slug}-direction"><option value="minimum">Below minimum</option><option value="maximum">Above maximum</option></select></div>
        <div><label for="limit-${metric.slug}-warning">Warning</label><input id="limit-${metric.slug}-warning" type="text" inputmode="decimal" spellcheck="false"></div>
        <div><label for="limit-${metric.slug}-critical">Critical</label><input id="limit-${metric.slug}-critical" type="text" inputmode="decimal" spellcheck="false"></div>
      </div>`;
    grid.append(card);
  });
}

function readingValue(reading, key) { return reading && reading[key] !== undefined ? String(reading[key]) : ""; }

function addReadingRow(reading = {}, afterIndex = null) {
  const row = document.createElement("tr");
  row.innerHTML = `
    <td><label class="sr-only">Reading timestamp</label><input class="reading-timestamp" type="text" spellcheck="false" value="${escapeAttribute(readingValue(reading, "timestamp"))}"></td>
    <td><label class="sr-only">Battery voltage</label><input class="reading-battery" type="text" inputmode="decimal" value="${escapeAttribute(readingValue(reading, "battery_voltage"))}"></td>
    <td><label class="sr-only">Temperature</label><input class="reading-temperature" type="text" inputmode="decimal" value="${escapeAttribute(readingValue(reading, "temperature_c"))}"></td>
    <td><label class="sr-only">Signal strength</label><input class="reading-signal" type="text" inputmode="decimal" value="${escapeAttribute(readingValue(reading, "signal_strength_dbm"))}"></td>
    <td><div class="row-actions"><button class="icon-button duplicate" type="button" title="Duplicate reading">Duplicate</button><button class="icon-button delete" type="button" title="Delete reading">Delete</button></div></td>`;
  const body = byId("readings-body");
  if (afterIndex === null || afterIndex >= body.children.length - 1) body.append(row);
  else body.insertBefore(row, body.children[afterIndex + 1]);
  renumberReadingRows();
}

function escapeAttribute(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function renumberReadingRows() {
  [...byId("readings-body").rows].forEach((row, index) => {
    row.dataset.index = String(index);
    const ids = ["timestamp", "battery-voltage", "temperature-c", "signal-strength-dbm"];
    [...row.querySelectorAll("input")].forEach((input, inputIndex) => {
      input.id = `reading-${index}-${ids[inputIndex]}`;
      input.previousElementSibling.htmlFor = input.id;
    });
  });
}

function setFullPayload(payload) {
  clearErrors();
  byId("full-pass-id").value = payload.pass_id ?? "";
  byId("full-spacecraft").value = payload.spacecraft ?? "";
  byId("full-started-at").value = payload.started_at ?? "";
  metricDefinitions.forEach((metric) => {
    const limit = payload.limits && payload.limits[metric.key] ? payload.limits[metric.key] : metric;
    byId(`limit-${metric.slug}-direction`).value = limit.direction;
    byId(`limit-${metric.slug}-warning`).value = limit.warning;
    byId(`limit-${metric.slug}-critical`).value = limit.critical;
  });
  byId("readings-body").replaceChildren();
  (payload.readings || []).forEach((reading) => addReadingRow(reading));
  state.fullLoaded = true;
  invalidateResult("Telemetry loaded. Validate when ready.");
}

function fullPayload() {
  const limits = {};
  metricDefinitions.forEach((metric) => {
    limits[metric.key] = {
      direction: byId(`limit-${metric.slug}-direction`).value,
      warning: valueOrRaw(byId(`limit-${metric.slug}-warning`).value),
      critical: valueOrRaw(byId(`limit-${metric.slug}-critical`).value),
    };
  });
  const readings = [...byId("readings-body").rows].map((row) => ({
    timestamp: row.querySelector(".reading-timestamp").value,
    battery_voltage: valueOrRaw(row.querySelector(".reading-battery").value),
    temperature_c: valueOrRaw(row.querySelector(".reading-temperature").value),
    signal_strength_dbm: valueOrRaw(row.querySelector(".reading-signal").value),
  }));
  return {
    pass_id: byId("full-pass-id").value,
    spacecraft: byId("full-spacecraft").value,
    started_at: byId("full-started-at").value,
    limits,
    readings,
  };
}

function switchMode(mode) {
  state.mode = mode;
  const quick = mode === "quick";
  byId("quick-panel").hidden = !quick;
  byId("full-panel").hidden = quick;
  byId("quick-tab").classList.toggle("active", quick);
  byId("full-tab").classList.toggle("active", !quick);
  byId("quick-tab").setAttribute("aria-selected", String(quick));
  byId("full-tab").setAttribute("aria-selected", String(!quick));
  byId("quick-tab").tabIndex = quick ? 0 : -1;
  byId("full-tab").tabIndex = quick ? -1 : 0;
  clearErrors();
  invalidateResult("Mode changed. Validate the visible telemetry when ready.");
  if (!quick && !state.fullLoaded) loadExample("nominal");
}

function fieldIdForPath(path) {
  if (state.mode === "quick") {
    const quickMap = {
      "readings.0.battery_voltage": "quick-battery",
      "readings.0.temperature_c": "quick-temperature",
      "readings.0.signal_strength_dbm": "quick-signal",
    };
    return quickMap[path] || "analyse-button";
  }
  const direct = { pass_id: "full-pass-id", spacecraft: "full-spacecraft", started_at: "full-started-at" };
  if (direct[path]) return direct[path];
  const limitMatch = path.match(/^limits\.(battery_voltage|temperature_c|signal_strength_dbm)\.(direction|warning|critical)$/);
  if (limitMatch) {
    const metric = metricDefinitions.find((item) => item.key === limitMatch[1]);
    return `limit-${metric.slug}-${limitMatch[2]}`;
  }
  const readingMatch = path.match(/^readings\.(\d+)\.(timestamp|battery_voltage|temperature_c|signal_strength_dbm)$/);
  if (readingMatch) {
    const fieldSlugs = { timestamp: "timestamp", battery_voltage: "battery-voltage", temperature_c: "temperature-c", signal_strength_dbm: "signal-strength-dbm" };
    return `reading-${readingMatch[1]}-${fieldSlugs[readingMatch[2]]}`;
  }
  return "analyse-button";
}

function clearErrors() {
  byId("error-summary").hidden = true;
  byId("error-list").replaceChildren();
  document.querySelectorAll('[aria-invalid="true"]').forEach((element) => element.removeAttribute("aria-invalid"));
}

function showErrors(result) {
  clearErrors();
  const issues = Array.isArray(result.issues) && result.issues.length ? result.issues : [{ path: "input", message: result.error || "The telemetry could not be analysed." }];
  issues.forEach((issue) => {
    const targetId = fieldIdForPath(issue.path);
    const target = byId(targetId);
    if (target && targetId !== "analyse-button") target.setAttribute("aria-invalid", "true");
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = `#${targetId}`;
    link.textContent = `${issue.path}: ${issue.message}`;
    item.append(link);
    byId("error-list").append(item);
  });
  byId("error-summary").hidden = false;
  byId("error-summary").focus();
  setBridgeStatus("Validation found fields that need attention.");
}

function renderResult(result) {
  const summary = result.summary;
  state.analysisId = result.analysis_id;
  byId("overall-status").className = `status-badge ${summary.overall_status}`;
  const symbols = { nominal: "✓", warning: "▲", critical: "!" };
  byId("overall-status").textContent = `${symbols[summary.overall_status]} ${summary.overall_status_label}`;
  byId("operational-summary").textContent = summary.operational_summary;
  byId("nominal-count").textContent = summary.counts.nominal;
  byId("warning-count").textContent = summary.counts.warning;
  byId("critical-count").textContent = summary.counts.critical;
  const quickStatuses = byId("quick-statuses");
  quickStatuses.replaceChildren();
  quickStatuses.hidden = state.mode !== "quick";
  if (state.mode === "quick") {
    metricDefinitions.forEach((metric) => {
      const status = summary.first_reading_metrics[metric.key];
      const chip = document.createElement("span");
      chip.className = `metric-chip ${status}`;
      chip.textContent = `${symbols[status]} ${metric.label}: ${status[0].toUpperCase()}${status.slice(1)}`;
      quickStatuses.append(chip);
    });
  }
  byId("report-preview").srcdoc = result.report_html;
  byId("result-panel").hidden = false;
  byId("save-json").disabled = false;
  byId("save-report").disabled = false;
  setBridgeStatus("Analysis complete. The report is current and ready to save.");
  byId("result-title").focus({ preventScroll: true });
  byId("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyseCurrent() {
  clearErrors();
  setBusy(true, "Validating and analyzing with Python…");
  const submittedRevision = state.inputRevision;
  try {
    const payload = state.mode === "quick" ? quickPayload() : fullPayload();
    const result = await callBridge("analyse", JSON.stringify(payload));
    if (submittedRevision !== state.inputRevision) {
      discardStaleAnalysis();
      return;
    }
    if (!result.ok) showErrors(result);
    else renderResult(result);
  } catch (error) {
    if (submittedRevision !== state.inputRevision) {
      discardStaleAnalysis();
    } else {
      showErrors({ error: error.message, issues: [] });
    }
  } finally {
    setBusy(false);
  }
}

async function loadExample(name) {
  setBridgeStatus(`Loading ${name} example…`);
  try {
    const result = await callBridge("load_example", name);
    if (!result.ok) showErrors(result);
    else setFullPayload(JSON.parse(result.payload_json));
  } catch (error) { showErrors({ error: error.message, issues: [] }); }
}

async function importJson() {
  setBridgeStatus("Opening telemetry JSON…");
  try {
    const result = await callBridge("open_input_json");
    if (result.cancelled) setBridgeStatus("Import cancelled.");
    else if (!result.ok) showErrors(result);
    else setFullPayload(JSON.parse(result.payload_json));
  } catch (error) { showErrors({ error: error.message, issues: [] }); }
}

async function save(kind) {
  if (!state.analysisId) return;
  const method = kind === "json" ? "save_input_json" : "save_report";
  setBridgeStatus(`Choosing where to save the ${kind === "json" ? "input JSON" : "HTML report"}…`);
  try {
    const result = await callBridge(method, state.analysisId);
    if (!result.ok) showErrors({ error: result.error, issues: [] });
    else if (result.cancelled) setBridgeStatus("Save cancelled; the current analysis is still available.");
    else setBridgeStatus(`Saved to ${result.path}`);
  } catch (error) { showErrors({ error: error.message, issues: [] }); }
}

function bindEvents() {
  Object.keys(quickFields).forEach(pairQuickControl);
  byId("quick-reset").addEventListener("click", resetQuick);
  byId("quick-tab").addEventListener("click", () => switchMode("quick"));
  byId("full-tab").addEventListener("click", () => switchMode("full"));
  document.querySelector(".mode-tabs").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const nextMode = state.mode === "quick" ? "full" : "quick";
    switchMode(nextMode);
    byId(`${nextMode}-tab`).focus();
  });
  byId("add-reading").addEventListener("click", () => { addReadingRow(); invalidateResult(); });
  byId("readings-body").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    const row = button.closest("tr");
    const index = Number(row.dataset.index);
    if (button.classList.contains("delete")) row.remove();
    if (button.classList.contains("duplicate")) {
      const reading = {
        timestamp: row.querySelector(".reading-timestamp").value,
        battery_voltage: row.querySelector(".reading-battery").value,
        temperature_c: row.querySelector(".reading-temperature").value,
        signal_strength_dbm: row.querySelector(".reading-signal").value,
      };
      addReadingRow(reading, index);
    }
    renumberReadingRows();
    invalidateResult();
  });
  document.querySelectorAll(".example-button").forEach((button) => button.addEventListener("click", () => loadExample(button.dataset.example)));
  byId("import-json").addEventListener("click", importJson);
  byId("analyse-button").addEventListener("click", analyseCurrent);
  byId("save-json").addEventListener("click", () => save("json"));
  byId("save-report").addEventListener("click", () => save("report"));
  document.addEventListener("input", (event) => {
    if (event.target.matches("input, select")) invalidateResult();
  });
}

renderLimitEditors();
bindEvents();
resetQuick();
window.addEventListener("pywebviewready", () => setBridgeStatus("The Python engine is ready."));
if (!bridgeApi()) setBridgeStatus("Waiting for the Python desktop bridge…");
