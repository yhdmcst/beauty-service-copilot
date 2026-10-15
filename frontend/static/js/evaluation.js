const $ = (id) => document.getElementById(id);
const INTENTS = {
  ingredient_query: "成分咨询", skin_type_match: "肤质适配", usage_method: "使用方法",
  authenticity_check: "真假鉴别", effect_inquiry: "效果咨询", allergy_concern: "担心过敏",
  product_comparison: "商品对比", order_query: "订单查询", logistics_query: "物流查询",
  refund_request: "退款退货", quality_issue: "质量问题", allergy_reaction: "使用后不适",
  coupon_query: "优惠券", activity_inquiry: "活动", invoice_request: "发票",
  general_consultation: "问候或一般咨询", unknown: "无法判断",
};
const EMOTIONS = {
  allergy_anxiety: "不适焦虑", effect_disappointment: "效果失望",
  price_dissatisfaction: "价格不满", purchase_hesitation: "购买犹豫",
  satisfaction: "满意", neutral: "中性", angry: "生气", sad: "难过",
  fearful: "担忧", happy: "高兴", 待人工确认: "无法判断",
};
let selectedSample = null, version = 0, activeTrial = null;

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
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function fillSelect(id, values) {
  const blank = node("option", "请选择");
  blank.value = "";
  $(id).replaceChildren(blank, ...Object.entries(values).map(([key, label]) => {
    const option = node("option", label); option.value = key; return option;
  }));
}
function evidenceNode(item) {
  const row = node("div", "", "ev-evidence-item");
  row.append(node("strong", `${item.label || item.type} · ${item.id}`));
  Object.entries(item.fields || {}).forEach(([key, value]) => row.append(
    node("p", `${key}：${value}`)));
  return row;
}
function contextNodes(context) {
  const messages = node("section"), evidence = node("section");
  messages.append(node("h3", "消息"));
  (context.messages || []).forEach((item) => {
    const row = node("div", "", "ev-message");
    row.append(node("small", item.role || "消息"), node("p", item.text || ""));
    messages.append(row);
  });
  evidence.append(node("h3", "业务字段"));
  (context.evidence || []).forEach((item) => evidence.append(evidenceNode(item)));
  if (!(context.evidence || []).length) evidence.append(node("p", "此时点无业务记录", "ev-muted"));
  return [messages, evidence];
}
async function loadAnnotations() {
  const split = $("annotation-split").value;
  const data = await api(`/api/evaluation/annotations?split=${split}`);
  if (split !== $("annotation-split").value) return;
  $("annotation-progress").textContent =
    `${split === "heldout" ? "冻结集" : split === "development" ? "开发集" : "全部"} ${data.progress.reviewed}/${data.progress.total}`;
  $("annotation-list").replaceChildren(...data.samples.map((sample) => {
    const button = node("button", "", `ev-sample ${selectedSample === sample.sample_id ? "active" : ""}`);
    button.append(node("strong", `${sample.sample_id} · ${sample.status === "reviewed" ? "已标注" : "待标注"}`),
      node("small", sample.buyer_message));
    button.onclick = () => loadSample(sample.sample_id).catch(e => { $("annotation-status").textContent = e.message; });
    return button;
  }));
}
async function loadSample(id) {
  const ticket = ++version;
  $("annotation-status").textContent = "";
  const sample = await api(`/api/evaluation/annotations/${encodeURIComponent(id)}`);
  if (ticket !== version) return;
  selectedSample = id;
  $("ann-label-source").value = sample.annotation_provenance?.declared_human_n
    ? "human" : (sample.human_annotation.label_source || "human");
  $("annotation-empty").hidden = true;
  $("annotation-content").hidden = false;
  $("sample-meta").textContent = `${id} · ${sample.context.analysis_at}`;
  $("sample-title").textContent = sample.buyer_message;
  $("sample-status").textContent = sample.human_annotation.status === "reviewed" ? "已标注" : "待标注";
  $("sample-warning").textContent = sample.context.basis_warning;
  const [messages, evidence] = contextNodes(sample.context);
  $("sample-messages").replaceChildren(messages);
  $("sample-evidence").replaceChildren(evidence);
  const a = sample.human_annotation;
  $("ann-intent").value = a.intent || "";
  $("ann-emotion").value = a.emotion || "";
  $("ann-risk").value = a.risk_level || "";
  $("ann-reviewer").value = a.reviewer || localStorage.getItem("evaluation_reviewer") || "";
  $("ann-facts").value = (a.expected_facts || []).map((x) => typeof x === "string" ? x : JSON.stringify(x)).join("\n");
  $("ann-evidence").value = (a.supporting_evidence_ids || []).join(", ");
  $("ann-action").value = a.acceptable_next_action || "";
  $("ann-notes").value = a.notes || "";
  await loadAnnotations();
}
async function loadEfficiency() {
  const data = await api("/api/evaluation/efficiency/tasks");
  const report = data.report;
  $("efficiency-progress").textContent = `完成配对 ${report.paired_tasks}`;
  $("efficiency-summary").textContent = report.median_time_improvement_pct == null ?
    "暂无完成配对" : `同人同任务配对 ${report.paired_tasks} 次 · 中位耗时变化 ${report.median_time_improvement_pct.toFixed(1)}%`;
  $("efficiency-list").replaceChildren(...data.tasks.map((task) => {
    const card = node("article", "", "ev-efficiency-card");
    card.append(node("h3", task.task_id), node("p", task.objective, "ev-muted"));
    const names = { manual: "传统方式", copilot: "副驾方式" };
    card.append(node("p", `建议顺序：${task.recommended_order.map(x => names[x]).join(" → ")}`, "ev-muted"));
    const methods = node("div", "", "ev-methods");
    task.recommended_order.forEach((method) => {
      const panel = node("section", "", "ev-method");
      panel.append(node("h3", names[method]));
      task.trials.filter(x => x.method === method).forEach((trial) => {
        panel.append(node("p", `${trial.operator} · ${trial.exclusion ? "已作废" :
          trial.ended_at ? `${(trial.elapsed_ms / 1000).toFixed(1)} 秒` : "计时中"}`));
        if (!trial.ended_at) {
          const resume = node("button", "继续任务");
          resume.onclick = () => openTrial(trial.trial_id).catch(e => alert(e.message));
          panel.append(resume);
        }
        if (trial.ended_at && !trial.exclusion) {
          const invalidate = node("button", "作废此记录");
          invalidate.onclick = () => invalidateTrial(trial);
          panel.append(invalidate);
        }
      });
      const start = node("button", "开始计时");
      start.onclick = async () => {
        const operator = prompt("姓名或工号", localStorage.getItem("evaluation_reviewer") || "");
        if (!operator) return;
        try {
          const result = await api("/api/evaluation/efficiency/trials", "POST", {
            task_id: task.task_id, method, operator,
          });
          await openTrial(result.trial.trial_id);
        } catch (e) { alert(e.message); }
      };
      panel.append(start); methods.append(panel);
    });
    card.append(methods); return card;
  }));
}
async function openTrial(id) {
  const detail = await api(`/api/evaluation/efficiency/trials/${id}`);
  activeTrial = detail.trial;
  $("trial-form").reset();
  $("trial-title").textContent = `${detail.sample.sample_id} · ${detail.trial.method === "manual" ? "传统方式" : "副驾方式"}`;
  $("trial-time").textContent = `操作者 ${detail.trial.operator} · 计时开始 ${new Date(detail.trial.started_at).toLocaleTimeString()}`;
  $("trial-context").replaceChildren(...contextNodes(detail.sample.context));
  $("trial-assist").hidden = detail.trial.method !== "copilot";
  $("trial-draft").hidden = true;
  $("trial-status").textContent = "";
  $("annotation-panel").hidden = $("efficiency-panel").hidden = true;
  $("trial-panel").hidden = false;
}
async function invalidateTrial(trial) {
  const reason = prompt("作废原因：例如误开计时、练习或中断。原记录会保留。", "");
  if (!reason?.trim()) return;
  if (!confirm("本次记录将保留，但不进入效率统计。确认作废？")) return;
  try {
    await api(`/api/evaluation/efficiency/trials/${trial.trial_id}/invalidate`, "POST", {
      operator: trial.operator, reason: reason.trim(),
    });
    if (activeTrial?.trial_id === trial.trial_id) {
      activeTrial = null;
      $("trial-panel").hidden = true; $("efficiency-panel").hidden = false;
    }
    await loadEfficiency();
  } catch (e) { alert(e.message); }
}
$("trial-invalidate").onclick = () => {
  if (activeTrial) invalidateTrial(activeTrial);
};
$("trial-assist").onclick = async () => {
  if (!activeTrial) return;
  const trialId = activeTrial.trial_id;
  $("trial-assist").disabled = true;
  $("trial-draft").hidden = false; $("trial-draft").textContent = "生成中";
  try {
    let { job } = await api(`/api/evaluation/efficiency/trials/${trialId}/assist`, "POST", {});
    const deadline = Date.now() + 180000;
    while (!["completed", "failed"].includes(job.status) && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 500));
      ({ job } = await api(`/api/assist-jobs/${job.job_id}`));
    }
    if (job.status !== "completed") throw new Error("生成超时或失败，请记录实际情况");
    if (activeTrial?.trial_id !== trialId) return;
    $("trial-draft").textContent = `${job.result.summary}；${job.result.suggested_reply}；建议：${job.result.next_action}`;
  } catch (e) { $("trial-draft").textContent = e.message; }
  finally { $("trial-assist").disabled = false; }
};
$("trial-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!activeTrial) return;
  try {
    await api(`/api/evaluation/efficiency/trials/${activeTrial.trial_id}`, "PATCH", {
      missed_facts: Number($("trial-missed").value), edit_count: Number($("trial-edits").value),
      success: $("trial-success").value === "true", outcome: $("trial-outcome").value,
      notes: $("trial-notes").value,
    });
    activeTrial = null;
    $("trial-panel").hidden = true; $("efficiency-panel").hidden = false;
    await loadEfficiency();
  } catch (e) { $("trial-status").textContent = e.message; }
};
document.querySelectorAll(".ev-tab").forEach(tab => {
  tab.onclick = () => {
    $("trial-panel").hidden = true;
    document.querySelectorAll(".ev-tab").forEach(x => x.classList.toggle("active", x === tab));
    $("annotation-panel").hidden = tab.dataset.tab !== "annotation";
    $("efficiency-panel").hidden = tab.dataset.tab !== "efficiency";
  };
});
fillSelect("ann-intent", INTENTS); fillSelect("ann-emotion", EMOTIONS);
$("annotation-split").onchange = () => {
  ++version; selectedSample = null;
  $("annotation-content").hidden = true; $("annotation-empty").hidden = false;
  loadAnnotations().catch(e => { $("annotation-status").textContent = e.message; });
};
$("suggest-annotation").onclick = async () => {
  if (!selectedSample) return;
  const ticket = version;
  try {
    const suggestion = await api(`/api/evaluation/annotations/${selectedSample}/suggestion`);
    if (ticket !== version) return;
    $("ann-intent").value = suggestion.intent;
    $("ann-emotion").value = suggestion.emotion;
    $("ann-risk").value = suggestion.risk_level;
    $("ann-evidence").value = suggestion.supporting_evidence_ids.join(", ");
    $("ann-action").value = suggestion.acceptable_next_action;
    $("annotation-status").textContent = "候选已填入；标注依据按你的实际判断方式选择";
  } catch (e) { $("annotation-status").textContent = e.message; }
};
$("annotation-form").onsubmit = async (event) => {
  event.preventDefault();
  if (!selectedSample) return;
  try {
    const reviewer = $("ann-reviewer").value.trim();
    await api(`/api/evaluation/annotations/${selectedSample}`, "POST", {
      reviewer, label_source: $("ann-label-source").value,
      intent: $("ann-intent").value, emotion: $("ann-emotion").value,
      risk_level: $("ann-risk").value,
      expected_facts: $("ann-facts").value.split("\n").map(x => x.trim()).filter(Boolean),
      supporting_evidence_ids: $("ann-evidence").value.split(/[,，]/).map(x => x.trim()).filter(Boolean),
      acceptable_next_action: $("ann-action").value.trim(), notes: $("ann-notes").value.trim(),
    });
    localStorage.setItem("evaluation_reviewer", reviewer);
    $("annotation-status").textContent = "已保存"; await loadAnnotations();
  } catch (e) { $("annotation-status").textContent = e.message; }
};
loadAnnotations().catch(e => { $("annotation-status").textContent = e.message; });
loadEfficiency().catch(e => { $("efficiency-summary").textContent = e.message; });
