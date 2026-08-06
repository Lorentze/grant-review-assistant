"use strict";

const state = {
  connected: false,
  files: [],
  outputDir: "",
  batch: null,
  selectedIndex: 0,
  detail: null,
  activeDetailTab: "basic",
};

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function nl2br(value) {
  return escapeHtml(value).replaceAll("\n", "<br>");
}

function displayValue(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function displayNumber(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toLocaleString("zh-CN")}${suffix}` : `${value}${suffix}`;
}

function showBusy(title, text = "请勿关闭窗口。") {
  byId("busyTitle").textContent = title;
  byId("busyText").textContent = text;
  byId("busyOverlay").classList.remove("hidden");
}

function hideBusy() {
  byId("busyOverlay").classList.add("hidden");
}

function toast(message, kind = "success", duration = 5200) {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  byId("toastContainer").appendChild(node);
  window.setTimeout(() => node.remove(), duration);
}

function showErrors(errors) {
  if (!Array.isArray(errors) || errors.length === 0) return;
  const text = errors
    .map((item) => `${item.file || "文件"}（${item.stage || "处理"}）：${item.message || "未知错误"}`)
    .join("\n");
  toast(text, "warning", 10000);
}

async function api(method, ...args) {
  if (!window.pywebview?.api?.[method]) {
    throw new Error("尚未连接本地应用。请使用打包后的桌面程序打开本界面。");
  }
  return await window.pywebview.api[method](...args);
}

function switchTab(name) {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  });
}

function switchDetailTab(name) {
  state.activeDetailTab = name;
  document.querySelectorAll(".subnav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.subtab === name);
  });
  document.querySelectorAll(".detail-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `detail-${name}`);
  });
}

function updateProviderUI() {
  const provider = byId("providerSelect").value;
  byId("providerRuleInfo").classList.toggle("hidden", provider !== "rule");
  byId("providerNoneInfo").classList.toggle("hidden", provider !== "none");
  byId("providerOllamaFields").classList.toggle("hidden", provider !== "ollama");
  byId("providerOpenAIFields").classList.toggle("hidden", provider !== "openai");
  updateProcessButton();
}

function updateFinalProviderUI() {
  const provider = byId("finalProvider").value;
  byId("finalApiKeyField").classList.toggle("hidden", provider !== "openai");
  if (provider === "rule") {
    byId("finalModel").value = "";
    byId("finalModel").placeholder = "本地规则无需模型";
  } else if (provider === "openai") {
    if (!byId("finalModel").value || byId("finalModel").value.includes(":")) {
      byId("finalModel").value = "gpt-5.6-terra";
    }
    byId("finalModel").placeholder = "例如：gpt-5.6-terra";
  } else {
    byId("finalModel").placeholder = "例如：qwen3:8b";
  }
}

function updateProcessButton() {
  const provider = byId("providerSelect").value;
  let ready = state.connected && state.files.some((file) => !file.error) && Boolean(state.outputDir);
  if (provider === "ollama") ready = ready && Boolean(byId("ollamaModel").value.trim());
  if (provider === "openai") {
    ready = ready && Boolean(byId("openaiModel").value.trim()) && Boolean(byId("openaiKey").value.trim());
    ready = ready && byId("remoteConsent").checked;
  }
  byId("processBtn").disabled = !ready;

  const labels = {
    none: "一键解密并整理",
    rule: "一键解密、整理并生成本地初评",
    ollama: "一键解密、整理并生成本地 AI 初评",
    openai: "一键解密、整理并生成 AI 初评",
  };
  byId("processBtnLabel").textContent = labels[provider] || labels.rule;
}

function renderFiles() {
  const tbody = byId("fileTableBody");
  if (state.files.length === 0) {
    byId("emptyFileState").classList.remove("hidden");
    byId("fileTableWrap").classList.add("hidden");
    tbody.innerHTML = "";
    updateProcessButton();
    return;
  }
  byId("emptyFileState").classList.add("hidden");
  byId("fileTableWrap").classList.remove("hidden");
  tbody.innerHTML = state.files
    .map((file, index) => {
      const status = file.error
        ? `<span class="badge danger">${escapeHtml(file.error)}</span>`
        : file.encrypted === true
          ? '<span class="badge warning">需要密码</span>'
          : file.encrypted === false
            ? '<span class="badge success">未加密</span>'
            : '<span class="badge">未知</span>';
      return `
        <tr>
          <td>
            <span class="file-name">${escapeHtml(file.name)}</span>
            <span class="file-path" title="${escapeHtml(file.path)}">${escapeHtml(file.path)}</span>
          </td>
          <td>${displayNumber(file.size_mb, " MB")}</td>
          <td>${status}</td>
          <td><input class="per-file-password" data-index="${index}" type="password" autocomplete="new-password" placeholder="不同时填写" ${file.error ? "disabled" : ""}></td>
          <td><button class="icon-button remove remove-file" data-index="${index}" title="移除">×</button></td>
        </tr>`;
    })
    .join("");

  document.querySelectorAll(".remove-file").forEach((button) => {
    button.addEventListener("click", () => {
      state.files.splice(Number(button.dataset.index), 1);
      renderFiles();
    });
  });
  document.querySelectorAll(".per-file-password").forEach((input) => {
    input.addEventListener("input", updateProcessButton);
  });
  updateProcessButton();
}

async function chooseFiles() {
  const result = await api("choose_pdf_files");
  if (!result?.ok) {
    if (result?.message) toast(result.message, "warning");
    return;
  }
  const existing = new Set(state.files.map((file) => file.path));
  for (const file of result.files || []) {
    if (!existing.has(file.path)) {
      state.files.push(file);
      existing.add(file.path);
    }
  }
  renderFiles();
}

async function chooseOutputFolder() {
  const result = await api("choose_output_folder");
  if (!result?.ok) {
    if (result?.message) toast(result.message, "warning");
    return;
  }
  if (result.path) {
    state.outputDir = result.path;
    byId("outputDir").value = result.path;
    updateProcessButton();
  }
}

function currentProcessSettings() {
  const provider = byId("providerSelect").value;
  let model = "";
  if (provider === "ollama") model = byId("ollamaModel").value.trim();
  if (provider === "openai") model = byId("openaiModel").value.trim();
  return {
    provider,
    model,
    api_key: provider === "openai" ? byId("openaiKey").value.trim() : "",
    ollama_url: byId("ollamaUrl").value.trim() || "http://127.0.0.1:11434",
    guide: byId("guideText").value,
  };
}

async function processBatch() {
  const settings = currentProcessSettings();
  if (settings.provider === "openai" && !byId("remoteConsent").checked) {
    toast("请先确认外部模型的数据发送范围。", "warning");
    return;
  }
  const passwordInputs = [...document.querySelectorAll(".per-file-password")];
  const files = state.files
    .filter((file) => !file.error)
    .map((file, index) => {
      const originalIndex = state.files.indexOf(file);
      const input = passwordInputs.find((node) => Number(node.dataset.index) === originalIndex);
      return { path: file.path, password: input?.value || "" };
    });

  const payload = {
    files,
    output_dir: state.outputDir,
    batch_name: byId("batchName").value.trim(),
    common_password: byId("commonPassword").value,
    ...settings,
  };

  showBusy("正在本地处理申请书", `共 ${files.length} 个文件。PDF 较大时可能需要几分钟。`);
  try {
    const result = await api("process_batch", payload);
    if (!result?.ok) {
      showErrors(result?.errors);
      toast(result?.message || "处理失败。", "error", 9000);
      return;
    }
    state.batch = result.batch;
    state.selectedIndex = 0;
    state.detail = null;
    clearSecrets();
    renderBatch();
    showErrors(result.errors);
    toast(result.message || "处理完成。", "success");
    switchTab("review");
    await loadRecordDetail(0);
  } catch (error) {
    toast(error.message || String(error), "error", 9000);
  } finally {
    hideBusy();
  }
}

function clearSecrets() {
  byId("commonPassword").value = "";
  document.querySelectorAll(".per-file-password").forEach((input) => { input.value = ""; });
  byId("openaiKey").value = "";
  byId("remoteConsent").checked = false;
  byId("finalApiKey").value = "";
  updateProcessButton();
}

function renderBatch() {
  const hasBatch = Boolean(state.batch?.records?.length);
  byId("reviewEmpty").classList.toggle("hidden", hasBatch);
  byId("reviewContent").classList.toggle("hidden", !hasBatch);
  byId("scoreEmpty").classList.toggle("hidden", hasBatch);
  byId("scoreContent").classList.toggle("hidden", !hasBatch);
  byId("outputEmpty").classList.toggle("hidden", hasBatch);
  byId("outputContent").classList.toggle("hidden", !hasBatch);

  if (!hasBatch) return;
  if (state.selectedIndex >= state.batch.records.length) state.selectedIndex = 0;
  renderRecordList();
  renderScoreSelect();
  renderRanking();
  renderOutputPaths();
  byId("reviewBatchCount").textContent = `${state.batch.count} 份申请书`;

  const provider = state.batch.provider || "rule";
  if (["rule", "ollama", "openai"].includes(provider)) {
    byId("finalProvider").value = provider;
  }
  if (state.batch.model) byId("finalModel").value = state.batch.model;
  updateFinalProviderUI();
}

function recordBadge(record) {
  if (record.manual_grade) return `<span class="badge primary">${escapeHtml(record.manual_grade)}</span>`;
  if (record.ai_grade) return `<span class="badge">${escapeHtml(record.ai_grade)}</span>`;
  return '<span class="badge">待评</span>';
}

function renderRecordList() {
  byId("recordList").innerHTML = state.batch.records
    .map((record) => `
      <button class="record-list-item ${record.index === state.selectedIndex ? "active" : ""}" data-index="${record.index}">
        <strong>${escapeHtml(record.applicant_name || "未识别申请人")}</strong>
        <span class="record-project">${escapeHtml(record.project_title || record.source_file)}</span>
        <span class="record-list-meta">
          ${recordBadge(record)}
          <span>${record.rank ? `第 ${record.rank} 名` : displayNumber(record.total_score, " 分")}</span>
        </span>
      </button>`)
    .join("");
  document.querySelectorAll(".record-list-item").forEach((button) => {
    button.addEventListener("click", async () => {
      state.selectedIndex = Number(button.dataset.index);
      renderRecordList();
      byId("scoreRecordSelect").value = String(state.selectedIndex);
      await loadRecordDetail(state.selectedIndex);
    });
  });
}

function renderScoreSelect() {
  byId("scoreRecordSelect").innerHTML = state.batch.records
    .map((record) => `<option value="${record.index}">${escapeHtml(record.applicant_name || "未识别")}｜${escapeHtml(record.project_title || record.source_file)}</option>`)
    .join("");
  byId("scoreRecordSelect").value = String(state.selectedIndex);
}

async function loadRecordDetail(index) {
  showBusy("正在载入项目详情", "读取本地结构化数据。 ");
  try {
    const result = await api("get_record_detail", Number(index));
    if (!result?.ok) {
      toast(result?.message || "无法载入项目详情。", "error");
      return;
    }
    state.detail = result.detail;
    state.selectedIndex = Number(index);
    renderRecordDetail();
    populateScoreForm();
  } finally {
    hideBusy();
  }
}

function renderRecordDetail() {
  if (!state.detail) return;
  const { summary, basic } = state.detail;
  byId("recordHero").innerHTML = `
    <span class="hero-applicant">${escapeHtml(summary.applicant_name || "未识别申请人")}</span>
    <h2>${escapeHtml(summary.project_title || summary.source_file)}</h2>
    <p>${escapeHtml(summary.institution || "未识别依托单位")} · ${escapeHtml(summary.program_type || "未识别项目类别")}</p>
    <div class="hero-meta">
      ${recordBadge(summary)}
      <span class="badge">${escapeHtml(summary.funding_summary)}</span>
      <span class="badge">${escapeHtml(summary.recent_publication_summary)}</span>
    </div>`;

  renderBasicPanel(basic);
  renderCareerPanel();
  renderPapersPanel();
  renderInitialPanel();
  renderSectionsPanel();
  switchDetailTab(state.activeDetailTab);
}

function infoItem(label, value, full = false) {
  return `<div class="info-item ${full ? "full" : ""}"><span>${escapeHtml(label)}</span><strong>${nl2br(displayValue(value))}</strong></div>`;
}

function renderBasicPanel(basic) {
  const partners = Array.isArray(basic.partner_institutions) ? basic.partner_institutions.join("；") : "";
  byId("detail-basic").innerHTML = `
    <div class="info-grid">
      ${infoItem("申请代码", basic.application_code)}
      ${infoItem("接收编号", basic.admission_no)}
      ${infoItem("资助类别", basic.program_type)}
      ${infoItem("申请人", basic.applicant_name)}
      ${infoItem("职称", basic.current_title || basic.proposed_title)}
      ${infoItem("依托单位", basic.current_institution || basic.proposed_institution)}
      ${infoItem("研究领域", basic.research_field)}
      ${infoItem("研究方向", basic.research_direction)}
      ${infoItem("研究期限", basic.research_period)}
      ${infoItem("申请直接费用", displayNumber(basic.requested_amount_wan, " 万元"))}
      ${infoItem("团队人数", displayNumber(basic.team_total, " 人"))}
      ${infoItem("高级职称", displayNumber(basic.team_senior, " 人"))}
      ${infoItem("合作单位", partners, true)}
      ${infoItem("关键词", basic.keywords, true)}
    </div>
    <div class="inline-edit-card">
      <h3>人工校正关键字段</h3>
      <div class="form-grid">
        <label class="field"><span>申请人</span><input id="editApplicant" value="${escapeHtml(basic.applicant_name)}"></label>
        <label class="field"><span>项目名称</span><input id="editProject" value="${escapeHtml(basic.project_title)}"></label>
        <label class="field"><span>依托单位</span><input id="editInstitution" value="${escapeHtml(basic.current_institution || basic.proposed_institution)}"></label>
        <label class="field"><span>职称</span><input id="editTitle" value="${escapeHtml(basic.current_title || basic.proposed_title)}"></label>
        <label class="field"><span>直接费用（万元）</span><input id="editAmount" type="number" step="0.01" value="${escapeHtml(basic.requested_amount_wan ?? "")}"></label>
        <label class="field"><span>团队总人数</span><input id="editTeamTotal" type="number" step="1" value="${escapeHtml(basic.team_total ?? "")}"></label>
      </div>
      <div class="button-row"><button id="saveBasicBtn" class="button secondary">保存校正</button></div>
    </div>`;
  byId("saveBasicBtn").addEventListener("click", saveBasicEdits);
}

function timeline(items, type) {
  if (!Array.isArray(items) || items.length === 0) return '<div class="mode-note">申请书中未识别到相关记录。</div>';
  return `<div class="timeline">${items.map((item) => {
    const title = type === "education"
      ? `${item.level || "教育经历"}｜${item.institution || ""}`
      : `${item.title || (item.category === "postdoc" ? "博士后" : "工作经历")}｜${item.institution || ""}`;
    const details = type === "education"
      ? [item.major, item.start && item.end ? `${item.start} 至 ${item.end}` : ""].filter(Boolean).join("；")
      : [item.department, item.start && item.end ? `${item.start} 至 ${item.end}` : ""].filter(Boolean).join("；");
    return `<div class="timeline-item"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(details || item.raw || "")}</p></div>`;
  }).join("")}</div>`;
}

function renderCareerPanel() {
  const fundingRows = (state.detail.funding || []).map((item) => `
    <tr>
      <td>${escapeHtml(item.source_type)}</td>
      <td>${escapeHtml(item.program_type)}</td>
      <td>${escapeHtml(item.grant_no)}</td>
      <td>${escapeHtml(item.title)}</td>
      <td>${escapeHtml(item.status)}</td>
      <td>${escapeHtml(item.role)}</td>
    </tr>`).join("");
  byId("detail-career").innerHTML = `
    <div class="detail-section">
      <div class="detail-section-title"><h3>教育经历</h3><span class="badge">${state.detail.education?.length || 0} 条</span></div>
      ${timeline(state.detail.education, "education")}
    </div>
    <div class="detail-section">
      <div class="detail-section-title"><h3>博士后与工作经历</h3><span class="badge">${state.detail.work_history?.length || 0} 条</span></div>
      ${timeline(state.detail.work_history, "work")}
    </div>
    <div class="detail-section">
      <div class="detail-section-title"><h3>基金主持与参与</h3><span class="badge primary">${escapeHtml(state.detail.summary.funding_summary)}</span></div>
      ${fundingRows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>来源</th><th>类别</th><th>批准号</th><th>项目名称</th><th>状态</th><th>角色</th></tr></thead><tbody>${fundingRows}</tbody></table></div>` : '<div class="mode-note">申请书中未识别到可结构化的基金记录。</div>'}
    </div>`;
}

function renderPapersPanel() {
  const rows = (state.detail.publications || []).map((item) => `
    <tr>
      <td>${item.is_representative ? '<span class="badge primary">代表作</span>' : '<span class="badge">其他</span>'}</td>
      <td>${escapeHtml(item.year ?? "")}</td>
      <td>${escapeHtml(item.journal)}</td>
      <td>${escapeHtml(item.title || item.citation)}</td>
      <td>${escapeHtml(item.role_label)}</td>
    </tr>`).join("");
  byId("detail-papers").innerHTML = `
    <div class="review-grid">
      <div class="review-box full">
        <h3>论文概况</h3>
        <p>${escapeHtml(state.detail.summary.publication_summary)}</p>
        <p><strong>近期情况：</strong>${escapeHtml(state.detail.summary.recent_publication_summary)}</p>
      </div>
    </div>
    <div class="detail-section top-gap">
      ${rows ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>类型</th><th>年份</th><th>期刊</th><th>题目</th><th>本人署名</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="mode-note">未识别到论文条目，请人工核对申请人简历。</div>'}
    </div>`;
}

function bulletList(items) {
  if (!Array.isArray(items) || items.length === 0) return "<p>—</p>";
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderInitialPanel() {
  const ai = state.detail.ai_review || {};
  byId("detail-initial").innerHTML = `
    <div class="review-grid">
      <div class="review-box full">
        <h3>总体初评 <span class="badge primary">${escapeHtml(ai.preliminary_grade || "暂不判级")}</span></h3>
        <p>${escapeHtml(ai.overall_assessment || "尚未生成初评。")}</p>
      </div>
      <div class="review-box positive"><h3>主要优势</h3>${bulletList(ai.strengths)}</div>
      <div class="review-box caution"><h3>需要进一步论证</h3>${bulletList(ai.weaknesses)}</div>
      <div class="review-box"><h3>实施风险</h3>${bulletList(ai.risks)}</div>
      <div class="review-box"><h3>证据缺口</h3>${bulletList(ai.evidence_gaps)}</div>
      <div class="review-box full"><h3>基金经历评价</h3><p>${escapeHtml(ai.funding_history_assessment || "—")}</p></div>
      <div class="review-box full"><h3>论文发表情况评价</h3><p>${escapeHtml(ai.publication_assessment || "—")}</p></div>
    </div>
    <div class="button-row top-gap"><button id="regenerateCurrentBtn" class="button secondary">按“一键处理”页当前设置重新生成本项目初评</button></div>`;
  byId("regenerateCurrentBtn").addEventListener("click", regenerateCurrentInitialReview);
}

function renderSectionsPanel() {
  const entries = Object.entries(state.detail.sections || {});
  if (entries.length === 0) {
    byId("detail-sections").innerHTML = '<div class="mode-note">未能稳定提取正文区块。</div>';
    return;
  }
  byId("detail-sections").innerHTML = entries
    .map(([name, text], index) => `<details class="section-accordion" ${index === 0 ? "open" : ""}><summary>${escapeHtml(name)}</summary><pre>${escapeHtml(text)}</pre></details>`)
    .join("");
}

async function saveBasicEdits() {
  showBusy("正在保存人工校正", "同步更新本地 Excel 与 JSON。 ");
  try {
    const currentBasic = state.detail.basic;
    const result = await api("update_record", state.selectedIndex, {
      basic: {
        applicant_name: byId("editApplicant").value,
        project_title: byId("editProject").value,
        current_institution: currentBasic.current_institution ? byId("editInstitution").value : "",
        proposed_institution: currentBasic.current_institution ? currentBasic.proposed_institution : byId("editInstitution").value,
        current_title: currentBasic.current_title ? byId("editTitle").value : "",
        proposed_title: currentBasic.current_title ? currentBasic.proposed_title : byId("editTitle").value,
        requested_amount_wan: byId("editAmount").value,
        team_total: byId("editTeamTotal").value,
      },
    });
    if (!result?.ok) throw new Error(result?.message || "保存失败");
    state.batch = result.batch;
    state.detail = result.detail;
    renderBatch();
    renderRecordDetail();
    toast("关键字段已保存。", "success");
  } catch (error) {
    toast(error.message || String(error), "error");
  } finally {
    hideBusy();
  }
}

async function regenerateCurrentInitialReview() {
  const settings = currentProcessSettings();
  if (settings.provider === "none") {
    toast("请先在“一键处理”页选择一种初评方式。", "warning");
    return;
  }
  if (settings.provider === "openai") {
    if (!settings.api_key || !byId("remoteConsent").checked) {
      toast("使用 OpenAI 时，请在“一键处理”页重新输入临时 API Key 并确认数据范围。", "warning", 8000);
      return;
    }
  }
  showBusy("正在重新生成初评", "只处理当前申请书。 ");
  try {
    const result = await api("generate_initial_reviews", { ...settings, indexes: [state.selectedIndex] });
    showErrors(result?.errors);
    if (!result?.batch) throw new Error(result?.message || "生成失败");
    state.batch = result.batch;
    clearSecrets();
    await loadRecordDetail(state.selectedIndex);
    renderBatch();
    toast(result.ok ? "初评已更新。" : "初评完成，但部分步骤出现问题。", result.ok ? "success" : "warning");
  } catch (error) {
    toast(error.message || String(error), "error");
  } finally {
    hideBusy();
  }
}

function scoreInputIds() {
  return ["scoreScientific", "scoreInnovation", "scoreTeam", "scoreBreakthrough", "scoreBudget"];
}

function numberOrEmpty(value) {
  return value === null || value === undefined ? "" : String(value);
}

function populateScoreForm() {
  if (!state.detail) return;
  const manual = state.detail.manual_review || {};
  byId("scoreScientific").value = numberOrEmpty(manual.scientific_question_score);
  byId("scoreInnovation").value = numberOrEmpty(manual.innovation_score);
  byId("scoreTeam").value = numberOrEmpty(manual.applicant_team_score);
  byId("scoreBreakthrough").value = numberOrEmpty(manual.breakthrough_score);
  byId("scoreBudget").value = numberOrEmpty(manual.budget_score);
  byId("overallGrade").value = manual.overall_grade || "";
  byId("fundingOpinion").value = manual.funding_opinion || "";
  byId("reviewerNotes").value = manual.reviewer_notes || "";
  byId("finalReviewText").value = state.detail.ai_review?.final_review || "";
  updateScoreTotal();
}

function updateScoreTotal() {
  const values = scoreInputIds().map((id) => {
    const raw = byId(id).value;
    return raw === "" ? null : Number(raw);
  });
  const valid = values.filter((value) => Number.isFinite(value));
  byId("scoreTotal").textContent = valid.length ? valid.reduce((a, b) => a + b, 0).toFixed(1).replace(/\.0$/, "") : "—";
}

function manualPayload() {
  return {
    scientific_question_score: byId("scoreScientific").value,
    innovation_score: byId("scoreInnovation").value,
    applicant_team_score: byId("scoreTeam").value,
    breakthrough_score: byId("scoreBreakthrough").value,
    budget_score: byId("scoreBudget").value,
    overall_grade: byId("overallGrade").value,
    funding_opinion: byId("fundingOpinion").value,
    reviewer_notes: byId("reviewerNotes").value,
  };
}

async function saveCurrentScore(showNotification = true) {
  if (!state.detail) return null;
  const result = await api("update_record", state.selectedIndex, {
    manual_review: manualPayload(),
    final_review: byId("finalReviewText").value,
  });
  if (!result?.ok) throw new Error(result?.message || "保存评分失败");
  state.batch = result.batch;
  state.detail = result.detail;
  renderBatch();
  renderRecordDetail();
  populateScoreForm();
  if (showNotification) toast("评分与评语已保存，并同步更新 Excel。", "success");
  return result;
}

function renderRanking() {
  if (!state.batch?.records) return;
  const records = [...state.batch.records].sort((a, b) => {
    if (a.rank && b.rank) return a.rank - b.rank;
    if (a.rank) return -1;
    if (b.rank) return 1;
    return a.index - b.index;
  });
  byId("rankingTableBody").innerHTML = records.map((record) => `
    <tr>
      <td>${record.rank || "—"}</td>
      <td>${escapeHtml(record.applicant_name || "未识别")}</td>
      <td>${displayNumber(record.total_score)}</td>
      <td>${escapeHtml(record.manual_grade || "—")}</td>
      <td>${escapeHtml(record.funding_opinion || "—")}</td>
    </tr>`).join("");
}

async function generateFinalReviews() {
  try {
    showBusy("正在保存当前评分", "随后将为整个批次起草正式评语。 ");
    await saveCurrentScore(false);

    const provider = byId("finalProvider").value;
    const model = byId("finalModel").value.trim();
    const apiKey = byId("finalApiKey").value.trim();
    if (provider === "ollama" && !model) throw new Error("请填写本地 Ollama 模型名称。 ");
    if (provider === "openai") {
      if (!model || !apiKey) throw new Error("请填写 OpenAI 模型和临时 API Key。 ");
      const accepted = window.confirm("将向外部模型发送每份申请书的结构化字段与必要正文片段。PDF 文件和 PDF 密码不会发送。是否继续？");
      if (!accepted) return;
    }
    showBusy("正在生成批次评语", "系统将严格遵循你填写的综合等级和资助意见。 ");
    const result = await api("generate_final_reviews", {
      provider,
      model,
      api_key: apiKey,
      ollama_url: byId("ollamaUrl").value.trim() || "http://127.0.0.1:11434",
      guide: byId("guideText").value,
    });
    showErrors(result?.errors);
    if (!result?.batch) throw new Error(result?.message || "评语生成失败");
    state.batch = result.batch;
    byId("finalApiKey").value = "";
    renderBatch();
    await loadRecordDetail(state.selectedIndex);
    toast(result.ok ? "整个批次的评语已生成。" : "已处理批次，但部分项目未生成评语。", result.ok ? "success" : "warning", 9000);
  } catch (error) {
    toast(error.message || String(error), "error", 9000);
  } finally {
    hideBusy();
  }
}

function renderOutputPaths() {
  if (!state.batch) return;
  byId("batchDirPath").textContent = state.batch.batch_dir || "—";
  byId("batchDirPath").title = state.batch.batch_dir || "";
  byId("excelPath").textContent = state.batch.excel_path || "—";
  byId("excelPath").title = state.batch.excel_path || "";
  byId("jsonPath").textContent = state.batch.json_path || "—";
  byId("jsonPath").title = state.batch.json_path || "";
}

async function exportBatch() {
  showBusy("正在更新本地文件", "写入 Excel 与批次 JSON。 ");
  try {
    const result = await api("export_batch");
    if (!result?.ok) throw new Error(result?.message || "导出失败");
    state.batch = result.batch;
    renderBatch();
    toast(result.message || "本地文件已更新。", "success");
  } catch (error) {
    toast(error.message || String(error), "error");
  } finally {
    hideBusy();
  }
}

async function loadExistingBatch() {
  showBusy("正在载入已有批次", "读取本地批次数据。 ");
  try {
    const result = await api("choose_batch_file");
    if (!result?.ok) {
      if (result?.message && result.message !== "未选择文件。") toast(result.message, "warning");
      return;
    }
    state.batch = result.batch;
    state.selectedIndex = 0;
    state.detail = null;
    renderBatch();
    await loadRecordDetail(0);
    switchTab("review");
    toast(result.message || "批次已载入。", "success");
  } catch (error) {
    toast(error.message || String(error), "error");
  } finally {
    hideBusy();
  }
}

async function clearBatch() {
  if (!state.batch) return;
  const accepted = window.confirm("仅清除应用内存中的当前批次；已经保存到本地的 PDF、Excel 和 JSON 不会删除。是否继续？");
  if (!accepted) return;
  const result = await api("clear_batch");
  if (!result?.ok) {
    toast(result?.message || "清除失败。", "error");
    return;
  }
  state.batch = null;
  state.detail = null;
  state.selectedIndex = 0;
  renderBatch();
  switchTab("process");
  toast("当前内存中的批次已清除，本地输出文件仍保留。", "success");
}

async function detectOllama() {
  showBusy("正在检测本地 Ollama", "只访问 127.0.0.1。 ");
  try {
    const result = await api("detect_ollama_models", byId("ollamaUrl").value.trim());
    if (!result?.ok) throw new Error(result?.message || "未检测到 Ollama");
    const models = result.models || [];
    if (models.length === 0) {
      toast("检测到 Ollama，但尚无已下载模型。", "warning");
      return;
    }
    byId("ollamaModel").value = models[0];
    updateProcessButton();
    toast(`检测到 ${models.length} 个本地模型，已选择 ${models[0]}。`, "success");
  } catch (error) {
    toast(error.message || String(error), "warning", 8000);
  } finally {
    hideBusy();
  }
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelectorAll(".jump-process").forEach((button) => {
    button.addEventListener("click", () => switchTab("process"));
  });
  document.querySelectorAll(".subnav-item").forEach((button) => {
    button.addEventListener("click", () => switchDetailTab(button.dataset.subtab));
  });

  byId("chooseFilesBtn").addEventListener("click", chooseFiles);
  byId("chooseOutputBtn").addEventListener("click", chooseOutputFolder);
  byId("chooseOutputInlineBtn").addEventListener("click", chooseOutputFolder);
  byId("providerSelect").addEventListener("change", updateProviderUI);
  byId("ollamaModel").addEventListener("input", updateProcessButton);
  byId("openaiModel").addEventListener("input", updateProcessButton);
  byId("openaiKey").addEventListener("input", updateProcessButton);
  byId("remoteConsent").addEventListener("change", updateProcessButton);
  byId("detectOllamaBtn").addEventListener("click", detectOllama);
  byId("processBtn").addEventListener("click", processBatch);

  byId("refreshBatchBtn").addEventListener("click", async () => {
    const result = await api("get_batch_summary");
    if (result?.ok) {
      state.batch = result.batch;
      renderBatch();
      await loadRecordDetail(state.selectedIndex);
    }
  });

  byId("scoreRecordSelect").addEventListener("change", async (event) => {
    state.selectedIndex = Number(event.target.value);
    renderRecordList();
    await loadRecordDetail(state.selectedIndex);
  });
  scoreInputIds().forEach((id) => byId(id).addEventListener("input", updateScoreTotal));
  byId("saveScoreBtn").addEventListener("click", async () => {
    showBusy("正在保存评分", "同步更新本地 Excel 与 JSON。 ");
    try {
      await saveCurrentScore(true);
    } catch (error) {
      toast(error.message || String(error), "error");
    } finally {
      hideBusy();
    }
  });
  byId("generateFinalBtn").addEventListener("click", generateFinalReviews);
  byId("finalProvider").addEventListener("change", updateFinalProviderUI);

  byId("loadBatchBtn").addEventListener("click", loadExistingBatch);
  byId("exportBtn").addEventListener("click", exportBatch);
  byId("openFolderBtn").addEventListener("click", async () => {
    const result = await api("open_output_folder");
    if (!result?.ok) toast(result?.message || "无法打开输出文件夹。", "error");
  });
  byId("clearBatchBtn").addEventListener("click", clearBatch);
}

async function initialize() {
  bindEvents();
  updateProviderUI();
  updateFinalProviderUI();
  renderFiles();
  renderBatch();

  try {
    const result = await api("ping");
    if (!result?.ok) throw new Error(result?.message || "连接失败");
    state.connected = true;
    byId("versionBadge").textContent = `v${result.version || "0.1.0"}`;
    byId("guideText").value = result.default_guide || "";
    state.outputDir = result.default_output_dir || "";
    byId("outputDir").value = state.outputDir;
    byId("footerStatus").textContent = `本地引擎已连接 · ${result.platform || "desktop"}`;
    updateProcessButton();
  } catch (error) {
    byId("footerStatus").textContent = "未连接本地引擎";
    toast(error.message || String(error), "error", 12000);
  }
}

window.addEventListener("pywebviewready", initialize);

// Helpful message when index.html is accidentally opened directly in a normal browser.
window.setTimeout(() => {
  if (!state.connected && !window.pywebview) {
    byId("footerStatus").textContent = "请通过桌面应用启动，而不是直接双击 index.html";
  }
}, 1800);
