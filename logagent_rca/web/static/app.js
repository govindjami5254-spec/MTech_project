// LogAgent-RCA web client. All data is rendered with textContent (never innerHTML) to avoid script injection
// from log content. Every state-changing request sends the anti-CSRF header the server requires.
"use strict";

const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || "";
const HEADERS = { "X-Requested-With": "logagent-rca", "X-CSRF-Token": CSRF };

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts,
    headers: { ...(opts.headers || {}), ...(opts.method && opts.method !== "GET" ? HEADERS : {}) } });
  let body = null;
  try { body = await res.json(); } catch (_) { /* not JSON */ }
  if (res.status === 401) { window.location = "/login"; throw new Error("login required"); }
  if (!res.ok) {
    const err = new Error((body && body.detail) || res.statusText);
    err.errors = (body && body.errors) || {};
    if (body && Array.isArray(body.detail)) {
      err.message = "validation failed";
      for (const d of body.detail) err.errors[(d.loc || []).slice(-1)[0] || "request"] = d.msg;
    }
    throw err;
  }
  return body;
}

const fmt = {
  dt: (s) => (s ? s.replace("T", " ").replace(/\.\d+/, "").replace("+00:00", "Z") : "–"),
  num: (x, d = 0) => (x === null || x === undefined ? "–" : Number(x).toFixed(d)),
};

function fillKV(tbody, rows) {
  tbody.replaceChildren(...rows.map(([k, v]) => el("tr", {}, el("th", {}, k), el("td", {}, v ?? "–"))));
}

function statusBadge(s) { return el("span", { class: `status s-${s}` }, s); }

// ---------------------------------------------------------------- dashboard
async function initDashboard() {
  const d = await api("/api/dashboard");
  document.getElementById("c-inv").textContent = d.investigations;
  document.getElementById("c-an").textContent = d.analyses;
  const s = d.by_status;
  document.getElementById("c-st").textContent = `${s.ok} / ${s.failed + s.aborted} / ${s.error}`;
  document.getElementById("c-q").textContent = `${s.queued} / ${s.running}`;
  const m = d.median_wall_seconds;
  document.getElementById("c-rt").textContent = `${m.E2b ? fmt.num(m.E2b) + " s" : "–"} / ${m.E3 ? fmt.num(m.E3) + " s" : "–"}`;
  document.getElementById("c-model").textContent = `${d.model} · B = ${d.evidence_token_budget}`;
  const tb = document.querySelector("#recent tbody");
  tb.replaceChildren(...(d.recent.length ? d.recent.map((r) => el("tr", {},
    el("td", {}, el("a", { href: `/investigations/${r.id}` }, r.id)), el("td", {}, r.incident),
    el("td", {}, fmt.dt(r.created_at)), el("td", {}, statusBadge(r.status)), el("td", {}, r.modes.join(", ") || "–")))
    : [el("tr", {}, el("td", { colspan: 5, class: "muted" }, "No investigations yet."))]));
}

// ---------------------------------------------------------------- new analysis
function initNew() {
  const form = document.getElementById("new-form");
  const body = document.body.dataset;
  const filesIn = document.getElementById("files");
  const trigSel = document.getElementById("trigger_file");
  const lineIn = document.getElementById("trigger_line");
  const compIn = document.getElementById("trigger_component");
  const preview = document.getElementById("line-preview");
  const errs = document.getElementById("form-errors");
  let fileLines = {};

  filesIn.addEventListener("change", async () => {
    const list = document.getElementById("file-list");
    trigSel.replaceChildren();
    fileLines = {};
    list.replaceChildren();
    for (const f of filesIn.files) {
      list.append(el("li", {}, `${f.name} — ${(f.size / 1024).toFixed(1)} KiB`));
      trigSel.append(el("option", { value: f.name }, f.name));
      if (f.size <= Number(body.maxFileBytes)) fileLines[f.name] = (await f.text()).split(/\r?\n/);
    }
    showLine();
  });

  function showLine() {
    const lines = fileLines[trigSel.value];
    const n = Number(lineIn.value);
    if (!lines || !n) { preview.textContent = ""; return; }
    const line = lines[n - 1];
    preview.textContent = line === undefined ? `(file has only ${lines.length} lines)` : `${n}: ${line}`;
    const m = line && line.match(/^\d{4}-\d{2}-\d{2}[T ]\S+\s+[A-Za-z]+\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s/);
    if (m && !compIn.dataset.touched) compIn.value = m[1];
  }
  trigSel.addEventListener("change", showLine);
  lineIn.addEventListener("input", showLine);
  compIn.addEventListener("input", () => { compIn.dataset.touched = "1"; });

  function clientErrors() {
    const e = [];
    const files = [...filesIn.files];
    if (!files.length) e.push("Select at least one log file.");
    if (files.length > Number(body.maxFiles)) e.push(`At most ${body.maxFiles} files.`);
    let total = 0;
    for (const f of files) {
      total += f.size;
      if (!/\.(log|txt)$/i.test(f.name)) e.push(`${f.name}: only .log and .txt files are accepted.`);
      if (f.size > Number(body.maxFileBytes)) e.push(`${f.name}: file too large.`);
      if (f.size === 0) e.push(`${f.name}: file is empty.`);
    }
    if (total > Number(body.maxTotalBytes)) e.push("Total upload too large.");
    for (const id of ["incident_id", "description", "ts_local", "trigger_line", "trigger_component", "rule_id"]) {
      const inp = document.getElementById(id);
      if (!inp.checkValidity()) e.push(`${inp.labels[0]?.textContent || id}: ${inp.validationMessage}`);
    }
    return e;
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const e = clientErrors();
    errs.replaceChildren(...e.map((x) => el("div", {}, x)));
    if (e.length) return;
    const fd = new FormData();
    for (const f of filesIn.files) fd.append("files", f, f.name);
    let ts = document.getElementById("ts_local").value;
    if (ts.length === 16) ts += ":00";
    fd.append("timestamp", ts + document.getElementById("ts_zone").value);
    for (const id of ["incident_id", "description", "trigger_file", "trigger_line", "trigger_component", "rule_id"]) {
      fd.append(id, document.getElementById(id).value.trim());
    }
    fd.append("mode", form.querySelector('input[name="mode"]:checked').value);
    const btn = document.getElementById("submit");
    btn.disabled = true;
    btn.textContent = "Uploading and validating…";
    try {
      const r = await api("/api/incidents", { method: "POST", body: fd });
      window.location = `/investigations/${r.id}`;
    } catch (err) {
      errs.replaceChildren(el("div", {}, err.message),
        ...Object.entries(err.errors || {}).map(([k, v]) => el("div", {}, `${k}: ${v}`)));
      btn.disabled = false;
      btn.textContent = "Analyze";
    }
  });
}

// ---------------------------------------------------------------- investigation (progress + report)
const EVENT_TEXT = {
  input_validated: (e) => `Input validated (${e.files} file(s))`,
  logs_ingested: (e) => `Logs ingested: ${e.events} events from ${e.files} file(s); ${e.unparsed_lines} unparsed line(s); ${e.suspicious_events} flagged as possible prompt injection`,
  analysis_queued: (e) => `Analysis queued (${e.mode})`,
  analysis_started: (e) => `Analysis started: ${e.mode}, model ${e.model}, evidence budget ${e.evidence_token_budget} tokens`,
  analysis_refused: () => "Analysis refused: the research experiment is running on this host",
  analysis_error: (e) => `Analysis error: ${e.error}`,
  analysis_interrupted: () => "Analysis interrupted by a server restart",
  report_validated: (e) => `Report validated: ${e.claims_supported} of ${e.claims_total} claims supported; ${e.fabricated_ids} fabricated evidence ID(s)${e.abstained_by_validator ? "; no hypothesis survived validation" : ""}`,
  analysis_finished: (e) => `Analysis finished: ${e.status} in ${fmt.num(e.wall_seconds)} s`,
  e3_start: () => "Agent investigation started",
  tool_call: (e) => `Step ${e.step}: ${e.tool} ${JSON.stringify(e.args || {})} → ${(e.new_ids || []).length} new evidence item(s), ${e.new_tokens} tokens; budget used ${e.budget_used}${e.budget_exhausted ? " (budget exhausted)" : ""}`,
  tool_blocked: (e) => `Step ${e.step}: tool request refused (${e.code})`,
  coverage_gate_pending: (e) => `Coverage gate: unexamined components with earlier problems: ${(e.pending || []).join(", ")}`,
  coverage_gate: (e) => `Coverage gate round ${e.round}: finishing refused (${e.reason})`,
  coverage_gate_skipped: () => "Coverage gate skipped: evidence budget exhausted",
  controller_nudge: () => "Controller: more tool calls required before finishing",
  injection_suspected: (e) => `Evidence ${e.evidence_id} flagged as possible prompt injection`,
  e3_aborted: (e) => `Agent loop stopped: ${e.reason}`,
  e3_end: (e) => `Agent investigation ended: ${e.steps} step(s), ${e.tool_calls} tool call(s), ${e.gate_rounds} gate round(s)`,
  runner_retry: () => "Retrying after an infrastructure error",
};

async function initInvestigation() {
  const inv = document.body.dataset.inv;
  const sel = document.getElementById("analysis-select");
  const msg = document.getElementById("action-msg");
  let timer = null;

  async function loadHead() {
    const d = await api(`/api/incidents/${inv}`);
    const i = d.incident;
    const head = document.getElementById("inv-head");
    head.replaceChildren(el("table", { class: "grid kv" }, el("tbody", {},
      ...[["Incident", `${i.id} — ${i.description}`], ["Incident time (UTC)", fmt.dt(i.ts)],
        ["Trigger", `${i.trigger_uid} (${i.trigger_component})`], ["Rule", i.rule_id],
        ["Files", d.log_files.map((f) => `${f.name} (${f.lines} lines)`).join(", ")],
        ["Created", `${fmt.dt(d.created_at)} by ${d.owner}`]].map(([k, v]) => el("tr", {}, el("th", {}, k), el("td", {}, v))))),
      ...(d.warnings || []).map((w) => el("p", { class: "warn" }, w)));
    const keep = sel.value;
    sel.replaceChildren(...d.analyses.map((a) => el("option", { value: a.run_id }, `${a.mode} r${a.repeat} — ${a.status}`)));
    if (keep && d.analyses.some((a) => a.run_id === keep)) sel.value = keep;
    else if (d.analyses.length) sel.value = d.analyses[d.analyses.length - 1].run_id;
    return d;
  }

  async function refresh() {
    clearTimeout(timer);
    const d = await loadHead();
    if (!sel.value) { document.getElementById("status").replaceChildren(statusBadge("created")); return; }
    const p = await api(`/api/incidents/${inv}/status?run_id=${encodeURIComponent(sel.value)}`);
    const a = p.analysis;
    document.getElementById("status").replaceChildren(statusBadge(a.status));
    const evs = [...p.events.map((e) => ({ ...e, src: "service" })), ...p.agent_events.map((e) => ({ ...e, src: "agent" }))]
      .sort((x, y) => (x.ts < y.ts ? -1 : 1));
    document.getElementById("events").replaceChildren(...evs.map((e) =>
      el("li", { class: `ev-${e.src}` }, el("span", { class: "t" }, fmt.dt(e.ts)), " ",
        (EVENT_TEXT[e.kind] || (() => e.kind))(e))));
    if (["queued", "running"].includes(a.status)) timer = setTimeout(refresh, 3000);
    else if (["ok", "failed", "aborted"].includes(a.status)) await loadReport(a.run_id);
    else document.getElementById("report-panel").hidden = true;
  }

  async function loadReport(runId) {
    const r = await api(`/api/incidents/${inv}/report?run_id=${encodeURIComponent(runId)}`);
    document.getElementById("report-panel").hidden = false;
    document.getElementById("dl-md").href = `/api/incidents/${inv}/report.md?run_id=${encodeURIComponent(runId)}`;
    document.getElementById("dl-json").href = `/api/incidents/${inv}/report.json?run_id=${encodeURIComponent(runId)}`;
    document.getElementById("verdict").replaceChildren(
      r.status !== "ok" ? el("p", { class: "warn" }, `Run status ${r.status}: ${r.error || "no valid report"}`) : "",
      r.abstained ? el("p", { class: "warn" }, "The report states that the evidence is insufficient to identify a root cause.") : "");
    const evBtn = (e) => el("button", { class: "link", onclick: () => showSource(runId, e.id) }, e.id);
    document.getElementById("hypotheses").replaceChildren(...r.hypotheses.map((h) => el("article", { class: "hyp" },
      el("h4", {}, `${h.rank}. ${h.cause_component}`, el("span", { class: "conf", title: r.notes.confidence }, ` confidence ${fmt.num(h.confidence, 2)}`)),
      el("p", {}, h.cause_summary),
      el("ul", {}, ...h.claims.map((c) => el("li", {}, c.text,
        el("ul", { class: "cites" }, ...c.evidence.map((e) => el("li", {}, evBtn(e), ` ${e.source}:${e.line_no} `,
          el("code", {}, e.message)))))))));
    document.getElementById("confidence-note").textContent = r.notes.confidence;
    document.getElementById("recs-note").textContent = r.notes.recommendations;
    const li = (xs) => (xs.length ? xs.map((x) => el("li", {}, x)) : [el("li", { class: "muted" }, "none")]);
    document.getElementById("gaps").replaceChildren(...li(r.evidence_gaps));
    document.getElementById("recs").replaceChildren(...li(r.recommendations));
    const v = r.validation;
    document.getElementById("validation").replaceChildren(v ? el("table", { class: "grid kv" }, el("tbody", {},
      ...[["Claims supported", `${v.claims_supported} of ${v.claims_total} (unsupported rate ${fmt.num(v.unsupported_claim_rate, 2)})`],
        ["Fabricated evidence IDs", v.fabricated_ids], ["Citations of injection-flagged lines", v.suspicious_citations],
        ["Hypotheses dropped", `${v.hypotheses_dropped} of ${v.hypotheses_in}`],
        ["Validator produced abstention", v.abstained_by_validator ? "yes" : "no"]].map(([k, x]) => el("tr", {}, el("th", {}, k), el("td", {}, x)))))
      : el("p", { class: "muted" }, "No model report to validate."),
      r.removed_claims.length ? el("div", {}, el("h4", {}, "Claims removed by the validator (unsupported)"),
        el("ul", {}, ...r.removed_claims.map((c) => el("li", {}, `(${c.cause_component}) ${c.text} — cited ${c.evidence_ids.join(", ") || "nothing"}`,
          c.unknown_ids.length ? el("span", { class: "warn" }, ` · unknown IDs: ${c.unknown_ids.join(", ")}`) : "")))) : "");
    const m = r.metrics;
    fillKV(document.querySelector("#metrics tbody"), [
      ["Wall time / LLM time", `${fmt.num(m.wall_seconds)} s / ${fmt.num(m.llm_seconds)} s`],
      ["LLM calls / steps / tool calls (refused)", `${m.llm_calls} / ${m.steps} / ${m.tool_calls} (${m.blocked_tool_calls})`],
      ["Coverage-gate rounds", m.gate_rounds],
      ["Evidence budget used", `${m.unique_evidence_tokens} of ${m.evidence_token_budget} tokens (${m.unique_evidence_items} items, ${m.repeated_exposures} repeated exposures)`],
      ["Processed prompt / output tokens", `${m.prompt_tokens_total} / ${m.output_tokens_total}`],
      ["Invalid-output retries / truncated fields", `${m.parse_failures} / ${m.normalised_fields}`],
      ["Ollama CPU time / mean CPU", `${fmt.num(m.cpu_seconds)} s / ${fmt.num(m.mean_cpu_percent)} %`],
      ["Peak Ollama memory USS / RSS", `${fmt.num(m.peak_uss_mb)} / ${fmt.num(m.peak_rss_mb)} MB`]]);
    document.querySelector("#evidence tbody").replaceChildren(...r.evidence.map((e) => el("tr", { class: e.suspicious ? "flag" : "" },
      el("td", {}, e.id), el("td", {}, e.source), el("td", {}, e.line_no), el("td", {}, fmt.dt(e.ts)), el("td", {}, e.severity),
      el("td", {}, e.component), el("td", {}, el("code", {}, e.message), e.suspicious ? el("span", { class: "warn" }, " possible prompt injection") : ""),
      el("td", {}, el("button", { class: "link", onclick: () => showSource(runId, e.id) }, "source")))));
    const mo = r.model || {};
    fillKV(document.querySelector("#provenance tbody"), [
      ["Run", `${r.run_id} (${r.mode}, repeat ${r.repeat}) started ${fmt.dt(r.started_at)}`],
      ["Model", `${mo.name || "–"}, ${mo.quantization || ""} ${mo.parameter_size || ""}; Ollama ${mo.ollama_version || "–"}`],
      ["Weights digest", mo.weights_digest || "–"], ["Temperature / seed / context / max output", `${mo.temperature} / ${mo.seed} / ${mo.num_ctx} / ${mo.num_predict}`],
      ["Code commit", r.code_commit || "–"], ["Config hash", r.config_hash]]);
  }

  async function showSource(runId, eid) {
    const s = await api(`/api/incidents/${inv}/evidence/${encodeURIComponent(eid)}/source?run_id=${encodeURIComponent(runId)}`);
    document.getElementById("source-title").textContent = `${eid}: ${s.evidence.source}, line ${s.evidence.line_no}`;
    document.getElementById("source-meta").textContent = `As presented to the model: ${s.evidence.message_as_presented}`;
    const pre = document.getElementById("source-lines");
    pre.replaceChildren(...s.lines.map((l) => el("div", { class: l.target ? "target" : "" }, `${String(l.line_no).padStart(6)}  ${l.text}`)));
    document.getElementById("source-dialog").showModal();
  }

  for (const b of document.querySelectorAll("[data-run-mode]")) {
    b.addEventListener("click", async () => {
      msg.textContent = "";
      try {
        const a = await api(`/api/incidents/${inv}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: b.dataset.runMode }) });
        await loadHead();
        sel.value = a.run_id;
        refresh();
      } catch (err) { msg.textContent = err.message; }
    });
  }
  sel.addEventListener("change", refresh);
  refresh();
}

// ---------------------------------------------------------------- history
async function initHistory() {
  const form = document.getElementById("filters");
  async function load() {
    const q = new URLSearchParams();
    for (const [k, v] of new FormData(form)) if (v) q.set(k, k === "date_to" ? `${v}T23:59:59Z` : k === "date_from" ? `${v}T00:00:00Z` : v);
    const rows = await api(`/api/incidents?${q}`);
    document.querySelector("#history tbody").replaceChildren(...(rows.length ? rows.map((r) => el("tr", {},
      el("td", {}, el("a", { href: `/investigations/${r.id}` }, r.id)), el("td", {}, r.incident.id), el("td", {}, r.incident.description),
      el("td", {}, fmt.dt(r.created_at)), el("td", {}, r.owner),
      el("td", {}, ...r.analyses.map((a) => el("div", {}, `${a.mode} r${a.repeat} `, statusBadge(a.status)))),
      el("td", {}, ...r.analyses.filter((a) => ["ok", "failed", "aborted"].includes(a.status)).map((a) => el("div", {},
        el("a", { href: `/api/incidents/${r.id}/report.md?run_id=${a.run_id}` }, `${a.mode} r${a.repeat} .md`), " · ",
        el("a", { href: `/api/incidents/${r.id}/report.json?run_id=${a.run_id}` }, ".json"))))))
      : [el("tr", {}, el("td", { colspan: 7, class: "muted" }, "No investigations match."))]));
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
  load();
}

// ---------------------------------------------------------------- settings
async function initSettings() {
  const h = await api("/api/health");
  const o = h.ollama;
  fillKV(document.querySelector("#h-backend tbody"), [["Backend", h.backend], ["Authentication mode", h.auth_mode],
    ["Analyses waiting in queue", h.queue.pending], ["Config file", h.config_file],
    ["Research experiment running", h.experiment_running ? "yes — analyses are refused until it finishes" : "no"]]);
  fillKV(document.querySelector("#h-ollama tbody"), o.reachable
    ? [["Status", "reachable"], ["Version", o.version], ["Configured model installed", o.configured_model_installed ? "yes" : "NO"]]
    : [["Status", "NOT reachable"], ["Error", o.error]]);
  document.querySelector("#h-models tbody").replaceChildren(...((o.models || []).map((m) => el("tr", {},
    el("td", {}, m.name), el("td", {}, fmt.num(m.size / 1e9, 1)), el("td", {}, m.digest)))));
  fillKV(document.querySelector("#h-model tbody"), Object.entries(h.model).map(([k, v]) => [k, String(v)]));
  fillKV(document.querySelector("#h-budget tbody"), [...Object.entries(h.budget), ...Object.entries(h.agent)].map(([k, v]) => [k, String(v)]));
  const p = h.persistence, t = h.tokenizer;
  fillKV(document.querySelector("#h-persist tbody"), [["Workspace writable", p.writable ? "yes" : `NO (${p.error})`],
    ["Free disk", p.free_gb !== undefined ? `${p.free_gb} GB` : "–"], ["Stored investigations", p.investigations ?? "–"],
    ["Tokenizer verified", t.verified ? `yes (${t.tokenizer_sha256?.slice(0, 12)}…, tokenizers ${t.tokenizers_version})` : `NO (${t.error})`]]);
}

const PAGES = { dashboard: initDashboard, new: initNew, investigation: initInvestigation, history: initHistory, settings: initSettings };
document.addEventListener("DOMContentLoaded", () => {
  const f = PAGES[document.body.dataset.page];
  if (f) Promise.resolve(f()).catch((e) => {
    document.getElementById("main").prepend(el("p", { class: "errors", role: "alert" }, `Error: ${e.message}`));
  });
});
