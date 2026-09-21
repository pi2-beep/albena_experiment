const instrument = JSON.parse(document.querySelector("#wave2-data").textContent);
const appState = { data: null, csrf: "", step: 0, timerId: null, saveTimer: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function showMessage(text, type = "error") {
  const box = $("#message");
  box.className = `message ${type}`;
  box.textContent = text;
  box.hidden = !text;
  if (text) box.scrollIntoView({ behavior: "smooth", block: "center" });
}

function showStep(index) {
  appState.step = index;
  for (const section of $$(".step")) section.hidden = Number(section.dataset.step) !== index;
  for (const item of $$("#step-list li")) {
    const value = Number(item.dataset.step);
    item.classList.toggle("active", value === index);
    item.classList.toggle("complete", value < index);
  }
  showMessage("");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  if (appState.csrf) headers["X-CSRF-Token"] = appState.csrf;
  const response = await fetch(path, { ...options, headers });
  const result = await response.json().catch(() => ({ error: "Невалиден отговор от сървъра." }));
  if (!response.ok) throw new Error(result.error || "Заявката не беше успешна.");
  if (result.csrf_token) appState.csrf = result.csrf_token;
  if (result.data) {
    appState.data = result.data;
    updateIdentity();
  }
  return result;
}

function updateIdentity() {
  const id = appState.data?.participant_id || "";
  $("#study-id-short").textContent = id ? `ID ${id.slice(0, 8)}` : "Нова сесия";
  $("#withdraw-button").hidden = !id || ["completed", "ineligible", "withdrawn"].includes(appState.data?.state);
}

function renderCase(target) {
  const caseData = instrument.case;
  target.innerHTML = `
    ${caseData.intro.map((text) => `<p>${escapeHtml(text)}</p>`).join("")}
    <h3>Възможни решения</h3>
    <div class="case-grid">${caseData.options.map((item) => `<article><b>${item.id}. ${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></article>`).join("")}</div>
    <h3>Налична информация</h3>
    <div class="evidence-grid">${caseData.evidence.map((item) => `<article><b>${escapeHtml(item.title)}</b><p>${escapeHtml(item.text)}</p></article>`).join("")}</div>`;
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}

function formObject(form) {
  const values = new FormData(form);
  return Object.fromEntries(values.entries());
}

function booleanRadio(value) {
  return value === "yes";
}

function judgementMarkup(buttonText) {
  return `
    <fieldset><legend>Кой вариант бихте препоръчали?</legend><div class="option-row"><label><input type="radio" name="preferred" value="A" required>A</label><label><input type="radio" name="preferred" value="B">B</label><label><input type="radio" name="preferred" value="C">C</label></div></fieldset>
    <fieldset><legend>Разпределете точно 100 точки</legend><div class="allocation-row"><label>A<input type="number" name="points_a" min="0" max="100" required></label><label>B<input type="number" name="points_b" min="0" max="100" required></label><label>C<input type="number" name="points_c" min="0" max="100" required></label></div><output class="allocation-total">Общо: 0 / 100</output></fieldset>
    <label class="field">Увереност 0-100<input type="number" name="confidence" min="0" max="100" required></label>
    <label class="field">Кратка обосновка<textarea name="rationale" rows="6" maxlength="20000" required></textarea></label>
    <div class="warning mismatch-warning" hidden><label><input type="checkbox" name="mismatch_confirmed"> Потвърждавам избора си, въпреки че не съответства на варианта с най-много точки.</label></div>
    <button class="button primary" type="submit">${buttonText}</button>`;
}

function setupJudgementForm(form) {
  const totalOutput = $(".allocation-total", form) || $("#baseline-total", form);
  const warning = $(".mismatch-warning", form) || $("#baseline-mismatch", form);
  const update = () => {
    const values = formObject(form);
    const allocations = ["A", "B", "C"].map((option) => Number(values[`points_${option.toLowerCase()}`]) || 0);
    const total = allocations.reduce((sum, value) => sum + value, 0);
    totalOutput.textContent = `Общо: ${total} / 100`;
    totalOutput.classList.toggle("valid", total === 100);
    const preferredIndex = ["A", "B", "C"].indexOf(values.preferred);
    const mismatch = preferredIndex >= 0 && allocations[preferredIndex] !== Math.max(...allocations);
    warning.hidden = !mismatch;
    if (!mismatch) $("[name='mismatch_confirmed']", warning).checked = false;
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
}

function caseContext() {
  const parts = [instrument.system_prompt, "", instrument.case.title, ...instrument.case.intro, "", "Възможни решения:"];
  for (const option of instrument.case.options) parts.push(`${option.id}. ${option.title}: ${option.text}`);
  parts.push("", "Налична информация:");
  for (const item of instrument.case.evidence) parts.push(`${item.title}: ${item.text}`);
  return parts.join("\n");
}

function taskText(task, field) {
  const preferred = appState.data.baseline.preferred;
  return String(task[field] || "").replaceAll("{preferred}", preferred);
}

function initialEntries() {
  return instrument.tasks.tasks.map((task) => ({
    sequence: task.sequence,
    task_origin: "assigned",
    mandatory_task_id: task.id,
    task_text: taskText(task, "reflection_prompt_bg"),
    prompt: taskText(task, "prompt_template_bg"),
    response: "",
    reflection: "",
  })).concat([4, 5].map((sequence) => ({
    sequence,
    task_origin: "participant_optional",
    mandatory_task_id: null,
    prompt: "",
    response: "",
    reflection: "",
  })));
}

function renderIntervention() {
  const aiArm = appState.data.assignment === "ai";
  $("#intervention-title").textContent = aiArm ? "Преосмисляне с избран от Вас ИИ инструмент" : "Структурирано преосмисляне без ИИ";
  $("#intervention-intro").textContent = aiArm
    ? "Използвайте ИИ инструмента, до който обичайно имате достъп. Копирайте контекста веднъж, след това изпълнете трите задачи. Последните две заявки са по избор."
    : "Отговорете самостоятелно на трите задачи, без ИИ, търсачка или нови източници. Последните две полета са по избор.";
  $("#ai-tool-fields").hidden = !aiArm;
  const entries = appState.data.intervention?.entries?.length ? appState.data.intervention.entries : initialEntries();
  appState.data.intervention = { ...(appState.data.intervention || {}), entries };
  $("#intervention-tasks").innerHTML = entries.map((entry, index) => {
    const required = index < 3;
    const title = required ? `Задача ${index + 1} - задължителна` : `Допълнителна задача ${index - 2} - по избор`;
    if (aiArm) {
      return `<article class="task-card" data-entry="${index}"><h3>${title}</h3>
        ${required ? `<p>${escapeHtml(entry.prompt)}</p><button class="button secondary copy-prompt" type="button">Копирай prompt</button>` : `<label class="field">Ваш свободен prompt<textarea class="entry-prompt" rows="3">${escapeHtml(entry.prompt)}</textarea></label><button class="button secondary copy-prompt" type="button">Копирай prompt</button>`}
        <label class="field">Отговор от ИИ<textarea class="entry-response" rows="7" ${required ? "required" : ""}>${escapeHtml(entry.response)}</textarea></label></article>`;
    }
    const taskText = required ? entry.task_text : "Допълнително съображение, което желаете да разгледате";
    return `<article class="task-card" data-entry="${index}"><h3>${title}</h3><p>${escapeHtml(taskText)}</p><label class="field">Вашият самостоятелен размисъл<textarea class="entry-reflection" rows="7" ${required ? "required" : ""}>${escapeHtml(entry.reflection)}</textarea></label></article>`;
  }).join("");

  $("#copy-context").onclick = async () => {
    await navigator.clipboard.writeText(caseContext());
    appState.data.intervention.context_copied_at = new Date().toISOString();
    showMessage("Контекстът е копиран. Поставете го в нов разговор с избрания ИИ.", "success");
    scheduleInterventionSave();
  };
  for (const card of $$(".task-card")) {
    const index = Number(card.dataset.entry);
    $(".copy-prompt", card)?.addEventListener("click", async () => {
      const promptField = $(".entry-prompt", card);
      const prompt = promptField ? promptField.value.trim() : entries[index].prompt;
      if (!prompt) return showMessage("Първо въведете prompt.");
      await navigator.clipboard.writeText(prompt);
      entries[index].prompt = prompt;
      entries[index].copied_at = new Date().toISOString();
      showMessage(`Prompt ${index + 1} е копиран.`, "success");
      scheduleInterventionSave();
    });
    for (const field of $$("textarea", card)) field.addEventListener("input", scheduleInterventionSave);
  }
  for (const field of [$("#ai-tool-name"), $("#ai-tool-plan"), $("#ai-browsing")]) field.addEventListener("input", scheduleInterventionSave);
  startTimer();
}

function collectIntervention() {
  const entries = appState.data.intervention.entries;
  for (const card of $$(".task-card")) {
    const index = Number(card.dataset.entry);
    const prompt = $(".entry-prompt", card);
    const response = $(".entry-response", card);
    const reflection = $(".entry-reflection", card);
    if (prompt) entries[index].prompt = prompt.value.trim();
    if (response) entries[index].response = response.value.trim();
    if (reflection) entries[index].reflection = reflection.value.trim();
  }
  return {
    entries,
    context_copied_at: appState.data.intervention.context_copied_at || null,
    ai_tool: appState.data.assignment === "ai" ? {
      name: $("#ai-tool-name").value.trim(),
      plan: $("#ai-tool-plan").value,
      browsing: $("#ai-browsing").value,
    } : null,
  };
}

function scheduleInterventionSave() {
  clearTimeout(appState.saveTimer);
  appState.saveTimer = setTimeout(async () => {
    try {
      const result = await api("/api/intervention", { method: "PUT", body: collectIntervention() });
      appState.data = result.data;
    } catch (error) {
      if (!String(error.message).includes("time has ended")) showMessage(error.message);
    }
  }, 450);
}

function startTimer() {
  clearInterval(appState.timerId);
  const timer = $("#timer");
  timer.hidden = false;
  const tick = () => {
    const deadline = Date.parse(appState.data.intervention_deadline_at || appState.data.intervention?.deadline_at || "");
    const remaining = Math.max(0, deadline - Date.now());
    const seconds = Math.ceil(remaining / 1000);
    timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    document.body.classList.toggle("time-critical", remaining > 0 && remaining <= 60_000);
    if (remaining <= 0) {
      clearInterval(appState.timerId);
      for (const field of $$("#intervention-tasks textarea, #ai-tool-fields input, #ai-tool-fields select")) field.disabled = true;
      $("#post-open").disabled = false;
      $("#timer-message").textContent = "12-минутната фаза приключи. Продължете към непосредствената оценка.";
    }
  };
  tick();
  appState.timerId = setInterval(tick, 250);
}

function stepForState(state) {
  return {
    started: 1,
    consented: 2,
    eligible: 3,
    baseline_draft: 3,
    randomised: 5,
    intervention_active: 5,
    immediate_post_complete: 7,
    review_decided: 8,
    final_complete: 9,
    completed: 9,
    withdrawn: 10,
    ineligible: 2,
  }[state] ?? 0;
}

async function enterIntervention() {
  if (appState.data.state === "randomised") await api("/api/intervention/start", { method: "POST", body: {} });
  renderIntervention();
  showStep(5);
}

$("#start-button").addEventListener("click", async () => {
  try {
    await api("/api/start", { method: "POST", body: { session_code: $("#session-code").value.trim() } });
    showStep(1);
  } catch (error) { showMessage(error.message); }
});

$("#withdraw-button").addEventListener("click", async () => {
  if (!window.confirm("Сигурни ли сте, че искате да прекратите участието? Тази сесия няма да може да бъде продължена.")) return;
  try {
    await api("/api/withdraw", { method: "POST", body: {} });
    clearInterval(appState.timerId);
    $("#timer").hidden = true;
    document.body.classList.remove("time-critical");
    showStep(10);
  } catch (error) { showMessage(error.message); }
});

$("#consent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  try {
    const payload = Object.fromEntries([...new FormData(event.currentTarget).keys()].map((key) => [key, true]));
    await api("/api/consent", { method: "POST", body: payload });
    showStep(2);
  } catch (error) { showMessage(error.message); }
});

$("#eligibility-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const raw = formObject(event.currentTarget);
  try {
    await api("/api/eligibility", { method: "POST", body: Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, booleanRadio(value)])) });
    if (appState.data.state === "ineligible") return showMessage("Не отговаряте на условията за участие в тази вълна.", "info");
    showStep(3);
  } catch (error) { showMessage(error.message); }
});

$("#case-continue").addEventListener("click", () => showStep(4));

$("#baseline-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const values = formObject(event.currentTarget);
  try {
    await api("/api/baseline/lock", { method: "POST", body: { judgement: values, mismatch_confirmed: values.mismatch_confirmed === "on" } });
    await enterIntervention();
  } catch (error) { showMessage(error.message); }
});

$("#post-open").addEventListener("click", () => showStep(6));

$("#post-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const values = formObject(event.currentTarget);
  values.mismatch_confirmed = values.mismatch_confirmed === "on";
  try {
    await api("/api/post", { method: "POST", body: values });
    $("#timer").hidden = true;
    showStep(7);
  } catch (error) { showMessage(error.message); }
});

$("#review-form").addEventListener("change", (event) => {
  if (event.target.name === "requested_review") $("#review-case").hidden = event.target.value !== "yes";
});

$("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const values = formObject(event.currentTarget);
  try {
    await api("/api/review", { method: "POST", body: {
      requested_review: values.requested_review === "yes",
      evaluation: {
        perceived_influence: values.perceived_influence,
        process_helpfulness: values.process_helpfulness,
        used_ai_during_intervention: values.used_ai_during_intervention,
      },
    } });
    showStep(8);
  } catch (error) { showMessage(error.message); }
});

$("#final-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const values = formObject(event.currentTarget);
  values.mismatch_confirmed = values.mismatch_confirmed === "on";
  try {
    await api("/api/final", { method: "POST", body: { judgement: values, evaluation: appState.data.evaluation } });
    $("#completed-id").textContent = appState.data.participant_id;
    showStep(9);
  } catch (error) { showMessage(error.message); }
});

async function restore() {
  renderCase($("#case-content"));
  renderCase($("#review-case"));
  $("#post-form").innerHTML = judgementMarkup("Запиши непосредствената оценка");
  $("#final-form").innerHTML = judgementMarkup("Завърши участието");
  setupJudgementForm($("#baseline-form"));
  setupJudgementForm($("#post-form"));
  setupJudgementForm($("#final-form"));
  try {
    await api("/api/state");
    const step = stepForState(appState.data.state);
    if (["randomised", "intervention_active"].includes(appState.data.state)) {
      await enterIntervention();
    } else {
      if (appState.data.state === "completed") $("#completed-id").textContent = appState.data.participant_id;
      showStep(step);
    }
  } catch {
    showStep(0);
  }
}

restore();
