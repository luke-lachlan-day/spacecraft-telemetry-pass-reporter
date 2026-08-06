"use strict";

let metricDefinitions = [];
const quickFields = {};
const state = {
  mode: "quick",
  analysisId: null,
  quickTimestamp: new Date().toISOString(),
  fullLoaded: false,
  inputRevision: 0,
  editorRequestRevision: 0,
  initialized: false,
  initializationPromise: null,
};

const byId = (id) => document.getElementById(id);

function bridgeApi() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

async function callBridge(method, ...args) {
  const api = bridgeApi();
  if (!api || typeof api[method] !== "function") {
    throw new Error("The Python desktop bridge is unavailable.");
  }
  return api[method](...args);
}

function setBridgeStatus(message) { byId("bridge-status").textContent = message; }

function setBusy(isBusy, message) {
  byId("analyse-button").disabled = isBusy || !state.initialized;
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
  state.editorRequestRevision += 1;
  if (state.analysisId) setBridgeStatus(message);
  clearResult();
}

function valueOrRaw(value) {
  const trimmed = String(value).trim();
  if (!trimmed) return "";
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : trimmed;
}

function formatQuickNumber(value, decimals) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return parsed.toFixed(decimals).replace("-", "−");
}

function formatLimitRule(metric, severity) {
  const symbol = metric.limit.direction === "minimum" ? "≤" : "≥";
  const value = formatQuickNumber(metric.limit[severity], metric.quick.decimals);
  const label = severity[0].toUpperCase() + severity.slice(1);
  return `${label} ${symbol} ${value} ${metric.unit}`;
}

function renderQuickControls() {
  const grid = byId("quick-grid");
  grid.replaceChildren();
  metricDefinitions.forEach((metric) => {
    const card = document.createElement("article");
    card.className = "control-card";
    card.innerHTML = `
      <div class="control-heading">
        <div><h3>${metric.label}</h3><p>${metric.limit.direction === "minimum" ? "Lower values move toward the unsafe range." : "Higher values move toward the unsafe range."}</p></div>
        <output id="quick-${metric.slug}-output" for="quick-${metric.slug}-range quick-${metric.slug}"></output>
      </div>
      <label class="sr-only" for="quick-${metric.slug}-range">${metric.label} slider</label>
      <input id="quick-${metric.slug}-range" data-quick-key="${metric.key}" data-quick-kind="range" type="range" min="${metric.quick.minimum}" max="${metric.quick.maximum}" step="${metric.quick.step}">
      <div class="number-row">
        <label for="quick-${metric.slug}">Exact value</label>
        <div class="input-with-unit"><input id="quick-${metric.slug}" data-quick-key="${metric.key}" data-quick-kind="number" type="number" min="${metric.quick.minimum}" max="${metric.quick.maximum}" step="${metric.quick.step}"><span>${metric.unit}</span></div>
      </div>
      <p class="limit-note"><strong>${formatLimitRule(metric, "warning")}</strong><span>${formatLimitRule(metric, "critical")}</span></p>`;
    grid.append(card);
    quickFields[metric.key] = {
      range: byId(`quick-${metric.slug}-range`),
      number: byId(`quick-${metric.slug}`),
      output: byId(`quick-${metric.slug}-output`),
      definition: metric,
    };
  });
}

function updateQuickOutput(key) {
  const field = quickFields[key];
  const formatted = formatQuickNumber(field.number.value, field.definition.quick.decimals);
  field.output.textContent = `${formatted} ${field.definition.unit}`;
}

function resetQuick() {
  if (!state.initialized) return;
  clearErrors();
  state.quickTimestamp = new Date().toISOString();
  metricDefinitions.forEach((metric) => {
    const field = quickFields[metric.key];
    field.range.value = String(metric.quick.default);
    field.number.value = String(metric.quick.default);
    updateQuickOutput(metric.key);
  });
  invalidateResult("Quick Experiment reset. Validate when ready.");
}

function quickPayload() {
  const limits = {};
  const reading = { timestamp: state.quickTimestamp };
  metricDefinitions.forEach((metric) => {
    limits[metric.key] = { ...metric.limit };
    reading[metric.key] = valueOrRaw(quickFields[metric.key].number.value);
  });
  return {
    pass_id: "QUICK-EXPERIMENT",
    spacecraft: "DEMO-CRAFT",
    started_at: state.quickTimestamp,
    limits,
    readings: [reading],
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

function renderReadingHeader() {
  const row = byId("readings-head-row");
  row.replaceChildren();
  const timestamp = document.createElement("th");
  timestamp.scope = "col";
  timestamp.textContent = "Timestamp";
  row.append(timestamp);
  metricDefinitions.forEach((metric) => {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.textContent = `${metric.label} (${metric.unit})`;
    row.append(heading);
  });
  const actions = document.createElement("th");
  actions.scope = "col";
  actions.setAttribute("aria-label", "Row actions");
  row.append(actions);
}

function readingValue(reading, key) {
  return reading && reading[key] !== undefined ? String(reading[key]) : "";
}

function escapeAttribute(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function addReadingRow(reading = {}, afterIndex = null) {
  const row = document.createElement("tr");
  const metricCells = metricDefinitions.map((metric) => `
    <td><label class="sr-only">${metric.label}</label><input class="reading-metric" data-metric-key="${metric.key}" type="text" inputmode="decimal" value="${escapeAttribute(readingValue(reading, metric.key))}"></td>`).join("");
  row.innerHTML = `
    <td><label class="sr-only">Reading timestamp</label><input class="reading-timestamp" type="text" spellcheck="false" value="${escapeAttribute(readingValue(reading, "timestamp"))}"></td>
    ${metricCells}
    <td><div class="row-actions"><button class="icon-button duplicate" type="button" title="Duplicate reading">Duplicate</button><button class="icon-button delete" type="button" title="Delete reading">Delete</button></div></td>`;
  const body = byId("readings-body");
  if (afterIndex === null || afterIndex >= body.children.length - 1) body.append(row);
  else body.insertBefore(row, body.children[afterIndex + 1]);
  renumberReadingRows();
}

function renumberReadingRows() {
  [...byId("readings-body").rows].forEach((row, index) => {
    row.dataset.index = String(index);
    const timestamp = row.querySelector(".reading-timestamp");
    timestamp.id = `reading-${index}-timestamp`;
    timestamp.previousElementSibling.htmlFor = timestamp.id;
    metricDefinitions.forEach((metric) => {
      const input = row.querySelector(`[data-metric-key="${metric.key}"]`);
      input.id = `reading-${index}-${metric.slug}`;
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
    const limit = payload.limits && payload.limits[metric.key] ? payload.limits[metric.key] : metric.limit;
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
  const readings = [...byId("readings-body").rows].map((row) => {
    const reading = { timestamp: row.querySelector(".reading-timestamp").value };
    metricDefinitions.forEach((metric) => {
      reading[metric.key] = valueOrRaw(row.querySelector(`[data-metric-key="${metric.key}"]`).value);
    });
    return reading;
  });
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

function metricForKey(key) {
  return metricDefinitions.find((metric) => metric.key === key);
}

function fieldTargetsForPath(path) {
  if (state.mode === "quick") {
    const readingMatch = path.match(/^readings\.0\.(.+)$/);
    const metric = readingMatch ? metricForKey(readingMatch[1]) : null;
    const id = metric ? `quick-${metric.slug}` : "analyse-button";
    return { focusId: id, invalidIds: metric ? [id] : [] };
  }

  const direct = {
    pass_id: "full-pass-id",
    spacecraft: "full-spacecraft",
    started_at: "full-started-at",
  };
  if (direct[path]) return { focusId: direct[path], invalidIds: [direct[path]] };

  const limitMatch = path.match(/^limits\.([^.]+)(?:\.(direction|warning|critical))?$/);
  if (limitMatch) {
    const metric = metricForKey(limitMatch[1]);
    if (metric && limitMatch[2]) {
      const id = `limit-${metric.slug}-${limitMatch[2]}`;
      return { focusId: id, invalidIds: [id] };
    }
    if (metric) {
      const ids = ["direction", "warning", "critical"].map((field) => `limit-${metric.slug}-${field}`);
      return { focusId: ids[0], invalidIds: ids };
    }
  }

  const readingMatch = path.match(/^readings\.(\d+)\.(timestamp|.+)$/);
  if (readingMatch) {
    if (readingMatch[2] === "timestamp") {
      const id = `reading-${readingMatch[1]}-timestamp`;
      return { focusId: id, invalidIds: [id] };
    }
    const metric = metricForKey(readingMatch[2]);
    if (metric) {
      const id = `reading-${readingMatch[1]}-${metric.slug}`;
      return { focusId: id, invalidIds: [id] };
    }
  }
  return { focusId: "analyse-button", invalidIds: [] };
}

function clearErrors() {
  byId("error-title").textContent = "Please correct the highlighted telemetry";
  byId("error-summary").hidden = true;
  byId("error-list").replaceChildren();
  document.querySelectorAll('[aria-invalid="true"]').forEach((element) => element.removeAttribute("aria-invalid"));
}

function showErrorSummary(result, { title, status, linkFields }) {
  clearErrors();
  byId("error-title").textContent = title;
  const issues = Array.isArray(result.issues) && result.issues.length
    ? result.issues
    : [{ path: "input", message: result.error || "The telemetry could not be analysed." }];
  issues.forEach((issue) => {
    const item = document.createElement("li");
    if (linkFields) {
      const targets = fieldTargetsForPath(issue.path);
      targets.invalidIds.forEach((id) => {
        const target = byId(id);
        if (target) target.setAttribute("aria-invalid", "true");
      });
      const link = document.createElement("a");
      link.href = `#${targets.focusId}`;
      link.textContent = `${issue.path}: ${issue.message}`;
      item.append(link);
    } else {
      item.textContent = `${issue.path}: ${issue.message}`;
    }
    byId("error-list").append(item);
  });
  byId("error-summary").hidden = false;
  byId("error-summary").focus();
  setBridgeStatus(status);
}

function showErrors(result) {
  showErrorSummary(result, {
    title: "Please correct the highlighted telemetry",
    status: "Validation found fields that need attention.",
    linkFields: true,
  });
}

function showLoadErrors(result, kind) {
  const example = kind === "example";
  showErrorSummary(result, {
    title: example
      ? "The bundled example could not be loaded"
      : "The selected JSON could not be imported",
    status: example
      ? "Example loading failed. The current editor and analysis are unchanged."
      : "Import failed. The current editor and analysis are unchanged.",
    linkFields: false,
  });
}

function showInitializationError(error) {
  clearErrors();
  byId("error-title").textContent = "The desktop application could not initialize";
  const item = document.createElement("li");
  item.textContent = error.message || String(error);
  byId("error-list").append(item);
  byId("error-summary").hidden = false;
  byId("error-summary").focus();
  byId("analyse-button").disabled = true;
  setBridgeStatus("Initialization failed. Restart the application or reinstall the complete bundle.");
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
  if (!state.initialized) return;
  clearErrors();
  clearResult();
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
    if (submittedRevision !== state.inputRevision) discardStaleAnalysis();
    else showErrors({ error: error.message, issues: [] });
  } finally {
    setBusy(false);
  }
}

function beginEditorRequest() {
  return {
    requestRevision: ++state.editorRequestRevision,
    inputRevision: state.inputRevision,
  };
}

function editorRequestIsCurrent(request) {
  return request.requestRevision === state.editorRequestRevision
    && request.inputRevision === state.inputRevision;
}

async function loadExample(name) {
  const request = beginEditorRequest();
  setBridgeStatus(`Loading ${name} example…`);
  try {
    const result = await callBridge("load_example", name);
    if (!editorRequestIsCurrent(request)) return;
    if (!result.ok) showLoadErrors(result, "example");
    else setFullPayload(JSON.parse(result.payload_json));
  } catch (error) {
    if (editorRequestIsCurrent(request)) {
      showLoadErrors({ error: error.message, issues: [] }, "example");
    }
  }
}

async function importJson() {
  const request = beginEditorRequest();
  setBridgeStatus("Opening telemetry JSON…");
  try {
    const result = await callBridge("open_input_json");
    if (!editorRequestIsCurrent(request)) return;
    if (result.cancelled) {
      setBridgeStatus(state.analysisId
        ? "Import cancelled. The current analysis remains available."
        : "Import cancelled. The editor is unchanged.");
    } else if (!result.ok) showLoadErrors(result, "import");
    else setFullPayload(JSON.parse(result.payload_json));
  } catch (error) {
    if (editorRequestIsCurrent(request)) {
      showLoadErrors({ error: error.message, issues: [] }, "import");
    }
  }
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
  byId("quick-grid").addEventListener("input", (event) => {
    const key = event.target.dataset.quickKey;
    if (!key) return;
    const field = quickFields[key];
    if (event.target.dataset.quickKind === "range") field.number.value = field.range.value;
    else if (Number.isFinite(Number(field.number.value))) field.range.value = field.number.value;
    updateQuickOutput(key);
  });
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
      const reading = { timestamp: row.querySelector(".reading-timestamp").value };
      metricDefinitions.forEach((metric) => {
        reading[metric.key] = row.querySelector(`[data-metric-key="${metric.key}"]`).value;
      });
      addReadingRow(reading, index);
    }
    renumberReadingRows();
    invalidateResult();
  });
  document.querySelectorAll(".example-button").forEach((button) => {
    button.addEventListener("click", () => loadExample(button.dataset.example));
  });
  byId("import-json").addEventListener("click", importJson);
  byId("analyse-button").addEventListener("click", analyseCurrent);
  byId("save-json").addEventListener("click", () => save("json"));
  byId("save-report").addEventListener("click", () => save("report"));
  document.addEventListener("input", (event) => {
    if (event.target.matches("input, select")) invalidateResult();
  });
}

function validateConfiguration(configuration) {
  if (!configuration || !Array.isArray(configuration.metrics) || configuration.metrics.length !== 3) {
    throw new Error("The Python bridge returned an invalid metric configuration.");
  }
  const keys = new Set(configuration.metrics.map((metric) => metric.key));
  const slugs = new Set(configuration.metrics.map((metric) => metric.slug));
  if (keys.size !== configuration.metrics.length || slugs.size !== configuration.metrics.length) {
    throw new Error("The Python bridge returned duplicate metric identifiers.");
  }
  configuration.metrics.forEach((metric) => {
    if (!metric.label || !metric.unit || !metric.quick || !metric.limit) {
      throw new Error(`The Python bridge returned incomplete configuration for '${metric.key}'.`);
    }
  });
  return configuration.metrics;
}

async function initializeApp() {
  if (state.initializationPromise) return state.initializationPromise;
  state.initializationPromise = (async () => {
    try {
      const configuration = await callBridge("get_configuration");
      metricDefinitions = validateConfiguration(configuration);
      renderQuickControls();
      renderLimitEditors();
      renderReadingHeader();
      bindEvents();
      state.initialized = true;
      resetQuick();
      byId("analyse-button").disabled = false;
      setBridgeStatus("The Python engine is ready.");
    } catch (error) {
      showInitializationError(error);
    }
  })();
  return state.initializationPromise;
}

window.addEventListener("pywebviewready", initializeApp, { once: true });
if (bridgeApi()) initializeApp();
else setBridgeStatus("Waiting for the Python desktop bridge…");
