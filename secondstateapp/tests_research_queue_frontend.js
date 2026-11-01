// Run with node --test. Queue selection requests use fixtures, never a real queue.
const assert = require("node:assert/strict");
const {test} = require("node:test");
const {createSelection, initQueuePage} = require("./static/secondstateapp/research_queue.js");

class Element {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
    this.value = "";
    this.classes = new Set();
    this.classList = {toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name)};
  }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  async dispatch(name, detail = {}) { return this.listeners[name]?.({target: this, ...detail}); }
  focus() { this.focused = true; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
const document = () => {
  const count = new Element("span");
  const secondCount = new Element("span");
  return {
    count, secondCount,
    createElement: tag => new Element(tag),
    querySelectorAll: selector => selector === "[data-research-queue-count]" ? [count, secondCount] : [],
  };
};
const selection = wrapper => ({checkbox: wrapper.children[0].children[0], status: wrapper.children[1]});
const lot = (id, overrides = {}) => ({
  id, title: "Sleeping Dancer", artist: "Henri Matisse",
  research_queue_selected: false, research_queue_update_url: `/calendar/research-queue/selection/${id}/`,
  email_tray_selected: true, artprice_url: "", ...overrides,
});

test("a lot without research links can save a selection independently of Email Tray", async () => {
  const doc = document();
  const item = lot(91001);
  const calls = [];
  const wrapper = createSelection(item, {document: doc, csrfToken: "test-token", fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({ok: true, selected: true, queue_count: 4})};
  }});
  const {checkbox, status} = selection(wrapper);
  assert.equal(calls.length, 0, "rendering does not begin research or fetch a queue");
  assert.equal(checkbox.disabled, undefined, "no Artprice or LiveArt link is required");
  assert.match(checkbox.attributes["aria-label"], /Add to research: Sleeping Dancer by Henri Matisse/);
  assert.equal(checkbox.attributes["aria-describedby"], status.id);
  checkbox.focus();
  checkbox.checked = true;
  await checkbox.dispatch("change");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, item.research_queue_update_url);
  assert.deepEqual(JSON.parse(calls[0].options.body), {selected: true});
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["X-CSRFToken"], "test-token");
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(item.research_queue_selected, true);
  assert.equal(item.email_tray_selected, true);
  assert.equal(checkbox.focused, true);
  assert.equal(checkbox.disabled, undefined, "saving never drops keyboard focus by disabling the input");
  assert.equal(doc.count.textContent, "4");
  assert.equal(doc.secondCount.textContent, "4");
  assert.match(status.textContent, /selection saved/);
});

test("all representations of one lot stay synchronized and duplicate in-flight changes are blocked", async () => {
  const doc = document();
  let finish;
  let requestCount = 0;
  const fetch = () => { requestCount += 1; return new Promise(resolve => { finish = resolve; }); };
  const item = lot(91002);
  const first = selection(createSelection(item, {document: doc, fetch}));
  const second = selection(createSelection(item, {document: doc, fetch}));
  first.checkbox.checked = true;
  const saved = first.checkbox.dispatch("change");
  assert.equal(second.checkbox.attributes["aria-disabled"], "true");
  second.checkbox.checked = true;
  await second.checkbox.dispatch("change");
  assert.equal(requestCount, 1);
  finish({ok: true, json: async () => ({ok: true, item: {selected: true}, queue_count: 1})});
  await saved;
  assert.equal(first.checkbox.checked, true);
  assert.equal(second.checkbox.checked, true);
  assert.equal(second.checkbox.attributes["aria-disabled"], "false");
  assert.equal(item.email_tray_selected, true);
});

test("quick selections of different lots retain click order and the final queue count", async () => {
  const doc = document();
  const requests = [];
  let finishFirst;
  const fetch = url => {
    requests.push(url);
    if (requests.length === 1) return new Promise(resolve => { finishFirst = resolve; });
    return Promise.resolve({ok: true, json: async () => ({ok: true, selected: true, queue_count: 2})});
  };
  const first = selection(createSelection(lot(91003), {document: doc, fetch}));
  const second = selection(createSelection(lot(91004), {document: doc, fetch}));
  first.checkbox.checked = second.checkbox.checked = true;
  const firstSave = first.checkbox.dispatch("change");
  const secondSave = second.checkbox.dispatch("change");
  await Promise.resolve();
  assert.equal(requests.length, 1, "a slow first save cannot reverse the requested queue order");
  finishFirst({ok: true, json: async () => ({ok: true, selected: true, queue_count: 1})});
  await Promise.all([firstSave, secondSave]);
  assert.deepEqual(requests, ["/calendar/research-queue/selection/91003/", "/calendar/research-queue/selection/91004/"]);
  assert.equal(doc.count.textContent, "2");
  assert.equal(first.checkbox.checked, true);
  assert.equal(second.checkbox.checked, true);
});

test("server and network failures preserve the saved selection, focus, count and visible error", async () => {
  for (const [offset, request] of [
    [1, async () => ({ok: false, json: async () => ({ok: false, error: "Sign in again to save your queue."})})],
    [2, async () => { throw new Error("Network unavailable"); }],
    [3, async () => ({ok: true, json: async () => ({ok: true, queue_count: 0})})],
    [4, async () => ({ok: false, json: async () => { throw new Error("HTML login page"); }})],
  ]) {
    const doc = document();
    doc.count.textContent = "7";
    const item = lot(91010 + offset, {research_queue_selected: true});
    const wrapper = createSelection(item, {document: doc, fetch: request});
    const {checkbox, status} = selection(wrapper);
    checkbox.checked = false;
    checkbox.focus();
    await checkbox.dispatch("change");
    assert.equal(checkbox.checked, true);
    assert.equal(item.research_queue_selected, true);
    assert.equal(item.email_tray_selected, true);
    assert.equal(checkbox.focused, true);
    assert.equal(wrapper.attributes["aria-busy"], "false");
    assert.equal(status.classes.has("is-error"), true);
    assert.notEqual(status.textContent, "");
    assert.equal(doc.count.textContent, "7");
  }
});

test("removing from research keeps Email Tray selected and uses the server's authoritative count", async () => {
  const doc = document();
  const item = lot(91020, {research_queue_selected: true});
  const {checkbox, status} = selection(createSelection(item, {document: doc, fetch: async () => ({
    ok: true, json: async () => ({ok: true, selected: false, selected_count: 0}),
  })}));
  checkbox.checked = false;
  await checkbox.dispatch("change");
  assert.equal(item.research_queue_selected, false);
  assert.equal(item.email_tray_selected, true);
  assert.equal(doc.count.textContent, "0");
  assert.match(status.textContent, /Removed/);
});

function queuePage(saved, options = {}) {
  const page = new Element();
  const form = new Element("form");
  const button = Object.assign(new Element("button"), {id: "queue-save-note-1", disabled: options.disabled});
  const heading = Object.assign(new Element("h3"), {id: "queue-item-1"});
  const title = Object.assign(new Element("h1"), {id: "research-queue-title"});
  const note = Object.assign(new Element("textarea"), {id: "queue-note-1", value: options.value || "Server note"});
  const hint = new Element("p");
  const error = options.error ? new Element("p") : null;
  form.dataset.queueItemForm = heading.id;
  form.querySelector = selector => selector.startsWith("button") ? button : selector.startsWith("textarea") ? note : null;
  page.querySelectorAll = selector => selector.startsWith("form") ? [form] : [];
  page.querySelector = () => error;
  const nodes = {[button.id]: button, [heading.id]: heading, [title.id]: title, [note.id]: note, [`${note.id}-status`]: hint};
  const doc = {querySelector: () => page, getElementById: id => nodes[id]};
  const values = new Map(saved ? [["secondstate.liveartQueue.returnFocus", JSON.stringify(saved)]] : []);
  const storage = {
    getItem: key => values.get(key), removeItem: key => values.delete(key), setItem: (key, value) => values.set(key, value),
  };
  initQueuePage(doc, storage);
  return {form, button, heading, title, note, hint, error, values};
}

test("normal queue form submissions remember focus and an unsaved note for a failed redirect", async () => {
  const page = queuePage(null);
  page.note.value = "Check dimensions";
  await page.form.dispatch("submit", {submitter: page.button});
  const saved = JSON.parse(page.values.get("secondstate.liveartQueue.returnFocus"));
  assert.equal(saved.note, "Check dimensions");
  assert.equal(saved.buttonId, page.button.id);
  const reloaded = queuePage(saved, {error: true});
  assert.equal(reloaded.note.value, "Check dimensions");
  assert.equal(reloaded.error.focused, true);
  assert.match(reloaded.hint.textContent, /unsaved note was restored/);
});

test("queue forms restore focus after success and use the item heading when a move reaches a boundary", () => {
  const saved = {buttonId: "queue-save-note-1", itemId: "queue-item-1", noteId: "queue-note-1", note: "Server note"};
  const success = queuePage(saved);
  assert.equal(success.button.focused, true);
  assert.equal(success.hint.textContent, undefined, "a saved note needs no unsaved warning");
  const boundary = queuePage(saved, {disabled: true});
  assert.equal(boundary.heading.focused, true);
});
