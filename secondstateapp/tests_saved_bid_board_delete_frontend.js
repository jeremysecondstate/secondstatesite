const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
const dataKey = name => name.replace(/^data-/, "").replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
class Element {
  constructor(tagName = "div") {
    Object.assign(this, {tagName, children: [], attributes: {}, dataset: {}, events: {}, className: "", value: "", disabled: false, hidden: false});
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: (...names) => {this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" ");},
      remove: (...names) => {this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(" ");},
      toggle: (name, enabled) => enabled ? this.classList.add(name) : this.classList.remove(name),
    };
  }
  set textContent(value) {this.text = String(value); this.children = [];}
  get textContent() {return (this.text || "") + this.children.map(node => node.textContent).join(" ");}
  get childElementCount() {return this.children.length;}
  get isConnected() {return this.tagName === "document" || Boolean(this.parentElement?.isConnected);}
  append(...nodes) {nodes.forEach(node => {node.parentElement = this; this.children.push(node);});}
  appendChild(node) {this.append(node); return node;}
  prepend(...nodes) {nodes.forEach(node => {node.parentElement = this;}); this.children.unshift(...nodes);}
  replaceChildren(...nodes) {this.children.forEach(node => {node.parentElement = null;}); this.children = []; this.text = ""; this.append(...nodes);}
  remove() {if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); this.parentElement = null;}
  setAttribute(name, value) {this.attributes[name] = String(value);}
  removeAttribute(name) {delete this.attributes[name];}
  addEventListener(name, handler) {(this.events[name] ||= []).push(handler);}
  async dispatch(name, event = {}) {for (const handler of this.events[name] || []) await handler({target: this, ...event});}
  querySelectorAll(selector) {
    return descendants(this).filter(node => selector.startsWith(".") ? node.classList.contains(selector.slice(1))
      : selector.startsWith("[data-") ? dataKey(selector.slice(1, -1)) in node.dataset : node.tagName === selector);
  }
  querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
  closest() {return null;}
  checkValidity() {return true;}
  showModal() {this.open = true;}
  close() {this.open = false; for (const handler of this.events.close || []) handler();}
  focus() {this.focused = true;}
}
const ok = payload => ({ok: true, json: async () => payload});
const deleted = () => ok({ok: true, saved_board: null});
const deferred = () => {let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;}); return {promise, resolve, reject};};
const summary = {qualifying_bid: "1450.00", qualifies: true, include_in_email: false};
const makeLot = (id = 41) => ({id, title: `Print ${id}`, saved_bid_board: {...summary}, bid_board_url: `/calendar/lots/${id}/bid-board/`, saved_bid_board_url: `/calendar/lots/${id}/bid-board/saved/`, bid_board_email_url: `/calendar/lots/${id}/bid-board/email/`});
const analysis = {assumptions: {starting_hammer: "100.00", increment_mode: "fixed", resale_overrides: {}}, cases: [], rows: []};

function environment(fetcher = async () => deleted()) {
  const document = new Element("document");
  document.body = new Element("body"); document.append(document.body); document.activeElement = document.body;
  document.createElement = tag => new Element(tag);
  document.getElementById = id => descendants(document).find(node => node.id === id) || null;
  const requests = [], events = [], listeners = new Map();
  const window = {
    location: {href: "https://example.test/calendar/?day=2026-11-04"},
    history: {replaceState(state, title, url) {window.location.href = String(url);}},
    addEventListener(name, handler) {const list = listeners.get(name) || []; list.push(handler); listeners.set(name, list);},
    dispatchEvent(event) {events.push(event); for (const handler of listeners.get(event.type) || []) handler(event);},
  };
  const storage = new Map();
  const context = vm.createContext({document, window, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    CustomEvent: class {constructor(type, options) {this.type = type; Object.assign(this, options);}},
    fetch: async (url, options) => {requests.push({url, options}); return fetcher(url, options);},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "static/secondstateapp/saved_bid_board.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "static/secondstateapp/archive_bid_board.js"), "utf8"), context);
  const mount = lot => {
    const root = new Element(); document.body.append(root);
    context.window.SavedBidBoard.mountSummary(root, {lot, csrfToken: "csrf-token"});
    return {root, remove: root.querySelector(".sb-delete-button"), email: root.querySelector("input"), status: root.querySelector(".sb-catalog-status")};
  };
  const publish = (lotId, savedBoard) => window.dispatchEvent({type: "archive-bid-board-saved", detail: {lotId, savedBoard}});
  const mountEditor = async (lot, options = {}) => {
    const root = new Element(); document.body.append(root);
    const view = window.ArchiveBidBoard.mount(root, {lot, csrfToken: "csrf-token", getEvidence: async () => ({selected_ids: []}), ...options});
    await view.refresh();
    return {root, view, save: root.querySelectorAll("button").find(node => node.textContent === "Save Bid Board"), status: root.querySelector(".ab-status")};
  };
  return {context, document, window, requests, events, mount, mountEditor, publish};
}

test("delete uses the retained board owner and updates every summary without affecting another board", async () => {
  const p = environment(), owner = makeLot(4375), canonical = makeLot(7040);
  const first = p.mount(owner), second = p.mount({...owner}), other = p.mount(canonical);
  assert.equal(first.remove.textContent, "Delete Bid Board");
  assert.equal(first.remove.attributes["aria-label"], "Delete Bid Board for Print 4375");
  await first.remove.dispatch("click");
  assert.equal(p.requests.length, 1);
  assert.equal(p.requests[0].url, owner.saved_bid_board_url);
  assert.equal(p.requests[0].options.method, "DELETE");
  assert.equal(p.requests[0].options.credentials, "same-origin");
  assert.equal(p.requests[0].options.headers["X-CSRFToken"], "csrf-token");
  assert.equal(owner.saved_bid_board, null);
  assert.equal(first.root.hidden, true); assert.equal(second.root.hidden, true);
  assert.equal(other.root.hidden, false); assert.deepEqual(canonical.saved_bid_board, summary);
  assert.equal(p.events.length, 1); assert.equal(p.events[0].detail.lotId, 4375); assert.equal(p.events[0].detail.savedBoard, null);
});

test("pending deletion disables duplicate controls and rejects a second request", async () => {
  const request = deferred(), p = environment(() => request.promise), lot = makeLot();
  const a = p.mount(lot), b = p.mount({...lot});
  const action = a.remove.dispatch("click");
  assert.equal(a.remove.disabled, true); assert.equal(b.remove.disabled, true);
  assert.equal(a.email.disabled, true); assert.equal(b.email.disabled, true);
  assert.equal(a.remove.textContent, "Deleting…");
  const later = p.mount({...lot}); assert.equal(later.remove.disabled, true); assert.equal(later.email.disabled, true);
  await b.remove.dispatch("click"); await a.email.dispatch("change");
  assert.equal(p.requests.length, 1);
  request.resolve(deleted()); await action;
  assert.equal(later.root.hidden, true); assert.equal(p.events.length, 1);
});

test("delete failure retains the board, displays the server error and permits an explicit retry", async () => {
  let attempt = 0;
  const p = environment(async () => ++attempt === 1 ? {ok: false, json: async () => ({ok: false, error: "An email is currently sending. Please try again after it finishes."})} : deleted());
  const lot = makeLot(), view = p.mount(lot);
  await view.remove.dispatch("click");
  assert.deepEqual(lot.saved_bid_board, summary); assert.equal(view.root.hidden, false);
  assert.match(view.status.textContent, /email is currently sending/); assert.equal(view.status.classList.contains("is-error"), true);
  assert.equal(view.remove.disabled, false); assert.equal(view.email.disabled, false);
  assert.equal(p.events.length, 0); assert.equal(p.requests.length, 1);
  await view.remove.dispatch("click");
  assert.equal(p.requests.length, 2); assert.equal(view.root.hidden, true); assert.equal(p.events.length, 1);
});

test("invalid success payload and network failure preserve the saved board", async () => {
  for (const fetcher of [async () => ok({ok: true}), async () => {throw new Error("Network unavailable");}]) {
    const p = environment(fetcher), lot = makeLot(), view = p.mount(lot);
    await view.remove.dispatch("click");
    assert.deepEqual(lot.saved_bid_board, summary); assert.equal(view.root.hidden, false);
    assert.equal(view.status.classList.contains("is-error"), true); assert.equal(view.remove.disabled, false);
    assert.equal(p.events.length, 0);
  }
});

test("email saving serializes before deletion and preserves the result until delete succeeds", async () => {
  const emailRequest = deferred();
  const p = environment((url, options) => options.method === "POST" ? emailRequest.promise : Promise.resolve(deleted()));
  const lot = makeLot(), view = p.mount(lot);
  view.email.checked = true;
  const action = view.email.dispatch("change");
  assert.equal(view.remove.disabled, true);
  await view.remove.dispatch("click"); assert.equal(p.requests.length, 1);
  emailRequest.resolve(ok({ok: true, saved_board: {...summary, include_in_email: true}})); await action;
  assert.equal(view.remove.disabled, false); assert.equal(lot.saved_bid_board.include_in_email, true);
  await view.remove.dispatch("click");
  assert.deepEqual(p.requests.map(x => x.options.method), ["POST", "DELETE"]);
  assert.equal(lot.saved_bid_board, null);
});

test("a late email response cannot resurrect a deleted or subsequently recreated board", async () => {
  for (const recreate of [false, true]) {
    const request = deferred(), p = environment(() => request.promise), lot = makeLot(), view = p.mount(lot);
    view.email.checked = true; const action = view.email.dispatch("change");
    p.publish(lot.id, null);
    const replacement = {...summary, qualifying_bid: "800.00"};
    if (recreate) p.publish(lot.id, replacement);
    request.resolve(ok({ok: true, saved_board: {...summary, include_in_email: true}})); await action;
    assert.deepEqual(lot.saved_bid_board, recreate ? replacement : null);
    assert.equal(p.events.length, recreate ? 2 : 1);
    assert.equal(view.root.hidden, !recreate);
  }
});

test("deleting a board closes its active viewer and clears its deep link", async () => {
  const p = environment(async (url, options) => options.method === "DELETE" ? deleted() : ok({ok: true, board: {summary, analysis: {}, assumptions: {}}}));
  const lot = makeLot(), view = p.mount(lot);
  await p.context.window.SavedBidBoard.open(lot, {csrfToken: "csrf-token"});
  const dialog = p.document.querySelector("dialog"); assert.equal(dialog.open, true);
  assert.match(p.window.location.href, /saved_bid_board=41/);
  await view.remove.dispatch("click");
  assert.equal(dialog.isConnected, false); assert.equal(p.document.querySelector("dialog"), null);
  assert.doesNotMatch(p.window.location.href, /saved_bid_board/);
});

test("deleted board does not return from an older in-flight viewer request", async () => {
  const request = deferred(), p = environment(() => request.promise), lot = makeLot(); p.mount(lot);
  const action = p.context.window.SavedBidBoard.open(lot, {csrfToken: "csrf-token"});
  p.publish(lot.id, null);
  request.resolve(ok({ok: true, board: {summary, analysis: {}, assumptions: {}}})); await action;
  assert.equal(p.document.querySelector("dialog"), null); assert.equal(lot.saved_bid_board, null);
  assert.equal(p.events.length, 1); assert.equal(p.requests.length, 1);
});

test("an empty summary cannot send a delete request", async () => {
  const p = environment(), view = p.mount({...makeLot(), saved_bid_board: null});
  assert.equal(view.root.hidden, true); await view.remove.dispatch("click");
  assert.equal(p.requests.length, 0);
});

test("delete preserves its keyboard focus origin through a disabled-button blur without stealing newer focus", async () => {
  for (const moveElsewhere of [false, true]) {
    const request = deferred(), p = environment(() => request.promise), view = p.mount(makeLot());
    p.document.activeElement = view.remove;
    const action = view.remove.dispatch("click");
    const elsewhere = new Element("button"); p.document.body.append(elsewhere);
    p.document.activeElement = moveElsewhere ? elsewhere : p.document.body;
    request.resolve(deleted()); await action;
    assert.equal(p.events[0].detail.focusOrigin, moveElsewhere ? undefined : view.remove);
  }
});

test("failed deletion returns keyboard focus to Delete unless the user moved elsewhere", async () => {
  for (const moveElsewhere of [false, true]) {
    const request = deferred(), p = environment(() => request.promise), view = p.mount(makeLot());
    p.document.activeElement = view.remove;
    const action = view.remove.dispatch("click");
    const elsewhere = new Element("button"); p.document.body.append(elsewhere);
    p.document.activeElement = moveElsewhere ? elsewhere : p.document.body;
    request.resolve({ok: false, json: async () => ({ok: false, error: "Please try again."})}); await action;
    assert.equal(Boolean(view.remove.focused), !moveElsewhere);
    assert.equal(view.remove.disabled, false); assert.equal(view.root.hidden, false);
  }
});

test("saving locks the owner before evidence loads and until its response, then deletion remains final", async () => {
  const evidence = deferred(), saving = deferred();
  let pauseEvidence = false;
  const p = environment((url, options) => options.method === "DELETE" ? Promise.resolve(deleted())
    : JSON.parse(options.body || "null")?.action === "save" ? saving.promise : Promise.resolve(ok({ok: true, analysis})));
  const lot = makeLot(), saved = p.mount(lot), other = p.mount(makeLot(42));
  const editor = await p.mountEditor(lot, {getEvidence: () => pauseEvidence ? evidence.promise : Promise.resolve({selected_ids: []})});
  const duplicate = await p.mountEditor({...lot});
  pauseEvidence = true;
  const before = p.requests.length, action = editor.save.dispatch("click");
  assert.equal(p.requests.length, before); // The owner is locked before awaiting evidence.
  assert.equal(saved.remove.disabled, true); assert.equal(saved.email.disabled, true);
  assert.equal(duplicate.save.disabled, true); assert.equal(other.remove.disabled, false);
  const later = p.mount({...lot}); assert.equal(later.remove.disabled, true);
  await saved.remove.dispatch("click"); await duplicate.save.dispatch("click"); await saved.email.dispatch("change");
  assert.equal(p.requests.length, before);
  evidence.resolve({selected_ids: []}); await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.requests.length, before + 1);
  assert.equal(JSON.parse(p.requests.at(-1).options.body).action, "save");
  await later.remove.dispatch("click"); assert.equal(p.requests.length, before + 1);
  const updated = {...summary, qualifying_bid: "900.00"};
  saving.resolve(ok({ok: true, saved_board: updated, analysis})); await action;
  assert.equal(saved.remove.disabled, false); assert.equal(duplicate.save.disabled, false);
  assert.deepEqual(lot.saved_bid_board, updated);
  await saved.remove.dispatch("click");
  assert.equal(lot.saved_bid_board, null); assert.equal(later.root.hidden, true);
  assert.deepEqual(p.events.map(event => event.detail.savedBoard), [updated, null]);
});

test("deletion blocks every Save handler, including an editor mounted while deletion is pending", async () => {
  const deleting = deferred();
  const p = environment((url, options) => options.method === "DELETE" ? deleting.promise
    : Promise.resolve(ok({ok: true, analysis, ...(JSON.parse(options.body || "null")?.action === "save" ? {saved_board: summary} : {})})));
  const lot = makeLot(), saved = p.mount(lot), editor = await p.mountEditor(lot);
  const action = saved.remove.dispatch("click");
  assert.equal(editor.save.disabled, true);
  const later = await p.mountEditor({...lot}); assert.equal(later.save.disabled, true);
  const before = p.requests.length;
  await editor.save.dispatch("click"); await later.save.dispatch("click");
  assert.equal(p.requests.length, before); assert.match(editor.status.textContent, /change is in progress/);
  deleting.resolve(deleted()); await action;
  assert.equal(editor.save.disabled, false); assert.equal(later.save.disabled, false);
  assert.equal(lot.saved_bid_board, null);
  await editor.save.dispatch("click"); // A later, explicit Save may intentionally recreate a board.
  assert.deepEqual(lot.saved_bid_board, summary);
  assert.deepEqual(p.events.map(event => event.detail.savedBoard), [null, summary]);
});

test("failed Save releases its owner lock after either evidence or network errors", async () => {
  for (const failEvidence of [false, true]) {
    let shouldFail = false;
    const p = environment(async (url, options) => {
      if (options.method === "DELETE") return deleted();
      if (JSON.parse(options.body || "null")?.action === "save") throw new Error("Save unavailable");
      return ok({ok: true, analysis});
    });
    const lot = makeLot(), saved = p.mount(lot);
    const editor = await p.mountEditor(lot, {getEvidence: async () => {
      if (failEvidence && shouldFail) throw new Error("Evidence unavailable");
      return {selected_ids: []};
    }});
    shouldFail = true; await editor.save.dispatch("click");
    assert.match(editor.status.textContent, /unavailable/);
    assert.equal(saved.remove.disabled, false); assert.equal(saved.email.disabled, false); assert.equal(editor.save.disabled, false);
    assert.deepEqual(lot.saved_bid_board, summary); assert.equal(p.events.length, 0);
    await saved.remove.dispatch("click"); assert.equal(lot.saved_bid_board, null);
  }
});

test("cached detached controls leave the busy state when Save or failed Delete finishes", async () => {
  const saving = deferred(), deleting = deferred();
  const p = environment((url, options) => options.method === "DELETE" ? deleting.promise
    : JSON.parse(options.body || "null")?.action === "save" ? saving.promise : Promise.resolve(ok({ok: true, analysis})));
  const lot = makeLot(), saved = p.mount(lot), editor = await p.mountEditor(lot);
  const action = editor.save.dispatch("click");
  editor.root.remove(); saved.root.remove();
  let rebuilt;
  p.window.addEventListener("archive-bid-board-saved", () => {
    rebuilt = p.mount({...lot}); rebuilt.root.remove();
    assert.equal(rebuilt.remove.disabled, true); assert.equal(rebuilt.email.disabled, true);
  });
  saving.resolve(ok({ok: true, analysis, saved_board: summary})); await action;
  assert.equal(editor.save.disabled, false); assert.equal(saved.remove.disabled, false); assert.equal(saved.email.disabled, false);
  assert.equal(rebuilt.remove.disabled, false); assert.equal(rebuilt.email.disabled, false);
  p.document.body.append(saved.root);
  const remove = saved.remove.dispatch("click"); saved.root.remove();
  assert.equal(editor.save.disabled, true); assert.equal(saved.remove.disabled, true);
  deleting.resolve({ok: false, json: async () => ({ok: false, error: "Try again"})}); await remove;
  assert.equal(editor.save.disabled, false); assert.equal(saved.remove.disabled, false); assert.equal(saved.email.disabled, false);
  assert.equal(rebuilt.remove.disabled, false); assert.equal(rebuilt.email.disabled, false);
});

test("a failed email preference also rolls back a newly cached detached checkbox", async () => {
  const request = deferred(), p = environment(() => request.promise), lot = makeLot(), saved = p.mount(lot);
  saved.email.checked = true; const action = saved.email.dispatch("change");
  const cached = p.mount({...lot}); cached.root.remove();
  assert.equal(cached.email.checked, true); assert.equal(cached.email.disabled, true);
  request.resolve({ok: false, json: async () => ({ok: false, error: "Email preference unavailable"})}); await action;
  assert.equal(cached.email.checked, false); assert.equal(cached.email.disabled, false);
  assert.equal(saved.email.checked, false); assert.deepEqual(lot.saved_bid_board, summary);
});
