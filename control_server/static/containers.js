/**
 * Containers page — Tailwind UI, slide-over execution, bulk actions, toasts.
 * Uses global: api(), createOrder(), state, $, $$, escapeHtml (from app.js)
 */
(function () {
  const COMPOSE_LABELS = {
    compose_project_up: "docker compose up -d",
    compose_project_restart: "docker compose restart",
    compose_project_down_rmi: "docker compose down --rmi local",
    compose_project_build_nocache: "docker compose build --no-cache",
    docker_start: "docker start",
    docker_stop: "docker stop",
    docker_restart: "docker restart",
  };

  const BULK_ACTIONS = {
    start: { action: "docker_start", perContainer: true, label: "Start" },
    stop: { action: "docker_stop", perContainer: true, label: "Stop" },
    restart: { action: "docker_restart", perContainer: true, label: "Restart" },
    build: { action: "compose_project_build_nocache", perProject: true, label: "Build" },
    delete: { action: "compose_project_down_rmi", perProject: true, label: "Delete" },
  };

  const LUCIDE = {
    wrench: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`,
    arrowUp: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 7-7 7 7"/><path d="M12 19V5"/></svg>`,
    trash2: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>`,
    chevronDown: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`,
    x: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`,
    copy: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`,
  };

  const cState = {
    rows: [],
    filter: "all",
    search: "",
    selected: new Set(),
    slideoverLogs: [],
    bulkDropdownOpen: false,
  };

  const BADGE = {
    running: "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium bg-green-500/15 text-green-400 ring-1 ring-green-500/30",
    stopped: "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30",
    exited: "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium bg-red-500/15 text-red-400 ring-1 ring-red-500/30",
    restarting: "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium bg-yellow-500/15 text-yellow-400 ring-1 ring-yellow-500/30",
    paused: "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/30",
  };

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  function containerKey(c) { return c.container_id || c.name || ""; }

  function statusKind(status) {
    const s = (status || "").toLowerCase();
    if (s.includes("restarting")) return "restarting";
    if (s.includes("paused")) return "paused";
    if (s.includes("exited")) return "exited";
    if (s.includes("stopped") || s === "created") return "stopped";
    if (s.includes("up") || s.includes("running")) return "running";
    return "stopped";
  }

  function statusLabel(status) {
    const kind = statusKind(status);
    const labels = { running: "Running", stopped: "Stopped", exited: "Exited", restarting: "Restarting", paused: "Paused" };
    if (kind === "exited" && status) {
      const m = status.match(/exited\s*\((\d+)\)/i);
      return m ? `Exited (${m[1]})` : "Exited";
    }
    return labels[kind] || "Stopped";
  }

  function statusBadge(status) {
    const kind = statusKind(status);
    const cls = BADGE[kind] || BADGE.stopped;
    return `<span class="${cls}"><span class="text-[10px]">●</span> ${escapeHtml(statusLabel(status))}</span>`;
  }

  function isRunningStatus(status) {
    const k = statusKind(status);
    return k === "running" || k === "restarting";
  }

  function isExitedStatus(status) {
    const k = statusKind(status);
    return k === "exited" || k === "stopped";
  }

  function filterRows(rows) {
    const q = cState.search.trim().toLowerCase();
    return rows.filter(c => {
      if (cState.filter === "running" && !isRunningStatus(c.status)) return false;
      if (cState.filter === "exited" && !isExitedStatus(c.status)) return false;
      if (!q) return true;
      return [c.name, c.image, c.status, c.project_path].join(" ").toLowerCase().includes(q);
    });
  }

  function iconBtn(action, label, colorCls, icon, projectPath, containerName) {
    const attrs = [
      `type="button"`,
      `class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition duration-150 hover:scale-105 active:scale-95 focus:outline-none focus:ring-2 focus:ring-slate-500 ${colorCls}"`,
      `data-c-action="${action}"`,
      `title="${label}"`,
      `aria-label="${label}"`,
    ];
    if (projectPath) attrs.push(`data-project-path="${escapeHtml(projectPath)}"`);
    if (containerName) attrs.push(`data-container-name="${escapeHtml(containerName)}"`);
    return `<button ${attrs.join(" ")}>${icon}</button>`;
  }

  function rowActions(c) {
    if (!c.project_path) return `<span class="text-slate-500 text-sm">—</span>`;
    return `<div class="flex items-center justify-end gap-2">
      ${iconBtn("compose_project_build_nocache", "Build", "bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20", LUCIDE.wrench, c.project_path)}
      ${iconBtn("compose_project_restart", "Restart", "bg-blue-500/10 text-blue-400 hover:bg-blue-500/20", LUCIDE.arrowUp, c.project_path)}
      ${iconBtn("compose_project_down_rmi", "Delete", "bg-red-500/10 text-red-400 hover:bg-red-500/20", LUCIDE.trash2, c.project_path)}
    </div>`;
  }

  function render() {
    const filtered = filterRows(cState.rows);
    const tbody = $("#containers-body");
    const wrap = $("#containers-table-wrap");
    const allKeys = filtered.map(containerKey);
    const allSelected = allKeys.length > 0 && allKeys.every(k => cState.selected.has(k));

    $("#containers-empty")?.classList.toggle("hidden", cState.rows.length > 0);
    $("#containers-filtered-empty")?.classList.toggle("hidden", cState.rows.length === 0 || filtered.length > 0);
    wrap?.classList.toggle("hidden", cState.rows.length === 0 || filtered.length === 0);

    const selCount = [...cState.selected].filter(k => allKeys.includes(k)).length;
    const bulkBar = $("#containers-bulk-bar");
    if (bulkBar) {
      bulkBar.classList.toggle("hidden", selCount === 0);
      $("#containers-bulk-count").textContent = `${selCount} container${selCount === 1 ? "" : "s"} selected`;
    }

    const selectAll = $("#containers-select-all");
    if (selectAll) {
      selectAll.checked = allSelected;
      selectAll.indeterminate = selCount > 0 && !allSelected;
    }

    if (!tbody) return;
    tbody.innerHTML = filtered.map((c, i) => {
      const key = containerKey(c);
      const checked = cState.selected.has(key);
      const rowBg = i % 2 === 0 ? "bg-slate-900" : "bg-slate-800/40";
      return `<tr class="group ${rowBg} border-b border-slate-700/80 transition-colors duration-150 hover:bg-slate-700/40" data-container-key="${escapeHtml(key)}">
        <td class="sticky left-0 z-10 w-10 px-3 ${rowBg} shadow-[2px_0_6px_-2px_rgba(0,0,0,0.4)] group-hover:bg-slate-700/40">
          <input type="checkbox" class="container-row-cb h-4 w-4 rounded border-slate-600 bg-slate-900 text-blue-500 focus:ring-blue-500/40" data-key="${escapeHtml(key)}" ${checked ? "checked" : ""} aria-label="Select ${escapeHtml(c.name || "")}" />
        </td>
        <td class="sticky left-10 z-10 max-w-[180px] px-3 ${rowBg} shadow-[2px_0_6px_-2px_rgba(0,0,0,0.4)] group-hover:bg-slate-700/40">
          <span class="block truncate font-medium text-slate-200" title="${escapeHtml(c.name || "")}">${escapeHtml(c.name || "—")}</span>
        </td>
        <td class="h-[50px] whitespace-nowrap px-4 font-mono text-xs text-slate-400">${escapeHtml(c.image || "—")}</td>
        <td class="h-[50px] whitespace-nowrap px-4">${statusBadge(c.status)}</td>
        <td class="h-[50px] max-w-[220px] truncate whitespace-nowrap px-4 font-mono text-xs text-slate-400" title="${escapeHtml(c.project_path || "")}">${escapeHtml(c.project_path || "—")}</td>
        <td class="sticky right-0 z-10 h-[50px] whitespace-nowrap px-3 ${rowBg} shadow-[-2px_0_6px_-2px_rgba(0,0,0,0.4)] group-hover:bg-slate-700/40">${rowActions(c)}</td>
      </tr>`;
    }).join("");

    // Re-apply hover bg on sticky cells via data attribute — handled by tr:hover in CSS
    syncFilterButtons();
  }

  function syncFilterButtons() {
    $$("#view-containers [data-c-filter]").forEach(btn => {
      const active = btn.dataset.cFilter === cState.filter;
      btn.classList.toggle("c-filter-active", active);
    });
  }

  function setBulkAction(key) {
    const cfg = BULK_ACTIONS[key];
    if (!cfg) return;
    const pick = $("#bulk-action-pick");
    if (pick) pick.value = key;
    const label = $("#bulk-dropdown-label");
    if (label) label.textContent = cfg.label;
    $$(".bulk-menu-item").forEach(btn => {
      const on = btn.dataset.bulkAction === key;
      const isDelete = btn.dataset.bulkAction === "delete";
      btn.classList.toggle("bulk-menu-item--active", on);
      btn.classList.toggle("bg-slate-700", on);
      btn.classList.toggle("text-white", on && !isDelete);
      btn.classList.toggle("text-red-400", isDelete);
      btn.classList.toggle("bg-slate-800", !on);
      btn.classList.toggle("text-slate-200", !on && !isDelete);
    });
  }

  // ── Toast ────────────────────────────────────────────────────────────────

  function showToast(type, message) {
    const host = $("#container-toasts");
    if (!host) return;
    const isOk = type === "success";
    const el = document.createElement("div");
    el.className = `pointer-events-auto flex items-center gap-3 rounded-xl border px-4 py-3 shadow-lg transition-all duration-150 ${
      isOk ? "border-green-500/30 bg-slate-800 text-green-400" : "border-red-500/30 bg-slate-800 text-red-400"
    }`;
    el.innerHTML = `<span class="text-sm font-medium">${escapeHtml(message)}</span>`;
    host.appendChild(el);
    setTimeout(() => {
      el.classList.add("opacity-0", "translate-x-2");
      setTimeout(() => el.remove(), 150);
    }, 4000);
  }

  // ── Slide-over ───────────────────────────────────────────────────────────

  function openSlideover(title, command) {
    cState.slideoverLogs = [];
    const root = $("#container-slideover");
    const panel = $("#container-slideover-panel");
    if (!root || !panel) return;
    $("#slideover-title").textContent = title;
    $("#slideover-command").textContent = command;
    $("#slideover-logs").innerHTML = `<p class="text-slate-400">Running...</p>`;
    root.classList.remove("hidden");
    requestAnimationFrame(() => {
      panel.classList.remove("translate-x-full");
    });
  }

  function closeSlideover() {
    const root = $("#container-slideover");
    const panel = $("#container-slideover-panel");
    if (!root || !panel) return;
    panel.classList.add("translate-x-full");
    setTimeout(() => root.classList.add("hidden"), 150);
  }

  function appendLog(line, type = "info") {
    const colors = { info: "text-slate-300", success: "text-green-400", error: "text-red-400" };
    cState.slideoverLogs.push({ line, type });
    const logs = $("#slideover-logs");
    if (!logs) return;
    const prefix = type === "success" ? "✔ " : type === "error" ? "✖ " : "";
    const p = document.createElement("p");
    p.className = `font-mono text-xs leading-relaxed ${colors[type] || colors.info}`;
    p.textContent = prefix + line;
    logs.appendChild(p);
    logs.scrollTop = logs.scrollHeight;
  }

  function setSlideoverRunning() {
    const logs = $("#slideover-logs");
    if (logs && !cState.slideoverLogs.length) {
      logs.innerHTML = `<p class="animate-pulse text-slate-400">Running...</p>`;
    }
  }

  async function pollOrder(commandId) {
    const steps = ["Pulling image...", "Creating network...", "Starting container...", "Healthy"];
    let stepIdx = 0;
    const deadline = Date.now() + 180000;

    while (Date.now() < deadline) {
      const orders = await api(`/api/ui/orders?agent_id=${encodeURIComponent(state.agentId)}&limit=40`);
      const order = orders.find(o => o.command_id === commandId);
      if (!order) {
        await sleep(2000);
        continue;
      }
      if (order.status === "pending") {
        setSlideoverRunning();
        await sleep(2000);
        continue;
      }
      if (order.status === "running") {
        if (stepIdx < steps.length) {
          appendLog(steps[stepIdx], "success");
          stepIdx++;
        }
        await sleep(2000);
        continue;
      }
      if (order.stdout?.trim()) {
        order.stdout.trim().split("\n").forEach(l => appendLog(l, "info"));
      }
      if (order.stderr?.trim()) {
        order.stderr.trim().split("\n").forEach(l => appendLog(l, "error"));
      }
      if (order.error_message) appendLog(order.error_message, "error");
      return order;
    }
    throw new Error("Timed out waiting for agent");
  }

  async function executeAction({ action, projectPath, containerName, title }) {
    const command = COMPOSE_LABELS[action] || action;
    const displayCmd = projectPath ? `${command}\n# in ${projectPath}` : containerName ? `${command} ${containerName}` : command;
    openSlideover(title || command, displayCmd);

    try {
      const body = { agent_id: state.agentId, action, params: {} };
      if (projectPath) body.params.project_path = projectPath;
      if (containerName) body.service = containerName;

      appendLog("Queuing order...", "info");
      const order = await createOrder(body);
      appendLog("Waiting for agent pickup...", "info");

      const result = await pollOrder(order.command_id);
      const ok = result.status === "completed" && (result.returncode == null || result.returncode === 0);

      if (ok) {
        showToast("success", title ? `${title} succeeded` : "Command completed");
      } else {
        showToast("error", title ? `Failed: ${title}` : "Command failed");
      }
      return result;
    } catch (err) {
      appendLog(err.message, "error");
      showToast("error", err.message);
      throw err;
    }
  }

  async function runBulkAction(actionKey) {
    const cfg = BULK_ACTIONS[actionKey];
    if (!cfg) return;

    const selected = cState.rows.filter(c => cState.selected.has(containerKey(c)));
    if (!selected.length) return;

    const tasks = [];
    if (cfg.perContainer) {
      for (const c of selected) {
        tasks.push({
          action: cfg.action,
          containerName: c.name,
          title: `${cfg.label} ${c.name}`,
        });
      }
    } else if (cfg.perProject) {
      const paths = [...new Set(selected.map(c => c.project_path).filter(Boolean))];
      for (const p of paths) {
        tasks.push({
          action: cfg.action,
          projectPath: p,
          title: `${cfg.label} ${p}`,
        });
      }
    }

    openSlideover(`Bulk ${cfg.label}`, `${tasks.length} operation(s)`);
    appendLog(`Executing ${cfg.label} on ${tasks.length} target(s)...`, "info");

    let failures = 0;
    for (const task of tasks) {
      try {
        appendLog(`→ ${task.title}`, "info");
        const body = { agent_id: state.agentId, action: task.action, params: {} };
        if (task.projectPath) body.params.project_path = task.projectPath;
        if (task.containerName) body.service = task.containerName;
        const order = await createOrder(body);
        const result = await pollOrder(order.command_id);
        const ok = result.status === "completed" && (result.returncode == null || result.returncode === 0);
        if (!ok) failures++;
      } catch (err) {
        failures++;
        appendLog(err.message, "error");
        if (err.message.includes("already pending")) {
          appendLog("Waiting before retry...", "info");
          await sleep(5000);
        }
      }
    }

    if (failures) showToast("error", `${failures} operation(s) failed`);
    else showToast("success", `Bulk ${cfg.label} completed`);
    cState.selected.clear();
    render();
    await refresh();
  }

  async function refresh() {
    if (!state.agentId) {
      cState.rows = [];
      render();
      return;
    }
    cState.rows = await api(`/api/ui/containers?agent_id=${encodeURIComponent(state.agentId)}`);
    const validKeys = new Set(cState.rows.map(containerKey));
    for (const k of [...cState.selected]) {
      if (!validKeys.has(k)) cState.selected.delete(k);
    }
    render();
  }

  function bindEvents() {
    const search = $("#containers-search");
    search?.addEventListener("input", () => {
      cState.search = search.value;
      render();
    });

    $$("[data-c-filter]").forEach(btn => {
      btn.addEventListener("click", () => {
        cState.filter = btn.dataset.cFilter;
        render();
      });
    });

    $("#containers-select-all")?.addEventListener("change", (e) => {
      const filtered = filterRows(cState.rows);
      if (e.target.checked) filtered.forEach(c => cState.selected.add(containerKey(c)));
      else filtered.forEach(c => cState.selected.delete(containerKey(c)));
      render();
    });

    $("#containers-body")?.addEventListener("change", (e) => {
      if (!e.target.classList.contains("container-row-cb")) return;
      const key = e.target.dataset.key;
      if (e.target.checked) cState.selected.add(key);
      else cState.selected.delete(key);
      render();
    });

    $("#containers-body")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-c-action]");
      if (!btn) return;
      e.preventDefault();
      const action = btn.dataset.cAction;
      const projectPath = btn.dataset.projectPath;
      const containerName = btn.dataset.containerName;
      const label = btn.getAttribute("title") || action;
      executeAction({ action, projectPath, containerName, title: label });
    });

    $("#container-slideover-backdrop")?.addEventListener("click", closeSlideover);
    $("#slideover-close")?.addEventListener("click", closeSlideover);
    $("#slideover-close-btn")?.addEventListener("click", closeSlideover);
    $("#slideover-copy")?.addEventListener("click", () => {
      const text = cState.slideoverLogs.map(l => l.line).join("\n");
      navigator.clipboard?.writeText(text);
      showToast("success", "Logs copied");
    });

    $("#bulk-dropdown-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      cState.bulkDropdownOpen = !cState.bulkDropdownOpen;
      $("#bulk-dropdown-menu")?.classList.toggle("hidden", !cState.bulkDropdownOpen);
    });

    $("#bulk-dropdown-menu")?.addEventListener("click", (e) => e.stopPropagation());

    document.addEventListener("click", () => {
      if (cState.bulkDropdownOpen) {
        cState.bulkDropdownOpen = false;
        $("#bulk-dropdown-menu")?.classList.add("hidden");
      }
    });

    $$("[data-bulk-action]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const key = btn.dataset.bulkAction;
        setBulkAction(key);
        $("#bulk-dropdown-menu")?.classList.add("hidden");
        cState.bulkDropdownOpen = false;
      });
    });

    setBulkAction($("#bulk-action-pick")?.value || "restart");

    $("#bulk-execute")?.addEventListener("click", () => {
      const key = $("#bulk-action-pick")?.value;
      if (key) runBulkAction(key);
    });
  }

  window.ContainersPage = { refresh, init: bindEvents };
})();
