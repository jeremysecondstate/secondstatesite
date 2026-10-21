// Run with Node. These regressions exercise the shipped Inventory browser script.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {};
    this.events = {}; this._text = ''; this.value = ''; this.hidden = false;
    this.scrollHeight = 0; this.scrollTop = 0; this.clientHeight = 0;
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(event, callback) { this.events[event] = callback; }
  querySelector(selector) { return descendants(this).find(child => selector === 'button[type=submit]' && child.tagName === 'button' && child.type === 'submit') || null; }
  closest(selector) { return selector === 'form[data-inventory-action]' && this.dataset.inventoryAction ? this : null; }
}
const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
const ids = ['inventory', 'inventory-form', 'inventory-notice', 'inventory-connection', 'inventory-cases', 'inventory-trash-count', 'inventory-empty-trash', 'inventory-trash-items', 'inventory-trash', 'inventory-last-check', 'inventory-conversation-title', 'inventory-case-actions', 'inventory-trashed-notice', 'inventory-title-field', 'inventory-body-label', 'inventory-messages', 'inventory-removed-messages', 'inventory-removed-count', 'inventory-removed-list'];
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
const root = elements.inventory;
root.dataset = { caseId: 'a', stateUrl: '/inventory/state/', homeUrl: '/inventory/', createUrl: '/inventory/cases/' };
const form = elements['inventory-form'];
form.elements = Object.fromEntries(['csrfmiddlewaretoken', 'client_message_id', 'body', 'title'].map(name => [name, new Element('input')]));
form.elements.csrfmiddlewaretoken.value = 'csrf-token';
const send = new Element('button'); send.type = 'submit'; form.append(send);
let fetchImpl = () => { throw new Error('Unexpected fetch'); };
const context = vm.createContext({
  document: { hidden: false, getElementById: id => elements[id], createElement: tag => new Element(tag), createTextNode: text => { const n = new Element('text'); n.textContent = text; return n; } },
  URL, Date, Map, FormData: class { constructor(value) { this.form = value; } },
  location: { origin: 'https://secondstate.example', hash: '' },
  history: { replaceState() {} }, window: { addEventListener() {} }, setInterval() {},
  fetch: (...args) => fetchImpl(...args),
});
let source = fs.readFileSync(path.join(__dirname, 'static/secondstateapp/inventory.js'), 'utf8');
source = source.replace('  poll(); setInterval(poll, 10000);', '  globalThis.testHooks = { render, poll };');
vm.runInContext(source, context);
const hooks = context.testHooks;
const caseA = { id: 'a', title: 'First request', url: '/inventory/a/', delete_url: '/inventory/a/trash/', restore_url: '/inventory/a/restore/', status: 'queued', deleted_at: null };
const caseB = { ...caseA, id: 'b', title: 'Second request', url: '/inventory/b/', delete_url: '/inventory/b/trash/', restore_url: '/inventory/b/restore/' };
const message = { id: 1, author: 'Staff', role: 'staff', body: 'Keep <script> as text.', status: 'queued', result: {}, deleted_at: null, delete_url: '/inventory/a/messages/1/trash/', restore_url: '/inventory/a/messages/1/restore/' };
const state = (overrides = {}) => ({ cases: [caseA, caseB], trash_cases: [], trash_messages: [], trash_count: 0, selected_case: caseA, messages: [message], worker: {}, message_token: 'next-token', ...overrides });
const response = value => ({ ok: true, status: 200, redirected: false, headers: { get: () => 'application/json' }, json: async () => value });

async function main() {
  hooks.render(state());
  assert.ok(elements['inventory-messages'].textContent.includes(message.body));
  assert.equal(descendants(elements['inventory-messages']).filter(child => child.tagName === 'script').length, 0);

  // Moving the last visible message clears its old content and exposes Restore.
  const removedMessage = { ...message, deleted_at: '2026-10-21T12:00:00Z' };
  hooks.render(state({ messages: [removedMessage], trash_messages: [{ ...removedMessage, case_url: caseA.url, case_title: caseA.title, case_id: caseA.id }], trash_count: 1 }));
  assert.ok(!elements['inventory-messages'].textContent.includes(message.body));
  assert.equal(elements['inventory-removed-messages'].hidden, false);
  assert.ok(elements['inventory-removed-list'].textContent.includes('Restore message'));
  hooks.render(state({ messages: [] }));
  assert.equal(elements['inventory-removed-messages'].hidden, true);
  assert.equal(elements['inventory-removed-list'].textContent, '');

  // Whole requests in Trash have no send, retry, or individual message mutations.
  const trashed = { ...caseA, deleted_at: '2026-10-21T12:00:00Z' };
  const trashedState = state({ cases: [caseB], trash_cases: [trashed], trash_count: 1, selected_case: trashed, messages: [{ ...message, retry_url: '/retry/' }] });
  hooks.render(trashedState);
  assert.equal(form.hidden, true);
  assert.equal(elements['inventory-trashed-notice'].hidden, false);
  assert.ok(elements['inventory-case-actions'].textContent.includes('Restore request'));
  assert.ok(!elements['inventory-messages'].textContent.includes('Move to Trash'));
  assert.ok(!elements['inventory-messages'].textContent.includes('Retry this request'));

  // A restore on another request never moves the current composer draft with it.
  hooks.render(state());
  form.elements.body.value = 'Draft for first request';
  hooks.render(state({ selected_case: caseB, messages: [] }));
  assert.equal(form.elements.body.value, '');
  form.elements.body.value = 'Draft for second request';
  hooks.render(state());
  assert.equal(form.elements.body.value, 'Draft for first request');
  assert.equal(form.action, '/inventory/a/messages/');

  // A slow poll that started before Trash cannot undo the subsequent response.
  let resolveOldPoll;
  fetchImpl = () => new Promise(resolve => { resolveOldPoll = resolve; });
  const oldPoll = hooks.poll();
  const trashForm = descendants(elements['inventory-case-actions']).find(child => child.tagName === 'form');
  fetchImpl = async () => response(trashedState);
  await root.events.submit({ target: trashForm, preventDefault() {} });
  assert.equal(form.hidden, true);
  resolveOldPoll(response(state()));
  await oldPoll;
  assert.equal(form.hidden, true);
  assert.equal(elements['inventory-trashed-notice'].hidden, false);

  // Emptying this request from another tab recovers from 404 without stale history.
  let calls = 0;
  fetchImpl = async () => ++calls === 1 ? { status: 404 } : response(state({ selected_case: null, messages: [] }));
  await hooks.poll();
  assert.equal(calls, 2);
  assert.equal(root.dataset.caseId, '');
  assert.equal(form.hidden, false);
  assert.equal(form.action, '/inventory/cases/');
  assert.equal(form.elements.body.value, '');
  assert.ok(!elements['inventory-messages'].textContent.includes(message.body));
  assert.ok(elements['inventory-notice'].textContent.includes('removed from Trash'));
  console.log('Inventory frontend regressions passed.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
