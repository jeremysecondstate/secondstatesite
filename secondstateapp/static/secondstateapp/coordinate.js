(() => {
  "use strict";

  const root = document.getElementById("coordinate");
  if (!root) return;
  const selectedId = root.dataset.caseId;
  const messageList = document.getElementById("coordinate-message-list");
  const replyDrafts = document.getElementById("coordinate-reply-drafts");
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
  const uncertainEmailSends = new Set();
  const renderedMessageBodies = new WeakMap();
  let initialPlanning = {};
  const initialPlanningScript = document.getElementById("coordinate-initial-planning");
  if (initialPlanningScript) {
    try { initialPlanning = JSON.parse(initialPlanningScript.textContent) || {}; } catch (_) { /* Native forms remain available. */ }
    initialPlanningScript.remove();
  }
  const panelKeys = { drafts: "drafts", mail: "mail", briefing: "brief", intake: "intake", plan: "plan", quotes: "quotes", research: "research" };
  const panelSignatures = Object.fromEntries(Object.keys(panelKeys).map((key) => [key, panelSignature(initialPlanning, key)]));

  function panelSignature(coordination, key) {
    const value = coordination?.[panelKeys[key]];
    // A fresh retry token is not a content update and must not replace an upload form.
    if (key === "intake" && value) {
      const { submission_token, ...content } = value;
      return JSON.stringify(content);
    }
    if (key === "drafts") return JSON.stringify({ drafts: value, mail: coordination?.mail });
    return JSON.stringify(value);
  }

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
  root.querySelectorAll(".coordinate-message-body").forEach((element) => {
    const article = element.closest(".coordinate-message");
    if (article) renderedMessageBodies.set(article, element.textContent);
    conversationBody(element, element.textContent, Boolean(element.closest(".coordinate-message--assistant:not(.is-deleted)")));
  });
  root.querySelectorAll(".coordinate-email-body").forEach((element) => messageBody(element, element.textContent));
  updateWorkspaceLinks(initialPlanning);
  initialPlanning = null;
  prepareSourceLinks(root);
  if (messageList) messageList.scrollTop = messageList.scrollHeight;

  function safePath(value) {
    try {
      const url = new URL(value, window.location.origin);
      return url.origin === window.location.origin && url.pathname.startsWith("/coordinate/")
        ? url.pathname + url.search : null;
    } catch (_) { return null; }
  }

  function httpLink(value) {
    if (typeof value !== "string" || /[\s\\\u0000-\u001f\u007f]/.test(value)) return null;
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? value : null;
    } catch (_) { return null; }
  }

  function prepareSourceLinks(container) {
    container.querySelectorAll("[data-source-link], [data-private-download]").forEach((link) => {
      const value = link.getAttribute("href") || "";
      const anchor = /^#coordinate-(?:message-\d+|document-[0-9a-f-]{36}|email-[0-9a-f-]{36}|mail-thread-[0-9a-f-]{36})$/i.test(value);
      const privatePath = value.startsWith("/") && safePath(value);
      if (anchor || privatePath) return;
      if (link.hasAttribute("data-private-download") || !httpLink(value)) {
        link.replaceWith(document.createTextNode(link.textContent));
        return;
      }
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
  }

  function notice(value, error = false) {
    const element = document.getElementById("coordinate-action-notice");
    if (!element) return;
    element.hidden = !value;
    element.dataset.error = error ? "true" : "false";
    text(element, value);
  }

  function newYorkDatetime(value) {
    // Only explicit ISO timestamps can fill the deadline; prose dates remain questions.
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(date).map((part) => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }

  function formatDeadlineInputs(container) {
    container.querySelectorAll("[data-new-york-datetime]").forEach((input) => {
      const value = newYorkDatetime(input.dataset.newYorkDatetime);
      if (!value) return;
      input.value = value;
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

  function appendLink(fragment, label, value) {
    if (!httpLink(value)) { fragment.append(document.createTextNode(label)); return; }
    const link = document.createElement("a");
    link.href = value;
    link.textContent = label;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    fragment.append(link);
  }

  function appendBareLinks(fragment, body) {
    const pattern = /https?:\/\/[^\s<>"'`]+/gi;
    let start = 0;
    for (const match of body.matchAll(pattern)) {
      fragment.append(document.createTextNode(body.slice(start, match.index)));
      let value = match[0];
      const trailing = value.match(/[.,;!?]+$/)?.[0] || "";
      value = value.slice(0, value.length - trailing.length);
      // Leave balanced URL parentheses alone, but exclude surrounding prose punctuation.
      let suffix = trailing;
      for (const [opening, closing] of [["(", ")"], ["[", "]"], ["{", "}"]]) {
        while (value.endsWith(closing) && value.split(closing).length > value.split(opening).length) {
          value = value.slice(0, -1);
          suffix = closing + suffix;
        }
      }
      appendLink(fragment, value, value);
      fragment.append(document.createTextNode(suffix));
      start = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(body.slice(start)));
  }

  // The only Markdown feature is [label](http(s) URL). Everything else remains
  // literal text, and no message content is ever interpreted as HTML.
  function messageBody(element, body) {
    const fragment = document.createDocumentFragment();
    const pattern = /\[([^\]\n]{1,300})\]\((?=https?:\/\/)/gi;
    let start = 0;
    for (const match of body.matchAll(pattern)) {
      if (match.index < start) continue;
      const urlStart = match.index + match[0].length;
      let end = urlStart;
      let depth = 0;
      for (; end < body.length; end += 1) {
        const char = body[end];
        if (/[\s<>"'`]/.test(char)) break;
        if (char === "(") depth += 1;
        else if (char === ")") {
          if (!depth) break;
          depth -= 1;
        }
      }
      const value = body.slice(urlStart, end);
      if (body[end] !== ")" || depth || !httpLink(value)) continue;
      appendBareLinks(fragment, body.slice(start, match.index));
      appendLink(fragment, match[1], value);
      start = end + 1;
    }
    appendBareLinks(fragment, body.slice(start));
    element.replaceChildren(fragment);
    element.style.whiteSpace = "pre-wrap";
  }

  function conversationBody(element, body, assistant) {
    // Keep older, lengthy replies readable without losing any of their wording.
    if (!assistant || body.length <= 900) { messageBody(element, body); return; }
    const firstParagraph = body.split(/\n\s*\n/)[0];
    const lead = document.createElement("div");
    lead.className = "coordinate-response-preview";
    messageBody(lead, firstParagraph);
    if (lead.textContent.length > 360) {
      const preview = lead.textContent.slice(0, 360).replace(/\s+\S*$/, "") + "…";
      lead.replaceChildren(document.createTextNode(preview));
    }
    const details = document.createElement("details");
    details.className = "coordinate-response-details";
    const summary = document.createElement("summary");
    summary.textContent = "Read full Coordinator response";
    const full = document.createElement("div");
    messageBody(full, body);
    details.append(summary, full);
    element.replaceChildren(lead, details);
    element.style.whiteSpace = "normal";
  }

  function workspaceItems(coordination) {
    const items = replyDraftBundle(coordination).map((draft) => ({
      panel: "drafts", target: `coordinate-draft-${draft.id}`, label: `Email draft · ${draft.subject || "Untitled draft"}`,
    }));
    if (coordination.brief) items.push({ panel: "briefing", label: `Case brief · ${(coordination.brief.lots || []).length} lots` });
    if (coordination.research?.length) items.push({ panel: "research", label: `Sources · ${coordination.research.length}` });
    return items;
  }

  function replyDraftBundle(coordination) {
    // Keep the exact latest reply's bundle, including delivered messages. Filtering
    // all case drafts before taking three can resurrect superseded old wording.
    const bundle = coordination?.chat_send;
    if (!bundle?.reply_id || !Array.isArray(bundle.drafts) || !bundle.drafts.length || bundle.drafts.length > 3) return [];
    const visible = coordination.drafts || [];
    const drafts = new Map(visible.map((draft) => [String(draft.id), draft]));
    const ids = bundle.drafts.map((item) => String(item.id));
    if (drafts.size !== visible.length || new Set(ids).size !== ids.length) return [];
    const matched = bundle.drafts.map((item) => drafts.get(String(item.id)));
    // The payload and signed snapshot can come from separate database reads.
    // Never approve a missing row or wording from a different saved version.
    if (matched.some((draft, index) => !draft || !bundle.drafts[index].content_digest
        || draft.current_digest !== bundle.drafts[index].content_digest)) return [];
    return matched;
  }

  function setSendContext(context) {
    const field = document.getElementById("coordinate-send-context");
    if (field) field.value = context?.token ? JSON.stringify(context) : "";
  }

  function prepareChatSendContext(form) {
    const field = form.elements.send_context;
    if (!field?.value) return;
    let context;
    try { context = JSON.parse(field.value); } catch (_) { field.value = ""; return; }
    const ids = new Set((context.drafts || []).map((draft) => String(draft.id)));
    const dirty = Array.from(planning?.querySelectorAll(".coordinate-draft[data-draft-id]") || [])
      .some((card) => ids.has(card.dataset.draftId) && card.querySelector("form[data-dirty='true']"));
    if (dirty || caseDeleted) {
      // Ordinary chat still works; a send instruction receives the server's
      // actionable missing-context response instead of sending unsaved wording.
      field.value = "";
      if (dirty) notice("Save or reset the draft’s edits before asking to send it.", true);
    }
  }

  function renderDraftPreview(draft, open = false) {
    const card = document.createElement("details");
    card.className = "coordinate-reply-draft";
    card.id = `coordinate-reply-draft-${draft.id}`;
    card.dataset.previewDraftId = String(draft.id);
    card.open = open;
    const summary = document.createElement("summary");
    summary.className = "coordinate-record-summary";
    const subject = document.createElement("span");
    subject.className = "coordinate-record-heading";
    subject.textContent = draft.subject || "Untitled draft";
    const recipient = document.createElement("span");
    recipient.className = "coordinate-record-preview";
    recipient.textContent = `${draft.quote_test ? "Intended provider" : "To"}: ${draft.recipient || "Recipient needed"}`;
    summary.append(subject, recipient);
    const content = document.createElement("div");
    content.className = "coordinate-record-content";
    if (draft.quote_test) {
      const route = document.createElement("p");
      route.className = "coordinate-mail-test-route";
      route.textContent = `Quote test · Actual recipient: ${draft.actual_recipient || "Not confirmed"}. The provider is not contacted by this test.`;
      content.append(route);
    }
    const body = document.createElement("div");
    body.className = "coordinate-reply-draft-body";
    // Saved wording remains text, and the canonical editor retains manual Send.
    body.textContent = String(draft.body || "");
    const footer = document.createElement("div");
    footer.className = "coordinate-reply-draft-footer";
    const status = document.createElement("span");
    const deliveryLabels = { sent: "Sent", unknown: "Delivery not confirmed", sending: "Sending", queued: "Send queued" };
    const locked = Object.hasOwn(deliveryLabels, draft.send_status) || draft.editable === false;
    status.textContent = deliveryLabels[draft.send_status] || (draft.blocked ? "Provider review needed"
      : draft.status === "reviewed" ? "Reviewed version" : "Draft for review");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "coordinate-button coordinate-button-secondary";
    edit.dataset.openPanel = "drafts";
    edit.dataset.openRecord = `coordinate-draft-${draft.id}`;
    edit.textContent = locked ? "View email details" : "Review and edit draft";
    footer.append(status, edit);
    content.append(body, footer);
    card.append(summary, content);
    return card;
  }

  function updateReplyDrafts(coordination, replyId) {
    if (!replyDrafts) return;
    const context = coordination?.chat_send;
    const drafts = !caseDeleted && replyId ? replyDraftBundle(coordination) : [];
    if (!drafts.length) {
      replyDrafts.hidden = true;
      replyDrafts.replaceChildren();
      delete replyDrafts.dataset.signature;
      setSendContext(null);
      return;
    }
    const composer = document.getElementById("coordinate-body");
    const field = document.getElementById("coordinate-send-context");
    // A new poll must not silently substitute different emails while the user
    // writes their approval. The server rejects this older binding if it changed.
    if (composer?.value.trim() && (composer.dataset.sendContextFrozen === "true" || (field?.value && replyDrafts.dataset.signature))) {
      const visibleIds = new Set((coordination.drafts || []).map((draft) => String(draft.id)));
      const displayed = Array.from(replyDrafts.querySelectorAll("[data-preview-draft-id]"));
      if (displayed.every((card) => visibleIds.has(card.dataset.previewDraftId))) return;
      replyDrafts.hidden = true;
      replyDrafts.replaceChildren();
      delete replyDrafts.dataset.signature;
      setSendContext(null);
      return;
    }
    setSendContext(context);
    const signature = JSON.stringify([context, drafts.map(({ id, recipient, subject, body, status, blocked, quote_test, actual_recipient, send_status, editable }) =>
      ({ id, recipient, subject, body, status, blocked, quote_test, actual_recipient, send_status, editable }))]);
    if (replyDrafts.dataset.signature === signature) return;
    const states = new Map(Array.from(replyDrafts.querySelectorAll("[data-preview-draft-id]"), (card) => [card.dataset.previewDraftId, card.open]));
    const heading = document.createElement("div");
    heading.className = "coordinate-reply-drafts-heading";
    const title = document.createElement("h3");
    title.textContent = "Email drafts";
    const count = document.createElement("span");
    const pending = drafts.filter((draft) => draft.editable !== false && !["queued", "sending", "sent", "unknown"].includes(draft.send_status)).length;
    count.textContent = pending ? `${pending} ready to review` : "Delivery status";
    heading.append(title, count);
    replyDrafts.replaceChildren(heading, ...drafts.map((draft, index) =>
      renderDraftPreview(draft, states.has(String(draft.id)) ? states.get(String(draft.id)) : index === 0)));
    replyDrafts.hidden = false;
    replyDrafts.dataset.signature = signature;
  }

  function updateWorkspaceLinks(coordination) {
    if (!messageList) return;
    const replies = Array.from(messageList.querySelectorAll(".coordinate-message--assistant:not(.is-deleted)"));
    const latest = replies[replies.length - 1];
    updateReplyDrafts(coordination, latest?.dataset.messageId);
    messageList.querySelectorAll(".coordinate-message-workspace").forEach((tray) => {
      if (tray.parentElement !== latest?.querySelector(".coordinate-message-content") || caseDeleted || !coordination) tray.remove();
    });
    if (!latest || caseDeleted || !coordination) return;
    const items = workspaceItems(coordination).filter((item) => item.panel !== "drafts" || !replyDrafts || replyDrafts.hidden);
    const content = latest.querySelector(".coordinate-message-content");
    let tray = content.querySelector(".coordinate-message-workspace");
    if (!items.length) { tray?.remove(); return; }
    const signature = JSON.stringify(items);
    if (tray?.dataset.signature === signature) return;
    if (!tray) {
      tray = document.createElement("nav");
      tray.className = "coordinate-message-workspace";
      tray.setAttribute("aria-label", "Open case contents");
      content.append(tray);
    }
    const label = document.createElement("span");
    label.textContent = "In this case";
    const buttons = items.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "coordinate-workspace-link";
      button.dataset.openPanel = item.panel;
      if (item.target) button.dataset.openRecord = item.target;
      button.textContent = item.label;
      return button;
    });
    tray.replaceChildren(label, ...buttons);
    tray.dataset.signature = signature;
  }

  function detailKey(item, container) {
    // Record IDs survive insertions and reorderings. Unkeyed disclosures are
    // scoped to their nearest keyed record so a new draft cannot inherit another's state.
    if (item.dataset.stateKey) return item.dataset.stateKey;
    if (item.id) return item.id;
    const owner = item.parentElement?.closest("details[id]");
    const scope = owner && container.contains(owner) ? owner : container;
    const summary = item.querySelector("summary")?.textContent.trim() || "";
    return `${scope.id || scope.dataset.panel}/${summary}`;
  }

  function preserveDetails(existing, replacement) {
    replacement.open = existing.open;
    const states = new Map(Array.from(existing.querySelectorAll("details"), (item) => [detailKey(item, existing), item.open]));
    replacement.querySelectorAll("details").forEach((item) => {
      const key = detailKey(item, replacement);
      if (states.has(key)) item.open = states.get(key);
    });
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
    if (isTrash) {
      const emptyTrash = document.getElementById("coordinate-empty-trash");
      if (emptyTrash) emptyTrash.hidden = cases.length === 0;
    }
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
        article.id = `coordinate-message-${id}`;
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
      const bodyText = String(message.body || "");
      if (deletionChanged || (!hidden && renderedMessageBodies.get(article) !== bodyText)) {
        const body = article.querySelector(".coordinate-message-body");
        if (hidden) {
          // Discard prior message content immediately; never retain it in hidden DOM.
          body.replaceChildren(document.createTextNode(caseDeleted ? "Hidden while this case is in trash." : "Message deleted. Restore to show it again."));
          renderedMessageBodies.delete(article);
        } else {
          conversationBody(body, bodyText, message.role === "assistant");
          renderedMessageBodies.set(article, bodyText);
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
      updateWorkspaceLinks(state.coordination);
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
      const locked = draft.editable === false || ["queued", "sending", "sent", "unknown"].includes(draft.send_status);
      const dirty = Boolean(card.querySelector("form[data-dirty='true']"));
      card.dataset.sendStatus = draft.send_status || "";
      const fields = card.querySelector(".coordinate-draft-fields");
      if (fields) fields.disabled = locked;
      text(card.querySelector("[data-delivery-status]"), draft.send_status || draft.status || "Draft");
      const deliveryNote = card.querySelector("[data-delivery-note]");
      if (deliveryNote) {
        deliveryNote.hidden = !locked;
        if (locked) text(deliveryNote, draft.send_status === "sent"
          ? "Sent. This message is read-only. The sent version appears in its linked email thread. Start a reply draft to continue."
          : draft.send_status === "unknown"
          ? "Delivery has not been confirmed. This message is locked while its status is checked. Do not resend it or create a duplicate."
          : "Sending is in progress. This message is locked while delivery is checked.");
      }
      if (locked) uncertainEmailSends.delete(String(draft.id));
      const review = card.querySelector(".coordinate-draft-review button[type='submit']");
      if (review && !actionInFlight) {
        const reviewed = draft.status === "reviewed" && draft.reviewed_digest && draft.reviewed_digest === draft.current_digest;
        review.disabled = Boolean(draft.blocked) || Boolean(reviewed) || locked || dirty;
        text(review, reviewed ? "Reviewed" : draft.status === "reviewed" ? "Review current draft" : "Mark reviewed");
      }
      const sendForm = card.querySelector(".coordinate-draft-send");
      const send = sendForm?.querySelector("button[type='submit']");
      if (send) {
        const current = sendForm.elements.content_digest?.value;
        const valid = Boolean(coordination.mail?.enabled && coordination.mail?.ready && draft.can_send
          && draft.status === "reviewed" && draft.reviewed_digest && draft.reviewed_digest === draft.current_digest
          && current === draft.reviewed_digest && !draft.blocked && !locked);
        sendForm.hidden = !valid;
        send.disabled = !valid || dirty || actionInFlight || uncertainEmailSends.has(String(draft.id));
      }
    });
  }

  async function refreshPanels(state) {
    if (!planning || caseDeleted || !state.coordination || panelsInFlight) return;
    const changed = Object.keys(panelSignatures).filter((key) => {
      const panel = planning.querySelector(`[data-panel='${key}']`);
      const dirty = panel?.querySelector("form[data-dirty='true']");
      if (dirty) {
        if (panelSignature(state.coordination, key) !== panelSignatures[key]) panel.dataset.updatesPending = "true";
        else delete panel.dataset.updatesPending;
        return false;
      }
      if (panel) delete panel.dataset.updatesPending;
      return panelSignature(state.coordination, key) !== panelSignatures[key] || !panel;
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
      if (!planning.querySelector(".coordinate-workspace-heading")) {
        const heading = documentCopy.querySelector("#coordinate-planning .coordinate-workspace-heading");
        if (heading) planning.prepend(document.importNode(heading, true));
      }
      for (const key of changed) {
        const existing = planning.querySelector(`[data-panel='${key}']`);
        if (existing?.querySelector("form[data-dirty='true']")) continue;
        const incoming = documentCopy.querySelector(`#coordinate-planning [data-panel='${key}']`);
        if (!incoming) continue;
        const replacement = document.importNode(incoming, true);
        if (existing) {
          preserveDetails(existing, replacement);
          existing.replaceWith(replacement);
        } else planning.append(replacement);
        replacement.querySelectorAll("time[datetime]").forEach((element) => formatTime(element, element.dateTime));
        formatDeadlineInputs(replacement);
        prepareSourceLinks(replacement);
        replacement.querySelectorAll(".coordinate-email-body").forEach((element) => messageBody(element, element.textContent));
        panelSignatures[key] = panelSignature(state.coordination, key);
      }
      updatePlanningRestrictions(latestState?.coordination || state.coordination);
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
      const home = safePath(root.dataset.homeUrl);
      if (response.status === 404 && selectedId && home) {
        // Another staff tab may have emptied trash while this case was selected.
        stopped = true;
        window.location.assign(home);
        return;
      }
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
    if (form) { form.dataset.dirty = "true"; form.dataset.editVersion = String(Number(form.dataset.editVersion || 0) + 1); }
    if (form?.matches(".coordinate-intake-form")) clearIntakeValidity(form);
    disableDirtyDraftActions(form);
  });
  root.addEventListener("change", (event) => {
    const form = event.target.closest(".coordinate-planning .coordinate-action-form");
    if (form) { form.dataset.dirty = "true"; form.dataset.editVersion = String(Number(form.dataset.editVersion || 0) + 1); }
    if (form?.matches(".coordinate-intake-form")) clearIntakeValidity(form);
    disableDirtyDraftActions(form);
  });
  root.addEventListener("reset", (event) => {
    if (!event.target.matches(".coordinate-action-form")) return;
    delete event.target.dataset.dirty;
    event.target.dataset.editVersion = String(Number(event.target.dataset.editVersion || 0) + 1);
    if (event.target.matches(".coordinate-intake-form")) clearIntakeValidity(event.target);
    setTimeout(() => { if (latestState) { updatePlanningRestrictions(latestState.coordination); refreshPanels(latestState); } }, 0);
  });
  root.addEventListener("click", async (event) => {
    const workspaceLink = event.target.closest("[data-open-panel]");
    if (workspaceLink) {
      const key = workspaceLink.dataset.openPanel;
      if (!Object.hasOwn(panelKeys, key) || caseDeleted) return;
      const panel = planning?.querySelector(`[data-panel='${key}']`);
      if (!panel) { notice("The case contents are updating. Try opening this section again in a moment."); return; }
      panel.open = true;
      const record = workspaceLink.dataset.openRecord && document.getElementById(workspaceLink.dataset.openRecord);
      const target = record && panel.contains(record) ? record : panel;
      if (target.tagName === "DETAILS") target.open = true;
      const summary = target.querySelector("summary");
      (summary || target).focus({ preventScroll: true });
      target.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    const source = event.target.closest("[data-source-link]");
    const reference = source?.getAttribute("href") || "";
    if (/^#coordinate-(?:message-\d+|document-[0-9a-f-]{36}|email-[0-9a-f-]{36}|mail-thread-[0-9a-f-]{36})$/i.test(reference)) {
      const target = document.getElementById(reference.slice(1));
      if (!target) {
        event.preventDefault();
        notice(planning?.querySelector("[data-panel='intake'] form[data-dirty='true']")
          ? "Finish or clear your document edits, then reopen this source."
          : "That source is not currently visible in this case.");
        return;
      }
      for (let details = target.closest("details"); details; details = details.parentElement?.closest("details")) {
        details.open = true;
      }
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
      return;
    }
    const suggestion = event.target.closest("[data-use-suggestion]");
    if (suggestion) { useSuggestion(suggestion); return; }
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

  function useSuggestion(button) {
    if (caseDeleted) return;
    if (actionInFlight) { notice("Wait for the current save to finish before adding a suggestion."); return; }
    const panel = planning?.querySelector("[data-panel='plan']");
    const form = panel?.querySelector("form");
    const data = button.closest(".coordinate-suggestion")?.querySelector("#coordinate-suggested-plan");
    if (!form || !data) { notice("The shipping plan is unavailable. Reload the case and try again.", true); return; }
    let suggestion;
    try { suggestion = JSON.parse(data.textContent); } catch (_) { return; }
    const notes = form.elements.notes;
    const deadline = form.elements.pickup_deadline;
    const suggestedNotes = typeof suggestion.notes === "string" ? suggestion.notes.trim() : "";
    const block = suggestedNotes ? `Suggested shipping plan — review before saving:\n${suggestedNotes}` : "";
    const current = notes.value;
    const addition = block && !current.includes(block) ? `${current ? "\n\n" : ""}${block}` : "";
    if (current.length + addition.length > (notes.maxLength > 0 ? notes.maxLength : 6000)) {
      notice("Your plan notes are too long to add the full suggestion. Keep the details you need and try again.", true);
      notes.focus();
      return;
    }
    const suggestedDeadline = newYorkDatetime(suggestion.pickup_deadline);
    const addDeadline = !deadline.value && suggestedDeadline;
    if (!addition && !addDeadline) {
      notice("The suggestion is already in your notes, or your plan already has a pickup deadline. Review the plan before saving.");
      panel.open = true;
      return;
    }
    if (addition) notes.value = current + addition;
    if (addDeadline) deadline.value = suggestedDeadline;
    form.dataset.dirty = "true";
    form.dataset.editVersion = String(Number(form.dataset.editVersion || 0) + 1);
    panel.open = true;
    (addition ? notes : deadline).focus();
    notice("Suggestion added to your unsaved plan. Review the details and select Save plan when ready.");
  }

  function clearIntakeValidity(form) {
    [form.elements.title, form.elements.pdf, form.elements.text].forEach((input) => input?.setCustomValidity(""));
  }

  function disableDirtyDraftActions(form) {
    if (!form?.matches(".coordinate-draft-edit")) return;
    form.closest(".coordinate-draft")?.querySelectorAll(".coordinate-draft-review button[type='submit'], .coordinate-draft-send button[type='submit']")
      .forEach((button) => { button.disabled = true; });
  }

  function validateEmailSend(form) {
    const card = form.closest(".coordinate-draft");
    const digest = form.elements.content_digest?.value;
    if (caseDeleted || !card || ["queued", "sending", "sent", "unknown"].includes(card.dataset.sendStatus)) {
      notice("This message cannot be sent from its current delivery state.", true); return false;
    }
    if (card.querySelector("form[data-dirty='true']")) {
      notice("Save and review the draft’s changes before sending.", true); return false;
    }
    if (uncertainEmailSends.has(card.dataset.draftId)) {
      notice("The previous send has not been confirmed. Check its delivery status before taking another email action.", true); return false;
    }
    if (!digest || digest !== form.dataset.reviewedDigest || !form.elements.request_id?.value) {
      notice("Review the current saved draft before sending.", true); return false;
    }
    const state = latestState?.coordination;
    if (state) {
      const draft = (state.drafts || []).find((item) => String(item.id) === card.dataset.draftId);
      if (!state.mail?.ready || !state.mail?.enabled || !draft?.can_send || draft.blocked || draft.editable === false
          || draft.status !== "reviewed" || draft.reviewed_digest !== digest || draft.current_digest !== digest) {
        notice("Email readiness or this draft’s review changed. Refresh the case and review its current state.", true); return false;
      }
    }
    return true;
  }

  function validateIntake(form) {
    clearIntakeValidity(form);
    const title = form.elements.title;
    const textInput = form.elements.text;
    const pdf = form.elements.pdf;
    const file = pdf.files?.[0];
    let invalid;
    let error;
    if (!title.value.trim() || title.value.length > 200) {
      invalid = title; error = "Add a document title of up to 200 characters.";
    } else if (Boolean(file) === Boolean(textInput.value.trim())) {
      invalid = textInput; error = "Choose one PDF or paste text for this document.";
    } else if (textInput.value.length > 24000) {
      invalid = textInput; error = "Keep pasted text to 24,000 characters or fewer.";
    } else if (file && (file.size > 5 * 1024 * 1024 || file.size === 0)) {
      invalid = pdf; error = "Choose a nonempty PDF no larger than 5 MiB.";
    } else if (file && file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) {
      invalid = pdf; error = "Choose a PDF file, or paste the relevant text.";
    }
    if (!error) return true;
    invalid.setCustomValidity(error);
    invalid.reportValidity();
    notice(error, true);
    return false;
  }

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form.matches(".coordinate-action-form")) return;
    event.preventDefault();
    if (actionInFlight) { notice("Please wait for the current change to finish."); return; }
    const intake = form.matches(".coordinate-intake-form");
    const emailSend = form.matches(".coordinate-draft-send");
    if (intake && !validateIntake(form)) return;
    if (emailSend && !validateEmailSend(form)) return;
    if (form.matches(".coordinate-draft-review") && form.closest(".coordinate-draft")?.querySelector("form[data-dirty='true']")) {
      notice("Save the draft’s changes before marking it reviewed.", true);
      return;
    }
    const path = safePath(form.getAttribute("action"));
    if (!path) { notice("This action is unavailable. Reload the page and try again.", true); return; }
    const button = event.submitter || form.querySelector("button[type='submit']");
    const label = button?.textContent || "";
    const payload = new FormData(form);
    const submittedVersion = form.dataset.editVersion || "0";
    const draftId = emailSend ? form.closest(".coordinate-draft").dataset.draftId : "";
    let sendOutcomeKnown = false;
    actionInFlight = true;
    mutationVersion += 1;
    if (button) { button.disabled = true; button.textContent = emailSend ? "Requesting send…" : "Saving…"; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), intake ? 60000 : 20000);
    try {
      const response = await fetch(path, {
        method: "POST", body: payload, credentials: "same-origin", redirect: "error",
        headers: { Accept: "application/json" }, signal: controller.signal,
      });
      const isJson = response.headers.get("content-type")?.includes("application/json");
      const result = isJson ? await response.json() : null;
      if (emailSend && response.status >= 400 && response.status < 500 && result?.error) sendOutcomeKnown = true;
      if (!response.ok) throw new Error(result?.error || "This change could not be saved. Reload and check your staff session.");
      if (!result?.selected_case) throw new Error("The server did not confirm the change. Reload to check before trying again.");
      if (emailSend) sendOutcomeKnown = true;
      const editedDuringSave = (form.dataset.editVersion || "0") !== submittedVersion;
      if (intake) {
        if (!editedDuringSave) form.reset();
        // Change the idempotency key only after the server confirms this upload.
        const token = result.coordination?.intake?.submission_token;
        if (typeof token === "string" && /^[0-9a-f-]{36}$/i.test(token)) {
          form.elements.client_message_id.value = token;
          form.elements.client_message_id.defaultValue = token;
        }
      }
      if (editedDuringSave) form.dataset.dirty = "true";
      else delete form.dataset.dirty;
      mutationVersion += 1;
      updateState(result);
      notice(emailSend ? "Send request recorded. Check the message’s delivery status below; do not create a duplicate."
        : intake ? "Document added. The coordinator will review it on the next worker check."
        : label.includes("Delete") ? "Message deleted. You can restore it in this conversation."
        : label.includes("Move to trash") ? "Case moved to trash. You can restore it at any time."
        : label.includes("Restore") ? "Restored."
        : label.includes("reviewed") || label.includes("review") ? "Review saved. No email was sent or payment authorized."
        : "Saved.");
    } catch (error) {
      if (emailSend && !sendOutcomeKnown) uncertainEmailSends.add(draftId);
      notice(emailSend && !sendOutcomeKnown
        ? "The send has not been confirmed. Do not resend or create a duplicate. Check the message’s delivery status; this control stays locked until its status is known."
        : intake && (error.name === "AbortError" || error instanceof TypeError)
        ? "The upload has not been confirmed. Your document is still selected; retrying will use the same submission to avoid duplicates."
        : error.name === "AbortError"
        ? "The server has not confirmed this change yet. Reload to check before trying again."
        : error instanceof TypeError ? "The connection was interrupted. Reload to check whether the change saved before trying again."
        : error.message || "Unable to save. Your edits are still here.", true);
    } finally {
      clearTimeout(timeout);
      actionInFlight = false;
      if (button?.isConnected) { button.disabled = emailSend && uncertainEmailSends.has(draftId); button.textContent = label; }
      if (latestState) updatePlanningRestrictions(latestState.coordination);
    }
  });
  // Retain the same idempotency token on retry. Native POST also works without JS.
  root.querySelectorAll(".coordinate-composer, .coordinate-new-form").forEach((form) => {
    const body = form.querySelector("textarea[name='body']");
    body.addEventListener("input", () => {
      body.setCustomValidity("");
      if (form.matches(".coordinate-composer")) {
        body.dataset.sendContextFrozen = body.value.trim() ? "true" : "false";
        if (!body.value.trim() && latestState) updateWorkspaceLinks(latestState.coordination);
      }
    });
    form.addEventListener("submit", (event) => {
      if (!body.value.trim()) {
        event.preventDefault();
        body.setCustomValidity("Write a message to continue.");
        body.reportValidity();
        return;
      }
      if (form.matches(".coordinate-composer")) prepareChatSendContext(form);
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
