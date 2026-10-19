// Run with Node. Exercises the actual browser functions with a minimal DOM;
// no package installation, network, browser session, or app mutation is needed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tagName = "div", value = "") {
    this.tagName = tagName;
    this.children = [];
    this.value = value;
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this._text = "";
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  append(...children) {
    for (const child of children) this.children.push(...(child.tagName === "fragment" ? child.children : [child]));
  }
  replaceChildren(...children) { this._text = ""; this.children = []; this.append(...children); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  addEventListener() {}
  getAttribute(key) { return this.attributes[key] ?? null; }
  setAttribute(key, value) { this.attributes[key] = value; }
  hasAttribute(key) { return key in this.attributes; }
  setCustomValidity(value) { this.validationMessage = value; }
  reportValidity() { return !this.validationMessage; }
  focus() { this.focused = true; }
}

const root = new Element();
root.dataset = { caseId: "case-1", caseDeleted: "false" };
const listeners = {};
root.addEventListener = (name, callback) => { (listeners[name] ||= []).push(callback); };
const planning = new Element();
const notice = new Element();
const document = {
  getElementById(id) {
    return { coordinate: root, "coordinate-planning": planning, "coordinate-action-notice": notice }[id] || null;
  },
  createElement: (tag) => new Element(tag),
  createDocumentFragment: () => new Element("fragment"),
  createTextNode(value) { const element = new Element("text"); element.textContent = value; return element; },
  addEventListener() {},
};
const context = vm.createContext({
  document, window: { location: { origin: "https://secondstate.example" }, addEventListener() {} },
  URL, Intl, Date, AbortController, setTimeout() {}, clearTimeout() {},
});
let source = fs.readFileSync(path.join(__dirname, "static/secondstateapp/coordinate.js"), "utf8");
const finalPoll = source.lastIndexOf("  poll();");
assert.ok(finalPoll > 0);
source = source.slice(0, finalPoll) + `
  globalThis.testHooks = { messageBody, httpLink, newYorkDatetime, useSuggestion,
    validateIntake, panelSignature, setActionInFlight(value) { actionInFlight = value; } };
` + source.slice(finalPoll + "  poll();".length);
vm.runInContext(source, context);
const hooks = context.testHooks;

function render(value) { const element = new Element(); hooks.messageBody(element, value); return element; }
let rendered = render("See [Lot 17](https://example.test/a_(b)) and https://example.test/next.");
assert.equal(rendered.textContent, "See Lot 17 and https://example.test/next.");
let links = rendered.children.filter((item) => item.tagName === "a");
assert.equal(links.length, 2);
assert.equal(links[0].href, "https://example.test/a_(b)");
assert.equal(links[0].textContent, "Lot 17");
assert.equal(links[1].href, "https://example.test/next");
assert.equal(links[0].rel, "noopener noreferrer");
assert.equal(links[0].target, "_blank");
rendered = render('<img src=x onerror=alert(1)> [bad](javascript:alert(1)) [safe <b>label</b>](https://example.test)');
assert.equal(rendered.children.filter((item) => item.tagName === "a").length, 1);
assert.ok(rendered.textContent.includes("<img src=x onerror=alert(1)>"));
assert.ok(rendered.textContent.includes("[bad](javascript:alert(1))"));
assert.ok(!rendered.children.some((item) => ["img", "b", "script"].includes(item.tagName)));
rendered = render("[https://example.test/lot], (https://example.test/another).");
links = rendered.children.filter((item) => item.tagName === "a");
assert.equal(links[0].href, "https://example.test/lot");
assert.equal(links[1].href, "https://example.test/another");
for (const value of ["javascript:alert(1)", "data:text/html,x", "https://user:secret@example.test", "https://example.test\\@evil.test", "https://example.test/\npath"]) {
  assert.equal(hooks.httpLink(value), null);
}
assert.equal(hooks.newYorkDatetime("next Friday"), "");
assert.equal(hooks.newYorkDatetime("2026-10-30T16:00"), "");
assert.equal(hooks.newYorkDatetime("2026-10-30T20:00:00Z"), "2026-10-30T16:00");

function suggestionFixture(notes = "Staff confirmed: keep the mat.", deadline = "") {
  const form = new Element("form");
  form.elements = {
    notes: new Element("textarea", notes), pickup_deadline: new Element("input", deadline),
    destination: new Element("select", "duarte"), handling: new Element("input", "Keep mat and hinges."),
  };
  form.elements.notes.maxLength = 6000;
  form.dataset.dirty = "true";
  const panel = new Element("details");
  panel.querySelector = () => form;
  planning.querySelector = () => panel;
  const data = new Element("script");
  data.textContent = JSON.stringify({ notes: "Request a packing quote.", pickup_deadline: "2026-10-30T20:00:00Z" });
  const button = { closest: () => ({ querySelector: () => data }) };
  return { form, panel, button };
}
let fixture = suggestionFixture();
hooks.useSuggestion(fixture.button);
assert.equal(fixture.form.elements.notes.value, "Staff confirmed: keep the mat.\n\nSuggested shipping plan — review before saving:\nRequest a packing quote.");
assert.equal(fixture.form.elements.pickup_deadline.value, "2026-10-30T16:00");
assert.equal(fixture.form.elements.destination.value, "duarte");
assert.equal(fixture.form.elements.handling.value, "Keep mat and hinges.");
assert.equal(fixture.form.dataset.dirty, "true");
assert.equal(fixture.panel.open, true);
hooks.useSuggestion(fixture.button);
assert.equal((fixture.form.elements.notes.value.match(/Request a packing quote/g) || []).length, 1);
fixture = suggestionFixture("Staff note", "2026-10-29T12:00");
hooks.useSuggestion(fixture.button);
assert.equal(fixture.form.elements.pickup_deadline.value, "2026-10-29T12:00");
fixture = suggestionFixture("x".repeat(5990));
hooks.useSuggestion(fixture.button);
assert.equal(fixture.form.elements.notes.value, "x".repeat(5990));
assert.equal(fixture.form.elements.pickup_deadline.value, "");
fixture = suggestionFixture();
hooks.setActionInFlight(true);
hooks.useSuggestion(fixture.button);
assert.equal(fixture.form.elements.notes.value, "Staff confirmed: keep the mat.");
hooks.setActionInFlight(false);

function intakeFixture(text = "Pickup instructions", file = null) {
  const form = { elements: { title: new Element("input", "Auction email"), text: new Element("textarea", text), pdf: new Element("input") } };
  form.elements.pdf.files = file ? [file] : [];
  return form;
}
assert.equal(hooks.validateIntake(intakeFixture()), true);
assert.equal(hooks.validateIntake(intakeFixture("", { name: "invoice.pdf", type: "application/pdf", size: 5242880 })), true);
assert.equal(hooks.validateIntake(intakeFixture("", { name: "invoice.pdf", type: "application/pdf", size: 5242881 })), false);
assert.equal(hooks.validateIntake(intakeFixture("text", { name: "invoice.pdf", type: "application/pdf", size: 10 })), false);
assert.equal(hooks.validateIntake(intakeFixture("")), false);
assert.equal(hooks.validateIntake(intakeFixture("x".repeat(24001))), false);
assert.equal(hooks.validateIntake(intakeFixture("", { name: "invoice.exe", type: "application/octet-stream", size: 100 })), false);
assert.equal(hooks.panelSignature({ intake: { documents: [], submission_token: "old" } }, "intake"),
  hooks.panelSignature({ intake: { documents: [], submission_token: "new" } }, "intake"));
assert.notEqual(hooks.panelSignature({ brief: { summary: "old" } }, "briefing"),
  hooks.panelSignature({ brief: { summary: "new" } }, "briefing"));

async function testSubmission() {
  const form = intakeFixture("Invoice details");
  form.elements.client_message_id = new Element("input", "11111111-1111-4111-8111-111111111111");
  form.elements.client_message_id.defaultValue = form.elements.client_message_id.value;
  form.dataset = { dirty: "true", editVersion: "1" };
  form.matches = (selector) => [".coordinate-action-form", ".coordinate-intake-form"].includes(selector);
  form.getAttribute = () => "/coordinate/case-1/intake/";
  form.reset = () => {
    form.elements.title.value = "";
    form.elements.text.value = "";
    form.elements.pdf.files = [];
    listeners.reset[0]({ target: form });
  };
  const button = new Element("button");
  button.textContent = "Add to case";
  button.isConnected = true;
  form.querySelector = () => button;
  const event = { target: form, submitter: button, preventDefault() {} };
  const requests = [];
  context.FormData = class {
    constructor(input) { this.token = input.elements.client_message_id.value; this.text = input.elements.text.value; }
  };
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: false, headers: { get: () => "application/json" }, json: async () => ({ error: "Please retry." }) };
  };
  await listeners.submit[0](event);
  assert.equal(form.elements.text.value, "Invoice details");
  assert.equal(form.elements.client_message_id.value, "11111111-1111-4111-8111-111111111111");
  assert.equal(form.dataset.dirty, "true");
  assert.ok(requests[0].options.body instanceof context.FormData);
  assert.equal(requests[0].options.headers["Content-Type"], undefined);
  const nextToken = "22222222-2222-4222-8222-222222222222";
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, headers: { get: () => "application/json" }, json: async () => ({
      selected_case: { id: "case-1", status: "waiting", deleted: false },
      coordination: { intake: { submission_token: nextToken }, quotes: [], drafts: [] },
    }) };
  };
  await listeners.submit[0](event);
  assert.equal(requests[1].options.body.token, requests[0].options.body.token);
  assert.equal(form.elements.text.value, "");
  assert.equal(form.elements.client_message_id.value, nextToken);
  assert.equal(form.elements.client_message_id.defaultValue, nextToken);
  assert.equal(form.dataset.dirty, undefined);
}

testSubmission().then(() => console.log("Coordinate frontend checks passed.")).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
