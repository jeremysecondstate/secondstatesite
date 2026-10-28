// Run with node --test. Exercise shipped Workbench bulk controls without requests.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function declaration(name) {
  const start = template.indexOf(`    const ${name} =`);
  assert(start >= 0, `Missing production helper: ${name}`);
  let depth = 0, quote = "", escaped = false, comment = "";
  for (let i = start; i < template.length; i += 1) {
    const c = template[i];
    if (comment === "line") { if (c === "\n") comment = ""; continue; }
    if (comment === "block") {
      if (c === "*" && template[i + 1] === "/") { comment = ""; i += 1; }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (c === "\\") escaped = true;
      else if (c === quote) quote = "";
      continue;
    }
    if (c === "/" && template[i + 1] === "/") { comment = "line"; i += 1; continue; }
    if (c === "/" && template[i + 1] === "*") { comment = "block"; i += 1; continue; }
    if (["\"", "'", "`"].includes(c)) { quote = c; continue; }
    if ("({[".includes(c)) depth += 1;
    if (")}]".includes(c)) depth -= 1;
    if (c === ";" && depth === 0) return template.slice(start, i + 1);
  }
  throw new Error(`Unterminated production helper: ${name}`);
}

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.events = {};
    this.textContent = "";
    this.className = "";
    this.disabled = false;
    this.checked = false;
  }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  appendChild(node) {
    if (node.parentNode) node.parentNode.children = node.parentNode.children.filter(child => child !== node);
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
  replaceChildren(...nodes) {
    this.children.forEach(node => { node.parentNode = null; });
    this.children = [];
    this.append(...nodes);
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.events[name] = listener; }
  dispatch(name) { return this.events[name]?.({target: this}); }
  focus() { this.focused = true; }
  scrollIntoView() {}
  matches(selector) {
    return selector.split(",").some(part => {
      const s = part.trim();
      const attr = s.match(/\[([^=\]]+)(?:="([^"]*)")?\]/);
      const base = s.replace(/\[[^\]]+\]/g, "");
      if (base.startsWith(".") ? !this.className.split(/\s+/).includes(base.slice(1)) : base && base !== this.tagName) return false;
      if (!attr) return true;
      const name = attr[1];
      const value = name.startsWith("data-")
        ? this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())]
        : this[name] ?? this.attributes[name];
      return attr[2] === undefined ? Boolean(value) : String(value) === attr[2];
    });
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const artprice = (id, changes = {}) => ({
  id: `artprice:${id}`, provider: "Artprice", match_type: "artprice_html",
  title: `Sale ${id}`, artist: "Example Artist", status: "sold", hammer_usd: "1000", credible: true, ...changes,
});
const liveart = (id, changes = {}) => ({
  id: `liveart:${id}`, provider: "LiveArt", match_type: "related_work", category_id: "2",
  title: `Sale ${id}`, artist: "Example Artist", status: "sold", hammer_usd: "1000", credible: true, ...changes,
});

function workbench(candidates, selected = []) {
  const section = new Element("section"), candidateResults = new Element("div"), subjectResults = new Element("div");
  const savedResults = new Element("div"), saveButton = new Element("button"), deleteButton = new Element("button");
  section.append(subjectResults, candidateResults, savedResults, saveButton, deleteButton);
  const drafts = [], statuses = [], scenarios = [], requests = [];
  const context = vm.createContext({
    window: {}, URL, section, candidateResults, subjectResults, savedResults, saveButton, deleteButton,
    document: {
      createElement: tag => new Element(tag),
      createTextNode: text => Object.assign(new Element("#text"), {textContent: text}),
    },
    currentCandidates: candidates, selectedIds: new Set(selected), candidatePages: new Map(),
    options: {workspace: true, isParentBusy: () => context.parentBusy, onScenarioSummary: value => scenarios.push(value)},
    parentBusy: false, busy: false, pendingSourceRefresh: false, currentSubjectMatches: [],
    hasResearch: true, subjectNeedsChoice: false, hasUnsavedChanges: false, localRevision: 0,
    currentAnalysis: {updated_at: "saved-baseline"}, currentResearchId: "research-receipt",
    researchRetrievedAt: "retrieved-time", currentSearchInfo: {data_units_spent: 8},
    lot: {id: 87}, costDefinitions: [], costFields: {},
    writeDraft(id, key, data) { drafts.push({id, key, data}); },
    setStatus(message, tone) { statuses.push({message, tone}); },
    requestAnalysisJson(...args) { requests.push(args); throw new Error("Bulk selection must not issue a request"); },
    providerLink: () => null, formatAnalysisMoney: value => String(value), formatAnalysisTimestamp: value => String(value),
    appendText(parent, tag, className, text) {
      return parent.appendChild(Object.assign(new Element(tag), {className, textContent: text}));
    },
    appendFact() {},
  });
  const helpers = ["saveDraft", "isArtpriceCandidate", "legacyManualReview", "needsManualReview", "supportedLiveArtCategory",
    "canSelectCandidate", "candidateGroupItems", "updateBulkSelectionControls", "changeCandidateGroupSelection", "textValue",
    "renderCandidateCard", "renderCandidates", "markAnalysisPending", "updateButtons", "syncBusyControls"];
  vm.runInContext(helpers.map(declaration).join("\n"), context);
  context.run = expression => vm.runInContext(expression, context);
  context.run("renderCandidates()");
  return Object.assign(context, {
    drafts, statuses, scenarios, requests,
    group: type => candidateResults.querySelectorAll(".research-candidate-group").find(group => group.dataset.group === type),
    toolbar: type => candidateResults.querySelectorAll(".research-candidate-bulk").find(group => group.dataset.group === type),
    button(type, action) { return this.toolbar(type).querySelector(`[data-bulk-action="${action}"]`); },
    selected: () => [...context.selectedIds],
  });
}

test("Select all spans every page, respects the shared 25-sale cap, and stages one draft without a request", () => {
  const candidates = [liveart(1), liveart(2), ...Array.from({length: 37}, (_, i) => artprice(i + 1))];
  const original = JSON.stringify(candidates);
  const p = workbench(candidates, ["liveart:1", "liveart:2"]);
  const button = p.button("artprice_html", "select");
  assert.equal(button.tagName, "button");
  assert.equal(button.type, "button");
  assert.equal(button.textContent, "Select all");
  assert.equal(p.toolbar("artprice_html").attributes.role, "group");
  assert.match(p.toolbar("artprice_html").attributes["aria-label"], /Saved Artprice HTML sales/);
  const group = p.group("artprice_html");
  const otherGroup = p.group("related_work");
  otherGroup.open = false;
  button.dispatch("click");
  assert.deepEqual(p.selected(), ["liveart:1", "liveart:2", ...Array.from({length: 23}, (_, i) => `artprice:${i + 1}`)]);
  assert.equal(p.group("artprice_html"), group, "bulk selection preserves the rendered controls and focus target");
  assert.equal(otherGroup.open, false, "another section's collapsed state stays unchanged");
  assert.equal(group.querySelectorAll('input[type="checkbox"]').length, 10);
  assert(group.querySelectorAll('input[type="checkbox"]').every(box => box.checked));
  assert.match(group.querySelector("summary").textContent, /23 selected$/);
  assert.match(p.statuses.at(-1).message, /25-sale limit.*14 eligible sales remain/);
  assert.equal(p.localRevision, 1);
  assert.equal(p.drafts.length, 1);
  assert.equal(p.drafts[0].id, 87);
  assert.equal(p.drafts[0].key, "evidence");
  assert.deepEqual(Array.from(p.drafts[0].data.selectedIds), p.selected());
  assert.equal(p.drafts[0].data.researchId, "research-receipt");
  assert.deepEqual(p.scenarios, [null], "old calculation display is invalidated once");
  assert.equal(p.requests.length, 0);
  assert.equal(JSON.stringify(candidates), original);
  p.candidatePages.set("artprice_html", 2);
  p.run("renderCandidates(currentSubjectMatches)");
  const thirdPage = p.group("artprice_html").querySelectorAll('input[type="checkbox"]');
  assert.deepEqual(thirdPage.filter(box => box.checked).map(box => box.value), ["artprice:21", "artprice:22", "artprice:23"]);
  assert.equal(p.button("artprice_html", "select").disabled, true);
});

test("auction archive evidence has a separate selectable group and truthful source labels", () => {
  const archive = liveart("archive", {id: "archive-web:338", provider: "Auction archive", match_type: "auction_archive",
    entry_method: "manual_web", source_confirmed: true, price_basis: "hammer", hammer_currency: "USD", category: "prints_and_multiples",
    credible: false, manual_selectable: true, hammer_usd: "1835.00",
    fx_conversion: {calculation: "2500.00 CAD / 1.3624 = 1835.00 USD", rate_date: "2024-06-12", source_url: "https://bank.example/rate"}});
  const p = workbench([liveart(1), archive]);
  assert.match(p.group("auction_archive").querySelector("summary").textContent, /Auction archive sales/);
  assert.equal(p.group("auction_archive").querySelector(".liveart-work-type").textContent, "Auction archive");
  assert.match(p.group("auction_archive").querySelector(".liveart-price-line").textContent, /converted using historical FX/);
  p.button("auction_archive", "select").dispatch("click");
  assert.deepEqual(p.selected(), ["archive-web:338"]);
  assert.equal(p.requests.length, 0);
  vm.runInContext(declaration("describeSources"), p);
  const description = p.run("describeSources({candidates: currentCandidates}, false)");
  assert.match(description, /1 LiveArt sale/);
  assert.match(description, /1 auction archive sale/);
  assert.doesNotMatch(description, /2 LiveArt/);
});

test("Deselect all clears this section on all pages while retaining other sources and saved records", () => {
  const candidates = [liveart(1), ...Array.from({length: 17}, (_, i) => artprice(i + 1))];
  candidates[16].hammer_usd = "0";
  const p = workbench(candidates, candidates.map(sale => sale.id));
  const saved = p.currentAnalysis;
  p.candidatePages.set("artprice_html", 1);
  p.run("renderCandidates(currentSubjectMatches)");
  p.button("artprice_html", "deselect").dispatch("click");
  assert.deepEqual(p.selected(), ["liveart:1"]);
  assert.equal(p.candidatePages.get("artprice_html"), 1);
  assert(p.group("artprice_html").querySelectorAll('input[type="checkbox"]').every(box => !box.checked));
  assert.doesNotMatch(p.group("artprice_html").querySelector("summary").textContent, /selected/);
  assert.equal(p.button("artprice_html", "deselect").disabled, true);
  assert.equal(p.button("artprice_html", "select").disabled, false);
  assert.equal(p.localRevision, 1);
  assert.equal(p.drafts.length, 1);
  assert.equal(p.currentAnalysis, saved, "the saved analysis is not deleted or rewritten");
  assert.equal(p.currentCandidates, candidates);
  assert.equal(p.requests.length, 0);
});

test("bulk selection uses the same sold USD hammer and manual-review eligibility as individual checkboxes", () => {
  const web = liveart("drawing", {match_type: "liveart_web", entry_method: "manual_web", category: "works_on_paper",
    category_id: null, source_confirmed: true, price_basis: "hammer", hammer_currency: "USD", credible: false, manual_selectable: true});
  const p = workbench([
    artprice("good"), artprice("unsold", {status: "unsold"}), artprice("zero", {hammer_usd: "0"}),
    artprice("bad-price", {hammer_usd: "not a number"}), artprice("too-large", {hammer_usd: "1000000000001"}),
    liveart("good"), liveart("review", {credible: false, manual_selectable: true}),
    liveart("wrong-category", {category_id: "1"}), liveart("unverified", {credible: false}),
    web, {...web, id: "wrong-basis", price_basis: "premium_inclusive"}, {...web, id: "unconfirmed", source_confirmed: false},
  ]);
  for (const type of ["artprice_html", "related_work", "liveart_web"]) p.button(type, "select").dispatch("click");
  assert.deepEqual(p.selected(), ["artprice:good", "liveart:good", "liveart:review", "liveart:drawing"]);
  const boxes = p.candidateResults.querySelectorAll('input[type="checkbox"]');
  assert(boxes.filter(box => box.disabled).every(box => !box.checked));
  assert.equal(p.localRevision, 3);
  assert.equal(p.requests.length, 0);
});

test("single-checkbox changes and busy transitions keep the bulk controls accurate", () => {
  const p = workbench([artprice(1), artprice(2, {status: "unsold"})], ["artprice:1"]);
  assert.equal(p.button("artprice_html", "select").disabled, true);
  const box = p.group("artprice_html").querySelectorAll('input[type="checkbox"]').find(box => box.value === "artprice:1");
  box.checked = false;
  box.dispatch("change");
  assert.equal(p.button("artprice_html", "select").disabled, false);
  assert.equal(p.button("artprice_html", "deselect").disabled, true);
  p.button("artprice_html", "select").dispatch("click");
  p.busy = true;
  p.run("syncBusyControls()");
  assert.equal(p.button("artprice_html", "select").disabled, true);
  assert.equal(p.button("artprice_html", "deselect").disabled, true);
  p.busy = false;
  p.run("syncBusyControls()");
  assert.equal(p.button("artprice_html", "select").disabled, true, "all eligible sales remain selected after re-enabling controls");
  assert.equal(p.button("artprice_html", "deselect").disabled, false);
  assert.equal(p.group("artprice_html").querySelectorAll('input[type="checkbox"]').find(box => box.value === "artprice:2").disabled, true);
});

test("busy, parent-busy, and pending-source-refresh guard bulk mutations and preserve drafts", () => {
  for (const flag of ["busy", "parentBusy", "pendingSourceRefresh"]) {
    const p = workbench([artprice(1), artprice(2)], ["artprice:1"]);
    p[flag] = true;
    p.run("updateBulkSelectionControls()");
    assert.equal(p.button("artprice_html", "select").disabled, true, flag);
    assert.equal(p.button("artprice_html", "deselect").disabled, true, flag);
    p.run('changeCandidateGroupSelection("artprice_html", true); changeCandidateGroupSelection("artprice_html", false)');
    assert.deepEqual(p.selected(), ["artprice:1"], flag);
    assert.equal(p.localRevision, 0, flag);
    assert.equal(p.drafts.length, 0, flag);
    assert.equal(p.requests.length, 0, flag);
  }
});

test("Other candidate results use the same catch-all membership for bulk selection and summary counts", () => {
  const p = workbench([liveart("legacy", {match_type: "legacy"}), liveart("missing", {match_type: undefined}), artprice(1)], ["artprice:1"]);
  p.button("other", "select").dispatch("click");
  assert.deepEqual(p.selected(), ["artprice:1", "liveart:legacy", "liveart:missing"]);
  assert.match(p.group("other").querySelector("summary").textContent, /2 selected$/);
  p.button("other", "deselect").dispatch("click");
  assert.deepEqual(p.selected(), ["artprice:1"]);
  assert.doesNotMatch(p.group("other").querySelector("summary").textContent, /selected/);
});

test("empty, already-selected, already-deselected, and full-cap operations do not create a new draft revision", () => {
  for (const scenario of [
    {candidates: [], selected: [], select: true},
    {candidates: [artprice(1)], selected: ["artprice:1"], select: true},
    {candidates: [artprice(1)], selected: [], select: false},
    {candidates: [artprice(1, {status: "unsold"})], selected: [], select: true},
    {candidates: [...Array.from({length: 25}, (_, i) => liveart(i)), artprice(1)], selected: Array.from({length: 25}, (_, i) => `liveart:${i}`), select: true},
  ]) {
    const p = workbench(scenario.candidates, scenario.selected);
    p.run(`changeCandidateGroupSelection("artprice_html", ${scenario.select})`);
    assert.deepEqual(p.selected(), scenario.selected);
    assert.equal(p.localRevision, 0);
    assert.equal(p.hasUnsavedChanges, false);
    assert.equal(p.drafts.length, 0);
    assert.equal(p.scenarios.length, 0);
    assert.equal(p.requests.length, 0);
  }
});
