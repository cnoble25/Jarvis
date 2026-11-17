/* ==========================================================================
   Jarvis dashboard: UI logic and the QWebChannel bridge to the Python daemon.
   Every piece of state shown here comes from the daemon; nothing is hard-coded.
   ========================================================================== */
"use strict";

/* ---------- Small DOM helpers ---------- */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* Build an element. Text is always set through textContent, so data is never parsed as HTML. */
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/* Text with `backticks` rendered as code, built safely as DOM nodes. */
function richText(text) {
  return String(text || "").split(/(`[^`]+`)/).filter(Boolean).map((part) =>
    part.startsWith("`") && part.endsWith("`") ? el("code", { text: part.slice(1, -1) }) : document.createTextNode(part));
}

function setRich(selector, text) {
  const node = $(selector);
  if (node) node.replaceChildren(...richText(text));
}

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/* "Today 14:04" style timestamps, so a list that spans days still reads in order. */
function formatWhen(ts) {
  if (!ts) return "";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return String(ts);
  const now = new Date();
  const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86400000);
  if (dayDiff === 0) return `Today ${time}`;
  if (dayDiff === 1) return `Yesterday ${time}`;
  if (dayDiff < 7) return `${date.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
  return `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${time}`;
}

function isToday(ts) {
  const date = new Date(ts);
  return !Number.isNaN(date.getTime()) && date.toDateString() === new Date().toDateString();
}

/* Render "Super + Space" as keycaps. */
function renderKeycaps(container, shortcut) {
  container.replaceChildren();
  const keys = String(shortcut || "").split("+").map((k) => k.trim()).filter(Boolean);
  if (keys.length === 0) {
    container.append(el("span", { class: "muted", text: "Not set" }));
    return;
  }
  keys.forEach((key, i) => {
    if (i > 0) container.append(el("span", { class: "key-plus", "aria-hidden": "true", text: "+" }));
    container.append(el("kbd", { class: "key", text: key }));
  });
  container.setAttribute("aria-label", keys.join(" plus "));
}

/* ---------- IPC bridge ---------- */

const state = {
  connected: false,
  status: null,
  transcripts: [],
  transcriptsSignature: "",
  rulesSignature: "",
  rules: [],
  tools: [],
  pendingDeletes: new Map(),
};

let bridgeResolve;
const bridgeReady = new Promise((resolve) => { bridgeResolve = resolve; });

if (window.qt && window.qt.webChannelTransport && typeof QWebChannel === "function") {
  new QWebChannel(window.qt.webChannelTransport, (channel) => {
    window.jarvisBridge = channel.objects.jarvisBridge;
    state.connected = true;
    bridgeResolve(window.jarvisBridge);
  });
}

/* Call a daemon action. Always resolves to an object with `success`; never throws. */
async function ipc(action, params = {}) {
  const bridge = await Promise.race([
    bridgeReady,
    new Promise((resolve) => setTimeout(() => resolve(null), 4000)),
  ]);
  if (!bridge || typeof bridge.call_ipc !== "function") {
    setConnection(false);
    return { success: false, error: "Not connected to the Jarvis daemon." };
  }
  return new Promise((resolve) => {
    bridge.call_ipc(action, JSON.stringify(params), (json) => {
      try {
        const res = JSON.parse(json);
        if (res && res.success === undefined) res.success = true;
        resolve(res || { success: false, error: "Empty response from the daemon." });
      } catch (err) {
        resolve({ success: false, error: `Unreadable response from the daemon (${err.message}).` });
      }
    });
  });
}

function setConnection(connected) {
  state.connected = connected;
  document.body.classList.toggle("is-disconnected", !connected);
  const banner = $("#connection-banner");
  if (banner) banner.hidden = connected;
}

/* ---------- Notifications (one announced toast, optional action) ---------- */

let toastTimer = null;

function notify(message, { tone = "info", actionLabel = null, onAction = null, timeout = 4000 } = {}) {
  const toast = $("#toast");
  if (!toast) return;
  clearTimeout(toastTimer);
  toast.replaceChildren(el("span", { class: "toast-message", text: message }));
  toast.dataset.tone = tone;
  if (actionLabel && onAction) {
    toast.append(el("button", {
      type: "button",
      class: "toast-action",
      text: actionLabel,
      onclick: () => { hideToast(); onAction(); },
    }));
  }
  toast.hidden = false;
  toastTimer = setTimeout(hideToast, timeout);
}

function hideToast() {
  const toast = $("#toast");
  if (toast) toast.hidden = true;
}

/* Remove something only after an undo window. The item is hidden immediately. */
function deleteWithUndo({ key, label, hideNode, commit, restore }) {
  hideNode();
  const timer = setTimeout(async () => {
    state.pendingDeletes.delete(key);
    const res = await commit();
    if (!res.success) {
      restore();
      notify(res.error || `Couldn't delete ${label}.`, { tone: "error", timeout: 6000 });
    }
  }, 6000);
  state.pendingDeletes.set(key, timer);
  notify(`Deleted ${label}.`, {
    actionLabel: "Undo",
    timeout: 6000,
    onAction: () => {
      clearTimeout(timer);
      state.pendingDeletes.delete(key);
      restore();
      notify(`Restored ${label}.`);
    },
  });
}

/* Put a button into a busy state for the length of an async task. */
async function withBusy(button, busyLabel, task) {
  if (!button || button.disabled) return;
  const original = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  if (busyLabel) button.textContent = busyLabel;
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = original;
  }
}

/* ---------- Navigation ---------- */

const pageLoaders = {
  "overview-page": () => { loadTranscripts(); loadSettings(); },
  "conversations-page": () => { loadTranscripts(); },
  "commands-page": () => { loadTools(); },
  "macros-page": () => { loadMacros(); },
  "knows-page": () => { loadMemoryProfile(); loadFastPathRules(); },
  "settings-page": () => { loadSettings(); },
};

function activePageId() {
  return $(".page-view.active")?.id || "overview-page";
}

function showPage(pageId, { focus = false } = {}) {
  const page = document.getElementById(pageId);
  if (!page) return;
  $$(".nav-item").forEach((item) => {
    const isActive = item.dataset.page === pageId;
    item.classList.toggle("active", isActive);
    if (isActive) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  $$(".page-view").forEach((view) => view.classList.toggle("active", view === page));
  $(".main-content")?.scrollTo({ top: 0 });
  if (focus) page.querySelector("h1")?.focus({ preventScroll: true });
  pageLoaders[pageId]?.();
}

function initNavigation() {
  $$(".nav-item").forEach((item) => {
    item.addEventListener("click", () => showPage(item.dataset.page, { focus: true }));
  });
  document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-goto]");
    if (link) showPage(link.dataset.goto, { focus: true });
  });
  // Alt+1..6 switches pages, matching the sidebar order.
  document.addEventListener("keydown", (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey || recorder.active) return;
    const index = Number.parseInt(e.key, 10);
    const items = $$(".nav-item");
    if (index >= 1 && index <= items.length) {
      e.preventDefault();
      showPage(items[index - 1].dataset.page, { focus: true });
    }
  });
}

/* ---------- Live status ---------- */

const VOICE_STATES = {
  idle: { label: "Ready", detail: "Hold your shortcut and speak." },
  listening: { label: "Listening", detail: "Release the keys when you're done." },
  thinking: { label: "Thinking", detail: "Working out what to do." },
  speaking: { label: "Speaking", detail: "Answering you now." },
};

async function loadStatus() {
  const res = await ipc("get_status");
  if (!res.success) {
    setConnection(false);
    return;
  }
  setConnection(true);
  state.status = res;
  renderStatus(res);
}

function renderStatus(s) {
  const check = s.llm?.check || { ok: true };
  const idle = !s.voice_state || s.voice_state === "idle";
  // "Ready" only when Jarvis could actually answer; otherwise say so.
  const voice = idle && !check.ok
    ? { label: "Can't think", detail: "Fix the model to talk again." }
    : VOICE_STATES[s.voice_state] || VOICE_STATES.idle;
  document.body.dataset.voiceState = s.voice_state || "idle";
  document.body.classList.toggle("is-blocked", idle && !check.ok);

  $$("[data-bind='voice-label']").forEach((node) => { node.textContent = voice.label; });
  $$("[data-bind='voice-detail']").forEach((node) => { node.textContent = voice.detail; });
  $$("[data-bind='hotkey']").forEach((node) => renderKeycaps(node, s.hotkey));

  const recorderDisplay = $("#active-keybind-display");
  if (recorderDisplay && !recorder.active) renderKeycaps(recorderDisplay, s.hotkey);

  setText("#metric-stt-provider", s.stt?.name || "Unknown");
  setText("#metric-tts-provider", s.tts?.name || "Unknown");

  const llmWarning = $("#llm-warning");
  if (llmWarning) {
    llmWarning.hidden = check.ok;
    setRich("#llm-warning-text", check.message || "");
  }

  const s3 = s.s3 || {};
  setText("#metric-backup", s3.enabled ? `Backing up to ${s3.bucket}` : "Off. Conversations stay on this computer.");

  const ipcRunning = Boolean(s.ipc?.running);
  setText("#metric-ipc", ipcRunning ? `Scripts can reach Jarvis at ${s.ipc.socket_path}` : "Stopped. Scripts can't reach Jarvis.");
  $("#metric-ipc")?.classList.toggle("is-error", !ipcRunning);

  // One line in the sidebar for whatever needs the user right now.
  const needs = !ipcRunning ? "Needs you: script access stopped." : "";
  const needsNode = $("#needs-you");
  if (needsNode) {
    needsNode.textContent = needs;
    needsNode.hidden = !needs;
  }

  // Settings fields that mirror live state (only fill when the user isn't editing them).
  fillIfIdle("#setting-s3-arn", s3.arn || "");
  fillIfIdle("#setting-s3-region", s3.region || "");
  const s3Toggle = $("#setting-s3-enabled");
  if (s3Toggle && document.activeElement !== s3Toggle) s3Toggle.checked = Boolean(s3.enabled);
}

function setText(selector, text) {
  const node = $(selector);
  if (node) node.textContent = text;
}

function fillIfIdle(selector, value) {
  const input = $(selector);
  if (input && document.activeElement !== input && !input.dataset.dirty) input.value = value;
}

/* ---------- Transcripts (Overview activity + full history) ---------- */

async function loadTranscripts() {
  const res = await ipc("get_transcripts");
  if (!res.success) {
    renderListError("#transcript-logs-list", res.error, loadTranscripts);
    return;
  }
  const transcripts = res.transcripts || [];
  const last = transcripts[transcripts.length - 1];
  const signature = `${transcripts.length}:${last?.record_id || ""}:${last?.synced_to_s3 || ""}`;
  if (signature === state.transcriptsSignature) return;
  state.transcriptsSignature = signature;
  state.transcripts = transcripts;
  renderOverviewActivity();
  renderTranscriptList();
}

function turnStatusLabel(turn) {
  return turn.status === "failed"
    ? el("span", { class: "tag tag-error", text: "Failed" })
    : null;
}

/* Outcome channels for the delta. Ordered by the tool name's first match. */
const OUTCOMES = [
  { id: "replies", label: "replies", test: (tool) => tool === "none" || tool === "" },
  { id: "media", label: "volume & media", test: (tool) => /volume|media|music|spotify|audio/.test(tool) },
  { id: "focus", label: "timers & focus", test: (tool) => /timer|locked_in|focus|alarm/.test(tool) },
  { id: "apps", label: "apps & macros", test: (tool) => /app|launch|macro|screenshot|window/.test(tool) },
  { id: "power", label: "power", test: (tool) => /power|shutdown|reboot|suspend|lock/.test(tool) },
  { id: "other", label: "other commands", test: () => true },
];
const FAILED_OUTCOME = { id: "failed", label: "failed" };

function outcomeOf(turn) {
  if (turn.status === "failed") return FAILED_OUTCOME;
  const tool = String(turn.tool_executed || "none").split("->")[0].trim().toLowerCase();
  return OUTCOMES.find((o) => o.test(tool));
}

const DELTA_WINDOW = 50;

function renderDelta() {
  const svg = $("#delta-svg");
  const legend = $("#delta-legend");
  if (!svg || !legend) return;
  const turns = state.transcripts.slice(-DELTA_WINDOW);
  const total = turns.length;

  const source = $("#delta-source");
  if (source) {
    source.replaceChildren(el("strong", { text: `${total} ${total === 1 ? "request" : "requests"}` }), total >= DELTA_WINDOW ? " · your last 50, by what Jarvis did" : " · by what Jarvis did");
  }

  svg.replaceChildren();
  legend.replaceChildren();
  const figure = svg.closest(".delta-figure");
  figure?.querySelector(".delta-empty")?.remove();
  figure?.classList.toggle("is-empty", total === 0);

  if (total === 0) {
    source?.replaceChildren(el("strong", { text: "No requests yet" }));
    figure?.append(el("p", { class: "delta-empty", text: "Each thing you ask becomes a channel here, grouped by what Jarvis did with it." }));
    return;
  }

  // Count per outcome; channels sorted by volume, failures always last.
  const counts = new Map();
  turns.forEach((t) => {
    const o = outcomeOf(t);
    counts.set(o.id, { outcome: o, n: (counts.get(o.id)?.n || 0) + 1 });
  });
  const channels = [...counts.values()]
    .filter((c) => c.outcome.id !== "failed")
    .sort((a, b) => b.n - a.n);
  if (counts.has("failed")) channels.push(counts.get("failed"));

  const W = 600;
  const H = 120;
  const mid = H / 2;
  const trunkEnd = 210;
  const mouth = W;
  const maxWidth = 34;
  const trunkWidth = Math.max(4, Math.min(maxWidth, 8 + total * 0.6));
  const ns = "http://www.w3.org/2000/svg";
  const path = (d, cls, width) => {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("d", d);
    p.setAttribute("class", cls);
    p.setAttribute("stroke-width", String(width));
    return p;
  };

  const animate = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const top = 8;
  const span = H - top * 2;
  const step = channels.length > 1 ? span / (channels.length - 1) : 0;

  // The source is a soft-cornered band, not a capsule: water entering from the left edge.
  const trunk = document.createElementNS(ns, "rect");
  trunk.setAttribute("class", "trunk");
  trunk.setAttribute("x", "0");
  trunk.setAttribute("y", String(mid - trunkWidth / 2));
  trunk.setAttribute("width", String(trunkEnd));
  trunk.setAttribute("height", String(trunkWidth));
  trunk.setAttribute("rx", "3");
  svg.append(trunk);

  // Each channel leaves its own slice of the trunk, sized by its share, like a braided delta.
  let offset = mid - trunkWidth / 2;
  channels.forEach((c, i) => {
    const y = channels.length > 1 ? top + step * i : mid;
    const share = (c.n / total) * trunkWidth;
    const width = Math.max(2, share);
    const y0 = offset + share / 2;
    offset += share;
    const failed = c.outcome.id === "failed";
    const ch = path(
      `M${trunkEnd - 1} ${y0} C${trunkEnd + 120} ${y0} ${trunkEnd + 150} ${y} ${mouth} ${y}`,
      `channel${failed ? " is-failed" : ""}`,
      width,
    );
    if (!failed) ch.style.stroke = `var(--outcome-${c.outcome.id})`;
    ch.dataset.outcome = c.outcome.id;
    svg.append(ch);
    if (animate && !failed) {
      const len = ch.getTotalLength();
      ch.style.strokeDasharray = `${len}`;
      ch.style.setProperty("--len", `${len}`);
      ch.style.animationDelay = `${120 + i * 70}ms`;
      ch.classList.add("draw");
    }

    const item = el("li", { style: `top:${(y / H) * 100}%;--dot: var(--outcome-${c.outcome.id})` }, el("button", {
      type: "button",
      class: failed ? "is-failed" : null,
      "aria-label": `${c.n} ${c.outcome.label}. Show these conversations.`,
      onclick: () => showOutcome(c.outcome),
      onmouseenter: () => highlightChannel(c.outcome.id),
      onmouseleave: () => highlightChannel(null),
      onfocus: () => highlightChannel(c.outcome.id),
      onblur: () => highlightChannel(null),
    }, [el("span", { class: "n", text: String(c.n) }), el("span", { text: c.outcome.label })]));
    legend.append(item);
  });
}

function highlightChannel(id) {
  $$("#delta-svg .channel").forEach((p) => p.classList.toggle("is-dimmed", Boolean(id) && p.dataset.outcome !== id));
}

function showOutcome(outcome) {
  state.outcomeFilter = outcome;
  const filter = $("#transcript-filter");
  if (filter) filter.value = "all";
  showPage("conversations-page", { focus: true });
  renderTranscriptList();
}

function renderLatest() {
  const box = $("#latest-exchange");
  if (!box) return;
  const turn = state.transcripts[state.transcripts.length - 1];
  box.classList.remove("is-failed");
  if (!turn) {
    box.replaceChildren(
      el("p", { class: "empty-state when-ready" },
        ["Nothing yet. Hold ", el("span", { class: "keycaps-inline", dataset: { bind: "hotkey" } }), " anywhere and say “what time is it?”"]),
      el("p", { class: "empty-state when-blocked", text: "Nothing yet. Once the model is back, your first request shows up here." }),
    );
    if (state.status) renderStatus(state.status);
    return;
  }
  const failed = turn.status === "failed";
  box.classList.toggle("is-failed", failed);
  const showHint = failed && turn.failure_hint && state.status?.llm?.check?.ok !== false;
  box.replaceChildren(
    el("div", { class: "latest-when" }, [
      el("time", { datetime: turn.timestamp || "", text: formatWhen(turn.timestamp) }),
      failed ? turnStatusLabel(turn) : (turn.tool_executed && turn.tool_executed !== "none")
        ? el("code", { class: "latest-tool", text: turn.tool_executed })
        : el("span", { class: "latest-tool", text: "Reply only" }),
    ]),
    el("q", { class: "latest-query", text: turn.user_query || "(nothing heard)" }),
    el("p", { class: "latest-reply", text: turn.spoken_response || "(no reply)" }),
    ...(showHint ? [el("p", { class: "fix-hint latest-hint" }, richText(turn.failure_hint))] : []),
  );
}

function renderRecentRows() {
  const list = $("#recent-rows");
  if (!list) return;
  const earlier = state.transcripts.slice(0, -1).slice(-4).reverse();
  if (earlier.length === 0) {
    list.replaceChildren(el("li", { class: "muted", text: "Earlier conversations appear here." }));
    return;
  }
  list.replaceChildren(...earlier.map((t) => {
    const failed = t.status === "failed";
    return el("li", { class: `row${failed ? " is-failed" : ""}` }, [
      el("time", { class: "row-when", datetime: t.timestamp || "", text: formatWhen(t.timestamp) }),
      el("span", { class: "row-query", text: t.user_query || "(nothing heard)" }),
      el("span", { class: "row-reply", text: t.spoken_response || "" }),
      el("span", { class: "row-tool outcome", style: `--dot: var(--outcome-${outcomeOf(t).id})`, text: failed ? "Failed" : outcomeOf(t).label }),
    ]);
  }));
}

function renderOverviewActivity() {
  renderDelta();
  renderLatest();
  renderRecentRows();
}

function renderTranscriptList() {
  const list = $("#transcript-logs-list");
  if (!list) return;
  const query = ($("#transcript-search")?.value || "").trim().toLowerCase();
  const filter = $("#transcript-filter")?.value || "all";

  if (state.transcripts.length === 0) {
    list.replaceChildren(el("p", { class: "empty-state" },
      ["No conversations recorded yet. Hold ", el("span", { class: "keycaps-inline", dataset: { bind: "hotkey" } }), " and speak to Jarvis."]));
    if (state.status) renderStatus(state.status);
    return;
  }

  const outcome = state.outcomeFilter;
  const chip = $("#category-chip");
  if (chip) {
    chip.hidden = !outcome;
    setText("#category-chip-label", outcome ? `Only ${outcome.label}` : "");
  }

  const matches = state.transcripts.slice().reverse().filter((t) => {
    const haystack = `${t.user_query || ""} ${t.tool_executed || ""} ${t.spoken_response || ""}`.toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (outcome && outcomeOf(t).id !== outcome.id) return false;
    if (filter === "today") return isToday(t.timestamp);
    if (filter === "failed") return t.status === "failed";
    if (filter === "local") return !(t.synced_to_s3 || t.s3_synced);
    return true;
  });

  setText("#transcript-count", `Showing ${matches.length} of ${state.transcripts.length}`);

  if (matches.length === 0) {
    list.replaceChildren(el("p", { class: "empty-state", text: "No conversations match. Clear the search or choose “Everything”." }));
    return;
  }

  list.replaceChildren(...matches.map((t) => {
    const failed = t.status === "failed";
    const synced = Boolean(t.synced_to_s3 || t.s3_synced);
    return el("article", { class: `turn${failed ? " is-failed" : ""}` }, [
      el("header", { class: "turn-head" }, [
        el("q", { class: "turn-query", text: t.user_query || "(nothing heard)" }),
        el("time", { class: "turn-time", datetime: t.timestamp || "", text: formatWhen(t.timestamp) }),
      ]),
      el("p", { class: "turn-reply", text: t.spoken_response || "(no reply)" }),
      failed && t.failure_hint ? el("p", { class: "fix-hint" }, richText(t.failure_hint)) : null,
      el("footer", { class: "turn-meta" }, [
        turnStatusLabel(t),
        failed ? null : el("span", { class: "outcome", style: `--dot: var(--outcome-${outcomeOf(t).id})`, text: outcomeOf(t).label }),
        (t.tool_executed && t.tool_executed !== "none") ? el("span", {}, ["Ran ", el("code", { text: t.tool_executed })]) : el("span", { text: "Reply only" }),
        synced ? null : el("span", { class: "tag", text: "Not backed up" }),
      ]),
    ]);
  }));
}

function renderListError(selector, message, retry) {
  const node = $(selector);
  if (!node) return;
  node.replaceChildren(el("div", { class: "inline-error", role: "alert" }, [
    el("span", { text: message || "Couldn't load this list." }),
    el("button", { type: "button", class: "btn btn-secondary btn-small", text: "Try again", onclick: retry }),
  ]));
}

function initTranscripts() {
  $("#transcript-search")?.addEventListener("input", debounce(renderTranscriptList, 150));
  $("#transcript-filter")?.addEventListener("change", renderTranscriptList);
  $("#category-chip-clear")?.addEventListener("click", () => {
    state.outcomeFilter = null;
    renderTranscriptList();
    $("#transcript-search")?.focus();
  });
}

/* ---------- Memory profile ---------- */

let reanalysisPoll = null;

async function loadMemoryProfile() {
  const res = await ipc("get_memory_profile");
  const container = $("#profile-md-container");
  if (!container) return res;
  if (!res.success) {
    renderListError("#profile-md-container", res.error, loadMemoryProfile);
    return res;
  }
  renderProfileMarkdown(container, res.content || "");
  return res;
}

/* Minimal, safe markdown: headings, bullet lists and paragraphs, built as DOM nodes. */
function renderProfileMarkdown(container, markdown) {
  container.replaceChildren();
  const lines = markdown.split(/\r?\n/);
  let list = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    if (line.startsWith("# ")) { list = null; continue; } // The page already has a title.
    if (line.startsWith("## ") || line.startsWith("### ")) {
      list = null;
      container.append(el("h3", { class: "profile-heading", text: line.replace(/^#+\s*/, "") }));
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      if (!list) { list = el("ul", { class: "profile-list" }); container.append(list); }
      list.append(el("li", { text: line.replace(/^[-*]\s+/, "") }));
      continue;
    }
    list = null;
    container.append(el("p", { text: line }));
  }
  if (!container.hasChildNodes()) {
    container.append(el("p", { class: "empty-state", text: "Jarvis hasn't learned anything about you yet. Talk to it for a while, then re-analyze." }));
  }
}

function initMemoryProfile() {
  const button = $("#btn-reanalyze-memory");
  if (!button) return;
  button.addEventListener("click", async () => {
    const res = await ipc("reanalyze_memory");
    if (!res.success) {
      notify(res.error || "Couldn't start re-analysis.", { tone: "error" });
      return;
    }
    setReanalyzing(true);
    notify("Re-analyzing your conversations. This can take a minute.");
    clearInterval(reanalysisPoll);
    reanalysisPoll = setInterval(async () => {
      const profile = await loadMemoryProfile();
      if (profile.success && !profile.reanalyzing) {
        clearInterval(reanalysisPoll);
        setReanalyzing(false);
        const result = profile.last_reanalysis;
        if (result && !result.success) notify(`Profile not updated: ${result.message}`, { tone: "error", timeout: 8000 });
        else notify("Profile updated from your latest conversations.");
      }
    }, 2000);
  });
}

function setReanalyzing(active) {
  const button = $("#btn-reanalyze-memory");
  if (!button) return;
  button.disabled = active;
  button.setAttribute("aria-busy", String(active));
  button.textContent = active ? "Re-analyzing…" : "Re-analyze conversations";
}

/* ---------- App commands (tool registry) ---------- */

async function loadTools() {
  const res = await ipc("get_tools");
  if (!res.success) {
    renderListError("#installed-tools-list", res.error, loadTools);
    return;
  }
  state.tools = res.tools || [];
  renderTools();
}

const RISK_LABELS = { SAFE: "Safe", MEDIUM: "Medium", HIGH: "High" };

function renderTools() {
  const list = $("#installed-tools-list");
  if (!list) return;
  setText("#tool-count", String(state.tools.length));
  if (state.tools.length === 0) {
    list.replaceChildren(el("p", { class: "empty-state", text: "No commands registered yet. Add one above." }));
    return;
  }
  list.replaceChildren(...state.tools.map((t) => el("article", { class: "tool-row" }, [
    el("div", { class: "tool-main" }, [
      el("strong", { class: "tool-name", text: t.name }),
      el("div", { class: "tool-meta" }, [
        el("code", { class: "tool-id", text: t.id }),
        el("span", { class: `tag risk-${(t.risk_level || "MEDIUM").toLowerCase()}`, text: `${RISK_LABELS[t.risk_level] || t.risk_level} risk` }),
      ]),
      el("p", { class: "tool-desc", text: t.description }),
      t.examples?.length ? el("p", { class: "tool-examples" }, ["Say: ", t.examples.slice(0, 3).map((x) => `“${x}”`).join(", ")]) : null,
    ]),
    t.command ? el("code", { class: "tool-command", text: t.command }) : null,
  ])));
}

/* Parse `User: "Take a screenshot" -> Args: {"x": 1} | User: "..."` into examples. */
function parseExamples(raw, fallback) {
  const examples = [];
  raw.split(/[|\n]/).map((s) => s.trim()).filter(Boolean).forEach((chunk) => {
    const [promptPart, argsPart] = chunk.split("->");
    const prompt = promptPart.replace(/^User:\s*/i, "").trim().replace(/^"|"$/g, "").trim();
    let args = {};
    if (argsPart) {
      const json = argsPart.replace(/^\s*Args:\s*/i, "").trim();
      try { args = json ? JSON.parse(json) : {}; } catch { args = {}; }
    }
    if (prompt) examples.push({ user_prompt: prompt, expected_args: args });
  });
  if (examples.length === 0 && fallback) examples.push({ user_prompt: fallback, expected_args: {} });
  return examples;
}

function collectToolManifest() {
  const value = (id) => ($(id)?.value || "").trim();
  const id = value("#tool-id-input").toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  const name = value("#tool-name-input");
  return {
    id,
    name,
    version: "1.0.0",
    description: value("#tool-desc-input"),
    category: "custom",
    parameters: { type: "object", properties: {} },
    execution: { type: "command_template", template: value("#tool-cmd-input") },
    examples: parseExamples(value("#tool-examples-input"), name),
    risk_level: value("#tool-risk-input") || "MEDIUM",
    spoken_confirmation_template: value("#tool-speak-input"),
  };
}

function initToolBuilder() {
  const form = $("#add-tool-form");
  const preview = $("#tool-preview");
  if (!form || !preview) return;
  let pendingManifest = null;

  // Step 1: submitting the form shows exactly what will be registered.
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    pendingManifest = collectToolManifest();
    if (!pendingManifest.id) {
      notify("The command ID needs at least one letter or number.", { tone: "error" });
      $("#tool-id-input")?.focus();
      return;
    }
    const exists = state.tools.some((t) => t.id === pendingManifest.id);
    setText("#tool-preview-id", pendingManifest.id);
    setText("#tool-preview-command", pendingManifest.execution.template);
    setText("#tool-preview-risk", RISK_LABELS[pendingManifest.risk_level]);
    setText("#tool-preview-examples", pendingManifest.examples.map((x) => `“${x.user_prompt}”`).join(", "));
    const warning = $("#tool-preview-exists");
    if (warning) warning.hidden = !exists;
    setText("#btn-tool-confirm", exists ? "Replace command" : "Register command");
    preview.hidden = false;
    $("#btn-tool-confirm")?.focus();
  });

  $("#btn-tool-edit")?.addEventListener("click", () => {
    preview.hidden = true;
    pendingManifest = null;
    $("#tool-cmd-input")?.focus();
  });

  // Step 2: confirm registers it.
  $("#btn-tool-confirm")?.addEventListener("click", (e) => withBusy(e.currentTarget, "Registering…", async () => {
    if (!pendingManifest) return;
    const overwrite = state.tools.some((t) => t.id === pendingManifest.id);
    const res = await ipc("register_custom_tool", { ...pendingManifest, overwrite });
    if (!res.success) {
      notify(res.error || "Couldn't register the command.", { tone: "error", timeout: 6000 });
      return;
    }
    notify(`Registered “${pendingManifest.name}”. Jarvis can use it right away.`);
    pendingManifest = null;
    preview.hidden = true;
    form.reset();
    loadTools();
  }));
}

/* ---------- Macros ---------- */

async function loadMacros() {
  const grid = $("#macros-container-grid");
  if (!grid) return;
  const res = await ipc("get_macros");
  if (!res.success) {
    renderListError("#macros-container-grid", res.error, loadMacros);
    return;
  }
  const macros = Object.values(res.macros || {}).filter((m) => !state.pendingDeletes.has(`macro:${m.id}`));
  if (macros.length === 0) {
    grid.replaceChildren(el("p", { class: "empty-state", text: "No macros yet. Create one above, or say “Create gaming mode with Steam and Discord.”" }));
    return;
  }
  grid.replaceChildren(...macros.map((m) => {
    const steps = m.steps || m.apps || [];
    const card = el("article", { class: "macro" }, [
      el("h3", { class: "macro-name", text: humanName(m.name || m.id) }),
      el("ol", { class: "macro-steps" }, steps.map((s) => el("li", {}, el("code", { text: s })))),
      m.directory ? el("p", { class: "macro-dir" }, ["Runs in ", el("code", { text: m.directory })]) : null,
      el("div", { class: "macro-actions" }, [
        el("button", { type: "button", class: "btn btn-secondary btn-small", text: "Run", onclick: (e) => runMacro(e.currentTarget, m) }),
        el("button", {
          type: "button",
          class: "btn btn-quiet btn-small",
          text: "Delete",
          "aria-label": `Delete ${humanName(m.name || m.id)}`,
          onclick: () => deleteWithUndo({
            key: `macro:${m.id}`,
            label: humanName(m.name || m.id),
            hideNode: () => { card.hidden = true; },
            restore: () => { card.hidden = false; },
            commit: () => ipc("delete_macro", { name: m.id }),
          }),
        }),
      ]),
    ]);
    return card;
  }));
}

function runMacro(button, macro) {
  return withBusy(button, "Running…", async () => {
    const res = await ipc("run_macro", { name: macro.id });
    if (res.success === false) notify(res.error || res.message || `Couldn't run ${macro.name || macro.id}.`, { tone: "error", timeout: 6000 });
    else notify(`Started ${humanName(macro.name || macro.id)}.`);
  });
}

function initMacroForm() {
  const form = $("#create-macro-form");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const submit = form.querySelector("[type='submit']");
    withBusy(submit, "Saving…", async () => {
      const name = ($("#macro-name-input")?.value || "").trim();
      const steps = ($("#macro-steps-input")?.value || "").split(/[|\n]/).map((s) => s.trim()).filter(Boolean);
      const directory = ($("#macro-dir-input")?.value || "").trim();
      if (!name || steps.length === 0) {
        notify("A macro needs a name and at least one step.", { tone: "error" });
        return;
      }
      const res = await ipc("save_macro", { name, steps, directory });
      if (!res.success) {
        notify(res.error || "Couldn't save the macro.", { tone: "error", timeout: 6000 });
        return;
      }
      notify(`Saved “${name}” with ${steps.length} ${steps.length === 1 ? "step" : "steps"}.`);
      form.reset();
      loadMacros();
    });
  });
}

/* ---------- Fast-path voice shortcuts ---------- */

async function loadFastPathRules({ force = false } = {}) {
  const res = await ipc("get_fast_path_rules");
  if (!res.success) {
    renderListError("#fast-path-rules-list", res.error, () => loadFastPathRules({ force: true }));
    return;
  }
  const rules = res.rules || [];
  const signature = JSON.stringify(rules.map((r) => [r.id, (r.triggers || []).length]));
  if (!force && signature === state.rulesSignature) return;
  state.rulesSignature = signature;
  state.rules = rules;
  renderFastPathRules();
}

function renderFastPathRules() {
  const list = $("#fast-path-rules-list");
  if (!list) return;
  const query = ($("#fastpath-search")?.value || "").trim().toLowerCase();
  // Learned phrases first: they're what this page exists to review.
  const rules = state.rules
    .filter((r) => !state.pendingDeletes.has(`rule:${r.id}`))
    .sort((x, y) => Number(Boolean(x.is_system)) - Number(Boolean(y.is_system)));
  const learned = rules.filter((r) => !r.is_system).length;
  setText("#fastpath-count", `${rules.length} shortcut phrases, ${learned} learned from you`);

  const matches = rules.filter((r) => {
    if (!query) return true;
    const haystack = `${r.name || ""} ${r.id || ""} ${(r.triggers || []).join(" ")} ${r.tool || ""}`.toLowerCase();
    return haystack.includes(query);
  });

  if (matches.length === 0) {
    list.replaceChildren(el("p", { class: "empty-state", text: query ? "No shortcut phrases match that search." : "No shortcut phrases yet. Jarvis learns them from things you say often." }));
    return;
  }

  const PAGE = 12;
  const visible = query || state.rulesExpanded ? matches : matches.slice(0, PAGE);

  list.replaceChildren(...visible.map((rule) => {
    const triggers = rule.triggers || [];
    const shown = triggers.slice(0, 6);
    const hidden = triggers.slice(6);
    const target = rule.tool && rule.tool !== "none"
      ? ["Runs ", el("code", { text: rule.tool })]
      : rule.spoken_summary ? ["Replies “", rule.spoken_summary, "”"] : ["Replies directly"];

    const triggerList = el("ul", { class: "trigger-list" }, shown.map((t) => el("li", { text: t })));
    const more = hidden.length
      ? el("button", {
          type: "button",
          class: "link-button",
          "aria-expanded": "false",
          text: `+${hidden.length} more`,
          onclick: (e) => {
            hidden.forEach((t) => triggerList.append(el("li", { text: t })));
            e.currentTarget.remove();
          },
        })
      : null;

    const row = el("article", { class: "rule" }, [
      el("div", { class: "rule-main" }, [
        el("div", { class: "rule-title" }, [
          el("strong", { text: ruleName(rule) }),
          el("span", { class: `tag ${rule.is_system ? "" : "tag-learned"}`, text: rule.is_system ? "Built in" : "Learned" }),
        ]),
        el("div", { class: "rule-triggers" }, [triggerList, more]),
        el("p", { class: "rule-target" }, target),
      ]),
      rule.is_system ? null : el("button", {
        type: "button",
        class: "btn btn-quiet btn-small",
        text: "Delete",
        "aria-label": `Delete shortcut phrase ${ruleName(rule)}`,
        onclick: () => deleteWithUndo({
          key: `rule:${rule.id}`,
          label: `“${ruleName(rule)}”`,
          hideNode: () => { row.hidden = true; },
          restore: () => { row.hidden = false; },
          commit: async () => {
            const res = await ipc("delete_fast_path_rule", { rule_id: rule.id });
            if (res.success) loadFastPathRules({ force: true });
            return res.success ? res : { success: false, error: "That shortcut couldn't be deleted. It may already be gone." };
          },
        }),
      }),
    ]);
    return row;
  }));

  if (visible.length < matches.length) {
    list.append(el("button", {
      type: "button",
      class: "btn btn-secondary btn-small list-more",
      text: `Show all ${matches.length}`,
      onclick: () => { state.rulesExpanded = true; renderFastPathRules(); },
    }));
  }
}

function ruleName(rule) {
  return String(rule.name || rule.id).replace(/^learned shortcut:\s*/i, "");
}

/* "gaming-mode" / "work_mode" → "Gaming mode". The spoken name is what people read. */
function humanName(raw) {
  const text = String(raw || "").replace(/[-_]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function initFastPaths() {
  $("#fastpath-search")?.addEventListener("input", debounce(renderFastPathRules, 120));
  $("#btn-refresh-fastpaths")?.addEventListener("click", (e) =>
    withBusy(e.currentTarget, "Refreshing…", () => loadFastPathRules({ force: true })));
}

/* ---------- Settings ---------- */

/* Provider names already carry the active model in parentheses; strip it so option labels don't double up. */
const PROVIDER_LABELS = {
  faster_whisper: "Faster-Whisper · on this computer",
  gemini_stt: "Google Gemini · cloud",
  kokoro: "Kokoro · on this computer",
  elevenlabs: "ElevenLabs · cloud",
};

function providerBaseName(p) {
  const name = String(p.name || "");
  if (!name || name === p.id) return PROVIDER_LABELS[p.id] || p.id;
  return name.replace(/\s*\([^)]*\)\s*$/, "");
}

function fillSelect(select, options, selectedValue) {
  select.replaceChildren(...options.map((o) => {
    if (o.group) {
      return el("optgroup", { label: o.group }, o.options.map((x) =>
        el("option", { value: x.value, selected: x.value === selectedValue, text: x.label })));
    }
    return el("option", { value: o.value, selected: o.value === selectedValue, text: o.label });
  }));
  if (selectedValue && !select.value) select.selectedIndex = 0;
}

function llmOptions(providers) {
  return providers.map((p) => ({
    group: `${providerBaseName(p)} · ${(p.type || "cloud") === "local" ? "on this computer" : "cloud"}`,
    options: (p.models && p.models.length ? p.models : [p.model_name || p.id]).map((m) => ({ value: `${p.id}:${m}`, label: `${m} · ${providerBaseName(p)}` })),
  }));
}

function llmValue(provider, model) {
  if (!provider) return "";
  if (provider.includes(":")) return provider;
  return model ? `${provider}:${model}` : provider;
}

async function loadSettings() {
  const res = await ipc("get_settings");
  if (!res.success) {
    notify(res.error || "Couldn't load settings.", { tone: "error" });
    return;
  }
  const s = res.settings || {};

  const stt = $("#setting-stt-provider");
  if (stt && res.stt_providers) fillSelect(stt, res.stt_providers.map((p) => ({ value: p.id, label: providerBaseName(p) })), s.stt_provider);

  const tts = $("#setting-tts-provider");
  if (tts && res.tts_providers) fillSelect(tts, res.tts_providers.map((p) => ({ value: p.id, label: providerBaseName(p) })), s.tts_provider);

  populateVoiceSelect(res.available_voices || [], s.tts_voice);

  if (res.llm_providers) {
    const llm = $("#setting-llm-provider");
    if (llm) fillSelect(llm, llmOptions(res.llm_providers), llmValue(s.llm_provider, s.llm_model));
    const quick = $("#overview-model-select");
    if (quick && document.activeElement !== quick) fillSelect(quick, llmOptions(res.llm_providers), llmValue(s.llm_provider, s.llm_model));
    const mem = $("#setting-memory-llm-provider");
    if (mem) {
      const memValue = !s.memory_llm_provider || s.memory_llm_provider === "inherit" ? "inherit" : llmValue(s.memory_llm_provider, s.memory_llm_model);
      fillSelect(mem, [{ value: "inherit", label: "Same as the main model" }, ...llmOptions(res.llm_providers)], memValue);
    }
  }

  // Never echo saved secrets back into the page; show whether one is set instead.
  ["anthropic", "gemini"].forEach((name) => {
    const input = $(`#setting-${name}-key`);
    if (!input) return;
    input.value = "";
    input.placeholder = s[`${name}_api_key`] ? "Key saved. Type a new one to replace it." : "Paste your API key";
  });
}

function populateVoiceSelect(voices, activeVoice) {
  const select = $("#setting-voice-select");
  if (!select) return;
  const list = voices.length ? voices : [activeVoice || "default"];
  fillSelect(select, list.map((v) => ({ value: v, label: v })), list.includes(activeVoice) ? activeVoice : list[0]);
}

async function saveSettings(extra = {}) {
  const value = (id) => ($(id)?.value || "").trim();
  const payload = {
    stt_provider: value("#setting-stt-provider") || "faster_whisper",
    llm_provider: value("#setting-llm-provider") || "ollama",
    memory_llm_provider: value("#setting-memory-llm-provider") || "inherit",
    tts_provider: value("#setting-tts-provider") || "kokoro",
    tts_voice: value("#setting-voice-select"),
    ...extra,
  };
  const res = await ipc("update_provider_config", payload);
  if (!res.success) {
    notify(res.error || "Couldn't save settings.", { tone: "error", timeout: 6000 });
    return res;
  }
  notify("Saved.", { timeout: 1800 });
  loadStatus();
  return res;
}

function initStatusActions() {
  $("#btn-switch-model")?.addEventListener("click", () => {
    const select = $("#overview-model-select");
    if (!select) return;
    select.focus();
    try { select.showPicker(); } catch { /* Not supported: focus is enough, arrow keys change it. */ }
  });
  $("#btn-recheck")?.addEventListener("click", (e) => withBusy(e.currentTarget, "Checking…", async () => {
    const res = await ipc("get_status", { recheck: true });
    if (!res.success) return;
    state.status = res;
    renderStatus(res);
    notify(res.llm?.check?.ok ? "Jarvis can think again." : "Still can't reach the model.", { tone: res.llm?.check?.ok ? "info" : "error" });
  }));
}

function initSettings() {
  // Overview's model switch mirrors the Settings field and saves through it.
  $("#overview-model-select")?.addEventListener("change", (e) => {
    const main = $("#setting-llm-provider");
    if (main) main.value = e.target.value;
    saveSettings().then((res) => { if (res.success) notify(`Now thinking with ${e.target.value.split(":").slice(1).join(":") || e.target.value}.`); });
  });
  $("#setting-llm-provider")?.addEventListener("change", (e) => {
    const quick = $("#overview-model-select");
    if (quick) quick.value = e.target.value;
  });
  ["#setting-stt-provider", "#setting-llm-provider", "#setting-memory-llm-provider", "#setting-voice-select"].forEach((id) => {
    $(id)?.addEventListener("change", () => saveSettings());
  });

  $("#setting-tts-provider")?.addEventListener("change", async (e) => {
    const res = await ipc("get_voices_for_provider", { tts_provider: e.target.value });
    if (res.success) populateVoiceSelect(res.voices || [], null);
    saveSettings();
  });

  // API keys save when the field loses focus, and only when something was typed.
  [["#setting-anthropic-key", "anthropic_api_key"], ["#setting-gemini-key", "gemini_api_key"]].forEach(([id, key]) => {
    const input = $(id);
    input?.addEventListener("change", async () => {
      const typed = input.value.trim();
      if (!typed) return;
      const res = await saveSettings({ [key]: typed });
      if (res.success) {
        input.value = "";
        input.placeholder = "Key saved. Type a new one to replace it.";
      }
    });
  });

  // S3 backup.
  ["#setting-s3-arn", "#setting-s3-region"].forEach((id) => {
    $(id)?.addEventListener("input", (e) => { e.target.dataset.dirty = "1"; });
  });
  const saveBackup = async () => {
    const arn = ($("#setting-s3-arn")?.value || "").trim();
    const region = ($("#setting-s3-region")?.value || "").trim();
    const enabled = Boolean($("#setting-s3-enabled")?.checked);
    if (enabled && !arn) {
      notify("Add a bucket name or ARN before turning on backup.", { tone: "error" });
      $("#setting-s3-enabled").checked = false;
      return;
    }
    const res = await saveSettings({ s3_sync_enabled: enabled, s3_bucket_arn: arn, aws_region: region });
    if (res.success) {
      ["#setting-s3-arn", "#setting-s3-region"].forEach((id) => { if ($(id)) delete $(id).dataset.dirty; });
    }
  };
  ["#setting-s3-arn", "#setting-s3-region", "#setting-s3-enabled"].forEach((id) => {
    $(id)?.addEventListener("change", saveBackup);
  });

  $("#btn-test-voice")?.addEventListener("click", (e) => withBusy(e.currentTarget, "Playing…", async () => {
    const res = await ipc("test_voice", { voice: $("#setting-voice-select")?.value || null });
    if (!res.success) notify(res.error || "Couldn't play the voice sample.", { tone: "error" });
    else await new Promise((resolve) => setTimeout(resolve, 2500));
  }));
}

/* ---------- Talk shortcut recorder ---------- */

/* Normalize physical key codes (e.code) so OS modifier masking doesn't change the result. */
function normalizeKey(e) {
  const code = e.code || "";
  if (code === "Space") return "Space";
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Meta") || code.startsWith("OS") || e.key === "Meta") return "Super";
  if (code.startsWith("Alt") || e.key === "Alt") return "Alt";
  if (code.startsWith("Control") || e.key === "Control") return "Ctrl";
  if (code.startsWith("Shift") || e.key === "Shift") return "Shift";
  return code || (e.key ? e.key.toUpperCase() : null);
}

function sortCombo(keys) {
  const order = ["Super", "Ctrl", "Alt", "Shift"];
  return Array.from(keys).sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    if (ia !== -1 && ib !== -1) return ia - ib;
    if (ia !== -1) return -1;
    if (ib !== -1) return 1;
    return a.localeCompare(b);
  });
}

const recorder = { active: false, keys: new Set(), releaseTimer: null };

function initKeybindRecorder() {
  const box = $("#keybind-recorder");
  const display = $("#active-keybind-display");
  const hint = $("#keybind-hint");
  if (!box || !display) return;

  const stop = (message) => {
    recorder.active = false;
    recorder.keys.clear();
    clearTimeout(recorder.releaseTimer);
    box.classList.remove("is-recording");
    box.setAttribute("aria-pressed", "false");
    if (hint) hint.textContent = message || "Click, then hold the new keys together. Esc cancels.";
    if (state.status) renderKeycaps(display, state.status.hotkey);
  };

  box.addEventListener("click", () => {
    if (recorder.active) return;
    recorder.active = true;
    recorder.keys.clear();
    box.classList.add("is-recording");
    box.setAttribute("aria-pressed", "true");
    display.replaceChildren(el("span", { class: "muted", text: "Hold the new keys…" }));
    if (hint) hint.textContent = "Hold all the keys together, then let go. Esc cancels.";
  });

  window.addEventListener("keydown", (e) => {
    if (!recorder.active) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === "Escape" && recorder.keys.size === 0) {
      stop("Kept your current shortcut.");
      return;
    }
    clearTimeout(recorder.releaseTimer);
    const key = normalizeKey(e);
    if (key) recorder.keys.add(key);
    if (e.metaKey) recorder.keys.add("Super");
    if (e.ctrlKey) recorder.keys.add("Ctrl");
    if (e.altKey) recorder.keys.add("Alt");
    if (e.shiftKey) recorder.keys.add("Shift");
    renderKeycaps(display, sortCombo(recorder.keys).join(" + "));
  }, true);

  window.addEventListener("keyup", (e) => {
    if (!recorder.active || recorder.keys.size === 0) return;
    e.preventDefault();
    clearTimeout(recorder.releaseTimer);
    // 200ms grace period after release so a slightly staggered release still counts as one combo.
    recorder.releaseTimer = setTimeout(async () => {
      const shortcut = sortCombo(recorder.keys).join(" + ");
      recorder.active = false;
      const res = await ipc("update_keybind", { keybind: shortcut });
      if (!res.success) {
        stop(res.error || "Couldn't save that shortcut.");
        notify(res.error || "Couldn't save that shortcut.", { tone: "error" });
        return;
      }
      if (state.status) state.status.hotkey = res.new_shortcut;
      stop("Saved. Hold it anywhere to talk.");
      notify(`Talk shortcut is now ${res.new_shortcut}.`);
      loadStatus();
    }, 200);
  }, true);
}

/* ---------- Boot ---------- */

function safely(name, fn) {
  try {
    fn();
  } catch (err) {
    console.error(`[Jarvis UI] ${name} failed to start:`, err);
  }
}

function boot() {
  safely("navigation", initNavigation);
  safely("keybind recorder", initKeybindRecorder);
  safely("transcripts", initTranscripts);
  safely("memory profile", initMemoryProfile);
  safely("tool builder", initToolBuilder);
  safely("macro form", initMacroForm);
  safely("fast paths", initFastPaths);
  safely("settings", initSettings);
  safely("status actions", initStatusActions);

  // First paint: load everything the visible page and the status line need.
  loadStatus();
  pageLoaders[activePageId()]?.();

  // Polling: status is cheap and drives the live voice state; lists refresh only while visible.
  // Nothing to watch while the window is hidden; catch up as soon as it's shown again.
  const visible = () => document.visibilityState !== "hidden";
  document.addEventListener("visibilitychange", () => {
    if (visible()) { loadStatus(); pageLoaders[activePageId()]?.(); }
  });
  setInterval(() => { if (visible()) loadStatus(); }, 1500);
  setInterval(() => {
    if (!visible()) return;
    const page = activePageId();
    if (page === "overview-page" || page === "conversations-page") loadTranscripts();
    if (page === "knows-page") loadFastPathRules();
  }, 4000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
