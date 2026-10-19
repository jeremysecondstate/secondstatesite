(() => {
  "use strict";

  const root = document.getElementById("coordinate");
  if (!root) return;
  const selectedId = root.dataset.caseId;
  const messageList = document.getElementById("coordinate-message-list");
  const caseList = document.getElementById("coordinate-case-list");
  const connection = document.getElementById("coordinate-connection");
  const statusLabels = { waiting: "Waiting", processing: "Processing", retrying: "Retrying", replied: "Replied" };
  const messageLabels = {
    waiting: "Saved · Waiting for worker", processing: "Saved · Worker is responding",
    retrying: "Saved · Awaiting retry", replied: "Saved · Replied",
  };
  const processingLabels = {
    waiting: "Your message is saved. It will be picked up on the next manual worker run.",
    processing: "The worker is reading this conversation and preparing a reply.",
    retrying: "Your message is saved. The worker will retry it on a later manual run.",
    replied: "The conversation is up to date. Add a message whenever you’re ready.",
  };
  let timer;
  let inFlight = false;
  let failures = 0;
  let stopped = false;

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

  function updateCases(cases) {
    const previous = new Map(Array.from(caseList.querySelectorAll("[data-case-id]"), (element) => [element.dataset.caseId, element]));
    if (cases.length) caseList.querySelector(".coordinate-no-cases")?.remove();
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
      setStatus(link.querySelector(".coordinate-status"), item.status);
      formatTime(link.querySelector("time"), item.updated_at);
      // Keep existing nodes (and keyboard focus) when their position has not changed.
      const atIndex = caseList.children[index];
      if (atIndex !== link) caseList.insertBefore(link, atIndex || null);
      previous.delete(id);
    }
    previous.forEach((element) => element.remove());
    text(document.getElementById("coordinate-case-count"), cases.length);
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
        article.className = `coordinate-message coordinate-message--${assistant ? "assistant" : "staff"}`;
        article.dataset.messageId = id;
        const avatar = document.createElement("div");
        avatar.className = "coordinate-message-avatar";
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = assistant ? "C" : "S";
        const content = document.createElement("div");
        content.className = "coordinate-message-content";
        const heading = document.createElement("div");
        heading.className = "coordinate-message-heading";
        const author = document.createElement("strong");
        author.textContent = assistant ? "Codex" : message.author || "Staff";
        const time = document.createElement("time");
        formatTime(time, message.created_at);
        heading.append(author, time);
        const body = document.createElement("div");
        body.className = "coordinate-message-body";
        messageBody(body, String(message.body || ""));
        content.append(heading, body);
        if (!assistant) {
          const status = document.createElement("span");
          status.className = "coordinate-message-status";
          content.append(status);
        }
        article.append(avatar, content);
        messageList.append(article);
        added = true;
      }
      const status = article.querySelector(".coordinate-message-status");
      if (status) {
        status.dataset.status = message.status;
        text(status, messageLabels[message.status] || "Saved");
      }
    }
    if (added && nearBottom) messageList.scrollTop = messageList.scrollHeight;
  }

  function updateState(state) {
    if (Array.isArray(state.cases)) updateCases(state.cases);
    if (selectedId && String(state.selected_case?.id) === selectedId) {
      setStatus(document.getElementById("coordinate-case-status"), state.selected_case.status);
      text(document.getElementById("coordinate-processing-note"), processingLabels[state.selected_case.status] || "Your conversation is saved.");
      if (Array.isArray(state.messages)) updateMessages(state.messages);
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

  async function poll() {
    clearTimeout(timer);
    if (stopped || inFlight) return;
    if (document.hidden) {
      timer = setTimeout(poll, 10000);
      return;
    }
    inFlight = true;
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
      updateState(await response.json());
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
  // Retain the same idempotency token on retry. Native POST also works without JS.
  root.querySelectorAll("form").forEach((form) => {
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
      root.querySelectorAll("button[type='submit']").forEach((button) => {
        button.disabled = false;
        button.textContent = selectedId ? "Send message ↗" : "Start case ↗";
      });
      poll();
    }
  });
  poll();
})();
