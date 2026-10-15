const byId = (id) => document.getElementById(id);
let emotionChart;
let intentChart;
const taskStatus = { pending: "待处理", in_progress: "处理中", resolved: "已完成", cancelled: "已取消" };
let currentAlerts = [];
let demoSessions = [];

function showAlerts(alerts) {
  const container = byId("alerts");
  container.replaceChildren();
  if (!alerts.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "暂无预警";
    container.append(empty);
    return;
  }
  alerts.forEach((item) => {
    const row = document.createElement("article");
    row.className = `alert ${["critical", "high", "medium"].includes(item.level) ? item.level : ""}`;
    const heading = document.createElement("header");
    const title = document.createElement("h3");
    title.textContent = `${item.name} · ${taskStatus[item.status] || item.level.toUpperCase()}`;
    const time = document.createElement("time");
    time.textContent = new Date(item.time).toLocaleTimeString("zh-CN");
    heading.append(title, time);
    const detail = document.createElement("p");
    detail.textContent = item.action;
    const session = document.createElement("small");
    session.textContent = `会话 ${item.session_id} · 负责人 ${item.owner || "未分配"}`;
    const link = document.createElement("a");
    link.className = "alert-link";
    link.href = `/workbench?session=${encodeURIComponent(item.session_id)}`;
    link.textContent = "打开会话与处置记录";
    row.append(heading, detail, session, link);
    container.append(row);
  });
}

function paintCharts(data) {
  if (!window.echarts) return;
  if (!emotionChart) emotionChart = echarts.init(byId("emotion-chart"));
  if (!intentChart) intentChart = echarts.init(byId("intent-chart"));
  const scores = { angry: -1, sad: -0.6, fearful: -0.7, neutral: 0, happy: 1 };
  emotionChart.setOption({
    grid: { left: 45, right: 20, top: 26, bottom: 30 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: data.emotion_trend.map((_, i) => i + 1), axisLabel: { color: "#758588" } },
    yAxis: { type: "value", min: -1, max: 1, axisLabel: { color: "#758588" } },
    series: [{ type: "line", smooth: true, showSymbol: false, lineStyle: { color: "#25917e", width: 2 },
      areaStyle: { color: "rgba(37,145,126,0.08)" },
      data: data.emotion_trend.map((item) => item.valence ?? scores[item.emotion] ?? 0) }]
  });
  intentChart.setOption({
    tooltip: { trigger: "item" },
    series: [{ type: "pie", radius: ["49%", "72%"], center: ["50%", "48%"],
      label: { formatter: "{b}", fontSize: 11, color: "#526164" },
      data: Object.entries(data.intent_distribution).map(([name, value]) => ({ name, value })),
      color: ["#278e7a", "#d39964", "#568ca0", "#ba675c", "#97aaa0"] }]
  });
}

async function refresh() {
  try {
    const [dashboard, costs] = await Promise.all([fetch("/api/dashboard"), fetch("/api/cost")]);
    if (!dashboard.ok || !costs.ok) throw new Error("数据暂不可用");
    const data = await dashboard.json();
    const usage = await costs.json();
    byId("served").textContent = data.served;
    byId("high-risk").textContent = data.high_risk;
    byId("alert-count").textContent = data.open_tasks;
    byId("satisfaction").textContent = data.adoption_rate === null ? "暂无审核" : `${Math.round(data.adoption_rate * 100)}%`;
    byId("tokens").textContent = usage.cost.total_tokens.toLocaleString();
    byId("cost").textContent = usage.cost.total_cost_cny === null ? "未计价" : `¥${usage.cost.total_cost_cny.toFixed(4)}`;
    byId("cache-rate").textContent = `${(usage.cache.hit_rate * 100).toFixed(0)}%`;
    byId("pricing-note").textContent = usage.cost.pricing_configured ?
      "金额依据配置单价计算；不含其他服务费用。" : "模型单价未配置，显示金额不代表真实账单。";
    byId("last-updated").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN")}`;
    currentAlerts = data.alerts;
    filterAlerts();
    paintCharts(data);
  } catch {
    byId("last-updated").textContent = "数据连接中断";
  }
}

async function loadDemoSessions() {
  try {
    const response = await fetch("/api/sessions");
    if (!response.ok) throw new Error("会话数据暂不可用");
    const data = await response.json();
    demoSessions = data.sessions || [];
    const select = byId("demo-session");
    select.replaceChildren();
    demoSessions.forEach((session) => {
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = `${session.session_id} · ${session.scene_minor || session.scene_major} · ${session.buyer_name}`;
      select.append(option);
    });
    if (demoSessions.length) {
      const preferred = demoSessions.find((session) => session.has_order && session.has_ticket);
      select.value = (preferred || demoSessions[0]).session_id;
    }
  } catch {
    const select = byId("demo-session");
    select.replaceChildren();
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "会话列表不可用";
    select.append(option);
  }
}

async function waitForDemoJob(job) {
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error("辅助分析失败，风险任务仍已保存");
    byId("demo-result").textContent =
      job.status === "queued" ? "分析排队中，风险任务已先登记" : "辅助分析中，风险任务已先登记";
    await new Promise((resolve) => setTimeout(resolve, 700));
    const response = await fetch(`/api/assist-jobs/${job.job_id}`);
    if (!response.ok) throw new Error("无法查询辅助分析状态");
    job = (await response.json()).job;
  }
  throw new Error("分析等待超时，请打开客服副驾查看任务");
}

byId("clock").textContent = new Date().toLocaleDateString("zh-CN");
refresh();
loadDemoSessions();
setInterval(refresh, 5000);
if (window.io) {
  const socket = io({ transports: ["websocket", "polling"] });
  socket.on("connect", () => { byId("connection").textContent = "实时连接"; byId("connection").classList.add("online"); socket.emit("subscribe_alerts"); });
  socket.on("disconnect", () => { byId("connection").textContent = "连接中断"; byId("connection").classList.remove("online"); });
  socket.on("new_alert", refresh);
  socket.on("assist_update", refresh);
} else {
  byId("connection").textContent = "定时刷新";
}
window.addEventListener("resize", () => { emotionChart?.resize(); intentChart?.resize(); });
function filterAlerts() {
  showAlerts(currentAlerts.filter((item) => !byId("alert-status").value ||
    item.status === byId("alert-status").value));
}
byId("alert-status").addEventListener("change", filterAlerts);
byId("demo-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.target.querySelector("button");
  submit.disabled = true;
  byId("demo-result").textContent = "处理中";
  try {
    const sessionId = byId("demo-session").value;
    if (!sessionId) throw new Error("请先选择一个演示会话");
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/assist-jobs`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: byId("demo-message").value, mode: "snapshot" }) });
    const submitted = await response.json();
    if (!response.ok) throw new Error(submitted.error || "请稍后重试");
    const result = await waitForDemoJob(submitted.job);
    byId("demo-result").textContent =
      `${result.risk_level}风险 · ${result.model_status} · ${result.suggested_reply} · 下一步：${result.next_action}`;
    await refresh();
  } catch {
    byId("demo-result").textContent = "分析失败或超时，请打开客服副驾查看已保存的风险任务";
  } finally {
    submit.disabled = false;
  }
});
