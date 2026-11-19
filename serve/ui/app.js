(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const make = (tag, className, value) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value != null) el.textContent = value;
    return el;
  };
  const svg = (tag) => document.createElementNS("http://www.w3.org/2000/svg", tag);
  const key = (value) => value == null ? null : String(value);
  const printable = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "";
  const idPart = (value) => encodeURIComponent(String(value));
  const updateText = (el, text) => { if (el.textContent !== text) el.textContent = text; };
  const jobStates = new Map([["running", "运行中"], ["queued", "排队中"], ["done", "已结束"]]);
  const statusName = (status) => jobStates.get(status) || status || "状态未知";
  const sourceName = (source) => source === "local" ? "本地演示" : source === "submission" ? "正式投题" : "来源未知";
  const date = (value) => {
    if (value == null || value === "") return null;
    const d = new Date(typeof value === "number" && Math.abs(value) < 1e11 ? value * 1000 : value);
    return Number.isFinite(d.getTime()) ? d : null;
  };
  const clock = (value) => date(value)?.toLocaleTimeString("zh-CN", {hour12: false}) || "时间未知";
  const stamp = (value) => date(value)?.toLocaleString("zh-CN", {hour12: false}) || "未报告";
  function duration(value) {
    if (!Number.isFinite(value) || value < 0) return "未报告";
    if (value < 60) return Number(value.toFixed(1)) + " 秒";
    return Math.floor(value / 60) + " 分 " + Math.floor(value % 60) + " 秒";
  }

  function emptyModel() {
    return {plan: null, steps: [], byId: new Map(), visits: new Map(), ends: new Map(),
      details: [], end: null, unsupported: 0};
  }
  // Execution IDs can be strings or numbers. A node name can occur in many executions.
  function ingest(model, event) {
    if (event?.v !== 1) { model.unsupported++; return false; }
    const id = key(event.id);
    switch (event.type) {
      case "graph":
        model.plan = event;
        return true;
      case "node_start": {
        if (id == null || model.byId.has(id)) break;
        const node = key(event.node);
        const visits = model.visits.get(node) || [];
        const step = {id, node, label: String(event.label || event.node || id), role: event.role,
          previous: key(event.previous), ts: event.ts, sequence: model.steps.length + 1, visit: visits.length + 1};
        visits.push(step);
        model.visits.set(node, visits);
        model.byId.set(id, step);
        model.steps.push(step);
        return true;
      }
      case "node_end":
        if (id == null) break;
        model.ends.set(id, event);
        return true;
      case "detail":
        model.details.push({id, event, index: model.details.length});
        return false;
      case "call_context":
      case "call_response":
        // The phase view uses the model lifecycle details for these calls.
        return false;
      case "run_end":
        model.end = event;
        return true;
    }
    model.unsupported++;
    return false;
  }

  const storageKey = "rtl.ui.selection.v1";
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(storageKey)); } catch { /* Storage may be disabled. */ }
  let follow = saved?.follow !== false;
  let jobId = null;
  let pinned = typeof saved?.job === "string" ? saved.job : null;
  let board = {mode: null, active_id: null, runs: []};
  let model = emptyModel(), run = null, cursor = 0;
  let scope = "latest", tab = "records", view = "trace", planSelection = null;
  let stateError = "", runError = "", runMissing = false, stateReady = false, boardOff = false, lastSync = null;
  let recordRows = new Map(), recordSignature = "", scopeSignature = "";
  let runEpoch = 0, runTimer = null, runController = null;
  let boardTimer = null, boardBusy = false, boardAgain = false, boardFailures = 0;
  let currentScene = null, zoom = {trace: 1, plan: 1};
  let presenterTasks = [], previewId = null, previewEpoch = 0, dialogEpoch = 0, launching = false;
  const remember = () => {
    try { sessionStorage.setItem(storageKey, JSON.stringify({follow, job: jobId || pinned})); } catch { /* Optional. */ }
  };
  const listedRun = () => board.runs.find((item) => item.job_id === jobId);
  const selectedRun = () => run || listedRun();
  const latest = () => model.steps.at(-1);
  const seqName = (step) => "#" + String(step.sequence).padStart(2, "0");
  const selectedStep = () => scope === "latest" ? latest()
    : scope.startsWith("step:") ? model.byId.get(scope.slice(5)) : null;
  function executionState(step) {
    const end = model.ends.get(step.id);
    if (end?.status === "failed") return ["failed", "执行异常"];
    if (end?.status === "finished") return ["finished", "执行结束"];
    if (end) return ["unknown", String(end.status || "结束状态未知")];
    if (selectedRun()?.status === "done" || model.end) return ["unknown", "未记录结束"];
    return ["current", "执行中"];
  }

  async function request(url, options = {}, ctrl = new AbortController()) {
    const timeout = setTimeout(() => ctrl.abort(), 12000);
    try {
      const response = await fetch(url, {cache: "no-store", credentials: "omit", redirect: "error",
        referrerPolicy: "no-referrer", ...options, signal: ctrl.signal});
      if (!response.ok) {
        const error = new Error("HTTP " + response.status);
        error.status = response.status;
        throw error;
      }
      if (options.method === "POST") {
        if (response.status !== 202) throw new Error("启动状态未知");
        return await response.json().catch(() => ({}));
      }
      return await response.json();
    } finally { clearTimeout(timeout); }
  }

  function renderConnection() {
    const offline = Boolean(stateError || (runError && !runMissing));
    const status = $("connection");
    status.dataset.state = offline ? "offline" : stateReady ? "online" : "waiting";
    updateText(status.lastElementChild, boardOff ? "展示已关闭" : offline ? "连接异常" : stateReady ? "实时连接" : "正在连接");
    const notice = [stateError, runError, run?.error].filter(Boolean).join("　");
    $("issue").hidden = !notice;
    updateText($("issue"), notice);
    if (lastSync) updateText($("synced"), "最近同步 " + clock(lastSync));
  }
  function renderHeader() {
    const item = selectedRun();
    updateText($("task-name"), item?.task_id || (boardOff ? "展示已关闭" : jobId && runError ? "运行记录不可用"
      : jobId ? "正在读取题目…" : stateReady ? "尚未收到题目" : "正在读取题目…"));
    const badge = $("job-status");
    badge.hidden = !item;
    badge.className = "badge " + (jobStates.has(item?.status) ? item.status : "");
    updateText(badge, item ? statusName(item.status) : "");
    const metadata = [];
    if (item) {
      metadata.push(sourceName(item.source));
      if (model.plan?.workflow) metadata.push("工作流 " + model.plan.workflow);
      if (item.submitted != null) metadata.push("收题 " + clock(item.submitted));
      if (item.started != null) metadata.push("开始 " + clock(item.started));
    }
    $("task-meta").replaceChildren(...metadata.map((value) => make("span", "", value)));
  }
  function renderQueue() {
    const list = $("runs");
    const focused = document.activeElement?.dataset.job;
    const buttons = [];
    for (const item of board.runs) {
      const button = make("button");
      button.type = "button";
      button.dataset.job = item.job_id;
      button.setAttribute("aria-current", String(item.job_id === jobId));
      button.title = item.task_id + " · " + item.job_id;
      const state = jobStates.has(item.status) ? item.status : "";
      button.append(make("i", "status-dot " + state), make("span", "run-name", item.task_id),
        make("span", "run-meta", statusName(item.status) + " · " + clock(item.submitted)));
      button.addEventListener("click", () => {
        follow = false;
        selectRun(item.job_id);
        remember();
        renderQueue();
      });
      const row = make("li");
      row.append(button);
      buttons.push(row);
    }
    list.replaceChildren(...buttons);
    if (focused) buttons.find((el) => el.firstChild.dataset.job === focused)?.firstChild.focus({preventScroll: true});
    $("queue-count").textContent = String(board.runs.length);
    $("queue-empty").hidden = board.runs.length > 0;
    updateText($("queue-empty"), boardOff ? "展示已关闭。" : stateReady ? "队列为空。" : "正在读取队列…");
    $("follow").setAttribute("aria-pressed", String(follow));
    $("mode").hidden = !board.mode;
    updateText($("mode"), board.mode ? sourceName(board.mode) + "模式" : "");
    $("present").hidden = board.mode !== "local";
    if (board.mode !== "local" && $("presenter").open) $("presenter").close();
  }
  function alignRun() {
    const target = follow ? board.active_id || board.runs[0]?.job_id || null
      : jobId || pinned || board.active_id || board.runs[0]?.job_id || null;
    return selectRun(target);
  }
  function selectRun(id, reload = false) {
    if (jobId === id && !reload) return false;
    runEpoch++;
    runController?.abort();
    clearTimeout(runTimer);
    jobId = id;
    pinned = id;
    run = null;
    model = emptyModel();
    cursor = 0;
    scope = "latest";
    planSelection = null;
    zoom = {trace: 1, plan: 1};
    recordRows = new Map();
    scopeSignature = recordSignature = "";
    for (const name of ["prompt", "solution", "summary"]) $("panel-" + name).replaceChildren();
    $("record-list").replaceChildren();
    $("record-search").value = "";
    runError = "";
    runMissing = false;
    remember();
    renderHeader();
    renderQueue();
    renderConnection();
    drawGraph();
    renderInspector();
    if (id) scheduleRun(0);
    return true;
  }
  function scheduleRun(delay) {
    clearTimeout(runTimer);
    const epoch = runEpoch, requested = jobId;
    runTimer = setTimeout(() => pollRun(epoch, requested), delay);
  }
  async function pollRun(epoch, requested) {
    const controller = new AbortController();
    runController = controller;
    try {
      const result = await request("/ui/api/runs/" + idPart(requested) + "?after=" + cursor, {}, controller);
      if (epoch !== runEpoch) return;
      if (result.job_id !== requested || !Array.isArray(result.events) ||
          !Number.isSafeInteger(result.cursor) || result.cursor < cursor ||
          result.cursor - cursor !== result.events.length || (result.more && result.cursor === cursor)) {
        throw new Error("游标或运行记录不匹配");
      }
      const oldCount = model.steps.length;
      const statusChanged = result.status !== run?.status;
      const firstRead = !run;
      const contentChanged = firstRead || result.prompt !== run.prompt || result.solution !== run.solution || result.error !== run.error;
      const {events, ...snapshot} = result;
      run = snapshot;
      cursor = result.cursor;
      let graphChanged = false;
      for (const event of events) if (ingest(model, event)) graphChanged = true;
      runError = "";
      runMissing = false;
      renderConnection();
      if (events.length || statusChanged || contentChanged) {
        renderHeader();
        if (graphChanged || statusChanged) drawGraph({locate: scope === "latest" && view === "trace" && oldCount < model.steps.length});
        renderInspector();
      }
      if (result.more) scheduleRun(0);
      else if (result.status !== "done") scheduleRun(document.hidden ? 4500 : 1100);
    } catch (error) {
      if (epoch !== runEpoch) return;
      runMissing = error.status === 404;
      runError = runMissing ? "此运行记录已不可用，可从题目队列选择其他记录。"
        : "读取执行记录失败，正在重试。已显示的内容会保留。";
      renderConnection();
      if (!run) renderHeader();
      if (error.status !== 404) scheduleRun(3500);
    }
  }
  function refreshBoard() {
    clearTimeout(boardTimer);
    if (boardBusy) boardAgain = true;
    else boardTimer = setTimeout(pollBoard, 0);
  }
  async function pollBoard() {
    boardBusy = true;
    try {
      const next = await request("/ui/api/state");
      if (!Array.isArray(next.runs) || !["local", "submission"].includes(next.mode)) throw new Error("题目队列格式无效");
      const changed = !stateReady || JSON.stringify(next) !== JSON.stringify(board);
      const retainedBefore = Boolean(listedRun());
      board = next;
      stateReady = true;
      boardOff = false;
      stateError = "";
      lastSync = Date.now();
      boardFailures = 0;
      if (!follow && retainedBefore && !listedRun() && jobId) {
        selectRun(jobId, true);
      } else if (!alignRun() && changed) {
        renderQueue();
        renderHeader();
        if (!run) drawGraph();
      }
    } catch (error) {
      boardFailures++;
      if (error.status === 404) {
        stateError = "展示页当前已关闭，重新开放时会自动连接。";
        if (!boardOff) {
          boardOff = true;
          stateReady = false;
          board = {mode: null, active_id: null, runs: []};
          const previousPin = pinned;
          selectRun(null, true);
          pinned = previousPin;
          remember();
        }
      } else stateError = "无法连接题目队列，正在重连。";
    } finally {
      renderConnection();
      boardBusy = false;
      const delay = boardAgain ? 0 : boardFailures ? Math.min(15000, 1500 * boardFailures) : document.hidden ? 6000 : 1800;
      boardAgain = false;
      boardTimer = setTimeout(pollBoard, delay);
    }
  }

  const NODE_W = 182, NODE_H = 82, GAP_X = 58, GAP_Y = 50, PAD = 35;
  function traceLayout() {
    const width = $("graph-scroll").clientWidth;
    const cols = Math.max(1, Math.min(model.steps.length, Math.floor((width - PAD * 2 + GAP_X) / (NODE_W + GAP_X))));
    const inset = Math.max(PAD, (width - cols * NODE_W - (cols - 1) * GAP_X) / 2);
    const points = new Map();
    for (const [index, step] of model.steps.entries()) {
      const row = Math.floor(index / cols), slot = index % cols;
      // Alternating rows keep adjacent executions close at the turn.
      const col = row % 2 ? cols - 1 - slot : slot;
      points.set(step.id, {x: inset + col * (NODE_W + GAP_X), y: PAD + row * (NODE_H + GAP_Y), step});
    }
    const links = model.steps.filter((step) => step.previous != null && points.has(step.previous))
      .map((step) => ({from: step.previous, to: step.id}));
    const scene = extent(points, links);
    if (points.size) scene.w = Math.max(scene.w, width);
    return scene;
  }
  function planLayout() {
    const plan = model.plan || {};
    const nodes = new Map(), children = new Map(), links = [];
    for (const node of Array.isArray(plan.nodes) ? plan.nodes : []) {
      const id = key(node?.id);
      if (id != null) { nodes.set(id, node); children.set(id, []); }
    }
    for (const edge of Array.isArray(plan.edges) ? plan.edges : []) {
      const from = key(edge?.from), to = key(edge?.to);
      if (!nodes.has(from) || !nodes.has(to)) continue;
      links.push({from, to, condition: edge.condition});
      children.get(from).push(to);
    }
    const level = new Map(), rows = new Map(), points = new Map();
    // Shortest distance from each component's entry produces layers even with cycles.
    let lastLevel = -1;
    for (const root of [key(plan.entrypoint), ...nodes.keys()]) {
      if (!nodes.has(root) || level.has(root)) continue;
      const queue = [root];
      level.set(root, lastLevel + 1);
      for (let i = 0; i < queue.length; i++) {
        const id = queue[i], column = level.get(id);
        lastLevel = Math.max(lastLevel, column);
        for (const next of children.get(id)) {
          if (level.has(next)) continue;
          level.set(next, column + 1);
          queue.push(next);
        }
      }
    }
    for (const [id, node] of nodes) {
      const column = level.get(id), row = rows.get(column) || 0;
      points.set(id, {x: PAD + column * (NODE_W + GAP_X), y: PAD + 12 + row * (NODE_H + GAP_Y), node});
      rows.set(column, row + 1);
    }
    return extent(points, links);
  }
  function extent(points, links) {
    let w = 0, h = 0;
    for (const {x, y} of points.values()) {
      w = Math.max(w, x + NODE_W + PAD);
      h = Math.max(h, y + NODE_H + PAD);
    }
    return {points, links, w, h};
  }
  function pathFor(s, t, index, scene) {
    const sx = s.x + NODE_W / 2, tx = t.x + NODE_W / 2, sy = s.y + NODE_H / 2, ty = t.y + NODE_H / 2;
    const gap = 11 + (index % 4) * 3;
    if (s === t) return `M ${s.x + NODE_W - 22} ${s.y} v -16 h 35 v 36 H ${s.x + NODE_W + 2}`;
    if (view === "plan") {
      if (t.x === s.x + NODE_W + GAP_X) {
        const mid = s.x + NODE_W + gap;
        return `M ${s.x + NODE_W} ${sy} H ${mid} V ${ty} H ${t.x - 2}`;
      }
      if (s.x === t.x) {
        const side = s.x + NODE_W + gap;
        return `M ${s.x + NODE_W} ${sy} H ${side} V ${ty} H ${t.x + NODE_W + 2}`;
      }
      const top = 5 + index % 7 * 4;
      const out = s.x - gap, into = t.x + NODE_W + gap;
      return `M ${s.x} ${sy} H ${out} V ${top} H ${into} V ${ty} H ${t.x + NODE_W + 2}`;
    }
    if (sy === ty && Math.abs(s.x - t.x) === NODE_W + GAP_X) {
      const forward = t.x > s.x;
      return `M ${forward ? s.x + NODE_W : s.x} ${sy} H ${forward ? t.x - 2 : t.x + NODE_W + 2}`;
    }
    if (sx === tx && t.y === s.y + NODE_H + GAP_Y) {
      return `M ${sx} ${s.y + NODE_H} V ${t.y - 2}`;
    }
    // A non-adjacent predecessor is a real branch. Route it around intervening cards.
    const bottom = s.y + NODE_H + gap;
    const port = s.x <= t.x ? 34 : -34;
    if (sy === ty) return `M ${sx + port} ${s.y + NODE_H} V ${bottom} H ${tx - port} V ${t.y + NODE_H + 2}`;
    const side = s.x <= t.x ? gap : scene.w - gap;
    return `M ${sx + port} ${s.y + NODE_H} V ${bottom} H ${side} V ${t.y - gap} H ${tx - port} V ${t.y - 2}`;
  }
  function drawWires(scene) {
    const layer = svg("svg");
    layer.classList.add("wires");
    layer.setAttribute("aria-hidden", "true");
    layer.setAttribute("width", scene.w);
    layer.setAttribute("height", scene.h);
    const defs = svg("defs"), marker = svg("marker"), arrow = svg("path");
    marker.id = "wire-arrow";
    marker.setAttribute("viewBox", "0 0 8 8");
    marker.setAttribute("refX", "7");
    marker.setAttribute("refY", "4");
    marker.setAttribute("markerWidth", "6");
    marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto");
    arrow.setAttribute("d", "M 0 0 L 8 4 L 0 8 z");
    arrow.setAttribute("fill", view === "trace" ? "#8bc7a3" : "#829489");
    marker.append(arrow);
    defs.append(marker);
    layer.append(defs);
    for (const [index, link] of scene.links.entries()) {
      const line = svg("path");
      line.setAttribute("class", view === "plan" ? "wire planned" : "wire");
      line.setAttribute("d", pathFor(scene.points.get(link.from), scene.points.get(link.to), index, scene));
      line.setAttribute("marker-end", "url(#wire-arrow)");
      layer.append(line);
    }
    return layer;
  }
  function graphButton(id, point) {
    const planned = view === "plan";
    const step = point.step;
    const visits = planned ? model.visits.get(id) || [] : [];
    const state = step ? executionState(step) : visits.some((visit) => executionState(visit)[0] === "current")
      ? ["current", "执行中"] : [visits.length ? "visited" : "", visits.length ? "已执行 " + visits.length + " 次" : "尚未执行"];
    const chosen = planned ? planSelection === id : selectedStep()?.id === id;
    const el = make("button", "graph-node" + (planned ? " planned" : "") + (state[0] ? " " + state[0] : "") + (chosen ? " selected" : ""));
    el.type = "button";
    el.dataset.graphId = id;
    el.setAttribute("aria-pressed", String(chosen));
    el.style.left = point.x + "px";
    el.style.top = point.y + "px";
    const label = step?.label || point.node?.label || id;
    const role = step?.role || point.node?.role;
    const top = make("span", "node-top"), bottom = make("span", "node-bottom");
    top.append(make("span", "node-index", step ? seqName(step) : id === key(model.plan?.entrypoint) ? "入口" : "定义节点"),
      make("span", "", state[1]));
    bottom.append(make("span", "", role || (step ? step.node : id)));
    if (step?.visit > 1) bottom.append(make("span", "", "第 " + step.visit + " 次"));
    el.append(top, make("span", "node-name", label), bottom);
    el.title = [step ? seqName(step) : id, label, role, state[1], step?.visit > 1 ? "第 " + step.visit + " 次执行" : ""].filter(Boolean).join(" · ");
    el.addEventListener("click", () => {
      if (planned) { planSelection = id; drawGraph(); }
      else chooseScope("step:" + id, true);
    });
    return el;
  }
  function drawGraph({locate = false} = {}) {
    const drawing = $("drawing"), viewport = $("graph-scroll");
    const focused = drawing.contains(document.activeElement) ? document.activeElement.dataset.graphId : null;
    $("view-trace").setAttribute("aria-pressed", String(view === "trace"));
    $("view-plan").setAttribute("aria-pressed", String(view === "plan"));
    const scene = view === "trace" ? traceLayout() : planLayout();
    currentScene = scene;
    const count = scene.points.size;
    const empty = $("graph-empty");
    empty.hidden = Boolean(count);
    if (!count) {
      empty.querySelector("strong").textContent = view === "plan" ? "暂无流程定义" : "暂无执行节点";
      empty.lastElementChild.textContent = !jobId ? "收到题目后会在这里显示工作流。"
        : selectedRun()?.status === "queued" ? "这道题正在队列中等待。"
        : selectedRun()?.status === "done" ? "该次运行没有提供此视图所需的事件。"
        : "正在等待这道题的工作流事件。";
    }
    $("edge-key").className = view === "trace" ? "edge-key" : "edge-key planned";
    updateText($("edge-caption"), view === "trace" ? "实际前序" : "定义的转移");
    updateText($("graph-count"), count ? count + (view === "trace" ? " 次执行" : " 个节点") : "");
    $("locate").disabled = !model.steps.length;
    for (const id of ["fit", "zoom-in", "zoom-out", "zoom-reset"]) $(id).disabled = !count;
    const fragment = document.createDocumentFragment();
    if (count) fragment.append(drawWires(scene));
    let focusTarget = null;
    for (const [id, point] of scene.points) {
      const button = graphButton(id, point);
      if (id === focused) focusTarget = button;
      fragment.append(button);
    }
    drawing.replaceChildren(fragment);
    sizeScene();
    if (focusTarget) focusTarget.focus({preventScroll: true});
    if (locate && latest()) locatePoint(latest().id);
    if (!count) { viewport.scrollLeft = 0; viewport.scrollTop = 0; }
    renderPlanInfo();
  }
  function sizeScene() {
    if (!currentScene) return;
    const {w, h} = currentScene, scale = zoom[view];
    const space = $("graph-space"), drawing = $("drawing");
    drawing.style.width = w + "px";
    drawing.style.height = h + "px";
    drawing.style.transform = "scale(" + scale + ")";
    space.style.width = Math.ceil(w * scale) + "px";
    space.style.height = Math.ceil(h * scale) + "px";
    $("zoom-reset").textContent = Math.round(scale * 100) + "%";
  }
  function locatePoint(id) {
    const point = currentScene?.points.get(id);
    if (!point) return;
    const v = $("graph-scroll"), scale = zoom[view];
    const left = point.x * scale, top = point.y * scale;
    if (left < v.scrollLeft || left + NODE_W * scale > v.scrollLeft + v.clientWidth) {
      v.scrollLeft = left - (v.clientWidth - NODE_W * scale) / 2;
    }
    if (top < v.scrollTop || top + NODE_H * scale > v.scrollTop + v.clientHeight) {
      v.scrollTop = top - (v.clientHeight - NODE_H * scale) / 2;
    }
  }
  function changeZoom(scale, all = false) {
    if (!currentScene?.points.size) return;
    const v = $("graph-scroll"), old = zoom[view];
    const cx = (v.scrollLeft + v.clientWidth / 2) / old, cy = (v.scrollTop + v.clientHeight / 2) / old;
    zoom[view] = scale;
    sizeScene();
    v.scrollLeft = all ? 0 : cx * scale - v.clientWidth / 2;
    v.scrollTop = all ? 0 : cy * scale - v.clientHeight / 2;
  }
  function renderPlanInfo() {
    const info = $("plan-info");
    info.hidden = view !== "plan" || !currentScene?.points.size;
    if (info.hidden) { info.replaceChildren(); return; }
    const node = currentScene.points.get(planSelection)?.node;
    if (!node) { updateText(info, "选择定义节点可查看转移条件和历次执行。"); return; }
    const entries = currentScene.links.filter((link) => link.from === planSelection);
    const list = make("ul");
    for (const link of entries) {
      const target = currentScene.points.get(link.to).node;
      list.append(make("li", "", (target.label || link.to) + (link.condition == null ? "" : "　" + printable(link.condition))));
    }
    const visits = model.visits.get(planSelection) || [];
    info.replaceChildren(make("strong", "", (node.label || node.id) + " · 可转到 " + entries.length + " 项"));
    if (entries.length) info.append(list);
    const history = make("div", "", visits.length ? "历次执行　" : "尚未收到此节点的执行记录。");
    for (const step of visits) {
      const button = make("button", "", seqName(step) + " · 第 " + step.visit + " 次");
      button.type = "button";
      button.addEventListener("click", () => { view = "trace"; chooseScope("step:" + step.id, true); });
      history.append(button);
    }
    info.append(history);
  }

  function setTab(name, withFocus = false) {
    tab = name;
    for (const item of document.querySelectorAll('[role="tab"]')) {
      const on = item.id === "tab-" + name;
      item.setAttribute("aria-selected", String(on));
      item.tabIndex = on ? 0 : -1;
      $(item.getAttribute("aria-controls")).hidden = !on;
      if (on && withFocus) item.focus();
    }
    renderInspector();
  }
  function chooseScope(value, showRecords = false) {
    scope = value;
    $("record-search").value = "";
    if (showRecords) setTab("records");
    else renderInspector();
    drawGraph();
    if (view === "trace" && selectedStep()) locatePoint(selectedStep().id);
  }
  async function copyText(value, button) {
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch { /* The user may be reading a local HTTP deployment. */ }
    if (!copied) {
      const field = make("textarea", "copy-field");
      field.value = value;
      document.body.append(field);
      field.select();
      try { copied = document.execCommand("copy"); } catch { /* Select the visible source below. */ }
      field.remove();
      button.focus({preventScroll: true});
    }
    if (!copied) {
      const selection = window.getSelection();
      const pre = button.closest(".content-box")?.querySelector("pre");
      if (selection && pre) {
        const range = document.createRange();
        range.selectNodeContents(pre);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
    button.textContent = copied ? "已复制" : "已选中，请复制";
    setTimeout(() => { button.textContent = "复制"; }, 1800);
  }
  function contentBox(title, value, isProse) {
    const box = make("div", "content-box");
    const head = make("div", "content-head"), button = make("button", "copy", "复制");
    button.type = "button";
    button.setAttribute("aria-label", "复制" + title);
    button.addEventListener("click", () => copyText(value, button));
    head.append(make("strong", "", title), button);
    const pre = make("pre", isProse ? "prose" : "", value);
    pre.tabIndex = 0;
    box.append(head, pre);
    return box;
  }
  const kinds = new Map([["code", "源码"], ["text", "文本"], ["json", "JSON"]]);
  function detailRow(record, openFirst) {
    if (recordRows.has(record.index)) return recordRows.get(record.index);
    const event = record.event, title = String(event.label || "执行记录");
    const row = make("details", "record"), summary = make("summary");
    summary.append(make("span", "record-label", title));
    if (event.status != null && event.status !== "") {
      const status = String(event.status);
      const style = ["failed", "fail", "error"].includes(status) ? " bad" : ["pass", "passed"].includes(status) ? " good" : "";
      summary.append(make("span", "badge" + style, status));
    }
    const step = model.byId.get(record.id);
    const owner = step ? seqName(step) + " " + step.label : record.id == null ? "运行级记录" : "执行 " + record.id;
    const kind = kinds.get(event.kind) || "记录";
    summary.append(make("span", "record-source", owner + " · " + kind));
    row.append(summary);
    const fill = () => {
      if (row.open && row.children.length === 1) row.append(contentBox(kind, printable(event.value), event.kind === "text"));
    };
    row.addEventListener("toggle", fill);
    row.open = openFirst;
    fill();
    recordRows.set(record.index, row);
    return row;
  }
  function renderRecords() {
    const select = $("scope");
    const sig = [runEpoch, model.steps.length, model.details.length].join("/");
    if (sig !== scopeSignature) {
      scopeSignature = sig;
      const options = [new Option("跟随最新步骤", "latest"), new Option("全部执行记录 (" + model.details.length + ")", "all"),
        new Option("运行级及未关联记录", "global")];
      for (const step of model.steps) options.push(new Option(seqName(step) + "　" + step.label + " · 第 " + step.visit + " 次", "step:" + step.id));
      select.replaceChildren(...options);
    }
    select.value = scope;
    const step = selectedStep(), info = $("step-info");
    if (step) {
      const prev = model.byId.get(step.previous);
      const origin = step.previous == null ? "无前序" : prev ? "前序 " + seqName(prev) + " " + prev.label : "前序执行 " + step.previous;
      const ended = model.ends.get(step.id);
      updateText(info, [seqName(step) + " " + step.label, step.role, executionState(step)[1],
        "第 " + step.visit + " 次", origin, step.ts != null ? clock(step.ts) : "", ended?.elapsed_s != null ? duration(ended.elapsed_s) : ""]
        .filter(Boolean).join("　·　"));
    } else updateText(info, scope === "all" ? "按记录到达顺序显示。" : scope === "global" ? "显示整次运行和未关联到已知步骤的记录。" : "");
    const query = $("record-search").value.trim().toLocaleLowerCase();
    let records = model.details;
    if (scope === "global") records = records.filter((item) => !model.byId.has(item.id));
    else if (scope !== "all") records = step ? records.filter((item) => item.id === step.id) : [];
    if (query) records = records.filter(({event}) => String(event.label || "").toLocaleLowerCase().includes(query));
    const signature = [runEpoch, scope, step?.id, query, records.length, records.at(-1)?.index].join("/");
    if (recordSignature !== signature) {
      recordSignature = signature;
      const list = $("record-list");
      const desired = records.map((item, i) => detailRow(item, i === 0 && scope !== "all"));
      // Keep open sources, text selection and keyboard focus attached while new events arrive.
      for (let i = 0; i < desired.length; i++) {
        if (list.children[i] !== desired[i]) list.insertBefore(desired[i], list.children[i] || null);
      }
      while (list.children.length > desired.length) list.lastChild.remove();
    }
    $("records-empty").hidden = records.length > 0;
    updateText($("records-empty"), query ? "没有匹配的记录。" : "所选范围暂无公开记录。");
  }
  function renderSummary() {
    const target = $("panel-summary"), end = model.end, item = selectedRun();
    if (!item) { target.replaceChildren(make("p", "empty-text", "选择题目后可查看运行摘要。")); return; }
    const values = [
      ["运行标识", jobId], ["任务来源", sourceName(item.source)], ["服务状态", statusName(item.status)],
      ["工作流", model.plan?.workflow], ["收题时间", stamp(item.submitted)], ["开始时间", stamp(item.started)],
      ["结束时间", stamp(item.finished)], ["求解状态", end?.status], ["停止原因", end?.stop_reason],
      ["交付方式", end?.submission_mode], ["交付版本", end?.candidate_id], ["求解用时", duration(end?.elapsed_s)],
      ["模型调用", end?.calls], ["输入 token", end?.tokens_in], ["输出 token", end?.tokens_out],
    ];
    const metrics = make("dl", "metrics");
    for (const [label, val] of values) {
      const group = make("div");
      group.append(make("dt", "", label), make("dd", "", val == null || val === "" ? "未报告" : printable(val)));
      metrics.append(group);
    }
    target.replaceChildren(metrics);
    if (model.unsupported) target.append(make("p", "notice", "有 " + model.unsupported + " 条事件无法按当前格式展示。"));
  }
  function renderInspector() {
    if (tab === "records") { renderRecords(); return; }
    if (tab === "summary") { renderSummary(); return; }
    const isPrompt = tab === "prompt", target = $("panel-" + tab);
    const value = isPrompt ? run?.prompt : run?.solution;
    const hasValue = typeof value === "string" && value.length > 0;
    const title = isPrompt ? "公开题面" : "solution.v";
    if (hasValue) {
      if (target.firstChild?.className === "content-box" && target.querySelector("pre").textContent === value) return;
      target.replaceChildren(contentBox(title, value, isPrompt));
    } else {
      const empty = isPrompt ? "尚未收到这道题的公开题面。" : selectedRun()?.status === "done"
        ? "本次运行未交付源码。" : "运行结束后可查看最终交付的源码。";
      if (target.firstChild?.className !== "empty-text") target.replaceChildren(make("p", "empty-text"));
      updateText(target.firstChild, empty);
    }
  }

  let previewController = null;
  function setLaunchNote(message, error = false) {
    updateText($("launch-note"), message);
    $("launch-note").classList.toggle("error", error);
  }
  function canLaunch() {
    return !launching && board.mode === "local" && $("presenter").open && previewId !== null &&
      previewId === $("task-options").value && $("presenter-key").value.length > 0;
  }
  const syncLaunch = () => { $("launch").disabled = !canLaunch(); };
  async function showPreview() {
    const epoch = ++previewEpoch, task = $("task-options").value;
    previewController?.abort();
    previewController = new AbortController();
    previewId = null;
    syncLaunch();
    $("preview").textContent = task ? "正在读取题面…" : "请选择题目。";
    if (!task) return;
    try {
      const data = await request("/ui/api/task?task_id=" + idPart(task), {}, previewController);
      if (epoch !== previewEpoch || !$("presenter").open) return;
      if (data.task_id !== task || typeof data.prompt !== "string") throw new Error("题面缺失");
      previewId = task;
      $("preview").textContent = data.prompt || "题面为空。";
    } catch {
      if (epoch !== previewEpoch || !$("presenter").open) return;
      $("preview").textContent = "题面读取失败，请重新选择。";
    }
    syncLaunch();
  }
  function filterTasks() {
    const select = $("task-options"), old = select.value;
    const term = $("task-search").value.trim().toLocaleLowerCase();
    const matches = presenterTasks.filter((task) => task.toLocaleLowerCase().includes(term));
    select.replaceChildren(...matches.map((task) => new Option(task, task)));
    if (matches.length) select.value = matches.includes(old) ? old : matches[0];
    updateText($("task-count"), matches.length + " / " + presenterTasks.length + " 道题");
    if (select.value !== old || previewId !== select.value) showPreview();
  }
  async function openPresenter() {
    if (board.mode !== "local") return;
    const epoch = ++dialogEpoch;
    presenterTasks = [];
    previewId = null;
    $("task-search").value = "";
    $("task-options").replaceChildren();
    $("presenter-key").value = "";
    $("task-count").textContent = "正在读取本地题库…";
    $("preview").textContent = "请选择题目。";
    setLaunchNote("口令仅用于本次启动，关闭窗口即清除。");
    $("presenter").showModal();
    $("task-search").focus();
    syncLaunch();
    try {
      const data = await request("/ui/api/tasks");
      if (epoch !== dialogEpoch || !$("presenter").open) return;
      if (!Array.isArray(data.tasks) || !data.tasks.every((task) => typeof task === "string")) throw new Error("题库格式无效");
      presenterTasks = data.tasks;
      filterTasks();
    } catch {
      if (epoch === dialogEpoch) $("task-count").textContent = "本地题库读取失败，重新打开可重试。";
    }
  }
  async function launchRun() {
    if (!canLaunch()) return;
    const task = previewId, epoch = dialogEpoch;
    const token = $("presenter-key").value;
    $("presenter-key").value = "";
    launching = true;
    syncLaunch();
    setLaunchNote("正在启动所选题目…");
    try {
      const data = await request("/ui/api/runs", {method: "POST",
        headers: {"Content-Type": "application/json", Authorization: "Bearer " + token}, body: JSON.stringify({task_id: task})});
      follow = true;
      if (data?.job_id) selectRun(data.job_id);
      remember();
      renderQueue();
      if (epoch === dialogEpoch && $("presenter").open) $("presenter").close();
      refreshBoard();
    } catch (error) {
      if (epoch === dialogEpoch && $("presenter").open) {
        const reasons = new Map([[401, "演示口令未通过，请重新输入。"], [403, "当前服务禁止启动本地演示。"],
          [409, "已有任务在处理，请等待队列空闲后再启动。"], [503, "本地演示暂不可用，请检查服务状态。"],
          [404, "所选题目已不可用，请重新选择。"]]);
        setLaunchNote(reasons.get(error.status) || "未能确认启动结果，请先在题目队列核对。", true);
      }
      refreshBoard();
    } finally { launching = false; syncLaunch(); }
  }

  $("present").addEventListener("click", openPresenter);
  $("close-dialog").addEventListener("click", () => $("presenter").close());
  $("presenter").addEventListener("close", () => {
    dialogEpoch++;
    previewEpoch++;
    previewController?.abort();
    previewId = null;
    $("presenter-key").value = "";
    syncLaunch();
  });
  $("task-search").addEventListener("input", filterTasks);
  $("task-options").addEventListener("change", showPreview);
  $("presenter-key").addEventListener("input", syncLaunch);
  $("presenter-key").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && canLaunch()) { event.preventDefault(); launchRun(); }
  });
  $("launch").addEventListener("click", launchRun);
  $("follow").addEventListener("click", () => {
    follow = !follow;
    if (follow) alignRun();
    remember();
    renderQueue();
  });
  for (const type of ["trace", "plan"]) {
    $("view-" + type).addEventListener("click", () => {
      if (view === type) return;
      view = type;
      drawGraph();
      $("graph-scroll").scrollTop = 0;
      $("graph-scroll").scrollLeft = 0;
      if (view === "trace" && selectedStep()) locatePoint(selectedStep().id);
    });
  }
  $("locate").addEventListener("click", () => { view = "trace"; chooseScope("latest"); });
  $("fit").addEventListener("click", () => {
    if (!currentScene?.points.size) return;
    const v = $("graph-scroll");
    changeZoom(Math.min(1, (v.clientWidth - 2) / currentScene.w, (v.clientHeight - 2) / currentScene.h), true);
  });
  $("zoom-in").addEventListener("click", () => changeZoom(Math.min(2.5, zoom[view] * 1.25)));
  $("zoom-out").addEventListener("click", () => changeZoom(Math.max(.08, zoom[view] / 1.25)));
  $("zoom-reset").addEventListener("click", () => changeZoom(1));
  $("scope").addEventListener("change", (event) => chooseScope(event.target.value));
  $("record-search").addEventListener("input", renderRecords);
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((button, i) => {
    const name = button.id.slice(4);
    button.addEventListener("click", () => setTab(name));
    button.addEventListener("keydown", (event) => {
      const next = {ArrowLeft: (i + tabs.length - 1) % tabs.length, ArrowRight: (i + 1) % tabs.length,
        Home: 0, End: tabs.length - 1}[event.key];
      if (typeof next !== "number") return;
      event.preventDefault();
      setTab(tabs[next].id.slice(4), true);
    });
  });
  let resizeFrame = null;
  window.addEventListener("resize", () => {
    if (resizeFrame !== null) return;
    resizeFrame = requestAnimationFrame(() => { resizeFrame = null; drawGraph({locate: view === "trace" && scope === "latest"}); });
  });
  window.addEventListener("online", refreshBoard);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshBoard(); });
  renderQueue();
  drawGraph();
  renderInspector();
  refreshBoard();
})();
