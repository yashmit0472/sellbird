"use strict";

const el = (id) => document.getElementById(id);
const steps = {
  profile: "Business profile", icp: "Ideal customer profile", research: "Prospect research",
  signals: "Buying signals", problem: "Problem hypothesis", score: "Prospect score",
  draft: "Email draft", reply: "Reply classification"
};
const statuses = { queued: "Queued", running: "Running", waiting: "Waiting", complete: "Complete", failed: "Failed" };
const fragment = new URLSearchParams(location.hash.slice(1));
let token = fragment.get("token") || sessionStorage.getItem("sellbird-local-token") || "";
if (fragment.has("token")) history.replaceState(null, "", location.pathname);
let workspace;
let activeId;
let runtime;
let displayedJob;
let refreshing = false;

function node(tag, value) {
  const item = document.createElement(tag);
  item.textContent = value;
  return item;
}

function notice(message, error = false) {
  el("notice").textContent = message;
  el("notice").classList.toggle("error", error);
}

async function api(path, payload) {
  const headers = { Authorization: "Bearer " + token };
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch("/api/" + path, {
    method: payload === undefined ? "GET" : "POST", headers,
    body: payload === undefined ? undefined : JSON.stringify(payload)
  });
  if (response.status === 401) {
    el("unlock").hidden = false;
    el("workspace").hidden = true;
    sessionStorage.removeItem("sellbird-local-token");
    token = "";
    throw new Error("Enter the token printed by the local launcher.");
  }
  const body = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map(item => item.loc.slice(1).join(".") + " " + item.msg).join(". ") : body.detail;
    throw new Error(detail || body.message || "Request failed.");
  }
  return body;
}

function updateOptions(select, options, preferred) {
  const old = select.value;
  select.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
  if (options.some(([value]) => String(value) === old)) select.value = old;
  else if (preferred) select.value = preferred;
}

async function updateRuntime() {
  runtime = await api("status");
  const { hardware, installed, models, offline, ollama, embeddings } = runtime;
  el("runtime").textContent = ollama ? (offline ? "Ollama ready · Offline mode" : "Ollama ready") : "Ollama unavailable";
  el("runtime").classList.toggle("error", !ollama);
  el("hardware").replaceChildren(
    node("p", hardware.cpu + " · " + hardware.logical_cpus + " logical CPUs · " + hardware.ram_gib + " GiB RAM (" + hardware.available_gib + " available)"),
    node("p", hardware.gpu + (hardware.vram_gib ? " · " + hardware.vram_gib + " GiB VRAM" : "")),
    node("p", "Recommended " + hardware.recommended + " · Standard " + hardware.standard + " · High performance " + hardware.high_performance),
    node("p", embeddings ? "Local embedding files found." : "Local embedding files missing."),
    node("p", runtime.endpoint)
  );
  const modelSelect = el("start").elements.model;
  updateOptions(modelSelect, models.map(model => [model, model + (installed.includes(model) ? " · installed" : " · download required")]), hardware.recommended);
  el("evidence-mode").querySelector('[value="public"]').disabled = offline;
  if (offline && el("evidence-mode").value === "public") {
    el("evidence-mode").value = "text";
    toggleEvidence();
  }
}

function rankLatestScores(jobs) {
  const latest = new Map();
  for (const job of jobs) {
    if (job.status !== "complete" || job.score == null) continue;
    const key = JSON.stringify([job.product_id, job.prospect_id]);
    const previous = latest.get(key);
    if (!previous || job.id > previous.id) latest.set(key, job);
  }
  return [...latest.values()].sort((a, b) => b.score - a.score || b.id - a.id);
}

function renderHistory() {
  const ranking = el("sort").value === "score";
  const jobs = ranking ? rankLatestScores(workspace.jobs) : workspace.jobs;
  const rows = jobs.map(job => {
    const row = document.createElement("tr");
    const open = node("button", "Open #" + job.id);
    open.className = "secondary";
    open.addEventListener("click", () => showJob(job.id, true).catch(error => notice(error.message, true)));
    const action = node("td", "");
    action.append(open);
    row.append(node("td", job.product), node("td", job.prospect ?? "—"),
      node("td", job.score ?? "—"), node("td", statuses[job.status]), action);
    return row;
  });
  if (!rows.length) {
    const row = document.createElement("tr");
    const empty = node("td", ranking ? "No completed scores yet." : "No runs yet.");
    empty.colSpan = 5;
    row.append(empty);
    rows.push(row);
  }
  el("jobs").replaceChildren(...rows);
}

async function updateWorkspace() {
  workspace = await api("workspace");
  const form = el("start").elements;
  updateOptions(form.product_id, [["", "Select a product"], ...workspace.products.map(item => [item.id, item.company + " / " + item.name])]);
  updateOptions(form.prospect_id, [["", "Profile and ICP only"], ...workspace.prospects.map(item => [item.id, item.name + " (" + item.sources + " sources)"])]);
  renderHistory();
}

function fieldLabel(key) {
  const text = key.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function fieldValue(value) {
  if (!Array.isArray(value)) return node("p", String(value));
  if (!value.length) return node("p", "—");
  const list = document.createElement("ul");
  for (const entry of value) {
    list.append(node("li", typeof entry === "object" ? "Source #" + entry.evidence_id + " · “" + entry.quote + "”" : entry));
  }
  return list;
}

async function showJob(id, scroll = false) {
  activeId = id;
  const job = await api("jobs/" + id);
  if (activeId !== id) return;
  const changed = displayedJob !== id;
  displayedJob = id;
  const newSteps = job.input.steps.map(key => {
    const row = document.createElement("li");
    const detail = document.createElement("details");
    const result = job.results[key];
    detail.dataset.step = key;
    const previous = changed ? null : el("steps").querySelector('[data-step="' + key + '"]');
    detail.open = previous ? previous.open : Boolean(result && (key === "draft" || key === "score"));
    const summary = node("summary", steps[key] + (result ? "" : " · Pending"));
    if (!result) summary.className = "pending";
    detail.append(summary);
    if (result) {
      const output = document.createElement("div");
      output.className = "output";
      for (const [field, value] of Object.entries(result)) {
        const section = document.createElement("div");
        section.append(node("strong", fieldLabel(field)), fieldValue(value));
        output.append(section);
      }
      detail.append(output);
    }
    row.append(detail);
    return row;
  });
  el("steps").replaceChildren(...newSteps);
  const entries = (job.input.evidence || []).map(source => {
    const entry = document.createElement("article");
    entry.append(node("h3", "#" + source.id + " · " + source.source), node("p", source.body));
    return entry;
  });
  el("sources").replaceChildren(...entries);
  el("logs").textContent = job.logs.map(log => [
    log.created_at + " UTC", log.step, log.status, log.model, log.endpoint,
    log.elapsed_ms + " ms", (log.output_tokens ?? "—") + " output tokens"
  ].join("  ")).join("\n") || "No inference requests yet.";
  el("result-title").textContent = "Run #" + id + " · " + job.input.product.name;
  el("result-status").textContent = statuses[job.status] + (job.error ? " · " + job.error : "");
  el("retry").hidden = !["waiting", "failed"].includes(job.status);
  el("result").hidden = false;
  if (scroll) el("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function initialize() {
  if (!token) {
    el("unlock").hidden = false;
    return;
  }
  await Promise.all([updateWorkspace(), updateRuntime()]);
  sessionStorage.setItem("sellbird-local-token", token);
  el("workspace").hidden = false;
  el("unlock").hidden = true;
}

function onSubmit(id, operation) {
  const form = el(id);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await operation(values);
    } catch (error) {
      notice(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

function toggleEvidence() {
  const mode = el("evidence-mode").value;
  el("import-data").hidden = mode === "public";
  el("capture-data").hidden = mode !== "public";
  el("body-field").hidden = mode !== "text";
  el("snapshot-field").hidden = mode !== "snapshot";
}

el("evidence-mode").addEventListener("change", toggleEvidence);
el("sort").addEventListener("change", renderHistory);

onSubmit("unlock", async values => {
  token = values.token.trim();
  await initialize();
  el("unlock").reset();
  notice("");
});

onSubmit("product", async values => {
  await api("products", values);
  await updateWorkspace();
  notice("Product saved.");
});

onSubmit("evidence", async values => {
  const mode = el("evidence-mode").value;
  if (mode === "public") {
    await api("capture", { name: values.name, url: values.url, permitted: Boolean(values.permitted) });
  } else if (mode === "snapshot") {
    if (!values.snapshot.size || values.snapshot.size > 500000) throw new Error("Select a saved HTML file up to 500 KB.");
    await api("snapshot", { name: values.name, source: values.source, html: await values.snapshot.text() });
  } else {
    await api("evidence", { name: values.name, source: values.source, body: values.body });
  }
  await updateWorkspace();
  notice("Prospect evidence saved.");
});

onSubmit("start", async values => {
  const job = await api("jobs", {
    ...values, product_id: Number(values.product_id), prospect_id: Number(values.prospect_id) || null
  });
  await updateWorkspace();
  await showJob(job.id, true);
  notice("Run queued.");
});

el("retry").addEventListener("click", async () => {
  try {
    await api("jobs/" + activeId + "/retry", {});
    await showJob(activeId);
  } catch (error) { notice(error.message, true); }
});

initialize().catch(error => notice(error.message, true));
setInterval(async () => {
  if (el("workspace").hidden || refreshing) return;
  refreshing = true;
  try {
    await updateWorkspace();
    if (activeId) await showJob(activeId);
  } catch (error) {
    notice(error.message, true);
  } finally {
    refreshing = false;
  }
}, 3000);
setInterval(() => {
  if (!el("workspace").hidden) updateRuntime().catch(error => notice(error.message, true));
}, 20000);
