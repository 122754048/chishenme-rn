"use strict";

const state = { job: null, task: null, pollTimer: null, batchFile: null, batch: null, batchPreflighted: false };
const form = document.querySelector("#intake-form");
const notice = document.querySelector("#notice");
const workspace = document.querySelector("#workspace");
const taskBox = document.querySelector("#task-json");

function api(path, options = {}) {
  return fetch("/api/" + path, options).then(async (response) => {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const code = payload && payload.code ? payload.code : "REQUEST_FAILED";
      throw new Error(code);
    }
    return payload;
  });
}

function showNotice(message, kind = "info") {
  notice.textContent = message;
  notice.className = "notice " + kind;
  window.setTimeout(() => notice.classList.add("hidden"), 5200);
}

function optionPresent() {
  const data = new FormData(form);
  const files = ["new_product_image", "new_model_image", "ui_screenshot", "ui_operation_video", "tail_video", "background_music"];
  return Boolean(data.get("app_store_url") || data.get("output_language") || files.some((name) => data.get(name) && data.get(name).size));
}

function validateIntake() {
  const data = new FormData(form);
  const source = data.get("source_video");
  const admissible = Boolean(source && source.size && optionPresent());
  document.querySelector("#create-job").disabled = !admissible;
  document.querySelector("#intake-hint").textContent = admissible
    ? "入口条件满足：可以创建任务。"
    : "必须上传原视频，并至少添加一项可选素材或指定输出语言。";
}

function setText(id, value) { document.querySelector(id).textContent = value; }

function latest(kind) {
  const revisions = (state.job.reviews || {})[kind] || [];
  return revisions[revisions.length - 1] || null;
}

function renderJob(job) {
  state.job = job;
  workspace.classList.remove("hidden");
  const provider = job.provider || {};
  const summary = document.querySelector("#job-summary");
  summary.replaceChildren();
  ["job_id", "stage", "version", "route", "output_language"].forEach((key) => {
    const item = document.createElement("div");
    const label = document.createElement("span"); label.textContent = key;
    const value = document.createElement("strong"); value.textContent = String(job[key] || "—");
    item.append(label, value); summary.append(item);
  });
  document.querySelectorAll("#timeline [data-stage]").forEach((node) => {
    node.classList.toggle("active", node.dataset.stage === job.stage);
  });
  renderReviews();
  renderRoutePreview(job.route_preview || {});
  renderTimingLedger(job.timing_ledger || {});
  renderProvider(provider);
  renderQaReceipt(job.qa_receipt || {});
  renderInputs(job.inputs || {});
  renderArtifacts(job.artifacts || []);
  schedulePolling(provider);
}

function renderRoutePreview(preview) {
  const target = document.querySelector("#route-preview");
  target.replaceChildren();
  const music = preview.background_music || {};
  const values = [
    ["mode", preview.run_mode || "pending"],
    ["analysis", preview.deep_analysis || "pending"],
    ["generate", (preview.generate_region_ids || []).join(", ") || "none"],
    ["splice", (preview.splice_region_ids || []).join(", ") || "none"],
    ["skip", (preview.skip_modules || []).join(", ") || "none"],
    ["audio", JSON.stringify(preview.audio_policy || {})],
    ["music", music.enabled ? String(music.timeline_status || "required") : "off"],
    ["music windows", JSON.stringify(music.source_windows || [])],
    ["uploaded music", JSON.stringify(music.uploaded_music_mapping || [])],
    ["singers", (music.visible_singer_regions || []).join(", ") || "none"],
    ["music risks", (music.risks || []).join(", ") || "none"],
  ];
  values.forEach(([label, value]) => {
    const line = document.createElement("div");
    const name = document.createElement("span"); name.textContent = label;
    const content = document.createElement("strong"); content.textContent = String(value);
    line.append(name, content); target.append(line);
  });
}

function renderTimingLedger(ledger) {
  const target = document.querySelector("#timing-ledger");
  target.replaceChildren();
  if (!ledger || !Object.keys(ledger).length) {
    target.textContent = "No stored receipt.";
    return;
  }
  ["queue_wait_ms", "active_ms", "provider_wait_ms", "retry_count", "cache_hit"].forEach((key) => {
    if (ledger[key] === undefined || ledger[key] === null) return;
    const line = document.createElement("div");
    const name = document.createElement("span"); name.textContent = key;
    const value = document.createElement("strong"); value.textContent = String(ledger[key]);
    line.append(name, value); target.append(line);
  });
  (ledger.stages || []).forEach((stage) => {
    if (!stage || !stage.name) return;
    const line = document.createElement("div");
    const name = document.createElement("span"); name.textContent = String(stage.name);
    const value = document.createElement("strong");
    value.textContent = String(stage.status || "unknown") + (stage.skipped_reason ? ": " + String(stage.skipped_reason) : "");
    line.append(name, value); target.append(line);
  });
}

function renderReviews() {
  const script = latest("script");
  const board = latest("storyboard");
  const scriptPanel = document.querySelector("#script-panel");
  const boardPanel = document.querySelector("#storyboard-panel");
  scriptPanel.classList.toggle("hidden", state.job.stage !== "SCRIPT_REVIEW");
  boardPanel.classList.toggle("hidden", state.job.stage !== "STORYBOARD_REVIEW");
  if (script) document.querySelector("#script-content").value = script.content || "";
  const boardContent = document.querySelector("#storyboard-content");
  boardContent.replaceChildren();
  if (board) appendStoryboard(boardContent, board.content);
}

function appendStoryboard(root, content) {
  const display = document.createElement("pre");
  display.textContent = JSON.stringify(content || {}, null, 2);
  root.append(display);
  const frames = content && Array.isArray(content.frames) ? content.frames : [];
  frames.forEach((frame, index) => {
    const card = document.createElement("article"); card.className = "board-card";
    const title = document.createElement("strong"); title.textContent = "镜头 " + (index + 1);
    const caption = document.createElement("p"); caption.textContent = typeof frame === "string" ? frame : JSON.stringify(frame);
    card.append(title, caption); root.append(card);
  });
}

function renderProvider(provider) {
  const target = document.querySelector("#provider-status");
  target.replaceChildren();
  const values = [
    ["状态", provider.status || provider.state || "等待 Codex 结果"],
    ["工作流", provider.request && provider.request.workflow_id || "—"],
    ["请求摘要", provider.request_sha256 || "—"],
    ["任务 ID", provider.task_id || "—"]
  ];
  values.forEach(([label, value]) => {
    const line = document.createElement("div");
    const name = document.createElement("span"); name.textContent = label;
    const content = document.createElement("strong"); content.textContent = String(value);
    line.append(name, content); target.append(line);
  });
}

function renderArtifacts(artifacts) {
  const target = document.querySelector("#artifact-list");
  target.replaceChildren();
  artifacts.forEach((artifact) => {
    const card = document.createElement("article"); card.className = "artifact";
    const title = document.createElement("strong"); title.textContent = artifact.role + " · " + artifact.filename;
    const link = document.createElement("a");
    link.href = "/api/jobs/" + encodeURIComponent(state.job.job_id) + "/artifacts/" + encodeURIComponent(artifact.artifact_id);
    link.textContent = "下载"; link.download = artifact.filename;
    card.append(title);
    if ((artifact.mime_type || "").startsWith("video/")) {
      const video = document.createElement("video"); video.controls = true; video.src = link.href; card.append(video);
    }
    card.append(link); target.append(card);
  });
}

function renderInputs(inputs) {
  const target = document.querySelector("#input-list");
  target.replaceChildren();
  Object.entries(inputs).forEach(([slot, record]) => {
    if (record.kind !== "file") return;
    const card = document.createElement("article"); card.className = "artifact";
    const title = document.createElement("strong"); title.textContent = slot + " · " + record.original_name;
    const link = document.createElement("a");
    link.href = "/api/jobs/" + encodeURIComponent(state.job.job_id) + "/inputs/" + encodeURIComponent(slot);
    link.textContent = "查看原始输入"; link.target = "_blank";
    card.append(title);
    if ((record.mime_type || "").startsWith("video/")) {
      const video = document.createElement("video"); video.controls = true; video.src = link.href; card.append(video);
    } else if ((record.mime_type || "").startsWith("image/")) {
      const image = document.createElement("img"); image.src = link.href; image.alt = slot; image.loading = "lazy"; card.append(image);
    }
    card.append(link); target.append(card);
  });
}

function schedulePolling(provider) {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  if (!provider.task_id || ["SUCCESS", "FAILED", "CANCELLED"].includes(provider.status)) return;
  state.pollTimer = window.setTimeout(async () => {
    try {
      const result = await api("jobs/" + encodeURIComponent(state.job.job_id) + "/provider/poll", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_version: state.job.version })
      });
      renderJob(result);
    } catch (error) { showNotice("Provider 轮询：" + error.message, "error"); }
  }, providerPollDelay(provider));
}

function renderQaReceipt(receipt) {
  const target = document.querySelector("#qa-receipt");
  target.replaceChildren();
  if (!receipt || !Object.keys(receipt).length) {
    target.textContent = "No stored receipt.";
    return;
  }
  const music = receipt.background_music_delivery || {};
  const mix = music.mix_receipt || {};
  const singing = music.route && music.route.singing_qa || {};
  const values = [
    ["passed", receipt.passed],
    ["final audio", music.final_audio_sha256],
    ["mix", mix.passed],
    ["music windows", Array.isArray(mix.window_receipts) ? mix.window_receipts.length : undefined],
    ["singing receipts", Array.isArray(singing.regions) ? singing.regions.length : undefined],
  ];
  values.forEach(([label, value]) => {
    if (value === undefined || value === null || value === "") return;
    const line = document.createElement("div");
    const name = document.createElement("span"); name.textContent = label;
    const content = document.createElement("strong"); content.textContent = String(value);
    line.append(name, content); target.append(line);
  });
}

function providerPollDelay(provider) {
  const status = String(provider.status || provider.state || "").toUpperCase();
  if (["QUEUED", "PENDING", "REQUEST_READY"].includes(status)) return 2000;
  if (["RUNNING", "PROCESSING"].includes(status)) return 8000;
  return 4000;
}

function renderBatch(result) {
  state.batch = result;
  const target = document.querySelector("#batch-rows");
  target.replaceChildren();
  const rows = result.rows || [];
  rows.forEach((row) => {
    const card = document.createElement("article"); card.className = "artifact";
    const title = document.createElement("strong");
    title.textContent = String(row.row_id || "row") + " · " + String(row.status || "pending");
    card.append(title);
    ["route", "queue_wait", "provider_wait", "skipped", "error"].forEach((key) => {
      if (row[key] === undefined || row[key] === null || row[key] === "") return;
      const detail = document.createElement("p"); detail.textContent = key + ": " + String(row[key]); card.append(detail);
    });
    if (result.batch_id && ["failed", "rejected"].includes(String(row.status || "").toLowerCase())) {
      const retry = document.createElement("button"); retry.type = "button"; retry.className = "secondary"; retry.textContent = "重试已知任务";
      retry.addEventListener("click", () => retryBatchRow(String(row.row_id || "")));
      card.append(retry);
    }
    target.append(card);
  });
  const index = document.querySelector("#batch-result-index");
  if (result.batch_id) {
    index.href = "/api/batches/" + encodeURIComponent(result.batch_id) + "/results-index";
    index.classList.remove("hidden");
  } else {
    index.classList.add("hidden");
  }
}

function batchFormData() {
  const data = new FormData(); data.append("manifest", state.batchFile); return data;
}

async function preflightBatch() {
  if (!state.batchFile) return;
  try {
    const result = await api("batches/manifest/preflight", { method: "POST", body: batchFormData() });
    state.batchPreflighted = true;
    document.querySelector("#batch-submit").disabled = false;
    setText("#batch-status", "预检完成");
    renderBatch(result);
  } catch (error) {
    state.batchPreflighted = false;
    document.querySelector("#batch-submit").disabled = true;
    showNotice("批次预检：" + error.message, "error");
  }
}

async function submitBatch() {
  if (!state.batchFile || !state.batchPreflighted) return;
  try {
    const result = await api("batches/manifest", { method: "POST", body: batchFormData() });
    setText("#batch-status", "批次已提交");
    renderBatch(result);
  } catch (error) { showNotice("批次提交：" + error.message, "error"); }
}

async function retryBatchRow(rowId) {
  if (!state.batch || !state.batch.batch_id || !rowId) return;
  try {
    const result = await api("batches/" + encodeURIComponent(state.batch.batch_id) + "/rows/" + encodeURIComponent(rowId) + "/retry", { method: "POST" });
    const batch = await api("batches/" + encodeURIComponent(result.batch_id));
    renderBatch(batch); showNotice("已恢复已知任务。", "success");
  } catch (error) { showNotice("批次重试：" + error.message, "error"); }
}

async function refreshJob() {
  if (!state.job) return;
  try { renderJob(await api("jobs/" + encodeURIComponent(state.job.job_id))); }
  catch (error) { showNotice("刷新失败：" + error.message, "error"); }
}

async function exportTask() {
  if (!state.job) return;
  try {
    state.task = await api("jobs/" + encodeURIComponent(state.job.job_id) + "/codex-task");
    taskBox.value = JSON.stringify(state.task, null, 2);
    document.querySelector("#copy-task").disabled = false;
    document.querySelector("#download-task").disabled = false;
    showNotice("Codex 任务包已生成。", "success");
  } catch (error) { showNotice("生成任务包失败：" + error.message, "error"); }
}

form.addEventListener("input", validateIntake);
form.addEventListener("change", validateIntake);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const job = await api("jobs", { method: "POST", body: new FormData(form) });
    renderJob(job); showNotice("任务已创建。", "success");
  } catch (error) { showNotice("创建任务失败：" + error.message, "error"); }
});
document.querySelector("#refresh-job").addEventListener("click", refreshJob);
document.querySelector("#export-task").addEventListener("click", exportTask);
document.querySelector("#copy-task").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(taskBox.value); showNotice("已复制任务包。", "success"); }
  catch (_) { showNotice("浏览器未授予剪贴板权限，请手动复制。", "error"); }
});
document.querySelector("#download-task").addEventListener("click", () => {
  const blob = new Blob([taskBox.value], { type: "application/json" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "codex_task.json"; link.click(); URL.revokeObjectURL(link.href);
});
document.querySelector("#result-file").addEventListener("change", async (event) => {
  const file = event.target.files[0]; if (!file || !state.job) return;
  try {
    const payload = JSON.parse(await file.text());
    renderJob(await api("jobs/" + encodeURIComponent(state.job.job_id) + "/codex-result", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    }));
    showNotice("Codex 结果已导入。", "success");
  } catch (error) { showNotice("导入失败：" + error.message, "error"); }
  event.target.value = "";
});
document.querySelector("#save-script").addEventListener("click", async () => {
  const content = document.querySelector("#script-content").value;
  try {
    await api("jobs/" + encodeURIComponent(state.job.job_id) + "/reviews/script", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: state.job.version, content })
    });
    await refreshJob(); showNotice("脚本已保存为新版本。", "success");
  } catch (error) { showNotice("保存失败：" + error.message, "error"); }
});
document.querySelector("#approve-script").addEventListener("click", async () => {
  const revision = latest("script"); if (!revision) return;
  try {
    renderJob(await api("jobs/" + encodeURIComponent(state.job.job_id) + "/reviews/script/" + revision.number + "/approve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: state.job.version, sha256: revision.sha256 })
    }));
    showNotice("文字脚本已确认。", "success");
  } catch (error) { showNotice("确认失败：" + error.message, "error"); }
});
document.querySelector("#approve-storyboard").addEventListener("click", async () => {
  const revision = latest("storyboard"); if (!revision) return;
  try {
    renderJob(await api("jobs/" + encodeURIComponent(state.job.job_id) + "/reviews/storyboard/" + revision.number + "/approve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: state.job.version, sha256: revision.sha256 })
    }));
    showNotice("故事板已确认。", "success");
  } catch (error) { showNotice("确认失败：" + error.message, "error"); }
});
document.querySelector("#batch-manifest").addEventListener("change", (event) => {
  state.batchFile = event.target.files[0] || null;
  state.batchPreflighted = false;
  document.querySelector("#batch-preflight").disabled = !state.batchFile;
  document.querySelector("#batch-submit").disabled = true;
  setText("#batch-status", state.batchFile ? state.batchFile.name : "等待清单。");
});
document.querySelector("#batch-preflight").addEventListener("click", preflightBatch);
document.querySelector("#batch-submit").addEventListener("click", submitBatch);

api("health").then(() => setText("#health", "本机服务正常")).catch(() => setText("#health", "服务检查失败"));
validateIntake();
