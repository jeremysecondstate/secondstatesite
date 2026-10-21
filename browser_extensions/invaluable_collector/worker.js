"use strict";
importScripts("core-prelude.js", "snapshot-core.js", "state.js");
const rules = globalThis.SecondStateCollector;
const STORAGE_KEY = "secondstateCollectorRun";
const ALARM = "secondstate-collector-page-timeout";
const TIMEOUT_MS = 90000;
let serial = Promise.resolve();
function enqueue(operation) {
  const result = serial.then(operation);
  serial = result.catch(() => {});
  return result;
}
async function load() {
  const stored = (await chrome.storage.local.get(STORAGE_KEY))[STORAGE_KEY];
  if (!stored) return null;
  if (stored.version !== 1 || !Array.isArray(stored.watches) || !Array.isArray(stored.snapshots)
      || !Array.isArray(stored.progress) || stored.progress.length !== stored.watches.length) {
    throw new Error("Saved run format is unsupported. Export or reset this local run.");
  }
  return stored;
}
async function save(state) {
  if (rules.byteSize(state) > rules.MAX_BYTES) throw new Error("Capture storage limit reached. Export this run first.");
  await chrome.storage.local.set({ [STORAGE_KEY]: state });
}
function publicView(state) {
  if (!state) return { run: null };
  const { snapshots, target, ...view } = state;
  delete view.document_id;
  delete view.tab_id;
  return { run: { ...view, snapshot_count: snapshots.length,
    lot_count: snapshots.reduce((count, snapshot) => count + snapshot.results[0].hits.length, 0),
    bytes: rules.byteSize(state), current_page: target?.page ?? state.progress[state.current_index]?.next_page ?? null } };
}
async function pauseRun(state, note, status) {
  const next = rules.pause(state, note, status);
  await save(next);
  await chrome.alarms.clear(ALARM);
  return next;
}
async function navigate(state) {
  let next = rules.prepareTarget(state, crypto.randomUUID(), new Date().toISOString());
  if (next.status === "complete") { await save(next); await chrome.alarms.clear(ALARM); return next; }
  next.target.deadline_at = Date.now() + TIMEOUT_MS;
  next.target.previous_document_id = state.document_id || null;
  await save(next);
  await chrome.alarms.create(ALARM, { when: next.target.deadline_at });
  try {
    if (Number.isInteger(next.tab_id)) {
      // Updating a tab URL makes a normal top-level browser navigation.
      // The extension never requests a catalog endpoint itself.
      if (state.navigated_url === next.target.url) await chrome.tabs.reload(next.tab_id);
      else await chrome.tabs.update(next.tab_id, { url: next.target.url });
    } else {
      const tab = await chrome.tabs.create({ url: next.target.url, active: true });
      next.tab_id = tab.id;
    }
    next.navigated_url = next.target.url;
    await save(next);
    return next;
  } catch {
    // Do not create replacement tabs automatically after an owned tab closes.
    next.tab_id = null;
    return pauseRun(next, "The collector tab could not be opened or was closed. Resume to open one tab.");
  }
}
function trustedUI(sender) {
  return sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL("collector.html");
}
function sourceMessageAllowed(sender, message, state) {
  return sender.id === chrome.runtime.id && sender.frameId === 0 && sender.tab?.id === state?.tab_id
    && state.status === "running" && state.target
    && rules.sameSearch(sender.url, state.target.url) && rules.sameSearch(message.page_url, state.target.url);
}
async function handle(message, sender) {
  if (!message || typeof message !== "object") throw new Error("Invalid collector message.");
  let state = await load();
  if (["hello", "capture", "blocked"].includes(message.type)) {
    if (!sourceMessageAllowed(sender, message, state)) return { ok: false, ignored: true };
    if (!sender.documentId || sender.documentId === state.target.previous_document_id) return { ok: false, ignored: true };
    if (message.type === "hello") {
      if (state.target.document_id && state.target.document_id !== sender.documentId) return { ok: false, ignored: true };
      state.target.document_id = sender.documentId;
      state.document_id = sender.documentId;
      await save(state);
      return { ok: true, nonce: state.target.nonce };
    }
    if (message.nonce !== state.target.nonce || sender.documentId !== state.target.document_id) return { ok: false, ignored: true };
    if (message.type === "blocked") {
      state = await pauseRun(state, "Invaluable is showing an access or verification screen. Resolve it normally in your browser, then Resume.", "blocked");
      return { ok: true, ...publicView(state) };
    }
    try {
      state = rules.acceptCapture(state, message, sender.tab.id, new Date().toISOString());
      await save(state);
      await chrome.alarms.clear(ALARM);
      if (state.status === "running") state = await navigate(state);
      return { ok: true, ...publicView(state) };
    } catch (error) {
      state = await pauseRun(state, `Capture paused: ${error.message}`);
      return { ok: false, error: error.message, ...publicView(state) };
    }
  }
  if (!trustedUI(sender)) return { ok: false, error: "Open the collector to manage this run." };
  switch (message.type) {
    case "status": return { ok: true, ...publicView(state) };
    case "configure":
      if (state?.status === "running" || state?.snapshots.length) throw new Error("Export and reset the current run before replacing it.");
      state = rules.makeRun(message.urls, message.window, crypto.randomUUID(), new Date().toISOString());
      await save(state);
      return { ok: true, ...publicView(state) };
    case "start":
    case "resume":
      if (!state) throw new Error("Import artist bookmarks and set the date window first.");
      if (state.status === "running") return { ok: true, ...publicView(state) };
      if (state.status === "complete") throw new Error("This run is finished. Export it or reset for a new run.");
      state = await navigate(state);
      return { ok: true, ...publicView(state) };
    case "pause":
      if (!state) throw new Error("There is no active run.");
      state = await pauseRun(state, "Paused by user. Resume reloads the pending page; captured results are kept.");
      return { ok: true, ...publicView(state) };
    case "skip":
      if (!state) throw new Error("There is no active run.");
      state = rules.skip(state); await save(state); await chrome.alarms.clear(ALARM);
      return { ok: true, ...publicView(state) };
    case "export": return { ok: true, bundle: rules.exportBundle(state, new Date().toISOString()) };
    case "reset":
      if (state?.status === "running") throw new Error("Pause the run before resetting it.");
      await chrome.storage.local.remove(STORAGE_KEY); await chrome.alarms.clear(ALARM);
      return { ok: true, run: null };
    default: throw new Error("Unknown collector action.");
  }
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  enqueue(() => handle(message, sender)).then(sendResponse, (error) => sendResponse({ ok: false, error: error.message }));
  return true;
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== ALARM) return;
  enqueue(async () => {
    const state = await load();
    if (state?.status !== "running" || !state.target) return;
    if (Date.now() < state.target.deadline_at) {
      await chrome.alarms.create(ALARM, { when: state.target.deadline_at }); return;
    }
    await pauseRun(state, "No verified results arrived within 90 seconds. Check the collector tab, then Resume or Skip this artist.", "blocked");
  }).catch(() => {});
});
chrome.tabs.onRemoved.addListener((tabId) => {
  enqueue(async () => {
    const state = await load();
    if (state?.tab_id !== tabId) return;
    state.tab_id = null;
    if (state.status === "running") await pauseRun(state, "The collector tab was closed. Captures are saved. Resume to open one tab.");
    else await save(state);
  }).catch(() => {});
});
chrome.runtime.onStartup.addListener(() => {
  enqueue(async () => {
    const state = await load();
    if (state?.status === "running") await pauseRun(state, "Browser restarted. Captures are saved; Resume when ready.");
  }).catch(() => {});
});
