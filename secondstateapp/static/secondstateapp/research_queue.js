/* Save queue selections only. LiveArt research runs are started by the worker. */
(function (root) {
  "use strict";
  let sequence = 0;
  let requestTail = Promise.resolve();
  const pending = new Set();
  const controls = new Map();
  const focusStorageKey = "secondstate.liveartQueue.returnFocus";

  const updateCount = (document, count) => {
    if (!Number.isInteger(count) || count < 0) return;
    document.querySelectorAll("[data-research-queue-count]").forEach((node) => {
      node.textContent = String(count);
    });
  };

  const synchronize = (key, selected, busy, message, error) => {
    (controls.get(key) || []).forEach((reference) => {
      const control = reference.deref();
      if (!control) { controls.get(key).delete(reference); return; }
      // Cached Archive cards can be detached and later restored, so keep their state too.
      control.lot.research_queue_selected = selected;
      control.checkbox.checked = selected;
      control.checkbox.setAttribute("aria-disabled", String(busy));
      control.wrapper.setAttribute("aria-busy", String(busy));
      control.status.textContent = message;
      control.status.classList.toggle("is-error", Boolean(error));
    });
  };

  const createSelection = (lot, options = {}) => {
    const document = options.document || root.document;
    const request = options.fetch || root.fetch.bind(root);
    const key = String(lot.id);
    const wrapper = document.createElement("div");
    wrapper.className = "research-queue-selection";
    wrapper.dataset.researchQueueLotId = key;
    const label = document.createElement("label");
    label.className = "research-queue-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(lot.research_queue_selected);
    checkbox.setAttribute("aria-label", `Add to research: ${lot.title || "Untitled lot"}${lot.artist ? ` by ${lot.artist}` : ""}`);
    const text = document.createElement("span");
    text.textContent = "Add to research";
    label.append(checkbox, text);
    const status = document.createElement("p");
    status.className = "research-queue-selection-status";
    status.id = `research-queue-selection-${++sequence}`;
    status.setAttribute("role", "status");
    checkbox.setAttribute("aria-describedby", status.id);
    status.textContent = checkbox.checked ? "In LiveArt Queue" : "";
    if (!lot.research_queue_update_url) {
      checkbox.disabled = true;
      status.textContent = "Queue selection is unavailable. Reload the Calendar to try again.";
    }
    wrapper.append(label, status);
    const control = {lot, wrapper, checkbox, status};
    // A rerendered gallery must not retain every old card and its event handlers.
    wrapper.researchQueueControl = control;
    if (!controls.has(key)) controls.set(key, new Set());
    controls.get(key).add(new WeakRef(control));
    if (pending.has(key)) synchronize(key, Boolean(lot.research_queue_selected), true, "Saving selection…", false);

    checkbox.addEventListener("change", async () => {
      const previous = Boolean(lot.research_queue_selected);
      if (pending.has(key)) {
        checkbox.checked = previous;
        return;
      }
      const selected = checkbox.checked;
      pending.add(key);
      // aria-disabled blocks duplicate changes without moving keyboard focus.
      synchronize(key, previous, true, "Saving selection…", false);
      try {
        // Preserve click order and prevent an older count response overwriting a newer one.
        const result = requestTail.then(async () => {
          const response = await request(lot.research_queue_update_url, {
            method: "POST",
            credentials: "same-origin",
            headers: {"Content-Type": "application/json", "X-CSRFToken": options.csrfToken || ""},
            body: JSON.stringify({selected}),
          });
          let payload;
          try { payload = await response.json(); } catch (_) { throw new Error("The queue could not be updated. Reload the page and try again."); }
          if (!response.ok || !payload.ok) throw new Error(payload.error || "The queue could not be updated. Please try again.");
          const saved = typeof payload.selected === "boolean" ? payload.selected : payload.item?.selected;
          if (typeof saved !== "boolean") throw new Error("The queue response was incomplete. Reload the page to check your selection.");
          synchronize(key, saved, false, saved ? "In LiveArt Queue · selection saved" : "Removed from LiveArt Queue", false);
          updateCount(document, payload.queue_count ?? payload.selected_count);
        });
        requestTail = result.catch(() => {});
        await result;
      } catch (error) {
        synchronize(key, previous, false, error instanceof Error ? error.message : "The queue could not be updated. Please try again.", true);
      } finally {
        pending.delete(key);
      }
    });
    return wrapper;
  };

  const initQueuePage = (document = root.document, storage) => {
    const page = document.querySelector("[data-research-queue-page]");
    if (!page) return;
    // Regular CSRF-protected forms remain usable when JavaScript or storage is unavailable.
    let saved;
    try {
      storage = storage || root.sessionStorage;
      saved = JSON.parse(storage.getItem(focusStorageKey) || "null");
      storage.removeItem(focusStorageKey);
    } catch (_) { /* Session storage is optional. */ }
    if (saved) {
      const note = saved.noteId ? document.getElementById(saved.noteId) : null;
      if (note && typeof saved.note === "string" && note.value !== saved.note) {
        note.value = saved.note;
        const hint = document.getElementById(`${saved.noteId}-status`);
        if (hint) hint.textContent = "Your unsaved note was restored. Choose Save note to try again.";
      }
      const error = page.querySelector(".calendar-alert.is-error");
      const button = saved.buttonId ? document.getElementById(saved.buttonId) : null;
      const focus = error || (button && !button.disabled ? button : null) || document.getElementById(saved.itemId) || document.getElementById("research-queue-title");
      const disclosure = focus?.closest?.("details");
      if (disclosure) disclosure.open = true;
      focus?.focus();
    }
    page.querySelectorAll("form[data-queue-item-form]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const button = event.submitter || form.querySelector("button[type=submit]");
        const note = form.querySelector("textarea[name=note]");
        try {
          storage.setItem(focusStorageKey, JSON.stringify({
            buttonId: button?.id, itemId: form.dataset.queueItemForm,
            noteId: note?.id, note: note?.value,
          }));
        } catch (_) { /* The server form still saves normally. */ }
      });
    });
    page.querySelectorAll("[data-queue-image]").forEach((image) => {
      const unavailable = image.parentElement.querySelector("[data-queue-image-fallback]");
      const showFallback = () => { image.hidden = true; if (unavailable) unavailable.hidden = false; };
      image.addEventListener("error", showFallback);
      if (image.complete && image.naturalWidth === 0) showFallback();
    });
  };

  const api = {createSelection, updateCount, initQueuePage};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ResearchQueue = api;
})(typeof window !== "undefined" ? window : globalThis);
