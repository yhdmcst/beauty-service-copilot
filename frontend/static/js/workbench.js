const $ = (id) => document.getElementById(id);
const STATUS = { pending: "待处理", in_progress: "处理中", resolved: "已完成", cancelled: "已取消" };
const DECISION = { accepted: "采纳", edited: "修改后采纳", rejected: "拒绝" };
const EMOTION_SCENES = {
  allergy_anxiety: "不适相关担忧", price_dissatisfaction: "价格不满",
  effect_disappointment: "效果失望", purchase_hesitation: "购买犹豫", satisfaction: "满意",
};
let sessions = [], currentSession = null, currentSessionData = null, latestAssist = null;
let viewVersion = 0, pendingTask = null, requestedVersion = null;
let pendingIdentity = null;

function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}
async function api(path, method = "GET", payload) {
  const response = await fetch(path, {
    method, headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
async function waitForAnalysis(job, version, savedRiskCount) {
  const deadline = Date.now() + 240000;
  const names = { queued: "排队中", running: "模型处理中" };
  while (Date.now() < deadline) {
    if (version !== viewVersion) return null;
    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error("分析失败，风险任务仍保留，可重试");
    $("request-status").textContent = `${names[job.status] || "处理中"}${savedRiskCount ? ` · ${savedRiskCount}项风险已保存` : ""}`;
    await new Promise((resolve) => setTimeout(resolve, 700));
    if (version !== viewVersion) return null;
    const status = await api(`/api/assist-jobs/${job.job_id}`);
    job = status.job;
  }
  throw new Error("等待超时，请查看已有风险任务或稍后重试");
}
function resetAssist() {
  latestAssist = null;
  $("summary").textContent = "等待分析";
  $("draft").textContent = "等待生成建议";
  $("emotion").textContent = $("risk").textContent = $("next-action").textContent = "—";
  $("model-badge").textContent = "待分析";
  $("review-editor").hidden = true;
  $("use-draft").disabled = $("create-task").disabled = true;
  $("missing-info").replaceChildren();
  $("communication-strategy").textContent = "尚未分析";
  $("communication-needs").replaceChildren();
  $("stated-preferences").replaceChildren();
  $("communication-basis").replaceChildren();
  $("provided-information").replaceChildren();
  $("trace").replaceChildren();
  $("analysis-record-id").textContent = "";
  $("review-status").textContent = "";
  $("risk-reasons").replaceChildren();
  $("emotion-change").textContent = "尚未分析";
  $("claim-checks").replaceChildren();
  $("knowledge-gate").textContent = "尚未检索";
  $("knowledge-results").replaceChildren();
}
function renderSessions() {
  const query = $("session-search").value.trim().toLowerCase();
  $("session-list").replaceChildren();
  sessions.filter((item) => `${item.session_id} ${item.buyer_name} ${item.scene_minor} ${item.latest_message}`.toLowerCase().includes(query))
    .forEach((item) => {
      const button = node("button", "", `session-item ${currentSession === item.session_id ? "active" : ""}`);
      button.type = "button";
      const row = node("div", "", "session-row");
      row.append(node("strong", item.buyer_name, "session-name"), node("span", item.latest_time.slice(5, 16), "session-time"));
      const tags = node("div", "", "session-tags");
      [item.scene_minor, item.has_order ? "订单" : "", item.has_ticket ? "工单" : ""]
        .filter(Boolean).forEach((label) => tags.append(node("span", label, "tag")));
      button.append(row, node("p", item.latest_message, "session-preview"), tags);
      button.onclick = () => loadSession(item.session_id);
      $("session-list").append(button);
    });
}
function renderEvidence(items) {
  $("evidence").replaceChildren();
  items.forEach((item) => {
    const row = node("div", "", "evidence");
    row.append(node("strong", `${item.label} · ${item.id}`), node("span", item.summary));
    const details = node("details");
    details.append(node("summary", "查看字段"));
    const fields = node("dl");
    Object.entries(item.fields || {}).forEach(([key, value]) => fields.append(node("dt", key), node("dd", value)));
    details.append(fields);
    row.append(details);
    $("evidence").append(row);
  });
  if (!items.length) $("evidence").append(node("p", "该时点无关联业务证据", "muted"));
}
function renderConversation(data) {
  $("buyer-name").textContent = `${data.buyer_name} · ${data.scene_minor || data.scene_major}`;
  $("session-meta").textContent = `${data.session_id} · ${data.analysis_at}`;
  $("basis-warning").textContent = data.basis_warning;
  $("conversation").replaceChildren();
  data.messages.forEach((item) => {
    const row = node("article", "", `message ${item["角色"] === "买家" ? "buyer" : "agent"}`);
    row.append(node("div", `${item["角色"]} · ${item["发送时间"]}`, "message-meta"),
      node("div", item["内容类型"] === "图片" ? `${item.message_text} [附件文件未提供]` : item.message_text, "message-body"));
    $("conversation").append(row);
  });
  $("message-input").value = data.latest_buyer_message;
  $("timeline").replaceChildren();
  data.timeline.forEach((item) => $("timeline").append(node(
    "div", `${item.time} · ${item.label} · ${item.detail}`, "timeline-event")));
  $("analysis-point").replaceChildren();
  data.message_choices.forEach((item) => {
    const option = node("option", `${item.time.slice(5)} · ${item.text}`);
    option.value = item.id;
    $("analysis-point").append(option);
  });
  $("analysis-point").value = data.analysis_point;
  $("analysis-mode").value = data.analysis_mode;
  $("conversation").scrollTop = $("conversation").scrollHeight;
  renderEvidence(data.evidence);
  renderServiceHistory(data.service_history);
}
function renderServiceHistory(history) {
  if (!history) return;
  const confirmed = history.identity_basis !== "unconfirmed";
  $("identity-basis").textContent = confirmed ? "已人工确认的演示关联" : "身份未确认，不自动合并脱敏同名";
  $("service-counts").textContent = `7天内 ${history.contacts_7d.length} 个不同会话 · 30天内 ${history.refund_records_30d.length} 张退款相关工单（不等于已退款次数）`;
  $("identity-sessions").replaceChildren();
  if (confirmed) history.confirmed_session_ids.forEach((id) => {
    const link = node("a", id);
    link.href = `/workbench?session=${encodeURIComponent(id)}`;
    $("identity-sessions").append(link);
  });
  $("identity-candidates").replaceChildren();
  history.candidate_sessions.forEach((candidate) => {
    const row = node("div", "", "identity-row");
    row.append(node("p", `${candidate.session_id} · ${candidate.first_contact_at} · 脱敏同名候选`));
    const button = node("button", "核实并确认关联", "secondary-btn");
    button.onclick = () => {
      pendingIdentity = { session: currentSession, peer: candidate.session_id, version: viewVersion };
      $("identity-target").textContent = `${currentSession} 与 ${candidate.session_id}`;
      $("identity-reason").value = "";
      $("identity-error").textContent = "";
      $("identity-dialog").showModal();
    };
    row.append(button);
    $("identity-candidates").append(row);
  });
}
async function loadSession(id, point) {
  const version = ++viewVersion;
  currentSession = id;
  requestedVersion = null;
  resetAssist();
  renderSessions();
  $("assist-btn").disabled = true;
  $("request-status").textContent = "载入会话";
  $("tasks").replaceChildren();
  $("reviews").replaceChildren();
  const params = new URLSearchParams({ mode: $("analysis-mode").value });
  if (point) params.set("before_message_id", point);
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(id)}?${params}`);
    if (version !== viewVersion) return;
    currentSessionData = data;
    renderConversation(data);
    $("request-status").textContent = "";
    $("assist-btn").disabled = false;
    await Promise.all([loadTasks(version), loadReviews(version)]);
  } catch (error) {
    if (version === viewVersion) $("request-status").textContent = error.message;
  }
}
function renderAssist(result) {
  latestAssist = result;
  $("summary").textContent = result.summary;
  const scene = EMOTION_SCENES[result.special_emotion];
  $("emotion").textContent = scene ? `${result.emotion} · ${scene}` : result.emotion;
  $("risk").textContent = result.risk_level;
  $("draft").textContent = result.suggested_reply;
  $("next-action").textContent = result.next_action;
  $("model-badge").textContent = result.model_status === "rule_safety" ? "即时安全建议" :
    result.model_status === "rule_evidence" ? "证据规则建议" :
    result.model_status === "fallback" ? "降级待复核" : result.cache_hit ? "缓存草稿" : "模型草稿";
  $("missing-info").replaceChildren(...result.missing_info.map((text) => node("li", text)));
  const brief = result.communication_brief || {};
  $("communication-strategy").textContent = brief.strategy || "结合当前问题核查后回复";
  $("communication-needs").replaceChildren(...(brief.needs || []).map((item) => node(
    "li", `${item.label}：${item.action}`)));
  $("stated-preferences").replaceChildren(...(brief.stated_preferences || []).map((item) => node(
    "p", `${item.label}：${item.value}（自述，非适配结论）`, "muted")));
  const citedBrief = [...(brief.needs || []), ...(brief.stated_preferences || [])];
  $("communication-basis").replaceChildren(...citedBrief.map((item) => node(
    "li", `${item.basis.message_id || "当前输入"}：${item.basis.quote}`)));
  (brief.human_review_reasons || []).forEach((reason) => $("communication-basis").append(node("li", reason)));
  const materialStatus = {
    buyer_reported_upload_unverified: "买家自述，先核是否收到及可用",
    asset_not_provided: "仅有图片消息记录，附件文件未提供",
    asset_available: "附件可用，内容仍需核查",
    buyer_reported_not_product_approval: "自述，非商品适配结论",
    structured_record: "已有字段，按当前业务时点核查",
    current_report_conflicts_with_prior_upload: "本次说明与此前自述冲突，先核材料情况",
  };
  $("provided-information").replaceChildren(...(brief.provided_information || []).map((item) => node(
    "li", `${item.label}：${item.value}；${materialStatus[item.status] || "待核"}；依据 ${item.basis.message_id || "当前输入"} ${item.basis.quote}`)));
  if (!(brief.provided_information || []).length) $("provided-information").append(node("li", "暂无可复用资料"));
  $("trace").replaceChildren(...result.trace.map((step) => node("li", `${step.node} · ${step.duration_ms} ms`)));
  $("analysis-record-id").textContent = `分析记录 ${result.analysis_id}`;
  $("use-draft").disabled = $("create-task").disabled = false;
  $("review-editor").hidden = true;
  renderServiceHistory(result.service_history);
  const trend = result.emotion_trend;
  $("emotion-change").textContent = `${trend.trend} · 当前倾向 ${trend.current_valence.toFixed(2)} · 历史 ${trend.history.length} 条（规则辅助，待人工复核）`;
  $("risk-reasons").replaceChildren(...result.rule_alerts.map((alert) => {
    const sources = alert.source_session_ids || alert.source_ticket_ids || alert.source_message_ids || [];
    return node("li", `${alert.name}：${alert.action}${sources.length ? `；依据 ${sources.join("、")}` : ""}`);
  }));
  const claimStates = {
    supported: "有字段依据", not_asserted: "未作事实断言",
    reported_claim: "买家自述，未作后台确认", planned_action: "建议动作，尚未执行",
  };
  $("claim-checks").replaceChildren(...(result.final_claim_checks || result.claim_checks || []).map((item) => node(
    "li", `${item.claim} · ${claimStates[item.status] || "缺少字段依据"} · ${item.bindings.map((binding) => `${binding.evidence_id}${binding.field ? ` ${binding.field}` : ""}`).join("、")}`)));
  const adjustedFields = { summary: "摘要", suggested_reply: "回复", next_action: "下一步", missing_info: "待核事项", emotion: "情绪" };
  (result.quality_adjustments || []).forEach((item) => {
    $("claim-checks").append(node("li", `${adjustedFields[item.field] || "草稿"}修正：${item.before} → ${item.after}`));
  });
  const knowledge = result.knowledge || {};
  $("knowledge-gate").textContent =
    `${knowledge.reason || "未检索"} · ${knowledge.can_auto_reply ? "可作为辅助依据" : "不可直接作为事实"} · 置信启发分 ${knowledge.confidence ?? 0}`;
  $("knowledge-results").replaceChildren(...(knowledge.retrieved_docs || []).map((doc) => {
    const row = node("div", "", "evidence");
    row.append(
      node("strong", `${doc.title || "知识记录"} · ${doc.verified ? "已审核" : "未审核"}`),
      node("span", `${doc.source || "未知来源"}${doc.approved_product_claim ? " · 产品声明已批准" : ""}`),
    );
    return row;
  }));
  $("request-status").textContent = (result.final_validation_flags || []).length ?
    "最终草稿仍有待核实事项" : result.quality_adjustments?.length ?
    `已修正 ${result.quality_adjustments.length} 处 · 待人工审核` :
    result.validation_flags.length ? "草稿有待复核事项" : `${result.latency_ms} ms`;
}
async function loadTasks(version = viewVersion) {
  const data = await api(`/api/tasks?session_id=${encodeURIComponent(currentSession)}`);
  if (version !== viewVersion) return;
  $("tasks").replaceChildren();
  data.tasks.forEach((task) => {
    const row = node("article", "", "task");
    row.append(node("strong", `${task.task_type} · ${STATUS[task.status]}`),
      node("span", `负责人：${task.owner || "未分配"}`), node("span", task.note));
    const actions = node("div", "", "task-actions");
    const options = task.status === "pending" ? [["认领", "in_progress"], ["取消任务", "cancelled"]] :
      task.status === "in_progress" ? [["完成任务", "resolved"], ["取消任务", "cancelled"]] : [];
    options.forEach(([label, status]) => {
      const button = node("button", label);
      button.onclick = () => {
        pendingTask = { task, status, version };
        $("task-dialog-title").textContent = label;
        $("task-owner").value = task.owner || $("reviewer").value;
        $("task-note").value = "";
        $("task-note").required = status === "resolved" || status === "cancelled";
        $("task-error").textContent = "";
        $("task-dialog").showModal();
      };
      actions.append(button);
    });
    const history = node("details");
    history.append(node("summary", `操作历史 (${task.history.length})`));
    task.history.forEach((event) => history.append(node(
      "div", `${STATUS[event.action] || "创建"} · ${event.actor} · ${event.time.slice(0, 19)} · ${event.note}`, "task-history")));
    row.append(actions, history);
    $("tasks").append(row);
  });
  if (!data.tasks.length) $("tasks").append(node("p", "暂无任务", "muted"));
}
async function loadReviews(version = viewVersion) {
  const data = await api(`/api/sessions/${encodeURIComponent(currentSession)}/analyses`);
  if (version !== viewVersion) return;
  $("reviews").replaceChildren(...data.feedback.map((item) => node(
    "div", `${DECISION[item.decision]} · ${item.reviewer} · ${item.edited_reply || item.reason}`, "review-entry")));
}
async function loadSessions() {
  try {
    const data = await api("/api/sessions");
    sessions = data.sessions;
    $("session-count").textContent = `${sessions.length} 个虚构会话`;
    renderSessions();
    if (!currentSession && sessions.length) {
      const requested = new URLSearchParams(location.search).get("session");
      await loadSession(sessions.find((item) => item.session_id === requested)?.session_id || sessions[0].session_id);
    }
  } catch (error) { $("request-status").textContent = error.message; }
}
$("assist-btn").onclick = async () => {
  if (!currentSessionData) return;
  const version = viewVersion;
  requestedVersion = version;
  const id = currentSession;
  resetAssist();
  $("assist-btn").disabled = true;
  $("model-badge").textContent = "分析中";
  $("request-status").textContent = "生成建议中";
  try {
    const submitted = await api(`/api/sessions/${encodeURIComponent(id)}/assist-jobs`, "POST", {
      message: $("message-input").value,
      before_message_id: currentSessionData.analysis_point,
      mode: $("analysis-mode").value,
    });
    const result = await waitForAnalysis(submitted.job, version, submitted.task_ids.length);
    if (version !== viewVersion) return;
    if (!result) return;
    renderAssist(result);
    await loadTasks(version);
  } catch (error) {
    if (version === viewVersion) { $("model-badge").textContent = "请求失败"; $("request-status").textContent = error.message; }
  } finally { if (version === viewVersion) { $("assist-btn").disabled = false; requestedVersion = null; } }
};
$("use-draft").onclick = () => {
  if (!latestAssist) return;
  $("review-editor").hidden = false;
  $("reply-editor").value = latestAssist.suggested_reply;
  $("review-reason").value = "";
  $("approve-reply").disabled = $("reject-reply").disabled = false;
  $("reply-editor").focus();
};
async function review(decision) {
  if (!latestAssist) return;
  const version = viewVersion;
  const reply = $("reply-editor").value;
  if (decision !== "rejected") decision = reply.trim() === latestAssist.suggested_reply.trim() ? "accepted" : "edited";
  $("approve-reply").disabled = $("reject-reply").disabled = true;
  try {
    await api(`/api/analyses/${latestAssist.analysis_id}/review`, "POST", {
      decision, edited_reply: reply, reason: $("review-reason").value, reviewer: $("reviewer").value,
    });
    if (version !== viewVersion) return;
    $("review-status").textContent = "已保存审核记录，未向客户发送消息";
    $("use-draft").disabled = true;
    await loadReviews(version);
  } catch (error) {
    if (version !== viewVersion) return;
    $("review-status").textContent = error.message;
    $("approve-reply").disabled = $("reject-reply").disabled = false;
  }
}
$("approve-reply").onclick = () => review("accepted");
$("reject-reply").onclick = () => review("rejected");
$("create-task").onclick = async () => {
  if (!latestAssist) return;
  const version = viewVersion;
  $("create-task").disabled = true;
  try {
    await api("/api/tasks", "POST", {
      session_id: currentSession, analysis_id: latestAssist.analysis_id,
      task_type: latestAssist.next_action, note: latestAssist.summary,
      actor: $("reviewer").value,
    });
    await loadTasks(version);
  } catch (error) { if (version === viewVersion) $("request-status").textContent = error.message; }
  finally { if (version === viewVersion) $("create-task").disabled = false; }
};
$("task-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!pendingTask) return;
  $("task-submit").disabled = true;
  try {
    await api(`/api/tasks/${pendingTask.task.task_id}`, "PATCH", {
      status: pendingTask.status, owner: $("task-owner").value,
      actor: $("task-owner").value, note: $("task-note").value,
    });
    const version = pendingTask.version;
    $("task-dialog").close();
    await loadTasks(version);
  } catch (error) { $("task-error").textContent = error.message; }
  finally { $("task-submit").disabled = false; }
};
$("task-cancel").onclick = () => $("task-dialog").close();
$("identity-cancel").onclick = () => $("identity-dialog").close();
$("identity-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!pendingIdentity || pendingIdentity.version !== viewVersion) {
    $("identity-error").textContent = "会话已切换，请关闭后重新选择";
    return;
  }
  $("identity-submit").disabled = true;
  try {
    await api(`/api/sessions/${encodeURIComponent(pendingIdentity.session)}/link`, "POST", {
      other_session_id: pendingIdentity.peer,
      reviewer: $("identity-reviewer").value, reason: $("identity-reason").value,
    });
    const id = pendingIdentity.session;
    const point = currentSessionData.analysis_point;
    $("identity-dialog").close();
    if (pendingIdentity.version === viewVersion) await loadSession(id, point);
  } catch (error) {
    $("identity-error").textContent = error.message;
  } finally {
    $("identity-submit").disabled = false;
  }
};
$("analysis-point").onchange = () => loadSession(currentSession, $("analysis-point").value);
$("analysis-mode").onchange = () => loadSession(currentSession, $("analysis-point").value);
$("session-search").oninput = renderSessions;
$("refresh-sessions").onclick = loadSessions;
if (window.io) {
  const socket = io();
  socket.on("assist_update", (event) => {
    if (event.session_id === currentSession) {
      loadTasks().catch(() => {});
      if (event.phase === "safety" && requestedVersion === viewVersion)
        $("request-status").textContent = "风险已登记，继续生成草稿";
    }
  });
}
loadSessions();
