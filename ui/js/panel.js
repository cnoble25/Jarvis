/* Jarvis task panel: background tasks at the screen edge, always on top (main.py EdgePanelWindow). */

const LINGER_MS = 15 * 1000; // a finished task stays long enough to read its outcome
const STATUS = { running: "Working", done: "Done", failed: "Couldn’t finish", cancelled: "Stopped" };
const PANEL_WIDTH = 360;
const TAB_WIDTH = 64;

let bridge = null;
let tasks = [];
let collapsed = false;
let ticker = null;

const $ = (s) => document.querySelector(s);

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function elapsed(fromSec, toSec) {
  const total = Math.max(0, Math.round((toSec ?? Date.now() / 1000) - fromSec));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function ipc(action, params = {}) {
  return new Promise((resolve) => {
    if (!bridge) return resolve(null);
    bridge.call_ipc(action, JSON.stringify(params), (raw) => {
      try { resolve(JSON.parse(raw)); } catch { resolve(null); }
    });
  });
}

function visibleTasks() {
  const now = Date.now() / 1000;
  return tasks
    .filter((t) => t.status === "running" || (t.finished_at && (now - t.finished_at) * 1000 < LINGER_MS))
    .sort((a, b) => (a.status === "running" ? 0 : 1) - (b.status === "running" ? 0 : 1) || b.started_at - a.started_at);
}

function renderTask(t) {
  const running = t.status === "running";
  const waiting = running && t.approval?.state === "waiting";
  const steps = (waiting ? (t.steps || []).slice(0, -1) : t.steps || []).slice(-4);
  return el("li", { class: `task is-${t.status}${waiting ? " is-waiting" : ""}` }, [
    el("div", { class: "task-top" }, [
      el("span", { class: "state", text: waiting ? "Needs your OK" : STATUS[t.status] || t.status }),
      el("span", { class: "time", text: elapsed(t.started_at, running ? null : t.finished_at) }),
      el("span", { class: "spacer" }),
      running ? el("button", { type: "button", class: "text-button", text: "Cancel",
        onclick: (e) => { e.currentTarget.disabled = true; ipc("cancel_task", { id: t.id }); } }) : null,
    ]),
    el("p", { class: "title", text: t.title, title: t.title }),
    steps.length ? el("ol", { class: "steps" }, steps.map((s) => el("li", { class: `step is-${s.state || "done"}` }, [
      el("span", { class: "label", text: s.label }),
      s.detail ? el("span", { class: "detail", text: s.detail, title: s.detail }) : null,
    ]))) : null,
    running && !waiting && t.current && !(t.steps || []).some((s) => s.state === "running")
      ? el("ol", { class: "steps" }, [el("li", { class: "step is-running" }, [el("span", { class: "label", text: t.current })])])
      : null,
    waiting ? el("div", { class: "approval" }, [
      el("p", { class: "approval-label", text: t.approval.label }),
      t.approval.detail ? el("pre", { text: t.approval.detail }) : null,
      el("div", { class: "approval-actions" }, [
        el("button", { type: "button", class: "btn btn-primary", text: "Go ahead", onclick: (e) => answer(t.id, true, e) }),
        el("button", { type: "button", class: "btn btn-secondary", text: "Don’t do it", onclick: (e) => answer(t.id, false, e) }),
      ]),
    ]) : null,
    !running && t.result ? el("p", { class: "result", text: t.result }) : null,
  ]);
}

function answer(id, approve, e) {
  e.currentTarget.closest(".approval").querySelectorAll("button").forEach((b) => { b.disabled = true; });
  ipc("answer_task", { id, approve });
}

function render() {
  const visible = visibleTasks();
  const running = visible.filter((t) => t.status === "running");
  const waiting = running.some((t) => t.approval?.state === "waiting");
  if (waiting) collapsed = false; // a question always comes out from the edge

  $("#count").textContent = running.length ? `${running.length} running` : "";
  $("#tab-count").textContent = String(running.length || visible.length);
  $("#tab").classList.toggle("is-waiting", waiting);
  $("#tasks").replaceChildren(...visible.map(renderTask));
  $("#panel").hidden = !visible.length || collapsed;
  $("#tab").hidden = !visible.length || !collapsed;

  if (visible.length && !ticker) ticker = setInterval(render, 1000);
  if (!visible.length && ticker) { clearInterval(ticker); ticker = null; }
  setTimeout(layout, 0); // not requestAnimationFrame: a hidden window's page gets no frames
}

/* Tell the window how big to be (it is resized to the content so it never blocks clicks elsewhere). */
let lastLayout = "";
function layout() {
  const visible = !$("#panel").hidden || !$("#tab").hidden;
  const box = !$("#panel").hidden ? $("#panel") : $("#tab");
  const width = !$("#panel").hidden ? PANEL_WIDTH : TAB_WIDTH;
  const height = visible ? Math.ceil(box.getBoundingClientRect().height) + 16 : 0;
  const key = `${visible}:${width}:${height}`;
  if (key === lastLayout || !bridge) return;
  lastLayout = key;
  bridge.layout(visible, width, height);
}

function upsert(task) {
  if (!task || !task.id) return;
  const i = tasks.findIndex((t) => t.id === task.id);
  if (i >= 0) tasks[i] = task;
  else tasks.unshift(task);
}

// Pushed by main.py for every task_* event.
window.panelEvent = (name, payload = {}) => {
  upsert(payload.task);
  if (name === "task_needs_approval" || name === "task_started") collapsed = false;
  render();
};

// Re-measure whenever the content changes size (fonts arriving, a long command wrapping).
const sizeWatch = new ResizeObserver(() => setTimeout(layout, 0));
sizeWatch.observe($("#panel"));
sizeWatch.observe($("#tab"));
document.fonts?.ready.then(() => setTimeout(layout, 0));

$("#collapse").addEventListener("click", () => { collapsed = true; render(); });
$("#tab").addEventListener("click", () => { collapsed = false; render(); });

new QWebChannel(window.qt.webChannelTransport, async (channel) => {
  bridge = channel.objects.jarvisBridge;
  const res = await ipc("get_tasks");
  tasks = (res && res.tasks) || [];
  render();
});
