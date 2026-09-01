const TOTAL_STEPS = 8;
const SESSION_DURATION_MS = 45 * 60 * 1000;
const appState = {
  currentStep: 0,
  data: {},
  saveTimer: null,
  saving: false,
  clockTimer: null,
  timeExpired: false,
  dialogReturnFocus: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const interactionsContainer = $("#interactions-container");
for (let index = 0; index < 5; index += 1) {
  const required = index < 3;
  interactionsContainer.insertAdjacentHTML("beforeend", `
    <article class="interaction-card" data-interaction="${index}">
      <div class="interaction-head">
        <h3>Взаимодействие ${index + 1}</h3>
        <span class="badge ${required ? "" : "optional-badge"}">${required ? "задължително" : "по избор"}</span>
      </div>
      <label>Prompt към ИИ
        <textarea name="interactions.${index}.prompt" rows="4" maxlength="20000" ${required ? "required" : ""}></textarea>
      </label>
      <label>Отговор на ИИ
        <textarea name="interactions.${index}.response" rows="7" maxlength="40000" ${required ? "required" : ""}></textarea>
      </label>
    </article>`);
}

const likertItems = [
  ["understand", "ИИ ми помогна да разбера по-добре проблема"],
  ["compare", "ИИ ми помогна да сравня алтернативите"],
  ["new_arguments", "ИИ ми помогна да видя аргументи, които първоначално не бях отчел/а"],
  ["recommendation_help", "ИИ ми помогна да достигна до окончателна препоръка"],
  ["evidence_based", "Анализът беше основан на доказателства"],
  ["reliable", "Анализът беше надежден"],
  ["persuasive", "Анализът беше убедителен"],
  ["balanced", "Анализът беше балансиран"],
];
const likertList = $("#likert-list");
for (const [key, label] of likertItems) {
  const scale = Array.from({ length: 7 }, (_, offset) => {
    const value = offset + 1;
    return `<label><input type="radio" name="after_ai.${key}" value="${value}" ${value === 1 ? "required" : ""}><span>${value}</span></label>`;
  }).join("");
  likertList.insertAdjacentHTML("beforeend", `<fieldset class="likert-item" data-required-group><legend>${label}</legend><div class="likert-scale">${scale}</div></fieldset>`);
}

const binaryExperience = [
  ["text_work", "Подготовка или редактиране на текстове"],
  ["analysis", "Анализ на информация"],
  ["options", "Формулиране на варианти за действие"],
  ["comparison", "Сравнение между различни варианти"],
  ["recommendations", "Подготовка на препоръки"],
  ["ai_data", "Професионалната Ви работа свързана ли е основно с ИИ или данни?"],
];
const experienceBinary = $("#experience-binary");
for (const [key, label] of binaryExperience) {
  experienceBinary.insertAdjacentHTML("beforeend", `
    <fieldset class="binary-field" data-required-group>
      <legend>${label}</legend>
      <label><input type="radio" name="experience.${key}" value="yes" required><span>Да</span></label>
      <label><input type="radio" name="experience.${key}" value="no"><span>Не</span></label>
    </fieldset>`);
}

function emptyData(code) {
  return {
    participant_code: code,
    consent: {},
    baseline: {},
    interactions: Array.from({ length: 5 }, () => ({ prompt: "", response: "" })),
    full_transcript: "",
    after_ai: {},
    experience: {},
    baseline_locked: false,
  };
}

function setPath(object, path, value) {
  const parts = path.split(".");
  let target = object;
  parts.forEach((part, index) => {
    const key = /^\d+$/.test(part) ? Number(part) : part;
    if (index === parts.length - 1) {
      target[key] = value;
      return;
    }
    const nextIsArray = /^\d+$/.test(parts[index + 1]);
    if (target[key] === undefined || target[key] === null) target[key] = nextIsArray ? [] : {};
    target = target[key];
  });
}

function getPath(object, path) {
  return path.split(".").reduce((value, part) => value?.[/^\d+$/.test(part) ? Number(part) : part], object);
}

function localKey(code) {
  return `albena-study:${code}`;
}

function saveLocal() {
  if (!appState.data.participant_code) return;
  localStorage.setItem(localKey(appState.data.participant_code), JSON.stringify(appState.data));
}

function loadLocal(code) {
  try {
    return JSON.parse(localStorage.getItem(localKey(code))) || null;
  } catch {
    return null;
  }
}

function collectForm() {
  for (const field of $$("#study-form [name]")) {
    if (field.type === "radio" && !field.checked) continue;
    const value = field.type === "checkbox" ? field.checked : field.value;
    setPath(appState.data, field.name, value);
  }
  return appState.data;
}

function fillForm() {
  for (const field of $$("#study-form [name]")) {
    const value = getPath(appState.data, field.name);
    if (field.type === "checkbox") field.checked = value === true;
    else if (field.type === "radio") field.checked = String(value) === field.value;
    else if (value !== undefined && value !== null) field.value = value;
  }
  $("#participant-label").textContent = appState.data.participant_code || "";
  $("#consent-code").value = appState.data.participant_code || "";
  const dateField = $('[name="consent.date"]');
  if (!dateField.value) {
    dateField.value = new Date().toISOString().slice(0, 10);
    setPath(appState.data, "consent.date", dateField.value);
  }
  updateRanges();
  updateAllocations();
  applyBaselineLock();
}

function applyBaselineLock() {
  const locked = appState.data.baseline_locked === true;
  for (const field of $$('[data-step="3"] [name]')) field.disabled = locked;
}

function updateRanges() {
  for (const input of $$('input[type="range"]')) {
    const output = $(`output[data-for="${input.name}"]`);
    if (output) output.value = input.value;
  }
}

function updateAllocations() {
  for (const block of $$('[data-allocation]')) {
    const inputs = $$('input[type="number"]', block);
    const total = inputs.reduce((sum, input) => sum + (Number(input.value) || 0), 0);
    const line = $(".total-line", block);
    $("[data-total]", block).textContent = total;
    line.classList.toggle("valid", total === 100);
  }
}

function setSaveStatus(text) {
  $("#save-status").textContent = text;
}

function scheduleSave() {
  if (appState.timeExpired) return;
  collectForm();
  saveLocal();
  setSaveStatus("Запазване…");
  clearTimeout(appState.saveTimer);
  appState.saveTimer = setTimeout(saveServer, 650);
}

async function saveServer() {
  if (!appState.data.participant_code || appState.saving || appState.timeExpired) return;
  appState.saving = true;
  try {
    const response = await fetch("/api/session", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(appState.data),
    });
    if (!response.ok) throw new Error("save failed");
    setSaveStatus("Черновата е запазена");
  } catch {
    setSaveStatus("Запазено само в браузъра");
  } finally {
    appState.saving = false;
  }
}

function clearValidation(step) {
  for (const element of $$(".invalid-block", step)) element.classList.remove("invalid-block");
}

function markInvalid(field) {
  const block = field.closest("[data-required-group], .interaction-card, label, fieldset") || field;
  block.classList.add("invalid-block");
}

function validateStep(index) {
  const step = $(`.step[data-step="${index}"]`);
  clearValidation(step);
  let firstInvalid = null;
  for (const field of $$('[required]:not(:disabled)', step)) {
    if (!field.checkValidity()) {
      markInvalid(field);
      firstInvalid ||= field;
    }
  }

  for (const block of $$('[data-allocation]', step)) {
    const total = $$('input[type="number"]', block).reduce((sum, input) => sum + (Number(input.value) || 0), 0);
    if (total !== 100) {
      block.classList.add("invalid-block");
      firstInvalid ||= $("input", block);
    }
  }

  if (index === 4) {
    for (const card of $$(".interaction-card")) {
      const fields = $$("textarea", card);
      const hasPrompt = fields[0].value.trim().length > 0;
      const hasResponse = fields[1].value.trim().length > 0;
      if (hasPrompt !== hasResponse) {
        card.classList.add("invalid-block");
        firstInvalid ||= hasPrompt ? fields[1] : fields[0];
      }
    }
  }

  if (firstInvalid) {
    firstInvalid.scrollIntoView({ behavior: "smooth", block: "center" });
    showToast("Моля, попълнете отбелязаните полета.");
    return false;
  }
  return true;
}

function showStep(index, skipScroll = false) {
  appState.currentStep = Math.max(0, Math.min(TOTAL_STEPS - 1, index));
  for (const step of $$(".step")) step.hidden = Number(step.dataset.step) !== appState.currentStep;
  for (const nav of $$("#step-nav button")) {
    const value = Number(nav.dataset.step);
    nav.classList.toggle("active", value === appState.currentStep);
    nav.classList.toggle("complete", value < appState.currentStep);
  }
  const progress = ((appState.currentStep + 1) / TOTAL_STEPS) * 100;
  $("#progress-bar").style.width = `${progress}%`;
  $("#step-counter").textContent = `Стъпка ${appState.currentStep + 1} от ${TOTAL_STEPS}`;
  $("#mobile-progress").textContent = `${appState.currentStep + 1} / ${TOTAL_STEPS}`;
  $("#back-button").hidden = appState.currentStep === 0;
  $("#next-button").hidden = appState.currentStep === TOTAL_STEPS - 1;
  if (appState.currentStep === TOTAL_STEPS - 1) renderReview();
  if (!skipScroll) window.scrollTo({ top: 0, behavior: "smooth" });
}

function nextStep() {
  if (appState.timeExpired) return;
  if (!validateStep(appState.currentStep)) return;
  collectForm();
  if (appState.currentStep === 1 && !appState.data.consent.accepted_at) {
    appState.data.consent.accepted_at = new Date().toISOString();
  }
  if (appState.currentStep === 3 && !appState.data.baseline_locked) {
    const confirmed = window.confirm("След преминаване към работата с ИИ самостоятелните Ви отговори ще бъдат заключени. Да продължим ли?");
    if (!confirmed) return;
    appState.data.baseline_locked = true;
    applyBaselineLock();
  }
  scheduleSave();
  showStep(appState.currentStep + 1);
}

function displayValue(value) {
  if (value === true || value === "yes") return "Да";
  if (value === false || value === "no") return "Не";
  if (value === "A") return "Вариант A";
  if (value === "B") return "Вариант B";
  if (value === "C") return "Вариант C";
  return value === undefined || value === null || value === "" ? "—" : String(value);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = displayValue(value);
  return div.innerHTML;
}

function reviewSection(title, rows) {
  return `<section class="review-section"><h3>${escapeHtml(title)}</h3><dl class="review-grid">${rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></section>`;
}

function renderReview() {
  collectForm();
  const baseline = appState.data.baseline || {};
  const after = appState.data.after_ai || {};
  const interactions = appState.data.interactions || [];
  const interactionRows = interactions.flatMap((item, index) => {
    if (!item?.prompt && !item?.response) return [];
    return [[`Prompt ${index + 1}`, item.prompt], [`Отговор ${index + 1}`, item.response]];
  });
  $("#review-content").innerHTML = [
    reviewSection("Участие", [["Код", appState.data.participant_code], ["Информирано съгласие", appState.data.consent?.participate]]),
    reviewSection("Самостоятелна преценка", [["Вариант", baseline.preferred], ["Точки A / B / C", `${displayValue(baseline.points_a)} / ${displayValue(baseline.points_b)} / ${displayValue(baseline.points_c)}`], ["Увереност", baseline.confidence], ["Съображение", baseline.rationale]]),
    reviewSection("Взаимодействия с ИИ", interactionRows.length ? interactionRows : [["Запис", "—"]]),
    reviewSection("След ИИ", [["Вариант", after.preferred], ["Точки A / B / C", `${displayValue(after.points_a)} / ${displayValue(after.points_b)} / ${displayValue(after.points_c)}`], ["Увереност", after.confidence], ["Влияние на ИИ", after.influence], ["Окончателен вариант", after.final_preferred], ["Окончателна увереност", after.final_confidence]]),
  ].join("");
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2600);
}

function downloadLocalBackup() {
  collectForm();
  appState.data.local_backup_at = new Date().toISOString();
  saveLocal();
  const safeCode = String(appState.data.participant_code || "participant").replace(/[^A-Za-zА-Яа-я0-9_-]/g, "-");
  const date = new Date().toISOString().replace(/[:.]/g, "-");
  const blob = new Blob([JSON.stringify(appState.data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `albena-cherнова-${safeCode}-${date}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function safeExit() {
  const confirmed = window.confirm("Ще бъде изтеглено локално копие на черновата и сесията ще бъде затворена. Да продължим ли?");
  if (!confirmed) return;
  const button = $("#safe-exit-button");
  button.disabled = true;
  downloadLocalBackup();
  showToast("Локалното копие е запазено.");
  await saveServer();
  try {
    await fetch("/api/logout", { method: "POST" });
  } finally {
    window.setTimeout(() => window.location.reload(), 500);
  }
}

function openCaseDialog() {
  appState.dialogReturnFocus = document.activeElement;
  const dialog = $("#case-dialog");
  dialog.hidden = false;
  document.body.classList.add("dialog-open");
  $("#case-dialog-close").focus();
}

function closeCaseDialog() {
  $("#case-dialog").hidden = true;
  document.body.classList.remove("dialog-open");
  appState.dialogReturnFocus?.focus?.();
}

function sessionDeadline() {
  const explicit = Date.parse(appState.data.deadline_at || "");
  if (Number.isFinite(explicit)) return explicit;
  const created = Date.parse(appState.data.created_at || "");
  return Number.isFinite(created) ? created + SESSION_DURATION_MS : Date.now() + SESSION_DURATION_MS;
}

function formatRemaining(milliseconds) {
  const seconds = Math.max(0, Math.ceil(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function lockExpiredSession() {
  if (appState.timeExpired) return;
  collectForm();
  appState.timeExpired = true;
  appState.data.time_limit_reached = true;
  appState.data.time_limit_reached_at = new Date().toISOString();
  saveLocal();
  document.body.classList.add("time-expired");
  document.body.classList.remove("time-critical");
  for (const field of $$("#study-form [name]")) field.disabled = true;
  for (const button of $$("#step-nav button, #back-button, #next-button")) button.disabled = true;
  setSaveStatus("Времето изтече — попълването е заключено");
  showStep(TOTAL_STEPS - 1, true);
  $("#time-expired-dialog").hidden = false;
}

function updateSessionClock() {
  const remaining = sessionDeadline() - Date.now();
  $("#timer-display").textContent = formatRemaining(remaining);
  document.body.classList.toggle("time-critical", remaining > 0 && remaining <= 60_000);
  if (remaining <= 0) {
    clearInterval(appState.clockTimer);
    lockExpiredSession();
  }
}

function startSessionClock() {
  clearInterval(appState.clockTimer);
  updateSessionClock();
  if (!appState.timeExpired) appState.clockTimer = setInterval(updateSessionClock, 250);
}

async function login(code) {
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ participant_code: code }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Входът не беше успешен.");
  const local = loadLocal(code);
  appState.data = local ? { ...result, ...local, participant_code: result.participant_code } : { ...emptyData(code), ...result };
  if (!Array.isArray(appState.data.interactions)) appState.data.interactions = emptyData(code).interactions;
  while (appState.data.interactions.length < 5) appState.data.interactions.push({ prompt: "", response: "" });
  enterApp();
  scheduleSave();
}

function enterApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  fillForm();
  showStep(0, true);
  startSessionClock();
}

async function restoreSession() {
  try {
    const response = await fetch("/api/session");
    const result = await response.json();
    if (!result.authenticated) return;
    const server = result.data;
    const local = loadLocal(server.participant_code);
    const useLocal = local && String(local.updated_at || "") > String(server.updated_at || "");
    appState.data = useLocal ? { ...server, ...local, participant_code: server.participant_code } : server;
    while ((appState.data.interactions || []).length < 5) appState.data.interactions.push({ prompt: "", response: "" });
    enterApp();
  } catch {
    // Login remains available when the local server is unreachable.
  }
}

async function downloadPdf() {
  const errors = $("#pdf-errors");
  errors.hidden = true;
  errors.classList.remove("info-panel");
  collectForm();
  await saveServer();
  const button = $("#download-pdf");
  button.disabled = true;
  button.textContent = "Генериране и запис…";
  try {
    const response = await fetch("/api/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(appState.data),
    });
    if (!response.ok) {
      const result = await response.json();
      const details = result.details || [result.error || "PDF файлът не беше създаден."];
      const diagnosticLog = [
        `Време: ${new Date().toISOString()}`,
        `HTTP статус: ${response.status}`,
        "Етап: проверка на формуляра",
        ...details.map((item, index) => `${index + 1}. ${item}`),
      ].join("\n");
      errors.innerHTML = `<strong>Необходими корекции:</strong><pre class="diagnostic-log">${escapeHtml(diagnosticLog)}</pre>`;
      errors.hidden = false;
      errors.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const archiveStatus = response.headers.get("X-Results-Archive") || "disabled";
    const pdfArchiveStatus = response.headers.get("X-Results-PDF-Archive") || "неизвестно";
    const jsonArchiveStatus = response.headers.get("X-Results-JSON-Archive") || "неизвестно";
    const archiveErrorId = response.headers.get("X-Results-Archive-Error-ID") || "няма";
    const archiveErrorStage = response.headers.get("X-Results-Archive-Error-Stage") || "няма";
    const generatedAt = response.headers.get("X-Results-Generated-At") || new Date().toISOString();
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    const filename = match ? decodeURIComponent(match[1].replace(/\"/g, "")) : "rezultati.pdf";
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    if (archiveStatus === "saved") {
      showToast("PDF файлът е изтеглен и записан в защитения архив.");
    } else if (archiveStatus === "partial") {
      const diagnosticLog = [
        `Време: ${generatedAt}`,
        "PDF генериране: успешно",
        `Локално изтегляне: успешно (${blob.size} байта)`,
        `PDF във FTP: ${pdfArchiveStatus === "saved" ? "записан" : "не е записан"}`,
        `JSON във FTP: ${jsonArchiveStatus === "saved" ? "записан" : "не е записан"}`,
        `Диагностичен код: ${archiveErrorId}`,
      ].join("\n");
      errors.classList.add("info-panel");
      errors.innerHTML = `<strong>Резултатът е записан частично в защитения FTP архив.</strong><p>Локалният PDF е изтеглен успешно. По-долу е описано точно кое копие е налично в архива.</p><pre class="diagnostic-log">${escapeHtml(diagnosticLog)}</pre>`;
      errors.hidden = false;
      errors.scrollIntoView({ behavior: "smooth", block: "center" });
      showToast("Файловете са генерирани; FTP записът е частичен.");
    } else if (archiveStatus === "failed") {
      const diagnosticLog = [
        `Време: ${generatedAt}`,
        "PDF генериране: успешно",
        `Локално изтегляне: успешно (${blob.size} байта)` ,
        `PDF във FTP: ${pdfArchiveStatus === "saved" ? "записан" : "не е записан"}`,
        `JSON във FTP: ${jsonArchiveStatus === "saved" ? "записан" : "не е записан"}`,
        `FTP архив: недостъпен (${archiveErrorStage})`,
        `Диагностичен код: ${archiveErrorId}`,
        `Файл: ${filename}`,
      ].join("\n");
      errors.innerHTML = `<strong>PDF файлът е изтеглен локално, но защитеният FTP архив е недостъпен.</strong><p>Запазете изтегления файл и го предайте на изследователя. Можете да опитате подаването отново по-късно.</p><pre class="diagnostic-log">${escapeHtml(diagnosticLog)}</pre>`;
      errors.hidden = false;
      errors.scrollIntoView({ behavior: "smooth", block: "center" });
      showToast("PDF е изтеглен; архивирането не успя.");
    } else {
      showToast("PDF файлът е изтеглен.");
    }
  } catch (downloadError) {
    const diagnosticLog = [
      `Време: ${new Date().toISOString()}`,
      "Етап: връзка, генериране или локално изтегляне",
      `Браузърът отчита интернет връзка: ${navigator.onLine ? "да" : "не"}`,
      `Грешка: ${downloadError?.message || "неизвестна грешка"}`,
    ].join("\n");
    errors.innerHTML = `<strong>PDF файлът не беше изтеглен.</strong><p>Проверете връзката и опитайте отново. Данните остават в локалната чернова.</p><pre class="diagnostic-log">${escapeHtml(diagnosticLog)}</pre>`;
    errors.hidden = false;
    errors.scrollIntoView({ behavior: "smooth", block: "center" });
  } finally {
    button.disabled = false;
    button.textContent = "Генерирай и запиши";
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#login-error");
  error.textContent = "";
  try {
    await login($("#participant-code").value.trim());
  } catch (loginError) {
    error.textContent = loginError.message;
  }
});

$("#study-form").addEventListener("input", (event) => {
  if (appState.timeExpired) return;
  if (event.target.matches('input[type="range"]')) updateRanges();
  if (event.target.closest("[data-allocation]")) updateAllocations();
  event.target.closest(".invalid-block")?.classList.remove("invalid-block");
  scheduleSave();
});
$("#study-form").addEventListener("change", scheduleSave);
$("#next-button").addEventListener("click", nextStep);
$("#back-button").addEventListener("click", () => showStep(appState.currentStep - 1));
$("#download-pdf").addEventListener("click", downloadPdf);
$("#case-dialog-content").innerHTML = $('.step[data-step="2"]').innerHTML;
$("#case-button").addEventListener("click", openCaseDialog);
$("#case-dialog-close").addEventListener("click", closeCaseDialog);
$("#case-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) closeCaseDialog();
});
$("#safe-exit-button").addEventListener("click", safeExit);
$("#time-expired-continue").addEventListener("click", () => {
  $("#time-expired-dialog").hidden = true;
  $("#download-pdf").focus();
});

for (const button of $$("#step-nav button")) {
  button.addEventListener("click", () => {
    if (appState.timeExpired) return;
    const target = Number(button.dataset.step);
    if (target <= appState.currentStep) showStep(target);
  });
}

$("#logout-button").addEventListener("click", async () => {
  await saveServer();
  await fetch("/api/logout", { method: "POST" });
  window.location.reload();
});

window.addEventListener("beforeunload", () => {
  collectForm();
  saveLocal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#case-dialog").hidden) closeCaseDialog();
});

restoreSession();
