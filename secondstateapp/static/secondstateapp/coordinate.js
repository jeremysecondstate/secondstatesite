(() => {
  "use strict";

  const root = document.getElementById("coordinate");
  if (!root) return;
  const selectedId = root.dataset.caseId;
  const messageList = document.getElementById("coordinate-message-list");
  const caseList = document.getElementById("coordinate-case-list");
  const trashList = document.getElementById("coordinate-trash-list");
  const planning = document.getElementById("coordinate-planning");
  const connection = document.getElementById("coordinate-connection");
  const statusLabels = { waiting: "Waiting", processing: "Processing", retrying: "Retrying", replied: "Replied", deleted: "In trash" };
  const messageLabels = {
    waiting: "Saved · Waiting for worker", processing: "Saved · Worker is responding",
    retrying: "Saved · Awaiting retry", replied: "Saved · Replied",
  };
  const processingLabels = {
    waiting: "Your message is saved. It will be picked up on the next worker check.",
    processing: "The worker is reading this conversation and preparing a reply.",
    retrying: "Your message is saved. The worker will retry it on a later check.",
    replied: "The conversation is up to date. Add a message whenever you’re ready.",
  };
  let timer;
  let inFlight = false;
  let failures = 0;
  let stopped = false;
  let caseDeleted = root.dataset.caseDeleted === "true";
  let latestState;
  let panelsInFlight = false;
  let actionInFlight = false;
  let mutationVersion = 0;
  let initialPlanning = {};
  const initialPlanningScript = document.getElementById("coordinate-initial-planning");
  if (initialPlanningScript) {
    try { initialPlanning = JSON.parse(initialPlanningScript.textContent) || {}; } catch (_) { /* Native forms remain available. */ }
    initialPlanningScript.remove();
  }
  const panelSignatures = Object.fromEntries(["plan", "quotes", "drafts", "research"].map((key) => [key, JSON.stringify(initialPlanning[key])]));
  initialPlanning = null;

  function text(element, value) {
    if (element && element.textContent !== String(value)) element.textContent = value;
  }

  function formatTime(element, value) {
    if (!element || !value) return;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return;
    const short = element.dataset.dateStyle === "short";
    element.dateTime = date.toISOString();
    element.title = date.toLocaleString(undefined, { timeZoneName: "short" });
    text(element, date.toLocaleString(undefined, short
      ? { month: "short", day: "numeric" }
      : { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }));
  }

  root.querySelectorAll("time[datetime]").forEach((element) => formatTime(element, element.dateTime));
  formatDeadlineInputs(root);
  root.querySelectorAll(".coordinate-message-body a").forEach((link) => {
    link.rel = "noopener noreferrer";
    link.target = "_blank";
  });
  if (messageList) messageList.scrollTop = messageList.scrollHeight;

  function safePath(value) {
    try {
      const url = new URL(value, window.location.origin);
      return url.origin === window.location.origin && url.pathname.startsWith("/coordinate/")
        ? url.pathname + url.search : null;
    } catch (_) { return null; }
  }

  function notice(value, error = false) {
    const element = document.getElementById("coordinate-action-notice");
    if (!element) return;
    element.hidden = !value;
    element.dataset.error = error ? "true" : "false";
    text(element, value);
  }

  function formatDeadlineInputs(container) {
    container.querySelectorAll("[data-new-york-datetime]").forEach((input) => {
      const value = input.dataset.newYorkDatetime;
      // Values with an explicit offset are converted to the form's stated timezone.
      if (!value || !/(Z|[+-]\d\d:\d\d)$/.test(value)) return;
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return;
      const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23",
      }).formatToParts(date).map((part) => [part.type, part.value]));
      input.value = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
      input.defaultValue = input.value;
    });
  }

  function renderAction(container, url, label) {
    if (!container) return;
    const path = safePath(url);
    if (!path) { container.replaceChildren(); return; }
    const existing = container.querySelector("form");
    if (existing?.getAttribute("action") === path) {
      text(existing.querySelector("button"), label);
      return;
    }
    const form = document.createElement("form");
    form.className = "coordinate-action-form coordinate-inline-form";
    form.method = "post";
    form.action = path;
    const csrf = document.createElement("input");
    csrf.type = "hidden";
    csrf.name = "csrfmiddlewaretoken";
    csrf.value = root.querySelector("input[name='csrfmiddlewaretoken']")?.value || "";
    const button = document.createElement("button");
    button.className = "coordinate-text-button";
    button.type = "submit";
    button.textContent = label;
    form.append(csrf, button);
    container.replaceChildren(form);
  }

  // Build links as DOM nodes: message content is always text, never injected HTML.
  function messageBody(element, body) {
    const fragment = document.createDocumentFragment();
    const pattern = /https?:\/\/[^\s<>]+/gi;
    let start = 0;
    for (const match of body.matchAll(pattern)) {
      fragment.append(document.createTextNode(body.slice(start, match.index)));
      let value = match[0];
      const trailing = value.match(/[.,;!?]+$/)?.[0] || "";
      value = value.slice(0, value.length - trailing.length);
      // Leave balanced URL parentheses alone, but exclude surrounding prose punctuation.
      let suffix = trailing;
      while (value.endsWith(")") && (value.match(/\)/g) || []).length > (value.match(/\(/g) || []).length) {
        value = value.slice(0, -1);
        suffix = ")" + suffix;
      }
      const link = document.createElement("a");
      link.href = value;
      link.textContent = value;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      fragment.append(link, document.createTextNode(suffix));
      start = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(body.slice(start)));
    element.replaceChildren(fragment);
    element.style.whiteSpace = "pre-wrap";
  }

  function setStatus(element, status) {
    if (!element) return;
    element.dataset.status = status;
    text(element, statusLabels[status] || "Saved");
  }

  function updateCases(cases, list = caseList, isTrash = false) {
    if (!list) return;
    const previous = new Map(Array.from(list.querySelectorAll("[data-case-id]"), (element) => [element.dataset.caseId, element]));
    if (cases.length) list.querySelector(".coordinate-no-cases, .coordinate-empty-list")?.remove();
    for (const [index, item] of cases.entries()) {
      const id = String(item.id);
      let link = previous.get(id);
      const href = safePath(item.url);
      if (!href) continue;
      if (!link) {
        link = document.createElement("a");
        link.className = "coordinate-case";
        link.dataset.caseId = id;
        const title = document.createElement("span");
        title.className = "coordinate-case-title";
        const meta = document.createElement("span");
        meta.className = "coordinate-case-meta";
        const status = document.createElement("span");
        status.className = "coordinate-status";
        const time = document.createElement("time");
        time.dataset.dateStyle = "short";
        meta.append(status, time);
        link.append(title, meta);
      }
      link.href = href;
      link.classList.toggle("is-selected", id === selectedId);
      if (id === selectedId) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
      text(link.querySelector(".coordinate-case-title"), item.title);
      setStatus(link.querySelector(".coordinate-status"), isTrash ? "deleted" : item.status);
      formatTime(link.querySelector("time"), item.updated_at);
      // Keep existing nodes (and keyboard focus) when their position has not changed.
      const atIndex = list.children[index];
      if (atIndex !== link) list.insertBefore(link, atIndex || null);
      previous.delete(id);
    }
    previous.forEach((element) => element.remove());
    if (!cases.length && !list.querySelector(".coordinate-no-cases, .coordinate-empty-list")) {
      const empty = document.createElement("p");
      empty.className = "coordinate-empty-list";
      empty.textContent = isTrash ? "Trash is empty." : "Start a new case to get things moving.";
      list.append(empty);
    }
    text(document.getElementById(isTrash ? "coordinate-trash-count" : "coordinate-case-count"), cases.length);
  }

  function updateMessages(messages) {
    if (!messageList) return;
    const nearBottom = messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight < 90;
    const previous = new Map(Array.from(messageList.querySelectorAll("[data-message-id]"), (element) => [element.dataset.messageId, element]));
    if (messages.length) messageList.querySelector(".coordinate-no-messages")?.remove();
    let added = false;
    for (const message of messages) {
      const id = String(message.id);
      let article = previous.get(id);
      if (!article) {
        article = document.createElement("article");
        const assistant = message.role === "assistant";
        const system = message.role === "system";
        article.className = `coordinate-message coordinate-message--${assistant ? "assistant" : system ? "system" : "staff"}`;
        article.dataset.messageId = id;
        const avatar = document.createElement("div");
        avatar.className = "coordinate-message-avatar";
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = assistant || system ? "C" : "S";
        const content = document.createElement("div");
        content.className = "coordinate-message-content";
        const heading = document.createElement("div");
        heading.className = "coordinate-message-heading";
        const author = document.createElement("strong");
        author.textContent = assistant ? "Codex" : system ? "Coordinate" : message.author || "Staff";
        const time = document.createElement("time");
        formatTime(time, message.created_at);
        heading.append(author, time);
        const body = document.createElement("div");
        body.className = "coordinate-message-body";
        content.append(heading, body);
        const footer = document.createElement("div");
        footer.className = "coordinate-message-footer";
        if (!assistant && !system) {
          const status = document.createElement("span");
          status.className = "coordinate-message-status";
          footer.append(status);
        }
        const actions = document.createElement("div");
        actions.className = "coordinate-message-actions";
        footer.append(actions);
        content.append(footer);
        article.append(avatar, content);
        messageList.append(article);
        added = true;
      }
      const deleted = Boolean(message.deleted);
      const hidden = deleted || caseDeleted;
      const deletionChanged = article.dataset.deleted !== String(deleted) || article.dataset.caseHidden !== String(caseDeleted);
      if (deletionChanged) {
        const body = article.querySelector(".coordinate-message-body");
        if (hidden) {
          // Discard prior message content immediately; never retain it in hidden DOM.
          body.replaceChildren(document.createTextNode(caseDeleted ? "Hidden while this case is in trash." : "Message deleted. Restore to show it again."));
        } else {
          messageBody(body, String(message.body || ""));
        }
        article.dataset.deleted = String(deleted);
        article.dataset.caseHidden = String(caseDeleted);
      }
      article.classList.toggle("is-deleted", hidden);
      const actions = article.querySelector(".coordinate-message-actions");
      if (caseDeleted) actions?.replaceChildren();
      else renderAction(actions, deleted ? message.restore_url : message.delete_url, deleted ? "Restore" : "Delete");
      const status = article.querySelector(".coordinate-message-status");
      if (status) {
        status.hidden = hidden;
        status.dataset.status = message.status;
        text(status, messageLabels[message.status] || "Saved");
      }
    }
    if (added && nearBottom) messageList.scrollTop = messageList.scrollHeight;
  }

  function updateState(state) {
    latestState = state;
    if (Array.isArray(state.cases)) updateCases(state.cases);
    if (Array.isArray(state.trash_cases)) updateCases(state.trash_cases, trashList, true);
    if (selectedId && String(state.selected_case?.id) === selectedId) {
      caseDeleted = Boolean(state.selected_case.deleted);
      root.dataset.caseDeleted = String(caseDeleted);
      setStatus(document.getElementById("coordinate-case-status"), caseDeleted ? "deleted" : state.selected_case.status);
      text(document.getElementById("coordinate-processing-note"), caseDeleted
        ? "This case is in trash. Restore it to see its messages and continue coordinating."
        : processingLabels[state.selected_case.status] || "Your conversation is saved.");
      renderAction(document.getElementById("coordinate-case-actions"), caseDeleted ? state.selected_case.restore_url : state.selected_case.delete_url, caseDeleted ? "Restore case" : "Move to trash");
      const composeFields = document.getElementById("coordinate-compose-fields");
      if (composeFields) composeFields.disabled = caseDeleted;
      if (caseDeleted) {
        document.getElementById("coordinate-trash").open = true;
        if (planning) { planning.hidden = true; planning.replaceChildren(); }
        Object.keys(panelSignatures).forEach((key) => { panelSignatures[key] = undefined; });
      } else if (planning) planning.hidden = !state.coordination;
      if (Array.isArray(state.messages)) updateMessages(state.messages);
      updatePlanningRestrictions(state.coordination);
      refreshPanels(state);
    }
    const check = state.worker?.last_successful_check;
    const lastCheck = document.getElementById("coordinate-last-check");
    if (check) {
      let time = lastCheck.querySelector("time");
      if (!time) {
        time = document.createElement("time");
        lastCheck.replaceChildren(time);
      }
      formatTime(time, check);
    }
  }

  function updatePlanningRestrictions(coordination) {
    if (!planning || !coordination) return;
    const quotes = new Map((coordination.quotes || []).map((quote) => [String(quote.id), quote]));
    planning.querySelectorAll("[data-quote-id]").forEach((card) => {
      const quote = quotes.get(card.dataset.quoteId);
      if (!quote) return;
      card.classList.toggle("is-paused", Boolean(quote.paused));
      const warning = card.querySelector("[data-quote-pause]");
      if (warning) warning.hidden = !quote.paused;
    });
    const drafts = new Map((coordination.drafts || []).map((draft) => [String(draft.id), draft]));
    planning.querySelectorAll("[data-draft-id]").forEach((card) => {
      const draft = drafts.get(card.dataset.draftId);
      // A deleted source message may remove its derived draft from visible state.
      if (!draft) { card.remove(); return; }
      const warning = card.querySelector("[data-draft-blocked]");
      if (warning) warning.hidden = !draft.blocked;
      const review = card.querySelector(".coordinate-draft-review button[type='submit']");
      if (review && !actionInFlight) {
        review.disabled = Boolean(draft.blocked) || draft.status === "reviewed";
        text(review, draft.status === "reviewed" ? "Reviewed" : "Mark reviewed");
      }
    });
  }

  async function refreshPanels(state) {
    if (!planning || caseDeleted || !state.coordination || panelsInFlight) return;
    const changed = Object.keys(panelSignatures).filter((key) => {
      const panel = planning.querySelector(`[data-panel='${key}']`);
      const dirty = panel?.querySelector("form[data-dirty='true']");
      if (dirty) {
        if (JSON.stringify(state.coordination[key]) !== panelSignatures[key]) panel.dataset.updatesPending = "true";
        else delete panel.dataset.updatesPending;
        return false;
      }
      if (panel) delete panel.dataset.updatesPending;
      return JSON.stringify(state.coordination[key]) !== panelSignatures[key] || !panel;
    });
    if (!changed.length) return;
    const path = safePath(state.selected_case?.url);
    if (!path) return;
    panelsInFlight = true;
    const version = mutationVersion;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, { credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal });
      if (!response.ok) throw new Error("Panel refresh unavailable");
      const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
      if (caseDeleted || version !== mutationVersion) return;
      for (const key of changed) {
        const existing = planning.querySelector(`[data-panel='${key}']`);
        if (existing?.querySelector("form[data-dirty='true']")) continue;
        const incoming = documentCopy.querySelector(`#coordinate-planning [data-panel='${key}']`);
        if (!incoming) continue;
        const replacement = document.importNode(incoming, true);
        if (existing) {
          replacement.open = existing.open;
          const nestedOpen = Array.from(existing.querySelectorAll("details"), (item) => item.open);
          replacement.querySelectorAll("details").forEach((item, index) => { item.open = nestedOpen[index] || false; });
          existing.replaceWith(replacement);
        } else planning.append(replacement);
        replacement.querySelectorAll("time[datetime]").forEach((element) => formatTime(element, element.dateTime));
        formatDeadlineInputs(replacement);
        panelSignatures[key] = JSON.stringify(state.coordination[key]);
      }
    } catch (_) {
      // Conversation polling continues; changed panels are retried on the next check.
    } finally {
      clearTimeout(timeout);
      panelsInFlight = false;
    }
  }

  async function poll() {
    clearTimeout(timer);
    if (stopped || inFlight) return;
    if (actionInFlight) { timer = setTimeout(poll, 3000); return; }
    if (document.hidden) {
      timer = setTimeout(poll, 10000);
      return;
    }
    inFlight = true;
    const version = mutationVersion;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const url = new URL(root.dataset.stateUrl, window.location.origin);
      if (selectedId) url.searchParams.set("case", selectedId);
      const response = await fetch(url, {
        credentials: "same-origin", cache: "no-store", redirect: "error",
        headers: { Accept: "application/json" }, signal: controller.signal,
      });
      if (response.status === 401 || response.status === 403) {
        stopped = true;
        connection.dataset.state = "error";
        text(connection, "Your staff session has ended. Reload and sign in to resume live updates.");
        return;
      }
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error("Refresh unavailable");
      const state = await response.json();
      if (version !== mutationVersion || actionInFlight) return;
      updateState(state);
      failures = 0;
      connection.dataset.state = "connected";
      text(connection, "Live updates connected");
    } catch (_) {
      failures += 1;
      connection.dataset.state = "error";
      text(connection, "Live updates interrupted. Retrying automatically; reload to check your session.");
    } finally {
      clearTimeout(timeout);
      inFlight = false;
      if (!stopped) timer = setTimeout(poll, Math.min(3000 * Math.max(1, failures), 15000));
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });
  root.addEventListener("input", (event) => {
    const form = event.target.closest(".coordinate-planning .coordinate-action-form");
    if (form) form.dataset.dirty = "true";
  });
  root.addEventListener("change", (event) => {
    const form = event.target.closest(".coordinate-planning .coordinate-action-form");
    if (form) form.dataset.dirty = "true";
  });
  root.addEventListener("reset", (event) => {
    if (!event.target.matches(".coordinate-action-form")) return;
    delete event.target.dataset.dirty;
    setTimeout(() => { if (latestState) refreshPanels(latestState); }, 0);
  });
  root.addEventListener("click", async (event) => {
    const button = event.target.closest(".coordinate-copy-draft");
    if (!button) return;
    const form = button.closest("form");
    const value = `to: ${form.elements.recipient.value}\nsubject: ${form.elements.subject.value}\n\n${form.elements.body.value}`;
    try {
      await navigator.clipboard.writeText(value);
      notice("Draft copied. No email has been sent.");
    } catch (_) {
      form.elements.body.focus();
      form.elements.body.select();
      notice("Select and copy the draft text. Clipboard access is unavailable in this browser.");
    }
  });
  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.matches(".coordinate-action-form")) return;
    event.preventDefault();
    if (actionInFlight) { notice("Please wait for the current change to finish."); return; }
    if (form.matches(".coordinate-draft-review") && form.closest(".coordinate-draft")?.querySelector("form[data-dirty='true']")) {
      notice("Save the draft’s changes before marking it reviewed.", true);
      return;
    }
    const path = safePath(form.getAttribute("action"));
    if (!path) { notice("This action is unavailable. Reload the page and try again.", true); return; }
    const button = event.submitter || form.querySelector("button[type='submit']");
    const label = button?.textContent || "";
    const payload = new FormData(form);
    actionInFlight = true;
    mutationVersion += 1;
    if (button) { button.disabled = true; button.textContent = "Saving…"; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(path, {
        method: "POST", body: payload, credentials: "same-origin", redirect: "error",
        headers: { Accept: "application/json" }, signal: controller.signal,
      });
      const isJson = response.headers.get("content-type")?.includes("application/json");
      const result = isJson ? await response.json() : null;
      if (!response.ok) throw new Error(result?.error || "This change could not be saved. Reload and check your staff session.");
      if (!result?.selected_case) throw new Error("The server did not confirm the change. Reload to check before trying again.");
      delete form.dataset.dirty;
      mutationVersion += 1;
      updateState(result);
      notice(label.includes("Delete") ? "Message deleted. You can restore it in this conversation."
        : label.includes("Move to trash") ? "Case moved to trash. You can restore it at any time."
        : label.includes("Restore") ? "Restored."
        : label.includes("reviewed") || label.includes("review") ? "Review saved. No email was sent or payment authorized."
        : "Saved.");
    } catch (error) {
      notice(error.name === "AbortError"
        ? "The server has not confirmed this change yet. Reload to check before trying again."
        : error instanceof TypeError ? "The connection was interrupted. Reload to check whether the change saved before trying again."
        : error.message || "Unable to save. Your edits are still here.", true);
    } finally {
      clearTimeout(timeout);
      actionInFlight = false;
      if (button?.isConnected) { button.disabled = false; button.textContent = label; }
      if (latestState) updatePlanningRestrictions(latestState.coordination);
    }
  });
  // Retain the same idempotency token on retry. Native POST also works without JS.
  root.querySelectorAll(".coordinate-composer, .coordinate-new-form").forEach((form) => {
    const body = form.querySelector("textarea[name='body']");
    body.addEventListener("input", () => body.setCustomValidity(""));
    form.addEventListener("submit", (event) => {
      if (!body.value.trim()) {
        event.preventDefault();
        body.setCustomValidity("Write a message to continue.");
        body.reportValidity();
        return;
      }
      const button = form.querySelector("button[type='submit']");
      button.disabled = true;
      button.textContent = "Saving…";
    });
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      root.querySelectorAll(".coordinate-composer button[type='submit'], .coordinate-new-form button[type='submit']").forEach((button) => {
        button.disabled = false;
        button.textContent = selectedId ? "Send message ↗" : "Start case ↗";
      });
      poll();
    }
  });
  poll();
})();
