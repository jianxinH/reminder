const form = document.querySelector("#composer");
const messages = document.querySelector("#messages");
const submitButton = document.querySelector("#submit");
const textarea = document.querySelector("#message");
const userIdInput = document.querySelector("#userId");
const sessionIdInput = document.querySelector("#sessionId");
const inbox = document.querySelector("#inbox");
const reminderList = document.querySelector("#reminderList");
const toggleRemindersButton = document.querySelector("#toggleReminders");
const draftActions = document.querySelector("#draftActions");
const draftActionsTitle = document.querySelector("#draftActionsTitle");
const draftActionsDesc = document.querySelector("#draftActionsDesc");
const confirmDraftButton = document.querySelector("#confirmDraft");
const cancelDraftButton = document.querySelector("#cancelDraft");

let lastInboxId = 0;
let inboxTimer = null;

function addMessage(role, text, meta = "", actions = []) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;

  const wrapper = document.createElement("div");
  const metaEl = document.createElement("div");
  metaEl.className = "meta";
  metaEl.textContent = meta || (role === "user" ? "你" : "Reminder Agent");

  wrapper.appendChild(metaEl);
  wrapper.appendChild(bubble);
  wrapper.style.alignSelf = role === "user" ? "flex-end" : "flex-start";

  if (actions.length) {
    const actionRow = document.createElement("div");
    actionRow.className = "message-actions";
    actions.forEach((action) => actionRow.appendChild(action));
    wrapper.appendChild(actionRow);
  }

  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
  return wrapper;
}

function createButton(label, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) {
    button.classList.add(className);
  }
  return button;
}

async function callJson(url, options = {}) {
  const response = await fetch(url, options);
  const rawText = await response.text();
  let data = null;

  try {
    data = rawText ? JSON.parse(rawText) : null;
  } catch (error) {
    if (!response.ok) {
      throw new Error(rawText || `请求失败（HTTP ${response.status}）`);
    }
    throw error;
  }

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || rawText || "请求失败");
  }

  return data;
}

async function sendMessage(message) {
  return callJson("/api/agent/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: Number(userIdInput.value),
      channel: "web",
      session_id: sessionIdInput.value.trim() || "web_demo",
      message,
    }),
  });
}

async function sendQuickReply(message, buttons = []) {
  addMessage("user", message);
  buttons.forEach((button) => {
    button.disabled = true;
  });

  try {
    const result = await sendMessage(message);
    await handleAgentResult(result.data);
  } catch (error) {
    addMessage("agent", `请求失败：${error.message}`, "system");
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

function setDraftActionsVisible(visible, config = null) {
  draftActions.classList.toggle("hidden", !visible);
  draftActions.hidden = !visible;

  if (config) {
    draftActionsTitle.textContent = config.title;
    draftActionsDesc.textContent = config.description;
    confirmDraftButton.textContent = config.confirmLabel;
    cancelDraftButton.textContent = config.cancelLabel;
    confirmDraftButton.dataset.message = config.confirmMessage;
    cancelDraftButton.dataset.message = config.cancelMessage;
  } else {
    draftActionsTitle.textContent = "当前有一份提醒草案";
    draftActionsDesc.textContent = "只有在你明确确认后，才会真正创建到系统；取消后这份草案会被丢弃。";
    confirmDraftButton.textContent = "确认创建";
    cancelDraftButton.textContent = "取消草案";
    confirmDraftButton.dataset.message = "确认创建";
    cancelDraftButton.dataset.message = "取消草案";
  }

  confirmDraftButton.disabled = false;
  cancelDraftButton.disabled = false;
}

async function markDone(reminderId) {
  return callJson(`/api/reminders/${reminderId}/done`, { method: "POST" });
}

async function snoozeReminder(reminderId, minutes = 10) {
  return callJson(`/api/reminders/${reminderId}/snooze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ minutes }),
  });
}

async function fetchReminders() {
  const userId = Number(userIdInput.value);
  if (!userId) return { data: [] };
  return callJson(`/api/reminders?user_id=${userId}&status=pending`);
}

function formatDateTime(value) {
  if (!value) return "未设置时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

function renderReminderList(items = []) {
  reminderList.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前还没有提醒，创建一条后这里会自动显示。";
    reminderList.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "reminder-item";

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `#${item.id} · ${String(item.channel_type || "web").toUpperCase()} · ${item.status}`;

    const title = document.createElement("p");
    title.textContent = `${item.title} · ${formatDateTime(item.next_remind_time)}`;

    card.appendChild(meta);
    card.appendChild(title);
    reminderList.appendChild(card);
  });
}

function setReminderPanelExpanded(expanded) {
  reminderList.classList.toggle("compact", !expanded);
  toggleRemindersButton.textContent = expanded ? "收起" : "展开";
  toggleRemindersButton.setAttribute("aria-expanded", String(expanded));
}

async function refreshReminderList() {
  try {
    const result = await fetchReminders();
    renderReminderList(result.data || []);
  } catch (error) {
    console.error("refresh reminder list failed", error);
  }
}

function buildPlanDraftActions() {
  const config = {
    confirmLabel: "确认创建",
    cancelLabel: "取消草案",
    confirmMessage: "确认创建",
    cancelMessage: "取消草案",
  };
  const confirmButton = createButton(config.confirmLabel);
  const cancelButton = createButton(config.cancelLabel, "secondary");

  confirmButton.addEventListener("click", async () => {
    await sendQuickReply(config.confirmMessage, [confirmButton, cancelButton]);
  });

  cancelButton.addEventListener("click", async () => {
    await sendQuickReply(config.cancelMessage, [confirmButton, cancelButton]);
  });

  return [confirmButton, cancelButton];
}

function buildConfirmActions(config) {
  const confirmButton = createButton(config.confirmLabel);
  const cancelButton = createButton(config.cancelLabel, "secondary");

  confirmButton.addEventListener("click", async () => {
    await sendQuickReply(config.confirmMessage, [confirmButton, cancelButton]);
  });

  cancelButton.addEventListener("click", async () => {
    await sendQuickReply(config.cancelMessage, [confirmButton, cancelButton]);
  });

  return [confirmButton, cancelButton];
}

function getActionConfig(intent) {
  if (intent === "plan_draft") {
    return {
      title: "当前有一份提醒草案",
      description: "这只是草案，还没有真正创建。只有你明确点“确认创建”或发送“确认创建”后，系统才会落库。",
      confirmLabel: "确认创建",
      cancelLabel: "取消草案",
      confirmMessage: "确认创建",
      cancelMessage: "取消草案",
    };
  }

  if (intent === "delete_confirm") {
    return {
      title: "当前有一份删除确认",
      description: "确认后才会真正删除提醒；取消后不会改动数据。",
      confirmLabel: "确认删除",
      cancelLabel: "取消删除",
      confirmMessage: "确认删除",
      cancelMessage: "取消删除",
    };
  }

  if (intent === "update_confirm" || intent === "snooze_confirm") {
    return {
      title: "当前有一份修改确认",
      description: "确认后才会真正更新时间；取消后不会改动数据。",
      confirmLabel: "确认修改",
      cancelLabel: "取消修改",
      confirmMessage: "确认修改",
      cancelMessage: "取消修改",
    };
  }

  return null;
}

async function handleAgentResult(data) {
  const config = getActionConfig(data.intent);
  let actions = [];

  if (data.intent === "plan_draft") {
    actions = buildPlanDraftActions();
  } else if (config) {
    actions = buildConfirmActions(config);
  }

  addMessage("agent", data.reply, `intent: ${data.intent}`, actions);

  if (config) {
    setDraftActionsVisible(true, config);
  } else {
    setDraftActionsVisible(false);
  }

  if (["create_reminder", "list_reminders", "update_reminder", "delete_reminder", "snooze_reminder", "mark_done", "plan_confirm"].includes(data.intent)) {
    await refreshReminderList();
  }
}

function addInboxItem(item) {
  const card = document.createElement("div");
  card.className = "inbox-item";

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${String(item.channel_type || "web").toUpperCase()} 提醒 #${item.reminder_id}`;

  const text = document.createElement("p");
  text.textContent = item.send_content || "你有一条新的提醒。";

  const actions = document.createElement("div");
  actions.className = "inbox-actions";

  const doneButton = createButton("完成");
  const snoozeButton = createButton("延后 10 分钟", "secondary");

  doneButton.addEventListener("click", async () => {
    doneButton.disabled = true;
    snoozeButton.disabled = true;
    try {
      const result = await markDone(item.reminder_id);
      addMessage("agent", result.message || `提醒 #${item.reminder_id} 已标记为完成`, "提醒动作");
      card.remove();
      await refreshReminderList();
    } catch (error) {
      addMessage("agent", `完成提醒失败：${error.message}`, "system");
      doneButton.disabled = false;
      snoozeButton.disabled = false;
    }
  });

  snoozeButton.addEventListener("click", async () => {
    doneButton.disabled = true;
    snoozeButton.disabled = true;
    try {
      const result = await snoozeReminder(item.reminder_id, 10);
      addMessage("agent", result.message || `提醒 #${item.reminder_id} 已延后 10 分钟`, "提醒动作");
      card.remove();
      await refreshReminderList();
    } catch (error) {
      addMessage("agent", `延后提醒失败：${error.message}`, "system");
      doneButton.disabled = false;
      snoozeButton.disabled = false;
    }
  });

  actions.appendChild(doneButton);
  actions.appendChild(snoozeButton);
  card.appendChild(meta);
  card.appendChild(text);
  card.appendChild(actions);
  inbox.prepend(card);
}

async function pollInbox() {
  const userId = Number(userIdInput.value);
  if (!userId) return;

  try {
    const result = await callJson(`/api/notifications/inbox?user_id=${userId}&after_id=${lastInboxId}`);
    for (const item of result.data || []) {
      addInboxItem(item);
      lastInboxId = Math.max(lastInboxId, item.id);
    }
  } catch (error) {
    console.error("poll inbox failed", error);
  }
}

function restartInboxPolling() {
  lastInboxId = 0;
  inbox.innerHTML = "";
  if (inboxTimer) clearInterval(inboxTimer);
  pollInbox();
  refreshReminderList();
  inboxTimer = setInterval(pollInbox, 5000);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = textarea.value.trim();
  if (!message) return;

  addMessage("user", message);
  textarea.value = "";
  submitButton.disabled = true;
  submitButton.textContent = "发送中...";

  try {
    const result = await sendMessage(message);
    await handleAgentResult(result.data);
  } catch (error) {
    addMessage("agent", `请求失败：${error.message}`, "system");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "发送";
    textarea.focus();
  }
});

userIdInput.addEventListener("change", restartInboxPolling);
userIdInput.addEventListener("input", restartInboxPolling);

toggleRemindersButton.addEventListener("click", () => {
  const expanded = toggleRemindersButton.getAttribute("aria-expanded") === "true";
  setReminderPanelExpanded(!expanded);
});

confirmDraftButton.onclick = async () => {
  confirmDraftButton.disabled = true;
  cancelDraftButton.disabled = true;
  await sendQuickReply(confirmDraftButton.dataset.message || "确认创建", [confirmDraftButton, cancelDraftButton]);
};

cancelDraftButton.onclick = async () => {
  confirmDraftButton.disabled = true;
  cancelDraftButton.disabled = true;
  await sendQuickReply(cancelDraftButton.dataset.message || "取消草案", [confirmDraftButton, cancelDraftButton]);
};

messages.innerHTML = "";
addMessage(
  "agent",
  "可以直接试试这些说法：\n- 明天下午三点提醒我交论文初稿\n- 帮我看看我的提醒\n- 今天23点31分发送，标题运动，仅一次提醒，优先级常规",
  "welcome"
);

restartInboxPolling();
setReminderPanelExpanded(false);
setDraftActionsVisible(false);
