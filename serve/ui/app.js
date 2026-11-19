(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const make = (tag, className, value) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value != null) el.textContent = String(value);
    return el;
  };
  const svg = (tag) => document.createElementNS("http://www.w3.org/2000/svg", tag);
  const key = (value) => value == null ? null : String(value);
  const printable = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "";
  const idPart = (value) => encodeURIComponent(String(value));
  const updateText = (el, text) => { if (el && el.textContent !== text) el.textContent = text; };

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
    if (value < 60) return Number(value.toFixed(1)) + "s";
    const m = Math.floor(value / 60);
    const s = Math.floor(value % 60);
    return m + "m " + String(s).padStart(2, "0") + "s";
  }

  function roleKey(role) {
    if (!role) return "runtime";
    const s = String(role);
    if (s.includes("策略")) return "planner";
    if (s.includes("作者")) return "author";
    if (s.includes("检查")) return "checker";
    if (s.includes("工具")) return "tool";
    return "runtime";
  }

  function statusTone(status) {
    const s = String(status || "").toLowerCase();
    if (["passed", "pass", "finished", "completed", "valid", "ok", "complete"].includes(s)) return "good";
    if (["failed", "fail", "error", "invalid"].includes(s)) return "bad";
    if (["partial_passed", "unverified", "unknown", "warn", "warning", "not_sent", "disputed"].includes(s)) return "warn";
    if (["started", "running", "current"].includes(s)) return "info";
    return "";
  }

  const statusLabels = new Map([
    ["passed", "通过"], ["pass", "通过"], ["partial_passed", "部分通过"],
    ["failed", "失败"], ["fail", "失败"], ["error", "错误"],
    ["unverified", "未验证"], ["unknown", "未知"], ["not_run", "未运行"],
    ["unavailable", "不可用"], ["valid", "有效"], ["invalid", "无效"],
    ["complete", "完成"], ["completed", "完成"], ["started", "进行中"],
    ["finished", "已完成"], ["not_sent", "未发送"],
  ]);
  const zhStatus = (status) => statusLabels.get(String(status || "").toLowerCase()) || String(status || "未知");

  const purposeLabels = new Map([
    ["guided_plan", "制定验证策略"],
    ["guided_solve", "编写初版 RTL"],
    ["guided_repair_structure", "修复结构问题"],
    ["guided_checker", "编写独立检查表"],
    ["guided_author_decision", "RTL 作者决策"],
    ["guided_checker_review", "检查员复核测试点"],
    ["generate", "生成 RTL"],
  ]);
  function zhPurpose(purpose) {
    if (!purpose) return "模型推理";
    const raw = String(purpose);
    if (purposeLabels.has(raw)) return purposeLabels.get(raw);
    for (const [prefix, label] of purposeLabels) {
      if (raw.startsWith(prefix + "_")) {
        const suffix = raw.slice(prefix.length + 1);
        return label + " #" + suffix;
      }
    }
    return raw;
  }

  const finishLabels = new Map([
    ["stop", ["正常结束", "good"]],
    ["tool_calls", ["调用工具", "info"]],
    ["length", ["长度截断", "warn"]],
    ["content_filter", ["内容过滤", "bad"]],
  ]);

  const actionLabels = new Map([
    ["generate", ["生成初稿", "info"]],
    ["revise", ["修改 RTL", "info"]],
    ["review", ["提请检查员复核", "warn"]],
    ["submit", ["决定提交", "good"]],
    ["keep", ["维持原期望", "info"]],
    ["revise_expectation", ["修正测试点期望", "warn"]],
    ["withdraw", ["撤回测试点", "warn"]],
  ]);

  /* ================= 数据模型与事件摄入 ================= */
  function emptyModel() {
    return {
      plan: null,
      steps: [],
      byId: new Map(),
      visits: new Map(),
      ends: new Map(),
      details: [],
      calls: new Map(),
      callOrder: [],
      stream: [],
      end: null,
      unsupported: 0,
      struct: {interface: "idle", lint: "idle", synth: "idle"},
      behavior: {state: "idle", label: "待验证", comparedBits: null, unknownBits: null},
      stepMeta: new Map(),
    };
  }

  function ensureStepMeta(model, stepId) {
    if (stepId == null) return null;
    let m = model.stepMeta.get(stepId);
    if (!m) {
      m = {calls: 0, verdict: null};
      model.stepMeta.set(stepId, m);
    }
    return m;
  }

  function lampStateFromStatus(status) {
    const t = statusTone(status);
    if (t === "good") return "passed";
    if (t === "bad") return "failed";
    if (t === "warn") return "warn";
    if (t === "info") return "running";
    return "idle";
  }

  function ensureCall(model, callId, stepId, purpose, ts) {
    const ck = callId != null && callId !== "" ? String(callId) : "anon-" + model.callOrder.length;
    let entry = model.calls.get(ck);
    if (!entry) {
      entry = {
        key: ck,
        call_id: callId,
        stepId: stepId,
        purpose: purpose || "",
        ts: ts,
        order: model.stream.length,
        context: null,
        response: null,
        meta: {},
      };
      model.calls.set(ck, entry);
      model.callOrder.push(ck);
      model.stream.push({type: "call", callKey: ck, id: stepId, order: entry.order});
      const sm = ensureStepMeta(model, stepId);
      if (sm) sm.calls++;
    } else {
      if (entry.stepId == null && stepId != null) {
        entry.stepId = stepId;
        const sm = ensureStepMeta(model, stepId);
        if (sm) sm.calls++;
      }
      if (!entry.purpose && purpose) entry.purpose = purpose;
      if (entry.ts == null && ts != null) entry.ts = ts;
    }
    return entry;
  }

  function updateTelemetryFromDetail(model, stepId, event) {
    const label = String(event.label || "");
    const val = event.value && typeof event.value === "object" ? event.value : null;
    const sm = ensureStepMeta(model, stepId);

    if (label.startsWith("接口检查 · ")) {
      model.struct.interface = lampStateFromStatus(event.status || val?.status);
      if (sm && model.struct.interface === "failed") sm.verdict = "bad";
    } else if (label.startsWith("编译与展开 · ")) {
      model.struct.lint = lampStateFromStatus(event.status || val?.status);
      if (sm && model.struct.lint === "failed") sm.verdict = "bad";
    } else if (label.startsWith("综合 · ")) {
      model.struct.synth = lampStateFromStatus(event.status || val?.status);
      if (sm && model.struct.synth === "failed") sm.verdict = "bad";
    } else if (label === "结构检查汇总" && val) {
      const notRun = new Set(Array.isArray(val.not_run) ? val.not_run : []);
      for (const stage of ["interface", "lint", "synth"]) {
        if (notRun.has(stage) && model.struct[stage] === "idle") model.struct[stage] = "idle";
      }
      if (sm) {
        sm.verdict = val.structural_passed && val.toolchain_passed ? "good"
          : val.code_failed ? "bad" : "warn";
      }
    } else if (label === "行为比对汇总" && val) {
      const st = event.status || val.status;
      const lamp = lampStateFromStatus(st);
      const bits = Number.isFinite(val.compared_bits) ? val.compared_bits : null;
      const unk = Number.isFinite(val.unknown_bits) ? val.unknown_bits : null;
      let text = zhStatus(st);
      if (bits != null && bits > 0) text += " · " + bits + "b";
      model.behavior = {state: lamp, label: text, comparedBits: bits, unknownBits: unk};
      if (sm) sm.verdict = lamp === "passed" ? "good" : lamp === "failed" ? "bad" : "warn";
    } else if (label === "交付候选的验证结果" && val) {
      if (val.behavior_status) {
        const lamp = lampStateFromStatus(val.behavior_status);
        const bits = Number.isFinite(val.compared_bits) ? val.compared_bits : null;
        let text = zhStatus(val.behavior_status);
        if (bits != null && bits > 0) text += " · " + bits + "b";
        model.behavior = {state: lamp, label: text, comparedBits: bits, unknownBits: null};
      }
    }
  }

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
        const step = {
          id, node, label: String(event.label || event.node || id), role: event.role,
          previous: key(event.previous), ts: event.ts, sequence: model.steps.length + 1,
          visit: visits.length + 1,
        };
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
      case "call_context": {
        const entry = ensureCall(model, event.call_id, id, event.purpose, event.ts);
        entry.context = {messages: Array.isArray(event.messages) ? event.messages : [], ts: event.ts};
        return true;
      }
      case "call_response": {
        const entry = ensureCall(model, event.call_id, id, event.purpose, event.ts);
        entry.response = {
          hasContent: Object.prototype.hasOwnProperty.call(event, "content"),
          content: event.content,
          reasoning_content: typeof event.reasoning_content === "string" ? event.reasoning_content : null,
          reasoning: typeof event.reasoning === "string" ? event.reasoning : null,
          finish_reason: event.finish_reason ?? null,
          tool_calls: Array.isArray(event.tool_calls) ? event.tool_calls : null,
          ts: event.ts,
        };
        return true;
      }
      case "detail": {
        const idx = model.details.length;
        const rec = {id, event, index: idx};
        model.details.push(rec);
        updateTelemetryFromDetail(model, id, event);

        // 将「模型调用」生命周期元数据合并到对应的 call 卡片
        if (event.label === "模型调用" && event.value && typeof event.value === "object") {
          const v = event.value;
          const cid = v.call_id != null ? String(v.call_id) : null;
          if (cid && model.calls.has(cid)) {
            const entry = model.calls.get(cid);
            entry.meta = {...entry.meta, ...v, status: event.status || entry.meta.status};
            return false;
          }
          if (cid && event.status === "started") {
            const entry = ensureCall(model, cid, id, v.purpose, event.ts);
            entry.meta = {...entry.meta, ...v, status: "started"};
            return true;
          }
          // 若未关联到任何 call_context（如预算拒绝/未发送），保留为紧凑提示条
          if (event.status === "failed") {
            model.stream.push({type: "detail", id, event, index: idx, order: model.stream.length});
          }
          return false;
        }
        model.stream.push({type: "detail", id, event, index: idx, order: model.stream.length});
        return false;
      }
      case "run_end":
        model.end = event;
        return true;
    }
    model.unsupported++;
    return false;
  }

  /* ================= 应用状态 ================= */
  const storageKey = "rtl.ui.selection.v1";
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(storageKey)); } catch { /* Optional */ }
  let follow = saved?.follow !== false;
  let queueCollapsed = saved?.queueCollapsed === true;
  let jobId = null;
  let pinned = typeof saved?.job === "string" ? saved.job : null;
  let board = {mode: null, active_id: null, runs: []};
  let model = emptyModel(), run = null, cursor = 0;
  let scope = "latest", tab = "records", view = "trace", planSelection = null;
  let stateError = "", runError = "", runMissing = false, stateReady = false, boardOff = false, lastSync = null;
  let recordSignature = "", scopeSignature = "";
  let openState = new Map(); // 记住用户手动展开/收起的 details 状态
  let runEpoch = 0, runTimer = null, runController = null;
  let boardTimer = null, boardBusy = false, boardAgain = false, boardFailures = 0;
  let currentScene = null, zoom = {trace: 1, plan: 1};
  let presenterTasks = [], previewId = null, previewEpoch = 0, dialogEpoch = 0, launching = false;

  const remember = () => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({
        follow, job: jobId || pinned, queueCollapsed,
      }));
    } catch { /* Optional */ }
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
    if (end?.status === "finished") return ["finished", "已完成"];
    if (end) return ["unknown", String(end.status || "结束状态未知")];
    if (selectedRun()?.status === "done" || model.end) return ["unknown", "未记录结束"];
    return ["current", "执行中"];
  }

  function stepElapsedText(step) {
    const end = model.ends.get(step.id);
    if (end?.elapsed_s != null && Number.isFinite(end.elapsed_s)) return duration(end.elapsed_s);
    const [st] = executionState(step);
    if (st === "current" && step.ts != null) {
      const startMs = date(step.ts)?.getTime();
      if (startMs != null) return duration(Math.max(0, (Date.now() - startMs) / 1000));
    }
    return st === "current" ? "运行中" : "";
  }

  function runElapsedText() {
    if (model.end?.elapsed_s != null && Number.isFinite(model.end.elapsed_s)) return duration(model.end.elapsed_s);
    const item = selectedRun();
    if (!item) return "--";
    const startMs = date(item.started ?? item.submitted)?.getTime();
    if (startMs == null) return "--";
    if (item.finished != null) {
      const endMs = date(item.finished)?.getTime();
      if (endMs != null) return duration(Math.max(0, (endMs - startMs) / 1000));
    }
    if (item.status === "running" || item.status === "queued") {
      return duration(Math.max(0, (Date.now() - startMs) / 1000));
    }
    return "--";
  }

  function applyQueueDrawer() {
    document.body.classList.toggle("queue-collapsed", queueCollapsed);
    const btn = $("toggle-queue");
    btn.setAttribute("aria-expanded", String(!queueCollapsed));
    btn.querySelector(".btn-label").textContent = queueCollapsed ? "展开队列" : "收起队列";
  }

  /* ================= 网络请求 ================= */
  async function request(url, options = {}, ctrl = new AbortController()) {
    const timeout = setTimeout(() => ctrl.abort(), 12000);
    try {
      const response = await fetch(url, {
        cache: "no-store", credentials: "omit", redirect: "error",
        referrerPolicy: "no-referrer", ...options, signal: ctrl.signal,
      });
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

  /* ================= HUD 与队列渲染 ================= */
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

  function renderTelemetry() {
    updateText($("hud-elapsed"), runElapsedText());
    const callCount = model.end?.calls != null ? model.end.calls : model.calls.size;
    updateText($("hud-steps"), model.steps.length + " / " + callCount);

    const structBox = $("hud-struct");
    const stageNames = {interface: "接口检查", lint: "编译与展开", synth: "综合"};
    for (const lamp of structBox.querySelectorAll(".lamp")) {
      const stage = lamp.dataset.stage;
      const st = model.struct[stage] || "idle";
      lamp.dataset.state = st;
      lamp.title = stageNames[stage] + "：" + (st === "idle" ? "未运行" : zhStatus(st));
    }

    const beh = $("hud-behavior");
    beh.dataset.state = model.behavior.state;
    updateText(beh.lastElementChild, model.behavior.label);
  }

  function renderHeader() {
    const item = selectedRun();
    updateText($("task-name"), item?.task_id || (boardOff ? "展示已关闭" : jobId && runError ? "运行记录不可用"
      : jobId ? "正在读取题目…" : stateReady ? "尚未收到题目" : "正在读取题目…"));
    const badge = $("job-status");
    badge.hidden = !item;
    badge.className = "status-pill " + (jobStates.has(item?.status) ? item.status : "");
    updateText(badge, item ? statusName(item.status) : "");

    const wf = $("task-workflow");
    wf.hidden = !model.plan?.workflow;
    if (model.plan?.workflow) updateText(wf, model.plan.workflow);

    const meta = [];
    if (item) {
      meta.push(sourceName(item.source));
      if (item.submitted != null) meta.push("收题 " + clock(item.submitted));
      if (item.started != null) meta.push("开始 " + clock(item.started));
    }
    updateText($("task-meta"), meta.join(" · "));
    renderTelemetry();
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
      button.append(
        make("i", "status-dot " + state),
        make("span", "run-name", item.task_id),
        make("span", "run-meta", statusName(item.status) + " · " + clock(item.submitted)),
      );
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
    openState = new Map();
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
        if (graphChanged || statusChanged) {
          drawGraph({locate: scope === "latest" && view === "trace" && oldCount < model.steps.length});
        }
        renderInspector();
      }
      if (result.more) scheduleRun(0);
      else if (result.status !== "done") scheduleRun(document.hidden ? 4500 : 1000);
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

  /* ================= 多角色工作流画布 ================= */
  const NODE_W = 204, NODE_H = 92, GAP_X = 54, GAP_Y = 46, PAD = 34;

  function traceLayout() {
    const width = $("graph-scroll").clientWidth || 500;
    const cols = Math.max(1, Math.min(model.steps.length, Math.floor((width - PAD * 2 + GAP_X) / (NODE_W + GAP_X))));
    const inset = Math.max(PAD, (width - cols * NODE_W - (cols - 1) * GAP_X) / 2);
    const points = new Map();
    for (const [index, step] of model.steps.entries()) {
      const row = Math.floor(index / cols), slot = index % cols;
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
      points.set(id, {x: PAD + column * (NODE_W + GAP_X), y: PAD + 14 + row * (NODE_H + GAP_Y), node});
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
    const gap = 12 + (index % 4) * 3;
    if (s === t) return `M ${s.x + NODE_W - 22} ${s.y} v -18 h 38 v 38 H ${s.x + NODE_W + 2}`;
    if (view === "plan") {
      if (t.x === s.x + NODE_W + GAP_X) {
        const mid = s.x + NODE_W + gap;
        return `M ${s.x + NODE_W} ${sy} H ${mid} V ${ty} H ${t.x - 2}`;
      }
      if (s.x === t.x) {
        const side = s.x + NODE_W + gap;
        return `M ${s.x + NODE_W} ${sy} H ${side} V ${ty} H ${t.x + NODE_W + 2}`;
      }
      const top = 6 + (index % 7) * 4;
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
    const bottom = s.y + NODE_H + gap;
    const port = s.x <= t.x ? 34 : -34;
    if (sy === ty) return `M ${sx + port} ${s.y + NODE_H} V ${bottom} H ${tx - port} V ${t.y + NODE_H + 2}`;
    const side = s.x <= t.x ? gap : scene.w - gap;
    return `M ${sx + port} ${s.y + NODE_H} V ${bottom} H ${side} V ${t.y - gap} H ${tx - port} V ${t.y - 2}`;
  }

  function makeMarker(id, fill) {
    const marker = svg("marker"), arrow = svg("path");
    marker.id = id;
    marker.setAttribute("viewBox", "0 0 8 8");
    marker.setAttribute("refX", "7");
    marker.setAttribute("refY", "4");
    marker.setAttribute("markerWidth", "6");
    marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto");
    arrow.setAttribute("d", "M 0 0 L 8 4 L 0 8 z");
    arrow.setAttribute("fill", fill);
    marker.append(arrow);
    return marker;
  }

  function drawWires(scene) {
    const layer = svg("svg");
    layer.classList.add("wires");
    layer.setAttribute("aria-hidden", "true");
    layer.setAttribute("width", scene.w);
    layer.setAttribute("height", scene.h);
    const defs = svg("defs");
    defs.append(
      makeMarker("wire-arrow", view === "trace" ? "#34d399" : "#64748b"),
      makeMarker("wire-arrow-active", "#22d3ee"),
    );
    layer.append(defs);

    for (const [index, link] of scene.links.entries()) {
      const targetStep = view === "trace" ? scene.points.get(link.to)?.step : null;
      const isActive = Boolean(targetStep && executionState(targetStep)[0] === "current");
      const line = svg("path");
      line.setAttribute("class", view === "plan" ? "wire planned" : isActive ? "wire active-wire" : "wire");
      line.setAttribute("d", pathFor(scene.points.get(link.from), scene.points.get(link.to), index, scene));
      line.setAttribute("marker-end", isActive ? "url(#wire-arrow-active)" : "url(#wire-arrow)");
      layer.append(line);
    }
    return layer;
  }

  function graphButton(id, point) {
    const planned = view === "plan";
    const step = point.step;
    const visits = planned ? model.visits.get(id) || [] : [];
    const state = step ? executionState(step)
      : visits.some((v) => executionState(v)[0] === "current") ? ["current", "执行中"]
      : [visits.length ? "visited" : "", visits.length ? "已执行 " + visits.length + " 次" : "未执行"];
    const chosen = planned ? planSelection === id : selectedStep()?.id === id;
    const role = step?.role || point.node?.role;
    const rk = roleKey(role);

    const el = make("button", "graph-node" + (planned ? " planned" : "") + (state[0] ? " " + state[0] : "") + (chosen ? " selected" : ""));
    el.type = "button";
    el.dataset.graphId = id;
    el.dataset.role = rk;
    el.setAttribute("aria-pressed", String(chosen));
    el.style.left = point.x + "px";
    el.style.top = point.y + "px";

    const label = step?.label || point.node?.label || id;
    const top = make("span", "node-top");
    const timerText = step ? (stepElapsedText(step) || state[1]) : state[1];
    const timerEl = make("span", "node-timer", timerText);
    if (step) timerEl.dataset.stepTimer = step.id;
    top.append(
      make("span", "node-index", step ? seqName(step) + (step.visit > 1 ? " · #" + step.visit : "")
        : id === key(model.plan?.entrypoint) ? "入口" : "节点"),
      timerEl,
    );

    const bottom = make("span", "node-bottom");
    bottom.append(make("span", "node-role-tag", role || (step ? step.node : id)));

    if (step) {
      const sm = model.stepMeta.get(step.id);
      if (sm && (sm.calls > 0 || sm.verdict)) {
        const badges = make("span", "node-badges");
        if (sm.calls > 0) badges.append(make("span", "node-pill llm", "思考×" + sm.calls));
        if (sm.verdict === "good") badges.append(make("span", "node-pill good", "✓"));
        else if (sm.verdict === "bad") badges.append(make("span", "node-pill bad", "✗"));
        else if (sm.verdict === "warn") badges.append(make("span", "node-pill warn", "!"));
        bottom.append(badges);
      }
    }

    el.append(top, make("span", "node-name", label), bottom);
    el.title = [step ? seqName(step) : id, label, role, state[1]].filter(Boolean).join(" · ");
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
      empty.querySelector("strong").textContent = view === "plan" ? "暂无流程定义" : "等待工作流事件";
      empty.lastElementChild.textContent = !jobId ? "收到题目后会实时渲染多角色执行轨迹。"
        : selectedRun()?.status === "queued" ? "这道题正在队列中等待开始。"
        : selectedRun()?.status === "done" ? "该次运行未提供此视图所需事件（如 baseline 模式）。"
        : "正在等待这道题的工作流节点事件…";
    }
    $("edge-key").className = view === "trace" ? "edge-key" : "edge-key planned";
    updateText($("edge-caption"), view === "trace" ? "实际前序" : "定义转移");
    updateText($("graph-count"), count ? count + (view === "trace" ? " 步" : " 节点") : "");
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
      v.scrollLeft = Math.max(0, left - (v.clientWidth - NODE_W * scale) / 2);
    }
    if (top < v.scrollTop || top + NODE_H * scale > v.scrollTop + v.clientHeight) {
      v.scrollTop = Math.max(0, top - (v.clientHeight - NODE_H * scale) / 2);
    }
  }

  function changeZoom(scale, all = false) {
    if (!currentScene?.points.size) return;
    const v = $("graph-scroll"), old = zoom[view];
    const cx = (v.scrollLeft + v.clientWidth / 2) / old, cy = (v.scrollTop + v.clientHeight / 2) / old;
    zoom[view] = scale;
    sizeScene();
    v.scrollLeft = all ? 0 : Math.max(0, cx * scale - v.clientWidth / 2);
    v.scrollTop = all ? 0 : Math.max(0, cy * scale - v.clientHeight / 2);
  }

  function renderPlanInfo() {
    const info = $("plan-info");
    info.hidden = view !== "plan" || !currentScene?.points.size;
    if (info.hidden) { info.replaceChildren(); return; }
    const node = currentScene.points.get(planSelection)?.node;
    if (!node) { updateText(info, "点击任意定义节点，查看其转移条件和历次执行。"); return; }
    const entries = currentScene.links.filter((link) => link.from === planSelection);
    const list = make("ul");
    for (const link of entries) {
      const target = currentScene.points.get(link.to).node;
      list.append(make("li", "", (target.label || link.to) + (link.condition == null ? "" : "　" + printable(link.condition))));
    }
    const visits = model.visits.get(planSelection) || [];
    info.replaceChildren(make("strong", "", (node.label || node.id) + " · 可转移至 " + entries.length + " 个节点"));
    if (entries.length) info.append(list);
    const history = make("div", "", visits.length ? "历次执行：" : "尚未收到此节点的执行记录。");
    for (const step of visits) {
      const button = make("button", "", seqName(step) + " · 第 " + step.visit + " 次");
      button.type = "button";
      button.addEventListener("click", () => { view = "trace"; chooseScope("step:" + step.id, true); });
      history.append(button);
    }
    info.append(history);
  }

  /* 画布拖拽平移 */
  function setupCanvasPan() {
    const vp = $("graph-scroll");
    let dragging = false, startX = 0, startY = 0, origLeft = 0, origTop = 0;
    vp.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest(".graph-node")) return;
      dragging = true;
      startX = e.clientX;
      startY = e.clientY;
      origLeft = vp.scrollLeft;
      origTop = vp.scrollTop;
      vp.classList.add("dragging");
      vp.setPointerCapture(e.pointerId);
    });
    vp.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      vp.scrollLeft = origLeft - (e.clientX - startX);
      vp.scrollTop = origTop - (e.clientY - startY);
    });
    const endDrag = (e) => {
      if (!dragging) return;
      dragging = false;
      vp.classList.remove("dragging");
      if (vp.hasPointerCapture(e.pointerId)) vp.releasePointerCapture(e.pointerId);
    };
    vp.addEventListener("pointerup", endDrag);
    vp.addEventListener("pointercancel", endDrag);
    vp.addEventListener("wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey) || !currentScene?.points.size) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      changeZoom(Math.min(2.5, Math.max(0.2, zoom[view] * factor)));
    }, {passive: false});
  }

  /* ================= 剪贴板 ================= */
  async function copyText(value, button) {
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch { /* Fallback */ }
    if (!copied) {
      const field = make("textarea", "copy-field");
      field.value = value;
      document.body.append(field);
      field.select();
      try { copied = document.execCommand("copy"); } catch { /* Ignore */ }
      field.remove();
      button.focus({preventScroll: true});
    }
    const prev = button.textContent;
    button.textContent = copied ? "已复制" : "请手动复制";
    setTimeout(() => { button.textContent = prev; }, 1600);
  }

  /* ================= 轻量 Verilog/SV 语法高亮与 Markdown ================= */
  const VERILOG_KW = new Set([
    "module", "endmodule", "function", "endfunction", "task", "endtask",
    "always", "always_ff", "always_comb", "always_latch", "initial", "assign",
    "begin", "end", "if", "else", "case", "casex", "casez", "endcase", "default",
    "for", "while", "repeat", "forever", "generate", "endgenerate", "genvar",
    "posedge", "negedge", "edge", "or", "and", "not", "return", "typedef", "enum", "struct",
    "localparam", "parameter", "defparam", "package", "endpackage", "import",
  ]);
  const VERILOG_TYPE = new Set([
    "input", "output", "inout", "wire", "reg", "logic", "bit", "byte",
    "int", "integer", "shortint", "longint", "signed", "unsigned", "tri", "supply0", "supply1",
  ]);
  const V_TOKEN = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|`[a-zA-Z_]\w*|\$[a-zA-Z_]\w*|\b\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_?]+\b|\b\d[\d_]*\b|\b[a-zA-Z_]\w*\b)/g;

  function highlightVerilogLine(line, state) {
    const frag = document.createDocumentFragment();
    let i = 0;
    const len = line.length;
    while (i < len) {
      if (state.inBlockComment) {
        const end = line.indexOf("*/", i);
        if (end === -1) {
          frag.append(make("span", "tok-cmt", line.slice(i)));
          return frag;
        }
        frag.append(make("span", "tok-cmt", line.slice(i, end + 2)));
        state.inBlockComment = false;
        i = end + 2;
        continue;
      }
      V_TOKEN.lastIndex = i;
      const m = V_TOKEN.exec(line);
      if (!m) {
        // 检查是否存在未闭合块注释 /*
        const openIdx = line.indexOf("/*", i);
        if (openIdx !== -1) {
          if (openIdx > i) frag.append(document.createTextNode(line.slice(i, openIdx)));
          frag.append(make("span", "tok-cmt", line.slice(openIdx)));
          state.inBlockComment = true;
        } else {
          frag.append(document.createTextNode(line.slice(i)));
        }
        break;
      }
      const openIdx = line.indexOf("/*", i);
      if (openIdx !== -1 && openIdx < m.index) {
        if (openIdx > i) frag.append(document.createTextNode(line.slice(i, openIdx)));
        frag.append(make("span", "tok-cmt", line.slice(openIdx)));
        state.inBlockComment = true;
        break;
      }
      if (m.index > i) frag.append(document.createTextNode(line.slice(i, m.index)));
      const tok = m[0];
      if (tok.startsWith("//") || tok.startsWith("/*")) {
        frag.append(make("span", "tok-cmt", tok));
      } else if (tok.startsWith('"')) {
        frag.append(make("span", "tok-str", tok));
      } else if (tok.startsWith("`")) {
        frag.append(make("span", "tok-dir", tok));
      } else if (tok.startsWith("$")) {
        frag.append(make("span", "tok-sys", tok));
      } else if (/^\d|'/.test(tok)) {
        frag.append(make("span", "tok-num", tok));
      } else if (VERILOG_KW.has(tok)) {
        frag.append(make("span", "tok-kw", tok));
      } else if (VERILOG_TYPE.has(tok)) {
        frag.append(make("span", "tok-type", tok));
      } else {
        frag.append(document.createTextNode(tok));
      }
      i = m.index + tok.length;
    }
    return frag;
  }

  function isVerilogLang(lang, code) {
    const l = String(lang || "").toLowerCase();
    if (["verilog", "systemverilog", "sv", "v"].includes(l)) return true;
    return !l && /\bmodule\s+\w+[\s\S]*\bendmodule\b/.test(code);
  }

  function renderCodeCard(code, lang, title) {
    const card = make("div", "code-card");
    const head = make("div", "code-head");
    const lines = String(code || "").replace(/\r\n/g, "\n").split("\n");
    const left = make("div", "");
    const verilog = isVerilogLang(lang, code);
    left.append(
      make("span", "code-lang", title || (verilog ? (lang || "Verilog") : (lang || "CODE"))),
      make("span", "mono", " · " + lines.length + " 行"),
    );
    const copyBtn = make("button", "copy-btn", "复制代码");
    copyBtn.type = "button";
    copyBtn.addEventListener("click", () => copyText(String(code || ""), copyBtn));
    head.append(left, copyBtn);

    const scroll = make("div", "code-scroll");
    const table = make("table", "code-table");
    const tbody = make("tbody");
    const state = {inBlockComment: false};
    for (let i = 0; i < lines.length; i++) {
      const tr = make("tr");
      const ln = make("td", "code-ln", String(i + 1));
      const td = make("td", "code-line");
      if (verilog) td.append(highlightVerilogLine(lines[i], state));
      else td.textContent = lines[i];
      tr.append(ln, td);
      tbody.append(tr);
    }
    table.append(tbody);
    scroll.append(table);
    card.append(head, scroll);
    return card;
  }

  function appendInlineMarkdown(parent, text) {
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
    let last = 0, m;
    while ((m = pattern.exec(text)) !== null) {
      if (m.index > last) parent.append(document.createTextNode(text.slice(last, m.index)));
      const tok = m[0];
      if (tok.startsWith("`")) parent.append(make("code", "inline-code", tok.slice(1, -1)));
      else parent.append(make("strong", "", tok.slice(2, -2)));
      last = m.index + tok.length;
    }
    if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
  }

  function renderMarkdown(text) {
    const root = make("div", "md-body");
    const src = String(text || "").replace(/\r\n/g, "\n");
    const fenceRe = /```([a-zA-Z0-9_-]*)[ \t]*\n([\s\S]*?)```/g;
    let pos = 0, match;

    const pushProse = (chunk) => {
      const lines = chunk.split("\n");
      let listEl = null, listTag = null;
      const flushList = () => { if (listEl) { root.append(listEl); listEl = null; listTag = null; } };
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) { flushList(); continue; }
        const h = /^(#{1,4})\s+(.+)$/.exec(trimmed);
        if (h) {
          flushList();
          const el = make("h" + h[1].length);
          appendInlineMarkdown(el, h[2]);
          root.append(el);
          continue;
        }
        const ul = /^[-*+]\s+(.+)$/.exec(trimmed);
        if (ul) {
          if (listTag !== "ul") { flushList(); listEl = make("ul"); listTag = "ul"; }
          const li = make("li");
          appendInlineMarkdown(li, ul[1]);
          listEl.append(li);
          continue;
        }
        const ol = /^\d+\.\s+(.+)$/.exec(trimmed);
        if (ol) {
          if (listTag !== "ol") { flushList(); listEl = make("ol"); listTag = "ol"; }
          const li = make("li");
          appendInlineMarkdown(li, ol[1]);
          listEl.append(li);
          continue;
        }
        flushList();
        const p = make("p");
        appendInlineMarkdown(p, line);
        root.append(p);
      }
      flushList();
    };

    while ((match = fenceRe.exec(src)) !== null) {
      if (match.index > pos) pushProse(src.slice(pos, match.index));
      const lang = match[1] || "";
      const code = match[2].replace(/\n$/, "");
      root.append(renderCodeCard(code, lang, lang ? lang.toUpperCase() : undefined));
      pos = match.index + match[0].length;
    }
    if (pos < src.length) {
      const tail = src.slice(pos);
      if (pos === 0 && /^\s*module\s+\w+/.test(tail) && /\bendmodule\b/.test(tail)) {
        root.append(renderCodeCard(tail.trim(), "verilog", "Verilog"));
      } else {
        pushProse(tail);
      }
    }
    return root;
  }

  /* ================= 思考与决策流：模型调用卡片 ================= */
  function messageText(msg) {
    if (typeof msg.content === "string") return msg.content;
    if (Array.isArray(msg.content)) {
      return msg.content.map((part) => {
        if (part?.type === "text" && typeof part.text === "string") return part.text;
        return "[" + (part?.type || "附件") + "]";
      }).join("\n");
    }
    if (msg.content === null) return "";
    return msg.content == null ? "" : printable(msg.content);
  }

  function renderCallCard(entry) {
    const card = make("article", "call-card");
    const head = make("div", "call-head");
    const headLeft = make("div", "call-head-left");
    const step = model.byId.get(entry.stepId);
    const rk = roleKey(step?.role);

    if (step?.role) {
      const rc = make("span", "role-chip", step.role);
      rc.dataset.role = rk;
      headLeft.append(rc);
    }
    headLeft.append(make("span", "call-title", zhPurpose(entry.purpose)));

    const finish = entry.response?.finish_reason || entry.meta?.finish_reason;
    if (entry.meta?.status === "failed") {
      headLeft.append(make("span", "badge bad", "调用异常" + (entry.meta.error_kind ? " · " + entry.meta.error_kind : "")));
    } else if (entry.response) {
      const [fText, fTone] = finishLabels.get(finish) || [finish || "已返回", "good"];
      headLeft.append(make("span", "badge " + fTone, fText));
    } else {
      headLeft.append(make("span", "badge info", "等待模型回复…"));
    }

    const metaParts = [];
    if (entry.meta?.elapsed_s != null) metaParts.push(duration(entry.meta.elapsed_s));
    if (entry.meta?.tokens_in != null || entry.meta?.tokens_out != null) {
      metaParts.push((entry.meta.tokens_in ?? "?") + "→" + (entry.meta.tokens_out ?? "?") + " tok");
    }
    if (entry.ts != null) metaParts.push(clock(entry.ts));
    const headRight = make("div", "call-meta", metaParts.join(" · "));
    head.append(headLeft, headRight);

    const body = make("div", "call-body");

    // 1. 收到的上下文 / Prompt（默认折叠）
    if (entry.context) {
      const msgs = entry.context.messages || [];
      const roleCounts = new Map();
      let totalChars = 0;
      for (const m of msgs) {
        const r = String(m.role || "unknown").toLowerCase();
        roleCounts.set(r, (roleCounts.get(r) || 0) + 1);
        totalChars += messageText(m).length;
      }
      const ctxKey = "ctx:" + entry.key;
      const details = make("details", "ctx-block");
      details.open = openState.get(ctxKey) === true;
      details.addEventListener("toggle", () => { openState.set(ctxKey, details.open); });

      const summary = make("summary");
      const sumLeft = make("span", "ctx-summary-left");
      sumLeft.append(make("span", "ctx-chevron", "▶"), make("strong", "", "收到的上下文 / Prompt"));
      for (const [r, cnt] of roleCounts) {
        const tone = r === "system" ? "violet" : r === "user" ? "info" : r === "assistant" ? "good" : "warn";
        sumLeft.append(make("span", "badge " + tone, r.toUpperCase() + (cnt > 1 ? " ×" + cnt : "")));
      }
      summary.append(sumLeft, make("span", "ctx-stats", msgs.length + " 条消息 · " + totalChars.toLocaleString("zh-CN") + " 字符"));
      details.append(summary);

      const list = make("div", "ctx-messages");
      for (const m of msgs) {
        const role = String(m.role || "unknown").toLowerCase();
        const item = make("div", "msg-item");
        item.dataset.msgRole = role;
        const mHead = make("div", "msg-head");
        mHead.append(
          make("span", "msg-role", role + (m.name ? " · " + m.name : "") + (m.tool_call_id ? " (" + m.tool_call_id + ")" : "")),
          make("span", "ctx-stats", messageText(m).length.toLocaleString("zh-CN") + " 字符"),
        );
        item.append(mHead);
        const txt = messageText(m);
        if (txt) item.append(make("pre", "msg-pre", txt));
        if (Array.isArray(m.tool_calls) && m.tool_calls.length) {
          for (const tc of m.tool_calls) {
            const fn = tc.function || {};
            item.append(make("pre", "msg-pre", "调用工具 " + (fn.name || tc.id || "tool") + "(" + (typeof fn.arguments === "string" ? fn.arguments : printable(fn.arguments)) + ")"));
          }
        }
        list.append(item);
      }
      details.append(list);
      body.append(details);
    }

    // 2. 模型推理思路（默认展开）
    if (entry.response) {
      const res = entry.response;
      const thoughts = [];
      if (res.reasoning_content) thoughts.push(["模型推理思路", res.reasoning_content, "rc"]);
      if (res.reasoning) thoughts.push(["模型推理过程", res.reasoning, "r"]);

      for (const [label, text, tag] of thoughts) {
        const tKey = "thought:" + entry.key + ":" + tag;
        const block = make("details", "thought-block");
        block.open = openState.has(tKey) ? openState.get(tKey) : true;
        block.addEventListener("toggle", () => { openState.set(tKey, block.open); });

        const sum = make("summary");
        const left = make("span", "ctx-summary-left");
        left.append(make("span", "", "◈ " + label), make("span", "ctx-stats", text.length.toLocaleString("zh-CN") + " 字符"));
        const copyBtn = make("button", "copy-btn", "复制思路");
        copyBtn.type = "button";
        copyBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); copyText(text, copyBtn); });
        sum.append(left, copyBtn);

        block.append(sum, make("div", "thought-body", text));
        body.append(block);
      }

      // 3. 模型最终输出（默认展开）
      const outBlock = make("div", "output-block");
      const outHead = make("div", "output-head");
      const outLeft = make("span", "ctx-summary-left");
      outLeft.append(make("span", "", "▸ 模型最终输出"));
      if (typeof res.content === "string" && res.content.length) {
        outLeft.append(make("span", "ctx-stats", res.content.length.toLocaleString("zh-CN") + " 字符"));
      }
      outHead.append(outLeft);
      if (typeof res.content === "string" && res.content.length) {
        const copyBtn = make("button", "copy-btn", "复制输出");
        copyBtn.type = "button";
        copyBtn.addEventListener("click", () => copyText(res.content, copyBtn));
        outHead.append(copyBtn);
      }
      outBlock.append(outHead);

      const outBody = make("div", "output-body");
      if (typeof res.content === "string" && res.content.trim().length > 0) {
        outBody.append(renderMarkdown(res.content));
      } else if (res.tool_calls && res.tool_calls.length) {
        outBody.append(make("p", "dialog-muted", "本轮输出为工具调用请求："));
      } else {
        const reason = finish === "length" ? "（输出达到长度上限，未生成最终正文）"
          : finish === "content_filter" ? "（输出被内容过滤）" : "（本轮无最终文本输出）";
        outBody.append(make("p", "dialog-muted", reason));
      }

      if (res.tool_calls && res.tool_calls.length) {
        for (const tc of res.tool_calls) {
          const fn = tc.function || {};
          const args = typeof fn.arguments === "string" ? fn.arguments : printable(fn.arguments);
          outBody.append(renderCodeCard(args, "json", "工具调用 · " + (fn.name || tc.id || "function")));
        }
      }

      outBlock.append(outBody);
      body.append(outBlock);
    }

    card.append(head, body);
    return card;
  }

  /* ================= 结构化验证视觉卡片 ================= */
  function makeCard(title, status, extraBadge) {
    const tone = statusTone(status);
    const card = make("article", "v-card" + (tone ? " status-" + tone : ""));
    const head = make("div", "v-card-head");
    const t = make("div", "v-card-title");
    t.append(make("span", "", title));
    if (extraBadge) t.append(extraBadge);
    head.append(t);
    if (status != null && status !== "") {
      head.append(make("span", "badge " + tone, zhStatus(status)));
    }
    const body = make("div", "v-card-body");
    card.append(head, body);
    return {card, head, body};
  }

  function makeKvGrid(pairs) {
    const grid = make("div", "kv-grid");
    for (const [k, v] of pairs) {
      if (v == null || v === "") continue;
      const item = make("div", "kv-item");
      item.append(make("span", "kv-k", k), make("span", "kv-v mono", String(v)));
      grid.append(item);
    }
    return grid;
  }

  function makeBitBar(comparedBits, unknownBits, status) {
    const cmp = Number.isFinite(comparedBits) ? Math.max(0, comparedBits) : 0;
    const unk = Number.isFinite(unknownBits) ? Math.max(0, unknownBits) : 0;
    const total = cmp + unk;
    const wrap = make("div", "bit-progress");
    const meta = make("div", "bit-progress-meta");
    meta.append(
      make("span", "mono", "已比对 " + cmp + " bit" + (unk > 0 ? " · 未知 " + unk + " bit" : "")),
      make("span", "mono", total > 0 ? Math.round((cmp / total) * 100) + "% 确定" : "无有效比对"),
    );
    const bar = make("div", "bit-bar");
    if (total > 0) {
      const cmpSeg = make("div", statusTone(status) === "bad" ? "bit-seg-bad" : "bit-seg-good");
      cmpSeg.style.width = ((cmp / total) * 100).toFixed(1) + "%";
      bar.append(cmpSeg);
      if (unk > 0) {
        const unkSeg = make("div", "bit-seg-unk");
        unkSeg.style.width = ((unk / total) * 100).toFixed(1) + "%";
        bar.append(unkSeg);
      }
    }
    wrap.append(meta, bar);
    return wrap;
  }

  function formatActualSignal(actual) {
    if (actual == null) return {text: "—", hasX: true};
    if (typeof actual !== "object") return {text: String(actual), hasX: false};
    const bits = actual.bits;
    const width = actual.width;
    const known = actual.known;
    if (width != null && known != null) {
      try {
        const fullMask = (1n << BigInt(width)) - 1n;
        const kBig = BigInt(known);
        if (kBig !== fullMask) return {text: String(bits) + " (含未知位 X)", hasX: true};
      } catch { /* fallback */ }
    }
    return {text: bits != null ? String(bits) : printable(actual), hasX: false};
  }

  function renderStructureCheckCard(label, event) {
    const v = event.value || {};
    const status = event.status || v.status;
    const {card, body} = makeCard(label, status);
    body.append(makeKvGrid([
      ["候选", v.candidate_id],
      ["耗时", v.elapsed_s != null ? duration(v.elapsed_s) : null],
      ["退出码", v.rc],
      ["工具版本", v.tool_version],
      ["失败类型", v.failure_kind],
    ]));
    if (v.summary) body.append(make("p", "reason-box", v.summary));
    if (Array.isArray(v.differences) && v.differences.length) {
      const ul = make("ul", "diag-list");
      for (const d of v.differences) ul.append(make("li", "diag-item sev-error", typeof d === "string" ? d : printable(d)));
      body.append(ul);
    }
    const items = v.diagnostics?.items || v.diagnostics?.root_errors || [];
    if (Array.isArray(items) && items.length) {
      const ul = make("ul", "diag-list");
      for (const it of items) {
        const sev = String(it.severity || "").toLowerCase();
        const prefix = [it.code, it.line_number != null ? "L" + it.line_number : null].filter(Boolean).join(" ");
        ul.append(make("li", "diag-item" + (sev === "error" ? " sev-error" : ""), (prefix ? "[" + prefix + "] " : "") + (it.message || "")));
      }
      body.append(ul);
    }
    if (Array.isArray(v.warnings) && v.warnings.length) {
      const ul = make("ul", "diag-list");
      for (const w of v.warnings) ul.append(make("li", "diag-item", typeof w === "string" ? w : printable(w)));
      body.append(ul);
    }
    return card;
  }

  function renderStructureSummaryCard(event) {
    const v = event.value || {};
    const ok = v.structural_passed && v.toolchain_passed;
    const {card, body} = makeCard("结构检查汇总" + (v.candidate_id ? " · " + v.candidate_id : ""), ok ? "passed" : v.code_failed ? "failed" : "unverified");
    const pills = make("div", "pill-list");
    pills.append(
      make("span", "badge " + (v.interface_verified ? "good" : "bad"), "接口：" + (v.interface_verified ? "通过" : "未通过")),
      make("span", "badge " + (v.structural_passed ? "good" : "bad"), "结构：" + (v.structural_passed ? "通过" : "未通过")),
      make("span", "badge " + (v.toolchain_passed ? "good" : "warn"), "工具链：" + (v.toolchain_passed ? "通过" : "未全部通过")),
    );
    if (Array.isArray(v.not_run) && v.not_run.length) {
      pills.append(make("span", "badge warn", "未运行：" + v.not_run.join("、")));
    }
    body.append(pills);
    return card;
  }

  function renderPlanCard(event) {
    const v = event.value || {};
    const methodText = v.method === "table" ? "独立检查表" : v.method || "未指定";
    const {card, body} = makeCard("验证策略与所选技能", null, make("span", "badge info", "方法：" + methodText));
    if (Array.isArray(v.skills) && v.skills.length) {
      const row = make("div", "pill-list");
      for (const sk of v.skills) row.append(make("span", "skill-pill", sk));
      body.append(row);
    }
    if (Array.isArray(v.focus) && v.focus.length) {
      const row = make("div", "pill-list");
      row.append(make("span", "kv-k", "关注点："));
      for (const f of v.focus) row.append(make("span", "skill-pill muted", f));
      body.append(row);
    }
    if (v.reason) body.append(make("p", "reason-box", v.reason));
    return card;
  }

  function renderCheckerTableCard(event) {
    const v = event.value || {};
    const {card, body} = makeCard("独立检查表", event.status || v.status,
      v.case_count != null ? make("span", "badge info", v.case_count + " 个测试点") : null);
    body.append(makeKvGrid([
      ["时钟", v.clock || "纯组合 / 无时钟"],
      ["覆盖输出", Array.isArray(v.checked_outputs) && v.checked_outputs.length ? v.checked_outputs.join(", ") : null],
      ["未覆盖输出", Array.isArray(v.unchecked_outputs) && v.unchecked_outputs.length ? v.unchecked_outputs.join(", ") : null],
    ]));
    if (v.ports && typeof v.ports === "object") {
      const pills = make("div", "pill-list");
      for (const [name, p] of Object.entries(v.ports)) {
        const dir = p?.direction === "input" ? "IN" : p?.direction === "output" ? "OUT" : "";
        const w = p?.width != null ? "[" + p.width + "b]" : "";
        pills.append(make("span", "skill-pill muted", (dir ? dir + " " : "") + name + w));
      }
      body.append(pills);
    }
    return card;
  }

  function renderBehaviorSummaryCard(event) {
    const v = event.value || {};
    const st = event.status || v.status;
    const {card, body} = makeCard("行为比对汇总" + (v.candidate_id ? " · " + v.candidate_id : ""), st);
    body.append(makeBitBar(v.compared_bits, v.unknown_bits, st));
    body.append(makeKvGrid([
      ["已检输出", Array.isArray(v.checked_outputs) && v.checked_outputs.length ? v.checked_outputs.join(", ") : null],
      ["未检输出", Array.isArray(v.unchecked_outputs) && v.unchecked_outputs.length ? v.unchecked_outputs.join(", ") : null],
      ["失败类型", v.failure_kind],
    ]));
    if (v.summary) body.append(make("p", "reason-box", v.summary));
    return card;
  }

  function renderPointComparisonCard(label, event) {
    const v = event.value || {};
    const st = event.status || v.status;
    const {card, body} = makeCard(label, st, v.candidate_id ? make("span", "badge", v.candidate_id) : null);
    if (v.explanation) body.append(make("p", "reason-box", v.explanation));
    if (v.compared_bits != null || v.unknown_bits != null) {
      body.append(makeBitBar(v.compared_bits, v.unknown_bits, st));
    }
    if (Array.isArray(v.comparisons) && v.comparisons.length) {
      const wrap = make("div", "cmp-wrap");
      const table = make("table", "cmp-table");
      const thead = make("thead");
      const hr = make("tr");
      for (const h of ["拍", "阶段", "信号", "期望值", "实测值", "结论"]) hr.append(make("th", "", h));
      thead.append(hr);
      const tbody = make("tbody");
      for (const row of v.comparisons) {
        const expObj = row.expected || {};
        const actObj = row.actual || {};
        for (const [sig, expVal] of Object.entries(expObj)) {
          const actFmt = formatActualSignal(actObj[sig]);
          const matched = !actFmt.hasX && String(expVal) === actFmt.text;
          const tr = make("tr", matched ? "match" : "mismatch");
          tr.append(
            make("td", "", String(row.step ?? "")),
            make("td", "", row.phase === "pre" ? "拍前" : "拍后"),
            make("td", "", sig),
            make("td", "", String(expVal)),
            make("td", "val-actual", actFmt.text),
            make("td", "", matched ? "✓ 一致" : "✗ 不一致"),
          );
          tbody.append(tr);
        }
      }
      table.append(thead, tbody);
      wrap.append(table);
      body.append(wrap);
    }
    return card;
  }

  function renderCandidateDiffCard(label, event) {
    const v = event.value || {};
    const changed = v.changed === true;
    const badge = v.changed != null ? make("span", "badge " + (changed ? "info" : "warn"), changed ? "代码已修改" : "代码无变化") : null;
    const {card, body} = makeCard(label, null, badge);
    const idFlow = v.parent_id && v.candidate_id ? v.parent_id + " → " + v.candidate_id : v.candidate_id;
    body.append(makeKvGrid([
      ["候选版本", idFlow],
      ["轮次", v.round != null ? "第 " + v.round + " 轮" : null],
      ["来源阶段", v.source_stage],
      ["代码大小", v.code_bytes != null ? v.code_bytes + " B" : null],
      ["提取状态", v.extraction_status],
    ]));
    if (v.added_lines != null || v.removed_lines != null) {
      const diff = make("div", "diff-badges");
      if (v.added_lines != null) diff.append(make("span", "diff-add", "+" + v.added_lines + " 行"));
      if (v.removed_lines != null) diff.append(make("span", "diff-del", "-" + v.removed_lines + " 行"));
      body.append(diff);
    }
    return card;
  }

  function renderDecisionCard(label, event) {
    const v = event.value || {};
    const act = v.review_action || v.action;
    const [actText, actTone] = actionLabels.get(act) || [act || "决定", "info"];
    const {card, body} = makeCard(label, null, make("span", "badge " + actTone, actText));
    body.append(makeKvGrid([
      ["轮次", v.round != null ? "第 " + v.round + " 轮" : null],
      ["候选", v.child_id ? (v.candidate_id + " → " + v.child_id) : v.candidate_id],
      ["测试点", v.case_id],
      ["结果", v.outcome],
    ]));
    const reason = v.review_reason || v.reason;
    if (reason) body.append(make("p", "reason-box", reason));
    return card;
  }

  function renderFinalVerificationCard(label, event) {
    const v = event.value || {};
    const {card, body} = makeCard(label, v.behavior_status || v.structure_status || (v.published ? "passed" : null),
      v.candidate_id || v.target_id ? make("span", "badge info", v.target_id || v.candidate_id) : null);
    const pills = make("div", "pill-list");
    if (v.interface_verified != null) pills.append(make("span", "badge " + (v.interface_verified ? "good" : "bad"), "接口：" + (v.interface_verified ? "通过" : "未通过")));
    if (v.structural_passed != null) pills.append(make("span", "badge " + (v.structural_passed ? "good" : "bad"), "结构：" + (v.structural_passed ? "通过" : "未通过")));
    if (v.toolchain_passed != null) pills.append(make("span", "badge " + (v.toolchain_passed ? "good" : "warn"), "工具链：" + (v.toolchain_passed ? "通过" : "未全过")));
    if (v.behavior_status) pills.append(make("span", "badge " + statusTone(v.behavior_status), "行为：" + zhStatus(v.behavior_status)));
    if (v.submitted_with_mismatch) pills.append(make("span", "badge warn", "带分歧提交"));
    if (pills.children.length) body.append(pills);
    body.append(makeKvGrid([
      ["交付方式", v.submission_mode || v.mode || v.delivery],
      ["比对位数", v.compared_bits != null ? v.compared_bits + " bit" : null],
      ["修正期望", v.expectations_revised],
      ["撤回测试点", v.withdrawn_cases],
    ]));
    if (v.reason) body.append(make("p", "reason-box", v.reason));
    return card;
  }

  function renderDetailCard(record) {
    const event = record.event;
    const label = String(event.label || "执行记录");
    const v = event.value;

    // 候选 RTL 源码
    if (event.kind === "code" && typeof v === "string") {
      const codeKey = "rtl:" + record.index;
      const details = make("details", "ctx-block");
      details.open = openState.has(codeKey) ? openState.get(codeKey) : false;
      details.addEventListener("toggle", () => { openState.set(codeKey, details.open); });
      const sum = make("summary");
      const left = make("span", "ctx-summary-left");
      left.append(make("span", "ctx-chevron", "▶"), make("strong", "", label), make("span", "badge good", "RTL 源码"));
      sum.append(left, make("span", "ctx-stats", v.split("\n").length + " 行 · " + v.length + " 字符"));
      details.append(sum, renderCodeCard(v, "verilog", label));
      return details;
    }

    if (label.startsWith("接口检查 · ") || label.startsWith("编译与展开 · ") || label.startsWith("综合 · ")) {
      return renderStructureCheckCard(label, event);
    }
    if (label === "结构检查汇总") return renderStructureSummaryCard(event);
    if (label === "验证策略与所选技能") return renderPlanCard(event);
    if (label === "独立检查表") return renderCheckerTableCard(event);
    if (label === "行为比对汇总") return renderBehaviorSummaryCard(event);
    if (label.startsWith("测试点比对 · ")) return renderPointComparisonCard(label, event);
    if (label.startsWith("测试点 · ")) {
      const d = v || {};
      const {card, body} = makeCard(label, null, d.steps ? make("span", "badge info", d.steps.length + " 拍激励") : null);
      if (d.explanation) body.append(make("p", "reason-box", d.explanation));
      if (d.expected && typeof d.expected === "object") {
        const pills = make("div", "pill-list");
        for (const [st, vals] of Object.entries(d.expected)) {
          const desc = Object.entries(vals || {}).map(([k, val]) => k + "=" + val).join(", ");
          pills.append(make("span", "skill-pill muted", "第 " + st + " 拍: " + desc));
        }
        body.append(pills);
      }
      return card;
    }
    if (label === "父子候选差异" || label === "候选身份" || label === "RTL 提取" || label === "已选候选") {
      return renderCandidateDiffCard(label, event);
    }
    if (label === "作者决定" || label === "检查员复核决定") {
      return renderDecisionCard(label, event);
    }
    if (label === "交付候选的验证结果" || label === "提交决定" || label === "最终交付") {
      return renderFinalVerificationCard(label, event);
    }
    if (label === "检查表适用性" || label === "选用的技能" || label === "本次请求采用的技能") {
      const d = v || {};
      const {card, body} = makeCard(label, d.table_supported === false ? "warn" : null);
      const sent = d.sent || d.selected || [];
      if (Array.isArray(sent) && sent.length) {
        const pills = make("div", "pill-list");
        for (const s of sent) pills.append(make("span", "skill-pill", s));
        body.append(pills);
      }
      if (d.reason) body.append(make("p", "reason-box", d.reason));
      return card;
    }
    if (label === "工具调用" || label === "仿真采样" || label === "采样结果" || label.startsWith("工具结果 · ") ||
        label === "请求未取得结果" || label === "阶段结果" || label === "运行错误" || label === "模型调用") {
      const d = v && typeof v === "object" ? v : {};
      const row = make("div", "compact-row");
      const left = make("div", "ctx-summary-left");
      left.append(make("strong", "", label));
      if (d.name) left.append(make("span", "mono", d.name));
      if (d.candidate_id) left.append(make("span", "badge", d.candidate_id));
      if (d.sample_rows != null) left.append(make("span", "mono", d.sample_rows + " 行采样"));
      if (d.summary || d.reason || d.error_kind || d.error_type) {
        left.append(make("span", "dialog-muted", String(d.summary || d.reason || d.error_kind || d.error_type)));
      }
      const right = make("div", "ctx-summary-left");
      if (d.elapsed_s != null) right.append(make("span", "mono ctx-stats", duration(d.elapsed_s)));
      if (event.status) right.append(make("span", "badge " + statusTone(event.status), zhStatus(event.status)));
      row.append(left, right);
      return row;
    }

    // 兜底：极少数未识别记录提供折叠原始字段查看
    const fb = make("details", "fallback-details");
    const sum = make("summary");
    sum.append(make("span", "", label), make("span", "badge", event.status ? zhStatus(event.status) : "原始记录"));
    fb.append(sum, make("pre", "fallback-pre", printable(v)));
    return fb;
  }

  /* ================= 右侧详情面板渲染 ================= */
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

  function renderStepBanner(step) {
    const banner = $("step-info");
    if (!step) {
      banner.hidden = scope !== "all" && scope !== "global";
      if (!banner.hidden) {
        banner.replaceChildren(make("span", "dialog-muted",
          scope === "all" ? "按时间顺序展示本次运行的全部思考与验证流。" : "显示运行级及未关联到具体步骤的记录。"));
      }
      return;
    }
    banner.hidden = false;
    const left = make("div", "step-banner-left");
    const rk = roleKey(step.role);
    if (step.role) {
      const rc = make("span", "role-chip", step.role);
      rc.dataset.role = rk;
      left.append(rc);
    }
    left.append(make("strong", "", seqName(step) + " " + step.label));
    const [st, stText] = executionState(step);
    const stTone = st === "finished" ? "good" : st === "failed" ? "bad" : st === "current" ? "info" : "warn";
    left.append(make("span", "badge " + stTone, stText));
    if (step.visit > 1) left.append(make("span", "badge", "第 " + step.visit + " 次"));

    const right = make("div", "step-banner-right");
    const tEl = make("span", "", stepElapsedText(step));
    tEl.dataset.bannerTimer = step.id;
    const prev = model.byId.get(step.previous);
    if (prev) right.append(make("span", "", "前序 " + seqName(prev)));
    if (step.ts != null) right.append(make("span", "", clock(step.ts)));
    right.append(tEl);
    banner.replaceChildren(left, right);
  }

  function matchesQuery(item, query) {
    if (!query) return true;
    if (item.type === "call") {
      const c = model.calls.get(item.callKey);
      if (!c) return false;
      const hay = [zhPurpose(c.purpose), c.purpose, c.response?.reasoning_content, c.response?.reasoning, c.response?.content]
        .filter(Boolean).join("\n").toLocaleLowerCase();
      return hay.includes(query);
    }
    const label = String(item.event.label || "").toLocaleLowerCase();
    if (label.includes(query)) return true;
    return printable(item.event.value).toLocaleLowerCase().includes(query);
  }

  function renderRecords() {
    const select = $("scope");
    const sig = [runEpoch, model.steps.length, model.stream.length].join("/");
    if (sig !== scopeSignature) {
      scopeSignature = sig;
      const options = [
        new Option("跟随最新步骤", "latest"),
        new Option("全部步骤流 (" + model.stream.length + ")", "all"),
        new Option("运行级及未关联记录", "global"),
      ];
      for (const step of model.steps) {
        options.push(new Option(seqName(step) + " " + step.label + (step.role ? " · " + step.role : ""), "step:" + step.id));
      }
      select.replaceChildren(...options);
    }
    select.value = scope;

    const step = selectedStep();
    renderStepBanner(step);

    const query = $("record-search").value.trim().toLocaleLowerCase();
    let items = model.stream;
    if (scope === "global") items = items.filter((it) => !model.byId.has(it.id));
    else if (scope !== "all") items = step ? items.filter((it) => it.id === step.id) : [];
    if (query) items = items.filter((it) => matchesQuery(it, query));

    const callVersions = items.filter((it) => it.type === "call").map((it) => {
      const c = model.calls.get(it.callKey);
      return c ? [c.key, Boolean(c.context), Boolean(c.response), c.meta?.status, c.meta?.elapsed_s].join(":") : "";
    }).join("|");
    const signature = [runEpoch, scope, step?.id, query, items.length, items.at(-1)?.order, callVersions].join("/");

    if (recordSignature !== signature) {
      recordSignature = signature;
      const list = $("record-list");
      const frag = document.createDocumentFragment();
      for (const item of items) {
        if (item.type === "call") {
          const entry = model.calls.get(item.callKey);
          if (entry) frag.append(renderCallCard(entry));
        } else {
          frag.append(renderDetailCard(item));
        }
      }
      list.replaceChildren(frag);
    }

    $("records-empty").hidden = items.length > 0;
    updateText($("records-empty"), query ? "没有匹配的思考或验证记录。"
      : selectedRun()?.status === "running" && step ? "该步骤正在执行中，等待模型思考或工具返回…"
      : "当前所选范围暂无思考或验证记录。");
  }

  function renderSummary() {
    const target = $("panel-summary"), end = model.end, item = selectedRun();
    if (!item) { target.replaceChildren(make("p", "empty-text", "选择题目后可查看运行摘要。")); return; }
    const values = [
      ["运行标识", jobId],
      ["任务来源", sourceName(item.source)],
      ["服务状态", statusName(item.status)],
      ["工作流", model.plan?.workflow],
      ["收题时间", stamp(item.submitted)],
      ["开始时间", stamp(item.started)],
      ["结束时间", stamp(item.finished)],
      ["求解状态", end?.status ? zhStatus(end.status) : null],
      ["停止原因", end?.stop_reason],
      ["交付方式", end?.submission_mode],
      ["交付版本", end?.candidate_id],
      ["求解用时", duration(end?.elapsed_s)],
      ["模型调用", end?.calls ?? model.calls.size],
      ["输入 Token", end?.tokens_in],
      ["输出 Token", end?.tokens_out],
    ];
    const grid = make("dl", "summary-grid");
    for (const [label, val] of values) {
      const tile = make("div", "summary-tile");
      tile.append(make("dt", "", label), make("dd", "mono", val == null || val === "" ? "未报告" : String(val)));
      grid.append(tile);
    }
    target.replaceChildren(grid);
    if (model.unsupported) {
      target.append(make("p", "notice-bar", "有 " + model.unsupported + " 条事件无法按当前格式展示。"));
    }
  }

  function renderInspector() {
    if (tab === "records") { renderRecords(); return; }
    if (tab === "summary") { renderSummary(); return; }
    const isPrompt = tab === "prompt", target = $("panel-" + tab);
    const value = isPrompt ? run?.prompt : run?.solution;
    const hasValue = typeof value === "string" && value.length > 0;
    if (hasValue) {
      if (target.dataset.renderedValue === value) return;
      target.dataset.renderedValue = value;
      if (isPrompt) {
        const card = make("div", "prompt-card");
        const head = make("div", "prompt-head");
        const btn = make("button", "copy-btn", "复制题面");
        btn.type = "button";
        btn.addEventListener("click", () => copyText(value, btn));
        head.append(make("strong", "", "公开题面"), btn);
        card.append(head, make("pre", "prompt-body", value));
        target.replaceChildren(card);
      } else {
        target.replaceChildren(renderCodeCard(value, "verilog", "solution.v"));
      }
    } else {
      delete target.dataset.renderedValue;
      const empty = isPrompt ? "尚未收到这道题的公开题面。" : selectedRun()?.status === "done"
        ? "本次运行未交付源码。" : "运行结束后可查看最终交付的 RTL 源码。";
      target.replaceChildren(make("p", "empty-text", empty));
    }
  }

  /* 实时计时器刷新（每 500ms 更新总耗时与运行中节点计时） */
  setInterval(() => {
    const item = selectedRun();
    if (!item || item.status === "done") return;
    updateText($("hud-elapsed"), runElapsedText());
    for (const el of document.querySelectorAll("[data-step-timer]")) {
      const step = model.byId.get(el.dataset.stepTimer);
      if (step && executionState(step)[0] === "current") {
        updateText(el, stepElapsedText(step));
      }
    }
    const bt = document.querySelector("[data-banner-timer]");
    if (bt) {
      const step = model.byId.get(bt.dataset.bannerTimer);
      if (step && executionState(step)[0] === "current") updateText(bt, stepElapsedText(step));
    }
  }, 500);

  /* ================= 演示者选题弹窗 ================= */
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
      const data = await request("/ui/api/runs", {
        method: "POST",
        headers: {"Content-Type": "application/json", Authorization: "Bearer " + token},
        body: JSON.stringify({task_id: task}),
      });
      follow = true;
      if (data?.job_id) selectRun(data.job_id);
      remember();
      renderQueue();
      if (epoch === dialogEpoch && $("presenter").open) $("presenter").close();
      refreshBoard();
    } catch (error) {
      if (epoch === dialogEpoch && $("presenter").open) {
        const reasons = new Map([
          [401, "演示口令未通过，请重新输入。"],
          [403, "当前服务禁止启动本地演示。"],
          [409, "已有任务在处理，请等待队列空闲后再启动。"],
          [503, "本地演示暂不可用，请检查服务状态。"],
          [404, "所选题目已不可用，请重新选择。"],
        ]);
        setLaunchNote(reasons.get(error.status) || "未能确认启动结果，请先在题目队列核对。", true);
      }
      refreshBoard();
    } finally { launching = false; syncLaunch(); }
  }

  /* ================= 事件绑定 ================= */
  $("toggle-queue").addEventListener("click", () => {
    queueCollapsed = !queueCollapsed;
    applyQueueDrawer();
    remember();
    requestAnimationFrame(() => drawGraph({locate: view === "trace" && scope === "latest"}));
  });

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
    changeZoom(Math.min(1, (v.clientWidth - 4) / currentScene.w, (v.clientHeight - 4) / currentScene.h), true);
  });
  $("zoom-in").addEventListener("click", () => changeZoom(Math.min(2.5, zoom[view] * 1.25)));
  $("zoom-out").addEventListener("click", () => changeZoom(Math.max(0.15, zoom[view] / 1.25)));
  $("zoom-reset").addEventListener("click", () => changeZoom(1));
  $("scope").addEventListener("change", (event) => chooseScope(event.target.value));
  $("record-search").addEventListener("input", renderRecords);

  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((button, i) => {
    const name = button.id.slice(4);
    button.addEventListener("click", () => setTab(name));
    button.addEventListener("keydown", (event) => {
      const next = {
        ArrowLeft: (i + tabs.length - 1) % tabs.length,
        ArrowRight: (i + 1) % tabs.length,
        Home: 0, End: tabs.length - 1,
      }[event.key];
      if (typeof next !== "number") return;
      event.preventDefault();
      setTab(tabs[next].id.slice(4), true);
    });
  });

  let resizeFrame = null;
  window.addEventListener("resize", () => {
    if (resizeFrame !== null) return;
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = null;
      drawGraph({locate: view === "trace" && scope === "latest"});
    });
  });
  window.addEventListener("online", refreshBoard);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshBoard(); });

  setupCanvasPan();
  applyQueueDrawer();
  renderQueue();
  drawGraph();
  renderInspector();
  refreshBoard();
})();
