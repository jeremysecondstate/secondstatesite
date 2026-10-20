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
const replyDrafts = new Element("section");
function descendants(element) {
  return element.children.flatMap((child) => [child, ...descendants(child)]);
}
replyDrafts.querySelectorAll = () => descendants(replyDrafts).filter((element) => element.dataset.previewDraftId);
const document = {
  getElementById(id) {
    return { coordinate: root, "coordinate-planning": planning, "coordinate-action-notice": notice,
      "coordinate-reply-drafts": replyDrafts }[id] || null;
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
  globalThis.testHooks = { messageBody, conversationBody, preserveDetails, workspaceItems, renderDraftPreview, updateReplyDrafts,
    httpLink, newYorkDatetime, useSuggestion,
    validateIntake, validateEmailSend, panelSignature,
    setCaseDeleted(value) { caseDeleted = value; },
    setEmailUncertain(id, value) { value ? uncertainEmailSends.add(id) : uncertainEmailSends.delete(id); },
    setLatestState(value) { latestState = value; },
    setActionInFlight(value) { actionInFlight = value; } };
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

const longResponse = "Here is the first finding.\n\n" + "Full source-backed research <script>untrusted()</script>. ".repeat(30);
rendered = new Element();
hooks.conversationBody(rendered, longResponse, true);
assert.equal(rendered.children[0].textContent, "Here is the first finding.");
const disclosure = rendered.children[1];
assert.equal(disclosure.tagName, "details");
assert.ok(!disclosure.open, "Long historical assistant replies start compact.");
assert.equal(disclosure.children[0].textContent, "Read full Coordinator response");
assert.equal(disclosure.children[1].textContent, longResponse, "Every word remains in the full response.");
assert.ok(!disclosure.children[1].children.some((item) => item.tagName === "script"));
rendered = new Element();
hooks.conversationBody(rendered, longResponse, false);
assert.equal(rendered.textContent, longResponse, "Staff messages and emails are not shortened.");
assert.ok(!rendered.children.some((item) => item.tagName === "details"));
rendered = new Element();
hooks.conversationBody(rendered, `See [the two lot records](https://example.test/${"lot".repeat(350)}).\n\nFull findings.`, true);
assert.equal(rendered.children[0].textContent, "See the two lot records.",
  "A long source URL must not cut a Markdown link in half in the reply preview.");
rendered = new Element();
hooks.conversationBody(rendered, "A short handoff to the email draft.", true);
assert.equal(rendered.textContent, "A short handoff to the email draft.");
assert.ok(!rendered.children.some((item) => item.tagName === "details"));

function detailFixture(id, open) {
  const detail = new Element("details");
  detail.id = id;
  detail.open = open;
  return detail;
}
const oldDetails = [detailFixture("draft-a", true), detailFixture("draft-b", false)];
const nextDetails = [detailFixture("draft-new", false), detailFixture("draft-b", true), detailFixture("draft-a", false)];
const oldPanel = detailFixture("drafts", true);
oldPanel.querySelectorAll = () => oldDetails;
const nextPanel = detailFixture("drafts", false);
nextPanel.querySelectorAll = () => nextDetails;
hooks.preserveDetails(oldPanel, nextPanel);
assert.equal(nextPanel.open, true);
assert.deepEqual(nextDetails.map((item) => item.open), [false, false, true],
  "Polling preserves the selected draft when another draft is inserted or reordered.");
const caseItems = hooks.workspaceItems({ drafts: [1, 2, 3, 4, 5].map((id) => ({ id, subject: `Inquiry ${id}` })),
  brief: { lots: [{}, {}] }, research: [{}] });
assert.deepEqual(Array.from(caseItems.slice(0, 3), (item) => item.target),
  ["coordinate-draft-5", "coordinate-draft-4", "coordinate-draft-3"],
  "A later reply surfaces newly prepared drafts after the case has accumulated earlier correspondence.");
assert.equal(caseItems[3].panel, "briefing");
assert.equal(caseItems[4].panel, "research");

const unsafeDraft = {
  id: "draft-preview-1", recipient: "packer@example.test", subject: '<img src=x onerror="alert(1)"> Packing inquiry',
  body: 'Hello,\n\nPlease protect the frame and certificate.\n<script>untrusted()</script>\n[link](javascript:alert(1))',
  status: "reviewed", editable: true,
};
const preview = hooks.renderDraftPreview(unsafeDraft, true);
assert.equal(preview.tagName, "details");
assert.equal(preview.id, "coordinate-reply-draft-draft-preview-1");
assert.equal(preview.dataset.previewDraftId, unsafeDraft.id);
assert.equal(preview.open, true, "The first email can be read immediately below the response.");
const previewNodes = descendants(preview);
const previewBody = previewNodes.find((element) => element.className === "coordinate-reply-draft-body");
assert.equal(previewBody.textContent, unsafeDraft.body, "The complete saved wording remains plain text.");
assert.ok(preview.textContent.includes(unsafeDraft.subject));
assert.ok(preview.textContent.includes(unsafeDraft.recipient));
assert.ok(!previewNodes.some((element) => ["img", "script", "form", "input", "textarea", "select"].includes(element.tagName)),
  "The preview cannot introduce HTML or a second mutable email form.");
const editDraft = previewNodes.find((element) => element.tagName === "button");
assert.equal(editDraft.type, "button");
assert.equal(editDraft.dataset.openPanel, "drafts");
assert.equal(editDraft.dataset.openRecord, "coordinate-draft-draft-preview-1",
  "Review opens the canonical editor, preserving its saved review and send bindings.");

const previewState = { drafts: [1, 2, 3, 4].map((id) => ({
  id: String(id), recipient: `packer${id}@example.test`, subject: `Inquiry ${id}`, body: `Saved email ${id}`, editable: true,
})).concat(["queued", "sending", "sent", "unknown"].map((send_status) => ({
  id: send_status, subject: "Locked correspondence", body: "Do not show as an available draft", editable: true, send_status,
})), [{ id: "readonly", body: "Read-only correspondence", editable: false }]) };
hooks.updateReplyDrafts(previewState, "reply-44");
const previewCards = () => descendants(replyDrafts).filter((element) => element.dataset.previewDraftId);
assert.equal(replyDrafts.hidden, false);
assert.deepEqual(Array.from(previewCards(), (card) => card.dataset.previewDraftId), ["4", "3", "2"],
  "Only the latest three editable, unsent drafts appear up front.");
assert.deepEqual(Array.from(previewCards(), (card) => Boolean(card.open)), [true, false, false]);
assert.ok(!replyDrafts.textContent.includes("Do not show as an available draft"));
assert.ok(!replyDrafts.textContent.includes("Read-only correspondence"));
previewCards()[0].open = false;
previewCards()[1].open = true;
previewState.drafts[3].body = "Revised saved wording for provider four.";
hooks.updateReplyDrafts(previewState, "reply-44");
assert.ok(replyDrafts.textContent.includes("Revised saved wording for provider four."),
  "Saved body changes refresh the preview even if its subject stays the same.");
assert.deepEqual(Array.from(previewCards(), (card) => Boolean(card.open)), [false, true, false],
  "Refreshing wording preserves which draft the user opened.");
previewState.drafts[3].recipient = "corrected@example.test";
hooks.updateReplyDrafts(previewState, "reply-44");
assert.ok(replyDrafts.textContent.includes("corrected@example.test"));
previewState.drafts[3].send_status = "sent";
hooks.updateReplyDrafts(previewState, "reply-44");
assert.deepEqual(Array.from(previewCards(), (card) => card.dataset.previewDraftId), ["3", "2", "1"]);
assert.ok(!replyDrafts.textContent.includes("Revised saved wording for provider four."),
  "A new delivery state removes the former draft from the preview immediately.");
hooks.updateReplyDrafts(previewState, "");
assert.equal(replyDrafts.hidden, true);
assert.equal(replyDrafts.textContent, "", "A hidden/deleted response leaves no previous email wording in the DOM.");
hooks.updateReplyDrafts({ drafts: [] }, "reply-44");
assert.equal(replyDrafts.hidden, true);
hooks.updateReplyDrafts(previewState, "reply-44");
hooks.setCaseDeleted(true);
hooks.updateReplyDrafts(previewState, "reply-44");
assert.equal(replyDrafts.hidden, true);
assert.equal(replyDrafts.textContent, "", "Trashing the case removes its private previews immediately.");
hooks.setCaseDeleted(false);

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
assert.notEqual(hooks.panelSignature({ drafts: [], mail: { ready: false } }, "drafts"),
  hooks.panelSignature({ drafts: [], mail: { ready: true } }, "drafts"));

function sendFixture(changes = {}) {
  const card = new Element();
  card.dataset = { draftId: "draft-1", sendStatus: "reviewed", ...changes };
  card.querySelector = () => changes.dirty ? {} : null;
  const form = new Element("form");
  form.dataset = { reviewedDigest: "reviewed-version" };
  form.elements = { content_digest: new Element("input", "reviewed-version"), request_id: new Element("input", "same-send-request") };
  form.closest = () => card;
  return { form, card };
}
let send = sendFixture();
assert.equal(hooks.validateEmailSend(send.form), true);
for (const sendStatus of ["queued", "sending", "sent", "unknown"]) {
  assert.equal(hooks.validateEmailSend(sendFixture({ sendStatus }).form), false);
}
assert.equal(hooks.validateEmailSend(sendFixture({ dirty: true }).form), false);
send.form.elements.content_digest.value = "changed-version";
assert.equal(hooks.validateEmailSend(send.form), false);
send = sendFixture();
hooks.setEmailUncertain("draft-1", true);
assert.equal(hooks.validateEmailSend(send.form), false);
hooks.setEmailUncertain("draft-1", false);
assert.equal(hooks.validateEmailSend(send.form), true);

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

async function testAmbiguousEmailSend() {
  const fixture = sendFixture();
  const form = fixture.form;
  form.matches = (selector) => [".coordinate-action-form", ".coordinate-draft-send"].includes(selector);
  form.getAttribute = () => "/coordinate/case/drafts/draft-1/send/";
  const button = new Element("button");
  button.textContent = "Send reviewed email";
  button.isConnected = true;
  form.querySelector = () => button;
  const event = { target: form, submitter: button, preventDefault() {} };
  hooks.setLatestState({ coordination: { mail: { enabled: true, ready: true }, drafts: [
    { id: "draft-1", can_send: true, editable: true, status: "reviewed", reviewed_digest: "reviewed-version", current_digest: "reviewed-version" },
  ] } });
  context.FormData = class { constructor(input) { this.digest = input.elements.content_digest.value; } };
  let requests = 0;
  context.fetch = async () => { requests += 1; throw new Error("Ambiguous connection loss"); };
  await listeners.submit[0](event);
  assert.equal(requests, 1);
  assert.equal(button.disabled, true);
  assert.ok(notice.textContent.includes("Do not resend or create a duplicate"));
  await listeners.submit[0](event);
  assert.equal(requests, 1, "A send with an unknown transport result must never be blindly retried.");
  hooks.setEmailUncertain("draft-1", false);
  hooks.setLatestState(undefined);
}

testSubmission().then(testAmbiguousEmailSend).then(() => console.log("Coordinate frontend checks passed.")).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
