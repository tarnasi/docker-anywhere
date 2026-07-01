const ACTIONS = [
  "docker_restart", "docker_rebuild", "docker_logs", "docker_status",
  "docker_stop", "docker_start", "docker_compose_up", "docker_compose_down",
  "compose_project_up", "compose_project_down_rmi", "compose_project_up_force",
  "compose_project_build_nocache",
  "containers_stop_all", "containers_remove_all", "image_pull", "image_remove",
  "network_create", "network_remove", "inventory_sync", "run_script", "server_reboot",
];

const COMPOSE_LABELS = {
  compose_project_up: "docker compose up -d",
  compose_project_down_rmi: "docker compose down --rmi local",
  compose_project_up_force: "docker compose up -d --force-recreate",
  compose_project_build_nocache: "docker compose build --no-cache",
};

const state = {
  token: localStorage.getItem("ui_token") || "",
  agentId: localStorage.getItem("agent_id") || "prod-server-01",
  view: "dashboard",
  refreshTimer: null,
  containers: [],
  containerFilter: "all",
  containerSearch: "",
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${state.token}`,
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function fmtSize(bytes) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function statusBadge(status) {
  const s = (status || "").toLowerCase();
  let cls = "exited";
  if (s.includes("up") || s.includes("running")) cls = "running";
  if (s === "pending" || s === "running") cls = s;
  if (s === "failed" || s === "rejected") cls = "failed";
  const label = shortStatus(status);
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

function shortStatus(status) {
  if (!status) return "—";
  const s = status.toLowerCase();
  if (s.includes("up") || s.includes("running")) return "Running";
  if (s.startsWith("exited")) {
    const m = status.match(/exited\s*\((\d+)\)/i);
    return m ? `Exited (${m[1]})` : "Exited";
  }
  return status.length > 28 ? `${status.slice(0, 25)}…` : status;
}

function isRunningStatus(status) {
  const s = (status || "").toLowerCase();
  return s.includes("up") || s.includes("running");
}

const ICON_DOWN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>`;
const ICON_UP = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>`;
const ICON_BUILD = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`;

function composeIconActions(projectPath) {
  if (!projectPath) return `<span class="text-muted">—</span>`;
  const path = escapeHtml(projectPath);
  const items = [
    ["compose_project_down_rmi", "Down", "icon-btn--danger", ICON_DOWN],
    ["compose_project_up", "Up", "icon-btn--primary", ICON_UP],
    ["compose_project_build_nocache", "Build", "icon-btn--warning", ICON_BUILD],
  ];
  return `<div class="icon-actions">${items.map(([action, label, cls, icon]) =>
    `<button type="button" class="icon-btn ${cls} compose-btn" data-compose-action="${action}" data-project-path="${path}" title="${label}" aria-label="${label}">${icon}</button>`
  ).join("")}</div>`;
}

function showView(name) {
  state.view = name;
  $$(".view").forEach(v => v.classList.add("hidden"));
  $(`#view-${name}`)?.classList.remove("hidden");
  $$("nav.bottom-nav button").forEach(b => {
    b.classList.toggle("active", b.dataset.view === name);
  });
  const titles = {
    dashboard: "Dashboard", containers: "Containers", images: "Images",
    networks: "Networks", orders: "Orders", commands: "Commands",
  };
  $("#page-heading").textContent = titles[name] || "Docker Anywhere";
  refreshCurrentView();
}

async function createOrder(body) {
  return api("/api/ui/orders", { method: "POST", body: JSON.stringify(body) });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function composeButtonsHtml(projectPath) {
  return composeIconActions(projectPath);
}

function uniqueProjectPaths(containers) {
  const paths = new Set();
  for (const c of containers) {
    if (c.project_path) paths.add(c.project_path);
  }
  return [...paths].sort();
}

function populateProjectSelect(paths, selected) {
  const sel = $("#project-select");
  if (!paths.length) {
    sel.innerHTML = `<option value="">No project paths synced yet</option>`;
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  sel.innerHTML = paths.map(p =>
    `<option value="${p}" ${p === selected ? "selected" : ""}>${p}</option>`
  ).join("");
}

async function queueComposeAction(action, projectPath) {
  if (!projectPath) throw new Error("Select a project directory first");
  const label = COMPOSE_LABELS[action] || action;
  if (!confirm(`Run in ${projectPath}?\n\n${label}`)) return false;
  await createOrder({
    agent_id: state.agentId,
    action,
    params: { project_path: projectPath },
  });
  return true;
}

async function refreshDashboard() {
  const [status, containers, images, networks, active] = await Promise.all([
    api("/api/ui/status"),
    api("/api/ui/containers"),
    api("/api/ui/images"),
    api("/api/ui/networks"),
    api(`/api/ui/orders/active?agent_id=${encodeURIComponent(state.agentId)}`).catch(() => null),
  ]);

  $("#stat-containers").textContent = containers.length;
  $("#stat-images").textContent = images.length;
  $("#stat-networks").textContent = networks.length;
  $("#stat-order").textContent = active ? active.status : "None";

  const agent = status.agents.find(a => a.agent_id === state.agentId);
  const pill = $("#agent-status");
  if (agent) {
    const lastSeen = new Date(agent.last_seen_at);
    const online = Date.now() - lastSeen.getTime() < 60000;
    pill.textContent = online ? "Online" : "Offline";
    pill.className = `status-pill ${online ? "online" : "offline"}`;
  } else {
    pill.textContent = "Offline";
    pill.className = "status-pill offline";
  }

  $("#last-poll").textContent = fmtDate(status.api_log?.last_agent_poll_at);
  $("#last-sync").textContent = fmtDate(status.api_log?.last_inventory_sync_at);

  const paths = uniqueProjectPaths(containers.filter(c => c.agent_id === state.agentId));
  const current = $("#project-select")?.value;
  populateProjectSelect(paths, paths.includes(current) ? current : paths[0]);
}

function filterContainers(rows) {
  const q = state.containerSearch.trim().toLowerCase();
  return rows.filter(c => {
    if (state.containerFilter === "running" && !isRunningStatus(c.status)) return false;
    if (state.containerFilter === "exited" && isRunningStatus(c.status)) return false;
    if (!q) return true;
    const hay = [c.name, c.image, c.status, c.project_path].join(" ").toLowerCase();
    return hay.includes(q);
  });
}

function renderContainersView(rows) {
  const running = rows.filter(c => isRunningStatus(c.status)).length;
  const exited = rows.length - running;
  $("#containers-stats").innerHTML = `
    <span class="stat-chip"><strong>${rows.length}</strong> total</span>
    <span class="stat-chip stat-chip--running"><strong>${running}</strong> running</span>
    <span class="stat-chip stat-chip--exited"><strong>${exited}</strong> exited</span>
  `;

  const filtered = filterContainers(rows);
  const wrap = $(".containers-table-wrap");
  const tbody = $("#containers-body");

  $("#containers-empty").classList.toggle("hidden", rows.length > 0);
  $("#containers-filtered-empty").classList.toggle("hidden", rows.length === 0 || filtered.length > 0);
  wrap.classList.toggle("hidden", rows.length === 0 || filtered.length === 0);

  tbody.innerHTML = filtered.map(c => `
    <tr>
      <td class="col-sticky-left">
        <span class="container-name" title="${escapeHtml(c.name || "")}">${escapeHtml(c.name || "—")}</span>
      </td>
      <td class="mono">${escapeHtml(c.image || "—")}</td>
      <td>${statusBadge(c.status)}</td>
      <td class="mono">${escapeHtml(c.project_path || "—")}</td>
      <td class="col-sticky-right">${composeIconActions(c.project_path)}</td>
    </tr>
  `).join("");
}

async function refreshContainers() {
  const rows = await api("/api/ui/containers");
  state.containers = rows.filter(r => r.agent_id === state.agentId || !state.agentId);
  renderContainersView(state.containers);
}

async function refreshImages() {
  const rows = await api("/api/ui/images");
  const filtered = rows.filter(r => r.agent_id === state.agentId);
  const tbody = $("#images-body");
  tbody.innerHTML = filtered.map(img => {
    const ref = `${img.repository}:${img.tag}`;
    return `
      <tr>
        <td>${img.repository || "—"}</td>
        <td>${img.tag || "—"}</td>
        <td>${fmtSize(img.size_bytes)}</td>
        <td>
          <button class="btn btn-danger btn-sm" data-remove-image="${ref}">Remove</button>
        </td>
      </tr>`;
  }).join("");
  tbody.querySelectorAll("[data-remove-image]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Remove image ${btn.dataset.removeImage}?`)) return;
      try {
        await createOrder({
          agent_id: state.agentId,
          action: "image_remove",
          params: { image: btn.dataset.removeImage },
        });
        alert("Order queued. Wait for agent to execute.");
        refreshImages();
      } catch (e) { alert(e.message); }
    });
  });
  $("#images-empty").classList.toggle("hidden", filtered.length > 0);
}

async function refreshNetworks() {
  const rows = await api("/api/ui/networks");
  const filtered = rows.filter(r => r.agent_id === state.agentId);
  const tbody = $("#networks-body");
  tbody.innerHTML = filtered.map(n => `
    <tr>
      <td>${n.name || "—"}</td>
      <td>${n.driver || "—"}</td>
      <td>${n.scope || "—"}</td>
      <td>
        ${["bridge", "host", "none"].includes(n.name) ? "—" : `
          <button class="btn btn-danger btn-sm" data-remove-network="${n.name}">Remove</button>`}
      </td>
    </tr>
  `).join("");
  tbody.querySelectorAll("[data-remove-network]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Remove network ${btn.dataset.removeNetwork}?`)) return;
      try {
        await createOrder({
          agent_id: state.agentId,
          action: "network_remove",
          params: { name: btn.dataset.removeNetwork },
        });
        alert("Order queued.");
        refreshNetworks();
      } catch (e) { alert(e.message); }
    });
  });
  $("#networks-empty").classList.toggle("hidden", filtered.length > 0);
}

async function refreshOrders() {
  const [orders, active] = await Promise.all([
    api(`/api/ui/orders?agent_id=${encodeURIComponent(state.agentId)}&limit=30`),
    api(`/api/ui/orders/active?agent_id=${encodeURIComponent(state.agentId)}`).catch(() => null),
  ]);

  const card = $("#active-order-card");
  if (active) {
    card.classList.remove("hidden");
    $("#active-order-text").textContent =
      `${active.action} — ${active.status} (since ${fmtDate(active.created_at)})`;
  } else {
    card.classList.add("hidden");
  }

  $("#orders-body").innerHTML = orders.map(o => `
    <tr>
      <td class="mono">${o.action}${o.service ? ` / ${o.service}` : ""}</td>
      <td>${statusBadge(o.status)}</td>
      <td>${fmtDate(o.created_at)}</td>
      <td>${o.returncode != null ? `exit ${o.returncode}` : o.error_message || "—"}</td>
    </tr>
  `).join("");
}

async function refreshCommands() {
  const templates = await api("/api/ui/commands");
  $("#commands-body").innerHTML = templates.map(t => `
    <tr>
      <td>${t.name}</td>
      <td class="mono">${t.action}</td>
      <td>${t.category}</td>
      <td><button class="btn btn-danger btn-sm" data-del-tpl="${t.id}">Delete</button></td>
    </tr>
  `).join("");

  const quickSel = $("#quick-template");
  quickSel.innerHTML = templates.map(t =>
    `<option value="${t.id}">${t.name} (${t.action})</option>`
  ).join("");

  tbodyDelHandlers();
}

function tbodyDelHandlers() {
  $("#commands-body").querySelectorAll("[data-del-tpl]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this template?")) return;
      await api(`/api/ui/commands/${btn.dataset.delTpl}`, { method: "DELETE" });
      refreshCommands();
    });
  });
}

async function refreshCurrentView() {
  try {
    switch (state.view) {
      case "dashboard": await refreshDashboard(); break;
      case "containers": await refreshContainers(); break;
      case "images": await refreshImages(); break;
      case "networks": await refreshNetworks(); break;
      case "orders": await refreshOrders(); break;
      case "commands": await refreshCommands(); break;
    }
  } catch (e) {
    console.error(e);
  }
}

function startAutoRefresh() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(refreshCurrentView, 15000);
}

function populateActionSelects() {
  const opts = ACTIONS.map(a => `<option value="${a}">${a}</option>`).join("");
  $("#tpl-action").innerHTML = opts;
}

async function login() {
  state.token = $("#ui-token").value.trim();
  state.agentId = $("#default-agent").value.trim() || "prod-server-01";
  if (!state.token) return;

  try {
    await api("/api/ui/status");
    localStorage.setItem("ui_token", state.token);
    localStorage.setItem("agent_id", state.agentId);
    $("#login-screen").classList.add("hidden");
    $("#app").classList.remove("hidden");
    populateActionSelects();
    showView("dashboard");
    startAutoRefresh();
  } catch (e) {
    const el = $("#login-error");
    el.textContent = e.message;
    el.classList.remove("hidden");
  }
}

function bindEvents() {
  $("#login-btn").addEventListener("click", login);
  $("#ui-token").addEventListener("keydown", e => { if (e.key === "Enter") login(); });

  $$("nav.bottom-nav button").forEach(btn => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  $$("[data-compose-action]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const msg = $("#compose-msg");
      try {
        const ok = await queueComposeAction(
          btn.dataset.composeAction,
          $("#project-select").value,
        );
        if (ok) {
          msg.textContent = "Order queued. Agent will execute on next poll.";
          msg.className = "alert alert-info";
          msg.classList.remove("hidden");
          refreshDashboard();
        }
      } catch (e) {
        msg.textContent = e.message;
        msg.className = "alert alert-error";
        msg.classList.remove("hidden");
      }
    });
  });

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".compose-btn");
    if (!btn) return;
    try {
      const ok = await queueComposeAction(btn.dataset.composeAction, btn.dataset.projectPath);
      if (ok) alert("Order queued. Agent will run on next poll.");
    } catch (err) {
      alert(err.message);
    }
  });

  const searchInput = $("#containers-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      state.containerSearch = searchInput.value;
      renderContainersView(state.containers);
    });
  }

  $$("[data-container-filter]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.containerFilter = btn.dataset.containerFilter;
      $$("[data-container-filter]").forEach(b => b.classList.toggle("active", b === btn));
      renderContainersView(state.containers);
    });
  });

  $("#quick-run-btn").addEventListener("click", async () => {
    const tplId = parseInt($("#quick-template").value, 10);
    const msg = $("#quick-msg");
    try {
      await createOrder({ agent_id: state.agentId, template_id: tplId });
      msg.textContent = "Command queued. Agent will execute on next poll.";
      msg.classList.remove("hidden");
      refreshDashboard();
    } catch (e) {
      msg.textContent = e.message;
      msg.classList.remove("hidden");
      msg.className = "alert alert-error";
    }
  });

  $("#pull-image-btn").addEventListener("click", async () => {
    const image = $("#pull-image-input").value.trim();
    if (!image) return;
    try {
      await createOrder({ agent_id: state.agentId, action: "image_pull", params: { image } });
      alert("Pull order queued.");
    } catch (e) { alert(e.message); }
  });

  $("#create-network-btn").addEventListener("click", async () => {
    const name = $("#network-name-input").value.trim();
    const driver = $("#network-driver-input").value;
    if (!name) return;
    try {
      await createOrder({
        agent_id: state.agentId,
        action: "network_create",
        params: { name, driver },
      });
      alert("Network create order queued.");
    } catch (e) { alert(e.message); }
  });

  $("#tpl-create-btn").addEventListener("click", async () => {
    try {
      await api("/api/ui/commands", {
        method: "POST",
        body: JSON.stringify({
          name: $("#tpl-name").value.trim(),
          action: $("#tpl-action").value,
          service: $("#tpl-service").value.trim() || null,
          category: $("#tpl-category").value.trim() || "docker",
          description: $("#tpl-desc").value.trim(),
          params: {},
        }),
      });
      $("#tpl-name").value = "";
      $("#tpl-desc").value = "";
      refreshCommands();
    } catch (e) { alert(e.message); }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  if (state.token) {
    $("#ui-token").value = state.token;
    $("#default-agent").value = state.agentId;
    login();
  }
});
