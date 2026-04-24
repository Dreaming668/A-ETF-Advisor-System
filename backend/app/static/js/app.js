const state = {
  userId: "demo-user",
  selectedEtf: null,
  latestAnalysis: null,
  latestReport: null,
  chatSessionId: null,
  dataSources: null,
  newsSources: null,
  modelProviders: null,
  reports: [],
  reportHistoryCollapsed: false,
  syncProgress: {
    timer: null,
    hideTimer: null,
  },
  chatPending: false,
};

const DEFAULT_CHAT_THINKING_STEPS = [
  "读取 ETF 上下文",
  "整理行情、新闻与因子线索",
  "生成投顾建议",
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) throw new Error((await response.text()) || `Request failed: ${response.status}`);
  return response.json();
}

const qs = (selector) => document.querySelector(selector);
const escapeHtml = (text) => String(text ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;");

function richText(text) {
  return escapeHtml(text).replaceAll("\n", "<br />");
}

function normalizeDisplayListItem(text) {
  const compact = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!compact) return "";
  return compact
    .replace(/^[；;，,、。.!！?？：:\-]+/u, "")
    .replace(/[；;，,、。.!！?？]+$/u, "")
    .trim();
}

function formatRiskText(items = []) {
  const normalized = items
    .map((item) => normalizeDisplayListItem(item))
    .filter(Boolean);
  return normalized.length ? normalized.join("；") : "暂无";
}

function truncateText(text, maxLength = 110) {
  const value = String(text ?? "").trim();
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength).trim()}...`;
}

function formatTimestamp(value) {
  return String(value ?? "").replace("T", " ");
}

function formatSignedPercent(value) {
  const numeric = Number(value || 0);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function computePreviewQuoteMetrics(quotes = []) {
  if (!quotes.length) {
    return {
      close_price: 0,
      pct_change: 0,
      change_20d: 0,
      change_60d: 0,
      annualized_volatility: 0,
      turnover_ratio: 1,
    };
  }

  const latest = quotes[quotes.length - 1];
  const recent20 = quotes.slice(-20);
  const recent60 = quotes.slice(-60);
  const calcWindowChange = (windowQuotes) => {
    if (windowQuotes.length < 2) return 0;
    const base = Number(windowQuotes[0].close_price || 0);
    const current = Number(windowQuotes[windowQuotes.length - 1].close_price || 0);
    if (!base) return 0;
    return ((current / base) - 1) * 100;
  };

  const returns = recent20
    .map((item) => Number(item.pct_change || 0) / 100)
    .filter((value) => Number.isFinite(value));
  const avgReturn = returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : 0;
  const variance = returns.length > 1
    ? returns.reduce((sum, value) => sum + ((value - avgReturn) ** 2), 0) / returns.length
    : 0;
  const latestTurnover = Number(latest.turnover || 0);
  const avgTurnover20 = recent20.length
    ? recent20.reduce((sum, item) => sum + Number(item.turnover || 0), 0) / recent20.length
    : latestTurnover;

  return {
    close_price: Number(latest.close_price || 0),
    pct_change: Number(latest.pct_change || 0),
    change_20d: calcWindowChange(recent20),
    change_60d: calcWindowChange(recent60),
    annualized_volatility: Math.sqrt(variance) * Math.sqrt(252) * 100,
    turnover_ratio: avgTurnover20 ? latestTurnover / avgTurnover20 : 1,
  };
}

function scrollToSection(event) {
  const target = document.getElementById(event.currentTarget.dataset.scrollTarget);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderProviderLines() {
  if (state.dataSources) {
    const labels = state.dataSources.providers.map((item) => `${item.name}:${item.usable ? "可用" : "不可用"}`).join(" / ");
    qs("#dataSourceText").textContent = `行情源：${state.dataSources.preferred}；${labels}`;
  }
  if (state.newsSources) {
    const labels = state.newsSources.providers.map((item) => `${item.name}:${item.usable ? "可用" : "不可用"}`).join(" / ");
    qs("#newsSourceText").textContent = `新闻源：${state.newsSources.preferred}；${labels}`;
  }
  if (state.modelProviders) {
    const labels = state.modelProviders.providers.map((item) => `${item.name}:${item.usable ? "可用" : "不可用"}`).join(" / ");
    qs("#modelProviderText").textContent = `模型：${state.modelProviders.preferred}；${labels}`;
  }
}

function renderRiskProfile(profile) {
  qs("#riskBadge").textContent = `${profile.risk_level} | ${profile.investment_horizon} | 最大回撤 ${profile.max_drawdown}`;
  qs("#riskLevelText").textContent = profile.risk_level;
  qs("#riskSummaryText").textContent = profile.summary;
}

function renderFeaturedEtfs(etfs) {
  qs("#featuredEtfs").innerHTML = etfs.map((etf) => `
    <article class="expert-card">
      <p class="eyebrow">${escapeHtml(etf.category)}</p>
      <h3>${escapeHtml(etf.name)}</h3>
      <p>${escapeHtml(etf.description)}</p>
      <p class="muted">${escapeHtml(etf.code)} · ${escapeHtml(etf.theme)} · ${escapeHtml(etf.risk_level)}</p>
      <button class="primary-btn" onclick="selectEtf('${etf.code}')">查看分析</button>
    </article>
  `).join("");
}

function renderEtfTable(etfs) {
  qs("#etfTableBody").innerHTML = etfs.map((etf) => `
    <tr>
      <td>${escapeHtml(etf.code)}</td>
      <td>${escapeHtml(etf.name)}</td>
      <td>${escapeHtml(etf.category)}</td>
      <td>${escapeHtml(etf.theme)}</td>
      <td>${escapeHtml(etf.risk_level)}</td>
      <td><button class="ghost-btn" onclick="selectEtf('${etf.code}')">选择</button></td>
    </tr>
  `).join("");
}

function renderSparkline(quotes) {
  const svg = qs("#sparkline");
  if (!quotes?.length) {
    svg.innerHTML = '<rect x="0" y="0" width="500" height="160" rx="20" fill="rgba(255,255,255,0.6)"></rect>';
    return;
  }

  const points = quotes.map((item) => Number(item.close_price || 0));
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = Math.max(max - min, 0.01);
  const width = 500;
  const height = 160;
  const path = points.map((value, index) => {
    const x = (index / Math.max(points.length - 1, 1)) * width;
    const y = height - ((value - min) / range) * (height - 16) - 8;
    return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");

  svg.innerHTML = `
    <rect x="0" y="0" width="500" height="160" rx="20" fill="rgba(255,255,255,0.6)"></rect>
    <path d="${path}" fill="none" stroke="#d96f32" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
  `;
}

function renderNewsDetail(analysis) {
  const items = analysis.news || [];
  if (!items.length) {
    return `<div class="detail-empty">暂无新闻明细，先刷新新闻或生成报告。</div>`;
  }
  return `
    <div class="expert-detail-list">
      ${items.map((item) => `
        <article class="detail-item">
          <div class="detail-item-meta">
            <strong>${escapeHtml(item.source)}</strong>
            <span>${escapeHtml(formatTimestamp(item.published_at))}</span>
          </div>
          <h4>${escapeHtml(item.title)}</h4>
          <p>${escapeHtml(item.summary || "暂无摘要")}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function renderAlphaDetail(analysis) {
  const factor = analysis.factor || {};
  const factorRows = [
    { label: "动量", value: factor.momentum },
    { label: "波动", value: factor.volatility },
    { label: "流动性", value: factor.liquidity },
    { label: "资金流", value: factor.money_flow },
    { label: "估值", value: factor.valuation },
    { label: "行业轮动", value: factor.industry_rotation },
    { label: "综合得分", value: factor.composite_score },
  ];
  return `
    <div class="factor-grid">
      ${factorRows.map((item) => `
        <div class="factor-chip">
          <span>${item.label}</span>
          <strong>${Number(item.value || 0).toFixed(1)}</strong>
        </div>
      `).join("")}
    </div>
    <p class="detail-foot muted">因子更新时间：${escapeHtml(factor.as_of || "暂无")}</p>
  `;
}

function renderFundamentalDetail(analysis) {
  const constituents = analysis.constituents || [];
  if (!constituents.length) {
    return `<div class="detail-empty">获取不到真实成分股信息，请稍后重试或更换 ETF。</div>`;
  }
  return `
    <div class="expert-detail-table">
      <div class="detail-table-head">
        <span>成分股</span>
        <span>权重</span>
        <span>PE</span>
        <span>ROE</span>
      </div>
      ${constituents.map((item) => `
        <div class="detail-table-row">
          <span>
            <strong>${escapeHtml(item.stock_name)}</strong>
            <em>${escapeHtml(item.stock_code)} · ${escapeHtml(item.sector || "未分类")}</em>
          </span>
          <span>${Number(item.weight || 0).toFixed(2)}%</span>
          <span>${Number(item.pe || 0).toFixed(1)}</span>
          <span>${Number(item.roe || 0).toFixed(1)}%</span>
        </div>
      `).join("")}
    </div>
  `;
}

function renderExpertDetail(expert, analysis) {
  if (expert.name === "新闻分析师") return renderNewsDetail(analysis);
  if (expert.name === "Alpha分析师") return renderAlphaDetail(analysis);
  if (expert.name === "基本面分析师") return renderFundamentalDetail(analysis);
  return "";
}

function renderExpertCard(expert, analysis) {
  const detailHtml = renderExpertDetail(expert, analysis);
  const detailBlock = detailHtml ? `
    <details class="expert-detail-box">
      <summary>查看明细</summary>
      <div class="expert-detail-body">${detailHtml}</div>
    </details>
  ` : "";
  return `
    <article class="expert-card">
      <p class="eyebrow">${escapeHtml(expert.name)}</p>
      <h3>${escapeHtml(expert.summary)}</h3>
      <ul>${(expert.signals || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      <p class="muted">风险提示：${escapeHtml(formatRiskText(expert.risks || []))}</p>
      ${detailBlock}
    </article>
  `;
}

function renderAnalysis(analysis) {
  const latest = analysis.latest_quote;
  const experts = analysis.experts;
  state.latestAnalysis = analysis;
  if (analysis.model_provider) state.modelProviders = analysis.model_provider;
  renderProviderLines();
  qs("#selectedEtfBadge").textContent = `${analysis.etf.name} (${analysis.etf.code}) · ${analysis.agent_mode || "rules"}`;
  qs("#analysisPlaceholder").classList.add("hidden");
  qs("#analysisContent").classList.remove("hidden");

  const metrics = [
    { label: "最新收盘", value: Number(latest.close_price).toFixed(4), tone: "" },
    { label: "单日涨跌", value: formatSignedPercent(latest.pct_change), tone: latest.pct_change >= 0 ? "positive" : "negative" },
    { label: "20日涨跌", value: formatSignedPercent(latest.change_20d), tone: latest.change_20d >= 0 ? "positive" : "negative" },
    { label: "60日涨跌", value: formatSignedPercent(latest.change_60d), tone: latest.change_60d >= 0 ? "positive" : "negative" },
    { label: "年化波动", value: `${Number(latest.annualized_volatility).toFixed(2)}%`, tone: "" },
    { label: "成交额比", value: `${Number(latest.turnover_ratio).toFixed(2)}x`, tone: "" },
  ];

  qs("#metricCards").innerHTML = metrics.map((item) => `
    <div class="metric-card">
      <span class="muted">${item.label}</span>
      <strong class="${item.tone}">${item.value}</strong>
    </div>
  `).join("");

  renderSparkline(analysis.quotes);
  const expertEntries = [experts.market, experts.news, experts.alpha, experts.fundamental, experts.general];
  qs("#expertCards").innerHTML = expertEntries.map((expert) => renderExpertCard(expert, analysis)).join("");

  qs("#reportSummary").innerHTML = `<strong>${escapeHtml(analysis.etf.name)}</strong><br />综合建议：${escapeHtml(experts.general.recommendation || "待生成")}<br />${richText(experts.general.summary || "点击“生成报告”后显示完整结果。")}`;
}

function updateDownloadButton() {
  qs("#downloadReportBtn").disabled = !state.latestReport;
}

function updateReportSummary(report = null) {
  state.latestReport = report;
  updateDownloadButton();
  if (!report) {
    qs("#reportSummary").textContent = state.selectedEtf
      ? "已选择 ETF，请点击“生成报告”后显示完整结果。"
      : "生成分析报告后，这里会展示摘要和下载入口。";
    return;
  }

  const confidence = Number(report.confidence ?? 0).toFixed(2);
  qs("#reportSummary").innerHTML = `
    <strong>${escapeHtml(report.title)}</strong><br />
    建议：${escapeHtml(report.recommendation)} · 置信度 ${confidence}<br />
    ${richText(report.summary)}
  `;
}

function renderReportHistory(reports) {
  qs("#reportCountBadge").textContent = `${reports.length} 份`;
  qs("#toggleReportHistoryBtn").textContent = state.reportHistoryCollapsed ? "展开列表" : "折叠列表";

  if (state.reportHistoryCollapsed) {
    qs("#reportHistory").innerHTML = `<div class="report-history-note muted">历史报告已折叠，当前共 ${reports.length} 份。</div>`;
    return;
  }

  qs("#reportHistory").innerHTML = reports.length ? reports.map((report) => `
    <article class="report-item ${state.latestReport?.id === report.id ? "active" : ""}">
      <div class="report-item-head">
        <div>
          <h3>${escapeHtml(report.title)}</h3>
          <p class="muted report-item-meta">${formatTimestamp(report.created_at)} · 建议：${escapeHtml(report.recommendation)}</p>
        </div>
        <div class="report-item-actions">
          <button class="ghost-btn small-btn" data-action="show-report" data-report-id="${report.id}">查看</button>
          <button class="ghost-btn small-btn" data-action="download-report" data-report-id="${report.id}">下载</button>
          <button class="danger-btn" data-action="delete-report" data-report-id="${report.id}">删除</button>
        </div>
      </div>
      <p class="report-item-preview">${escapeHtml(truncateText(report.summary, 120))}</p>
    </article>
  `).join("") : `<div class="muted">还没有生成过报告。</div>`;
}

function setSyncButtonsDisabled(disabled) {
  ["#refreshQuoteBtn", "#refreshNewsBtn", "#refreshFundamentalBtn", "#refreshFactorBtn", "#generateReportBtn"].forEach((selector) => {
    const element = qs(selector);
    if (element) element.disabled = disabled;
  });
}

function clearSyncTimers() {
  if (state.syncProgress.timer) {
    window.clearInterval(state.syncProgress.timer);
    state.syncProgress.timer = null;
  }
  if (state.syncProgress.hideTimer) {
    window.clearTimeout(state.syncProgress.hideTimer);
    state.syncProgress.hideTimer = null;
  }
}

function setSyncProgress({ visible = true, title = "正在刷新...", percent = 0, detail = "", tone = "" } = {}) {
  const container = qs("#syncProgress");
  const bar = qs("#syncProgressBar");
  container.classList.remove("success", "error");
  if (tone) container.classList.add(tone);
  if (visible) {
    container.classList.remove("hidden");
  } else {
    container.classList.add("hidden");
  }
  qs("#syncProgressTitle").textContent = title;
  qs("#syncProgressPercent").textContent = `${Math.max(0, Math.min(100, Math.round(percent)))}%`;
  qs("#syncProgressDetail").textContent = detail;
  bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function scheduleHideSyncProgress(delay = 2200) {
  if (state.syncProgress.hideTimer) window.clearTimeout(state.syncProgress.hideTimer);
  state.syncProgress.hideTimer = window.setTimeout(() => {
    setSyncProgress({ visible: false, percent: 0, detail: "" });
  }, delay);
}

function startSyncProgress(kind) {
  clearSyncTimers();
  const plans = {
    quotes: {
      title: "正在刷新行情",
      steps: [
        { percent: 12, detail: "系统正在连接实时行情源。" },
        { percent: 38, detail: "正在抓取最新量价数据。" },
        { percent: 62, detail: "正在校验交易日并写入行情数据。" },
        { percent: 86, detail: "正在刷新页面上的最新价格与涨跌信息。" },
      ],
    },
    news: {
      title: "正在刷新新闻",
      steps: [
        { percent: 10, detail: "系统正在连接中文财经新闻源。" },
        { percent: 34, detail: "正在抓取与 ETF 相关的最新新闻。" },
        { percent: 66, detail: "正在清洗标题、摘要与情绪信息。" },
        { percent: 88, detail: "正在保存新闻并准备刷新分析结果。" },
      ],
    },
    fundamentals: {
      title: "正在刷新基本面",
      steps: [
        { percent: 10, detail: "系统正在连接 ETF 成分股真实数据源。" },
        { percent: 36, detail: "正在抓取最新成分股与权重信息。" },
        { percent: 64, detail: "正在抓取成分股估值、盈利与成长指标。" },
        { percent: 88, detail: "正在写入基本面明细并刷新页面展示。" },
      ],
    },
    factors: {
      title: "正在刷新因子",
      steps: [
        { percent: 12, detail: "系统正在读取最新行情与真实成分股基本面。" },
        { percent: 40, detail: "正在计算动量、波动、流动性与资金流因子。" },
        { percent: 68, detail: "正在计算估值、行业轮动与综合评分。" },
        { percent: 88, detail: "正在保存因子结果并刷新页面展示。" },
      ],
    },
    report: {
      title: "正在生成报告",
      steps: [
        { percent: 14, detail: "系统正在汇总行情、新闻、基本面与 Alpha 数据。" },
        { percent: 39, detail: "五专家正在分别生成观点与风险提示。" },
        { percent: 68, detail: "通用专家正在整合建议、置信度与操作结论。" },
        { percent: 90, detail: "正在写入报告中心并生成下载文件。" },
      ],
    },
  };
  const plan = plans[kind] || plans.quotes;

  let stepIndex = 0;
  let currentPercent = plan.steps[0].percent;
  setSyncProgress({ title: plan.title, percent: currentPercent, detail: plan.steps[0].detail });

  state.syncProgress.timer = window.setInterval(() => {
    const step = plan.steps[Math.min(stepIndex, plan.steps.length - 1)];
    currentPercent = Math.min(92, currentPercent + (currentPercent < step.percent ? 6 : 4));
    if (currentPercent >= step.percent && stepIndex < plan.steps.length - 1) {
      stepIndex += 1;
    }
    const detailStep = plan.steps[Math.min(stepIndex, plan.steps.length - 1)];
    setSyncProgress({ title: plan.title, percent: currentPercent, detail: detailStep.detail });
  }, 420);
}

function finishSyncProgress(message) {
  clearSyncTimers();
  setSyncProgress({ visible: true, title: "刷新完成", percent: 100, detail: message, tone: "success" });
  scheduleHideSyncProgress();
}

function failSyncProgress(message) {
  clearSyncTimers();
  setSyncProgress({ visible: true, title: "刷新失败", percent: 100, detail: message, tone: "error" });
  scheduleHideSyncProgress(3200);
}

function scrollChatToBottom() {
  qs("#chatMessages").scrollTop = qs("#chatMessages").scrollHeight;
}

function renderTraceSteps(traceSteps = []) {
  if (!traceSteps.length) return "";
  return `
    <div class="message-trace">
      <span class="message-trace-label">本轮处理</span>
      ${traceSteps.map((item) => `<span class="trace-chip">${escapeHtml(item)}</span>`).join("")}
    </div>
  `;
}

function renderMessage(wrapper, role, content, expertName, { traceSteps = [] } = {}) {
  wrapper.className = `message ${role}`;
  wrapper.innerHTML = `
    <div class="message-meta">${escapeHtml(expertName)}</div>
    <div class="message-body">${richText(content)}</div>
    ${renderTraceSteps(traceSteps)}
  `;
}

function appendMessage(role, content, expertName = role === "assistant" ? "通用专家" : "你", options = {}) {
  const wrapper = document.createElement("div");
  renderMessage(wrapper, role, content, expertName, options);
  qs("#chatMessages").appendChild(wrapper);
  scrollChatToBottom();
  return wrapper;
}

function setChatPending(pending) {
  state.chatPending = pending;
  qs("#chatInput").disabled = pending;
  const submitBtn = qs("#chatForm button[type='submit']");
  if (submitBtn) {
    submitBtn.disabled = pending;
    submitBtn.textContent = pending ? "思考中..." : "发送";
  }
}

function createThinkingMessage(steps = DEFAULT_CHAT_THINKING_STEPS) {
  const wrapper = document.createElement("div");
  const safeSteps = steps.length ? steps : DEFAULT_CHAT_THINKING_STEPS;
  wrapper.className = "message assistant thinking";
  wrapper.innerHTML = `
    <div class="message-meta">
      通用专家
      <span class="thinking-inline">
        正在思考
        <span class="thinking-dots"><span></span><span></span><span></span></span>
      </span>
    </div>
    <div class="message-body">
      <div class="thinking-title">正在整理这轮问答</div>
      <div class="thinking-subtitle">系统会先读取 ETF 上下文，再生成更自然的投顾回复。</div>
      <div class="thinking-steps">
        ${safeSteps.map((item, index) => `<div class="thinking-step ${index === 0 ? "active" : ""}">${escapeHtml(item)}</div>`).join("")}
      </div>
    </div>
  `;
  qs("#chatMessages").appendChild(wrapper);
  scrollChatToBottom();

  const stepNodes = [...wrapper.querySelectorAll(".thinking-step")];
  let activeIndex = 0;
  const paintSteps = (index) => {
    stepNodes.forEach((node, nodeIndex) => {
      node.classList.toggle("done", nodeIndex < index);
      node.classList.toggle("active", nodeIndex === index);
    });
  };
  const timer = window.setInterval(() => {
    if (activeIndex < stepNodes.length - 1) {
      activeIndex += 1;
      paintSteps(activeIndex);
    }
  }, 950);

  return {
    resolve(content, expertName = "通用专家", options = {}) {
      window.clearInterval(timer);
      renderMessage(wrapper, "assistant", content, expertName, options);
      scrollChatToBottom();
    },
    reject(message) {
      window.clearInterval(timer);
      renderMessage(wrapper, "assistant", message, "系统提示");
      scrollChatToBottom();
    },
  };
}

async function loadBootstrap() {
  const data = await api("/api/bootstrap");
  state.userId = data.user.id;
  state.dataSources = data.data_sources;
  state.newsSources = data.news_sources;
  state.modelProviders = data.model_providers;
  qs("#userName").textContent = data.user.display_name;
  renderRiskProfile(data.risk_profile);
  renderProviderLines();
  renderFeaturedEtfs(data.featured_etfs);
  renderEtfTable(data.featured_etfs);
  await refreshReports({ preferLatest: true });
}

async function searchEtfs() {
  const query = qs("#searchInput").value.trim();
  const category = qs("#categoryFilter").value;
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (category) params.set("category", category);
  renderEtfTable(await api(`/api/etfs?${params.toString()}`));
}

async function refreshReports({ syncSummary = false, preferLatest = false } = {}) {
  const reports = await api(`/api/reports?user_id=${encodeURIComponent(state.userId)}`);
  state.reports = reports;

  if (preferLatest && !state.latestReport && reports.length) {
    updateReportSummary(reports[0]);
  }

  if (syncSummary) {
    const current = state.latestReport ? reports.find((item) => item.id === state.latestReport.id) : null;
    if (current) updateReportSummary(current);
    else if (reports.length) updateReportSummary(reports[0]);
    else updateReportSummary(null);
  }

  renderReportHistory(reports);
}

async function ensureChatSession() {
  if (state.chatSessionId) return state.chatSessionId;
  if (!state.selectedEtf) throw new Error("请先选择一只 ETF。");
  const session = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ user_id: state.userId, etf_code: state.selectedEtf.code }),
  });
  state.chatSessionId = session.id;
  appendMessage("assistant", `已为 ${state.selectedEtf.name} 开启投顾会话，你可以继续追问风险、仓位、新闻或因子。`);
  return state.chatSessionId;
}

async function loadAnalysisForEtf(etfCode, { preserveSyncUi = false } = {}) {
  const detail = await api(`/api/etfs/${etfCode}`);
  const previewMetrics = computePreviewQuoteMetrics(detail.quotes);
  state.selectedEtf = detail;
  state.chatSessionId = null;
  state.latestReport = null;
  updateDownloadButton();
  qs("#reportSummary").textContent = "已选择 ETF，请点击“生成报告”或直接开始问答。";
  if (!preserveSyncUi) {
    qs("#syncFeedback").textContent = "";
    clearSyncTimers();
    setSyncProgress({ visible: false, percent: 0, detail: "" });
  }

  renderAnalysis({
    etf: detail,
    latest_quote: previewMetrics,
    quotes: detail.quotes.slice(-40),
    news: detail.news,
    constituents: detail.constituents || [],
    factor: detail.factor || {
      as_of: null,
      momentum: 0,
      volatility: 0,
      liquidity: 0,
      money_flow: 0,
      valuation: 0,
      industry_rotation: 0,
      composite_score: 0,
    },
    experts: {
      market: { name: "市场专家", summary: "点击“生成报告”后显示完整结果。", signals: [], risks: [] },
      news: { name: "新闻分析师", summary: "可先刷新新闻，再生成完整结果。", signals: detail.news.slice(0, 3).map((item) => item.title), risks: [] },
      alpha: {
        name: "Alpha分析师",
        summary: detail.factor?.as_of ? `最新因子已更新至 ${detail.factor.as_of}。` : "暂无因子结果，请先刷新因子或生成报告。",
        signals: detail.factor?.as_of ? [`综合得分 ${Number(detail.factor.composite_score || 0).toFixed(1)}`, `动量 ${Number(detail.factor.momentum || 0).toFixed(1)}`, `估值 ${Number(detail.factor.valuation || 0).toFixed(1)}`] : [],
        risks: [],
      },
      fundamental: {
        name: "基本面分析师",
        summary: (detail.constituents || []).length ? `已加载 ${detail.constituents.length} 个真实成分股样本。` : "暂无真实成分股基本面，请先刷新基本面或更换 ETF。",
        signals: (detail.constituents || []).slice(0, 3).map((item) => `${item.stock_name} ${Number(item.weight || 0).toFixed(2)}%`),
        risks: [],
      },
      general: { name: "通用专家", summary: "点击“生成报告”后显示完整结果。", signals: [], risks: [], recommendation: "待生成" },
    },
    model_provider: state.modelProviders,
    agent_mode: "preview",
  });
}

async function refreshSelectedEtf() {
  if (!state.selectedEtf) return window.alert("请先选择一只 ETF。");

  setSyncButtonsDisabled(true);
  qs("#syncFeedback").textContent = "正在刷新行情...";
  startSyncProgress("quotes");

  try {
    const result = await api(`/api/etfs/${state.selectedEtf.code}/quotes/refresh`, {
      method: "POST",
      body: JSON.stringify({ provider: "auto", days: 120 }),
    });

    state.dataSources = result.data_sources;
    renderProviderLines();
    await loadAnalysisForEtf(state.selectedEtf.code, { preserveSyncUi: true });

    const quoteResult = result || {};
    const latestClose = Number.isFinite(Number(quoteResult.latest_close))
      ? Number(quoteResult.latest_close).toFixed(4)
      : "-";
    const successMessage = `已通过 ${quoteResult.provider || "实时源"} 刷新 ${quoteResult.inserted_quotes || 0} 条行情，最新交易日 ${quoteResult.latest_trade_date || "-"}，收盘价 ${latestClose}。`;
    qs("#syncFeedback").textContent = successMessage;
    finishSyncProgress(`最新交易日 ${quoteResult.latest_trade_date || "-"} 的行情已同步完成。`);
  } catch (error) {
    const message = `刷新失败：${error.message}`;
    qs("#syncFeedback").textContent = message;
    failSyncProgress(message);
  } finally {
    setSyncButtonsDisabled(false);
  }
}

async function refreshSelectedNews() {
  if (!state.selectedEtf) return window.alert("请先选择一只 ETF。");

  setSyncButtonsDisabled(true);
  qs("#syncFeedback").textContent = "正在刷新新闻与摘要...";
  startSyncProgress("news");

  try {
    const result = await api(`/api/etfs/${state.selectedEtf.code}/news/refresh`, {
      method: "POST",
      body: JSON.stringify({ provider: "auto", summarize_with: "auto", limit: 6 }),
    });

    state.newsSources = result.news_sources;
    state.modelProviders = result.model_providers;
    renderProviderLines();
    await loadAnalysisForEtf(state.selectedEtf.code, { preserveSyncUi: true });

    const successMessage = `已通过 ${result.provider || "新闻源"} 刷新 ${result.inserted_news || 0} 条新闻，最新时间 ${formatTimestamp(result.latest_published_at || "-")}`;
    qs("#syncFeedback").textContent = successMessage;
    finishSyncProgress("新闻抓取、清洗与摘要已刷新完成。");
  } catch (error) {
    const message = `新闻刷新失败：${error.message}`;
    qs("#syncFeedback").textContent = message;
    failSyncProgress(message);
  } finally {
    setSyncButtonsDisabled(false);
  }
}

async function refreshSelectedFundamentals() {
  if (!state.selectedEtf) return window.alert("请先选择一只 ETF。");

  setSyncButtonsDisabled(true);
  qs("#syncFeedback").textContent = "正在刷新基本面...";
  startSyncProgress("fundamentals");

  try {
    const result = await api(`/api/etfs/${state.selectedEtf.code}/fundamentals/refresh`, {
      method: "POST",
      body: JSON.stringify({ max_items: 10 }),
    });

    await loadAnalysisForEtf(state.selectedEtf.code, { preserveSyncUi: true });

    const successMessage = `已通过 ${result.provider || "真实数据源"} 刷新 ${result.inserted_constituents || 0} 个成分股基本面，报告期 ${result.report_date || "-"}`;
    qs("#syncFeedback").textContent = successMessage;
    finishSyncProgress("真实成分股基本面已刷新完成。");
  } catch (error) {
    const message = `基本面刷新失败：${error.message}`;
    qs("#syncFeedback").textContent = message;
    failSyncProgress(message);
  } finally {
    setSyncButtonsDisabled(false);
  }
}

async function refreshSelectedFactors() {
  if (!state.selectedEtf) return window.alert("请先选择一只 ETF。");

  setSyncButtonsDisabled(true);
  qs("#syncFeedback").textContent = "正在刷新因子...";
  startSyncProgress("factors");

  try {
    const result = await api(`/api/etfs/${state.selectedEtf.code}/factors/refresh`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    await loadAnalysisForEtf(state.selectedEtf.code, { preserveSyncUi: true });

    const successMessage = `已通过 ${result.provider || "因子引擎"} 刷新 Alpha 因子，最新日期 ${result.as_of || "-"}，综合得分 ${Number(result.composite_score || 0).toFixed(1)}。`;
    qs("#syncFeedback").textContent = successMessage;
    finishSyncProgress("Alpha 因子已刷新完成。");
  } catch (error) {
    const message = `因子刷新失败：${error.message}`;
    qs("#syncFeedback").textContent = message;
    failSyncProgress(message);
  } finally {
    setSyncButtonsDisabled(false);
  }
}

async function generateReport() {
  if (!state.selectedEtf) return window.alert("请先选择一只 ETF。");

  setSyncButtonsDisabled(true);
  qs("#syncFeedback").textContent = "正在生成五专家投顾报告...";
  startSyncProgress("report");

  try {
    const result = await api("/api/analysis/reports", {
      method: "POST",
      body: JSON.stringify({ user_id: state.userId, etf_code: state.selectedEtf.code, mode: "llm" }),
    });

    renderAnalysis(result.analysis);
    updateReportSummary(result.report);
    await refreshReports();

    const confidence = Number(result.report.confidence ?? 0).toFixed(2);
    const successMessage = `报告已生成：${result.report.title}，建议 ${result.report.recommendation}，置信度 ${confidence}`;
    qs("#syncFeedback").textContent = successMessage;
    finishSyncProgress("五专家分析、综合建议与报告文件已生成完成。");
  } catch (error) {
    const message = `报告生成失败：${error.message}`;
    qs("#syncFeedback").textContent = message;
    failSyncProgress(message);
  } finally {
    setSyncButtonsDisabled(false);
  }
}

async function submitRiskForm(event) {
  event.preventDefault();
  renderRiskProfile(await api("/api/risk-assessments", {
    method: "POST",
    body: JSON.stringify({ user_id: state.userId, answers: Object.fromEntries(new FormData(event.currentTarget).entries()) }),
  }));
}

async function sendChat(event) {
  event.preventDefault();
  if (state.chatPending) return;
  const content = qs("#chatInput").value.trim();
  if (!content) return;
  appendMessage("user", content, "你");
  qs("#chatInput").value = "";
  const thinking = createThinkingMessage();
  setChatPending(true);

  try {
    const sessionId = await ensureChatSession();
    const reply = await api(`/api/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    thinking.resolve(reply.content, reply.expert_name || "通用专家", {
      traceSteps: reply.thinking_steps || DEFAULT_CHAT_THINKING_STEPS,
    });
  } catch (error) {
    thinking.reject(`这轮回复生成失败：${error.message}`);
  } finally {
    setChatPending(false);
    qs("#chatInput").focus();
  }
}

async function startNewChat() {
  if (!state.selectedEtf) return window.alert("请先选择一只 ETF。");
  state.chatSessionId = null;
  qs("#chatMessages").innerHTML = "";
  await ensureChatSession();
}

function toggleReportHistory() {
  state.reportHistoryCollapsed = !state.reportHistoryCollapsed;
  renderReportHistory(state.reports);
}

function showReport(reportId) {
  const report = state.reports.find((item) => item.id === reportId);
  if (!report) return;
  updateReportSummary(report);
  renderReportHistory(state.reports);
}

function downloadReport(reportId) {
  window.open(`/api/reports/${reportId}/download`, "_blank");
}

async function deleteReport(reportId) {
  const report = state.reports.find((item) => item.id === reportId);
  if (!report) return;
  const confirmed = window.confirm(`确认删除报告“${report.title}”吗？`);
  if (!confirmed) return;

  await api(`/api/reports/${reportId}`, { method: "DELETE" });
  if (state.latestReport?.id === reportId) {
    state.latestReport = null;
  }
  await refreshReports({ syncSummary: true });
}

function handleReportHistoryClick(event) {
  const actionTarget = event.target.closest("[data-action]");
  if (!actionTarget) return;
  const reportId = Number(actionTarget.dataset.reportId);
  const action = actionTarget.dataset.action;

  if (action === "show-report") showReport(reportId);
  if (action === "download-report") downloadReport(reportId);
  if (action === "delete-report") {
    deleteReport(reportId).catch((error) => window.alert(`删除失败：${error.message}`));
  }
}

window.selectEtf = async function selectEtf(code) {
  try {
    await loadAnalysisForEtf(code);
    document.getElementById("analysisSection").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    window.alert(`该 ETF 暂无法获取行情数据，已从列表中隐藏：${error.message}`);
    await searchEtfs();
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  document.querySelectorAll("[data-scroll-target]").forEach((button) => button.addEventListener("click", scrollToSection));
  qs("#riskForm").addEventListener("submit", submitRiskForm);
  qs("#searchBtn").addEventListener("click", searchEtfs);
  qs("#categoryFilter").addEventListener("change", searchEtfs);
  qs("#searchInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchEtfs();
    }
  });
  qs("#refreshQuoteBtn").addEventListener("click", refreshSelectedEtf);
  qs("#refreshNewsBtn").addEventListener("click", refreshSelectedNews);
  qs("#refreshFundamentalBtn").addEventListener("click", refreshSelectedFundamentals);
  qs("#refreshFactorBtn").addEventListener("click", refreshSelectedFactors);
  qs("#generateReportBtn").addEventListener("click", generateReport);
  qs("#downloadReportBtn").addEventListener("click", () => state.latestReport && downloadReport(state.latestReport.id));
  qs("#toggleReportHistoryBtn").addEventListener("click", toggleReportHistory);
  qs("#reportHistory").addEventListener("click", handleReportHistoryClick);
  qs("#chatForm").addEventListener("submit", sendChat);
  qs("#newChatBtn").addEventListener("click", startNewChat);

  try {
    await loadBootstrap();
  } catch (error) {
    console.error(error);
    qs("#featuredEtfs").innerHTML = `<div class="muted">初始化失败，请检查后端服务。</div>`;
  }
});
