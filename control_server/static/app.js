const ACTIONS = [
  "docker_restart", "docker_rebuild", "docker_logs", "docker_status",
  "docker_stop", "docker_start", "docker_compose_up", "docker_compose_down",
  "docker_compose_restart",
  "compose_project_up", "compose_project_down_rmi", "compose_project_up_force",
  "compose_project_build_nocache", "compose_project_restart",
  "containers_stop_all", "containers_remove_all", "image_pull", "image_remove",
  "network_create", "network_remove", "inventory_sync", "run_script", "server_reboot",
];

const COMPOSE_LABELS = {
  compose_project_up: "docker compose up -d",
  compose_project_restart: "docker compose restart",
  compose_project_down_rmi: "docker compose down --rmi local",
  compose_project_up_force: "docker compose up -d --force-recreate",
  compose_project_build_nocache: "docker compose build --no-cache",
  docker_compose_restart: "docker compose restart",
};

const state = {
  token: localStorage.getItem("ui_token") || "",
  agentId: localStorage.getItem("agent_id") || "",
  agents: [],
  templates: [],
  view: "dashboard",
  refreshTimer: null,
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function agentQuery() {
  if (!state.agentId) return "";
  return `?agent_id=${encodeURIComponent(state.agentId)}`;
}

function isAgentOnline(agent) {
  if (!agent?.last_seen_at) return false;
  return Date.now() - new Date(agent.last_seen_at).getTime() < 60000;
}

function agentOptionLabel(agent) {
  const online = isAgentOnline(agent);
  return `${agent.agent_id} (${online ? "online" : "offline"})`;
}

function updateAgentStatusPill() {
  const pill = $("#agent-status");
  const label = $("#agent-status-label");
  if (!pill) return;
  if (!state.agentId) {
    if (label) label.textContent = "No agent";
    pill.className = "status-pill offline";
    return;
  }
  const agent = state.agents.find(a => a.agent_id === state.agentId);
  if (agent) {
    const online = isAgentOnline(agent);
    if (label) label.textContent = online ? "Online" : "Offline";
    pill.className = `status-pill ${online ? "online" : "offline"}`;
  } else {
    if (label) label.textContent = "Offline";
    pill.className = "status-pill offline";
  }
}

function populateAgentSelect() {
  const sel = $("#agent-select");
  if (!sel) return;

  if (!state.agents.length) {
    sel.innerHTML = `<option value="">No agents connected yet</option>`;
    sel.disabled = true;
    return;
  }

  sel.disabled = false;
  sel.innerHTML = state.agents.map(agent => {
    const selected = agent.agent_id === state.agentId ? "selected" : "";
    return `<option value="${escapeHtml(agent.agent_id)}" ${selected}>${escapeHtml(agentOptionLabel(agent))}</option>`;
  }).join("");
}

async function loadAgents() {
  const status = await api("/api/ui/status");
  state.agents = status.agents || [];

  const knownIds = new Set(state.agents.map(a => a.agent_id));
  if (!state.agentId || !knownIds.has(state.agentId)) {
    state.agentId = state.agents[0]?.agent_id || "";
    if (state.agentId) localStorage.setItem("agent_id", state.agentId);
    else localStorage.removeItem("agent_id");
  }

  populateAgentSelect();
  updateAgentStatusPill();
  return status;
}

function switchAgent(agentId) {
  if (agentId === state.agentId) return;
  state.agentId = agentId || "";
  if (state.agentId) localStorage.setItem("agent_id", state.agentId);
  else localStorage.removeItem("agent_id");
  updateAgentStatusPill();
  refreshCurrentView();
}

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
  if (s.includes("restarting")) return "Restarting";
  if (s.includes("paused")) return "Paused";
  if (s.includes("up") || s.includes("running")) return "Running";
  if (s.startsWith("exited")) {
    const m = status.match(/exited\s*\((\d+)\)/i);
    return m ? `Exited (${m[1]})` : "Exited";
  }
  return status.length > 28 ? `${status.slice(0, 25)}…` : status;
}

function showView(name) {
  state.view = name;
  $$(".view").forEach(v => v.classList.add("hidden"));
  $(`#view-${name}`)?.classList.remove("hidden");
  $$("nav.bottom-nav button").forEach(b => {
    const active = b.dataset.view === name;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  const titles = {
    dashboard: "Dashboard", containers: "Containers", images: "Images",
    networks: "Networks", orders: "Orders", commands: "Commands",
  };
  const title = titles[name] || "Docker Anywhere";
  $("#page-heading").textContent = title;
  refreshCurrentView();
}

async function createOrder(body) {
  if (!state.agentId) throw new Error("Select an agent first");
  return api("/api/ui/orders", {
    method: "POST",
    body: JSON.stringify({ ...body, agent_id: state.agentId }),
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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
  if (!state.agentId) {
    $("#stat-containers").textContent = "—";
    $("#stat-images").textContent = "—";
    $("#stat-networks").textContent = "—";
    $("#stat-order").textContent = "—";
    $("#dashboard-agent-id").textContent = "—";
    $("#last-poll").textContent = "—";
    $("#last-sync").textContent = "—";
    updateAgentStatusPill();
    return;
  }

  const [containers, images, networks, active] = await Promise.all([
    api(`/api/ui/containers${agentQuery()}`),
    api(`/api/ui/images${agentQuery()}`),
    api(`/api/ui/networks${agentQuery()}`),
    api(`/api/ui/orders/active?agent_id=${encodeURIComponent(state.agentId)}`).catch(() => null),
  ]);

  $("#stat-containers").textContent = containers.length;
  $("#stat-images").textContent = images.length;
  $("#stat-networks").textContent = networks.length;
  $("#stat-order").textContent = active ? active.status : "None";

  const agent = state.agents.find(a => a.agent_id === state.agentId);
  updateAgentStatusPill();

  $("#dashboard-agent-id").textContent = state.agentId;
  $("#last-poll").textContent = fmtDate(agent?.last_seen_at);
  $("#last-sync").textContent = fmtDate(agent?.last_inventory_at);

  const paths = uniqueProjectPaths(containers);
  const current = $("#project-select")?.value;
  populateProjectSelect(paths, paths.includes(current) ? current : paths[0]);

  await loadCommandTemplates();
}

function populateQuickTemplateSelect(templates) {
  const quickSel = $("#quick-template");
  if (!quickSel) return;

  if (!templates.length) {
    quickSel.innerHTML = `<option value="">No command templates — create one in Commands</option>`;
    quickSel.disabled = true;
    $("#quick-run-btn").disabled = true;
    return;
  }

  quickSel.disabled = false;
  $("#quick-run-btn").disabled = false;
  quickSel.innerHTML = templates.map(t =>
    `<option value="${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.action)})</option>`
  ).join("");
}

async function loadCommandTemplates() {
  const templates = await api("/api/ui/commands");
  state.templates = templates;
  populateQuickTemplateSelect(templates);
  return templates;
}

async function refreshContainers() {
  if (window.ContainersPage) await ContainersPage.refresh();
}

async function refreshImages() {
  if (!state.agentId) {
    $("#images-body").innerHTML = "";
    $("#images-empty").classList.remove("hidden");
    return;
  }
  const filtered = await api(`/api/ui/images${agentQuery()}`);
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
  if (!state.agentId) {
    $("#networks-body").innerHTML = "";
    $("#networks-empty").classList.remove("hidden");
    return;
  }
  const filtered = await api(`/api/ui/networks${agentQuery()}`);
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
  if (!state.agentId) {
    $("#active-order-card").classList.add("hidden");
    $("#orders-body").innerHTML = "";
    return;
  }
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
  const templates = await loadCommandTemplates();
  $("#commands-body").innerHTML = templates.map(t => `
    <tr>
      <td>${t.name}</td>
      <td class="mono">${t.action}</td>
      <td>${t.category}</td>
      <td><button class="btn btn-danger btn-sm" data-del-tpl="${t.id}">Delete</button></td>
    </tr>
  `).join("");

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
    await loadAgents();
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
  if (!state.token) return;

  try {
    await api("/api/ui/status");
    localStorage.setItem("ui_token", state.token);
    $("#login-screen").classList.add("hidden");
    $("#app").classList.remove("hidden");
    populateActionSelects();
    await loadAgents();
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

  $("#agent-select")?.addEventListener("change", (e) => {
    switchAgent(e.target.value);
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
    if (!btn || btn.closest("#view-containers")) return;
    try {
      const ok = await queueComposeAction(btn.dataset.composeAction, btn.dataset.projectPath);
      if (ok) alert("Order queued. Agent will run on next poll.");
    } catch (err) {
      alert(err.message);
    }
  });

  $("#quick-run-btn").addEventListener("click", async () => {
    const tplId = parseInt($("#quick-template").value, 10);
    const msg = $("#quick-msg");
    if (!tplId) {
      msg.textContent = "Select a command template first (or create one in Commands).";
      msg.className = "alert alert-error";
      msg.classList.remove("hidden");
      return;
    }
    try {
      await createOrder({ template_id: tplId });
      msg.textContent = "Command queued. Agent will execute on next poll.";
      msg.className = "alert alert-info";
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
  if (window.ContainersPage) ContainersPage.init();
  if (state.token) {
    $("#ui-token").value = state.token;
    login();
  }
});
