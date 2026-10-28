// Run with node --test. No network or API calls; exercise the shipped paste and entry controls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const {parsePaste} = require("./static/secondstateapp/liveart_manual_entry.js");

const sample = {
  artist: "Pierre Alechinsky", title: "Droit et regard", sale_date: "2024-05-22",
  auction_house: "Germann", lot_number: "123", hammer_usd: "3305.00",
  provider_url: "https://www.liveart.ai/artists/pierre-alechinsky/droit-et-regard?source=web:result#sale",
  evidence_note: "Prints & Multiples; sold; USD hammer: $3,305. Original CHF 3,000 excludes premium.",
  category: "prints_and_multiples",
};
const pasteText = () => Object.entries(sample).map(([key, value]) => `${key}: ${value}`).join("\n");

test("pasting labeled fields preserves source URLs, quoted titles and evidence punctuation", () => {
  assert.deepEqual(parsePaste(pasteText()), sample);
  const parsed = parsePaste('  ARTIST: Pierre Alechinsky\r\nTitle: "Droit et regard": an edition\r\nUSD HAMMER: 3305.00\r\n\r\n');
  assert.deepEqual(parsed, {artist: sample.artist, title: '"Droit et regard": an edition', hammer_usd: "3305.00"});
});

test("optional source and artwork fields use the same readable labels as the form", () => {
  assert.deepEqual(parsePaste("Original hammer: 3000\nOriginal currency: CHF\nOriginal auction URL: https://auction.example/sales/1\nMedium: Etching and aquatint\nEdition: 10/65\nSize: 40 x 60 cm\nSignature: Signed in pencil\nCondition: Unexamined outside frame"), {
    original_hammer: "3000", original_currency: "CHF", lot_url: "https://auction.example/sales/1",
    medium: "Etching and aquatint", edition: "10/65", size: "40 x 60 cm",
    signature: "Signed in pencil", condition: "Unexamined outside frame",
  });
});

test("category paste accepts only supported names and labels", () => {
  for (const value of ["works_on_paper", "Drawings / Works on paper"]) {
    assert.equal(parsePaste(`Category: ${value}`).category, "works_on_paper");
  }
  assert.equal(parsePaste("Category: Prints & Multiples").category, "prints_and_multiples");
  for (const value of ["painting", "2", "drawing maybe"]) {
    assert.throws(() => parsePaste(`Category: ${value}`), /Category must be/);
  }
});

test("blank templates can fill fields but empty input has a clear error", () => {
  assert.deepEqual(parsePaste("Artist: Pierre Alechinsky\nTitle: \nSale date: \nUSD hammer: "), {
    artist: sample.artist, title: "", sale_date: "", hammer_usd: "",
  });
  for (const value of ["", " \n\r\n\t"]) assert.throws(() => parsePaste(value), /Paste the sale details first/);
});

test("unknown labels and unlabeled continued source lines fail without silently dropping content", () => {
  for (const value of ["USD price: 3305", "Source evidence: Sold\nAnother unlabeled line", "No colon", "__proto__: forged", "constructor: forged"]) {
    assert.throws(() => parsePaste(value), /Use a template label/);
  }
});

test("a repeated sale or mixed aliases is rejected instead of merging two records", () => {
  assert.throws(() => parsePaste(`${pasteText()}\n${pasteText()}`), /appears twice/);
  assert.throws(() => parsePaste("USD hammer: 3305\nhammer_usd: 9000"), /appears twice/);
  assert.throws(() => parsePaste("Title: First\nTITLE: Second"), /appears twice/);
});

test("price paste requires unambiguous plain decimal amounts", () => {
  for (const amount of ["$3,305", "3,305", "3.305,00", "3 305", "3305 USD", "1e3", "NaN", "Infinity", "-30", "+30", "30.123", ".50"]) {
    assert.throws(() => parsePaste(`USD hammer: ${amount}`), /plain amount/, amount);
    assert.throws(() => parsePaste(`Original hammer: ${amount}`), /plain amount/, amount);
  }
  assert.equal(parsePaste("USD hammer: 3305.0").hammer_usd, "3305.0");
});

test("ambiguous date formats are refused; actual date validity remains a native/server check", () => {
  for (const date of ["05/22/2024", "22 May 2024", "2024-5-22", "2024-05-22T00:00:00Z"]) {
    assert.throws(() => parsePaste(`Sale date: ${date}`), /YYYY-MM-DD|too long/);
  }
  assert.equal(parsePaste("Sale date: 2024-05-22").sale_date, "2024-05-22");
});

test("paste and individual fields are bounded without truncating evidence", () => {
  for (const value of [null, {}, 3, "x".repeat(12001)]) assert.throws(() => parsePaste(value), /12,000 characters/);
  for (const [label, max] of [["Artist", 200], ["Title", 500], ["LiveArt URL", 2000], ["Source evidence", 3000], ["Original currency", 3]]) {
    assert.equal(Object.values(parsePaste(`${label}: ${"x".repeat(max)}`))[0].length, max);
    assert.throws(() => parsePaste(`${label}: ${"x".repeat(max + 1)}`), /too long/);
  }
});

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.events = {};
    this.attributes = {};
    this.value = "";
    this.checked = false;
    this.valid = true;
  }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { (this.events[name] ||= []).push(callback); }
  async dispatch(name, event = {}) { for (const callback of this.events[name] || []) await callback({target: this, ...event}); }
  contains(node) { return this === node || this.children.some(child => child.contains?.(node)); }
  focus() { this.focused = true; }
  checkValidity() { return this.valid; }
  reportValidity() { this.reported = true; return this.valid; }
}
const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
function page({draft = null, onAdd = async () => {}} = {}) {
  const storage = new Map(draft ? [["test-draft", JSON.stringify(draft)]] : []);
  const context = vm.createContext({
    window: {}, document: {createElement: tag => new Element(tag)},
    sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "static/secondstateapp/liveart_manual_entry.js"), "utf8"), context);
  const root = new Element("section");
  context.window.LiveArtManualEntry.mount(root, {artist: sample.artist, idPrefix: "lot-1-", draftKey: "test-draft", onAdd});
  const nodes = descendants(root);
  return {
    root, storage,
    fields: Object.fromEntries(nodes.filter(node => node.name).map(node => [node.name, node])),
    find: predicate => nodes.find(predicate),
    button: text => nodes.find(node => node.tagName === "button" && node.textContent === text),
    paste: nodes.find(node => node.id === "lot-1-manual-paste"),
    confirmed: nodes.find(node => node.type === "checkbox"),
    body: nodes.find(node => node.className === "liveart-manual-body"),
    status: nodes.find(node => node.attributes.role === "status"),
  };
}

test("draft restoration retains typed evidence but never restores verification confirmation", () => {
  const p = page({draft: {fields: sample, paste: pasteText(), confirmed: true}});
  for (const [name, value] of Object.entries(sample)) assert.equal(p.fields[name].value, value);
  assert.equal(p.paste.value, pasteText());
  assert.equal(p.confirmed.checked, false);
  assert.equal(p.confirmed.required, true);
});

test("drawing category restores in the form and changing it resets source confirmation", async () => {
  const p = page({draft: {fields: {...sample, category: "works_on_paper"}}});
  assert.equal(p.fields.category.tagName, "select");
  assert.equal(p.fields.category.value, "works_on_paper");
  assert.equal(p.confirmed.checked, false);
  p.confirmed.checked = true;
  p.fields.category.value = "prints_and_multiples";
  await p.fields.category.dispatch("change");
  assert.equal(p.confirmed.checked, false);
  assert.equal(JSON.parse(p.storage.get("test-draft")).fields.category, "prints_and_multiples");
});

test("drawing add submits and retains its category on failure, then resets to prints on success", async () => {
  let reject = true, submitted;
  const p = page({draft: {fields: {...sample, category: "works_on_paper"}}, onAdd: async entry => {
    submitted = entry;
    if (reject) throw new Error("Review the source.");
  }});
  await p.button("Add sale for review").dispatch("click");
  assert.equal(submitted.category, "works_on_paper");
  assert.equal(p.fields.category.value, "works_on_paper");
  reject = false;
  await p.button("Add sale for review").dispatch("click");
  assert.equal(p.fields.category.value, "prints_and_multiples");
  assert.equal(p.confirmed.checked, false);
});

test("a paste without Category resets the prior drawing category to the print default", async () => {
  const p = page({draft: {fields: {...sample, category: "works_on_paper"}}});
  p.paste.value = "Title: Another sale";
  p.confirmed.checked = true;
  await p.button("Fill fields from paste").dispatch("click");
  assert.equal(p.fields.category.value, "prints_and_multiples");
  assert.equal(p.confirmed.checked, false);
});

test("auction archive conversion requests original hammer and historical proof while preserving source identity", async () => {
  const p = page();
  p.fields.source_kind.value = "auction_archive";
  await p.fields.source_kind.dispatch("change");
  assert.equal(p.fields.price_mode.disabled, false);
  p.fields.price_mode.value = "historical_fx";
  p.fields.hammer_usd.value = "9999";
  await p.fields.price_mode.dispatch("change");
  assert.equal(p.fields.hammer_usd.disabled, true);
  assert.equal(p.fields.hammer_usd.required, false);
  assert.equal(p.fields.hammer_usd.value, "");
  for (const key of ["original_hammer", "original_currency", "fx_rate", "fx_direction", "fx_date", "fx_source_url"]) assert.equal(p.fields[key].required, true, key);
  assert.equal(p.confirmed.checked, false);
  assert.equal(JSON.parse(p.storage.get("test-draft")).fields.source_kind, "auction_archive");
  assert.equal(JSON.parse(p.storage.get("test-draft")).fields.price_mode, "historical_fx");
  p.fields.source_kind.value = "liveart_web";
  await p.fields.source_kind.dispatch("change");
  assert.equal(p.fields.price_mode.value, "source_usd");
  assert.equal(p.fields.hammer_usd.required, true);
  assert.equal(p.fields.fx_rate.required, false);
  assert.equal(p.fields.fx_rate.disabled, true);
});

test("historical conversion paste preserves the rate precision, direction and source URL", () => {
  const parsed = parsePaste("Evidence source: auction_archive\nUSD price basis: historical_fx\nHistorical exchange rate: 1.3624\nExchange-rate direction: original_per_usd\nExchange-rate date: 2024-06-12\nExchange-rate source URL: https://bank.example/rate?date=2024-06-12");
  assert.equal(parsed.source_kind, "auction_archive");
  assert.equal(parsed.fx_rate, "1.3624");
  assert.equal(parsed.fx_direction, "original_per_usd");
  assert.equal(parsed.fx_source_url, "https://bank.example/rate?date=2024-06-12");
});

test("editing or filling a paste resets source confirmation and persists the new draft", async () => {
  const p = page();
  p.confirmed.checked = true;
  p.paste.value = pasteText();
  await p.button("Fill fields from paste").dispatch("click");
  assert.equal(p.confirmed.checked, false);
  assert.equal(p.fields.provider_url.value, sample.provider_url);
  assert.deepEqual(JSON.parse(p.storage.get("test-draft")).fields.evidence_note, sample.evidence_note);
  p.confirmed.checked = true;
  p.fields.hammer_usd.value = "4000";
  await p.body.dispatch("input", {target: p.fields.hammer_usd});
  assert.equal(p.confirmed.checked, false);
  assert.equal(JSON.parse(p.storage.get("test-draft")).fields.hammer_usd, "4000");
});

test("invalid paste is atomic and keeps existing fields available to correct", async () => {
  const p = page({draft: {fields: sample}});
  p.paste.value = "Title: A different work\nUSD hammer: $5,000";
  await p.button("Fill fields from paste").dispatch("click");
  assert.equal(p.fields.title.value, sample.title);
  assert.equal(p.fields.hammer_usd.value, sample.hammer_usd);
  assert.match(p.status.textContent, /plain amount/);
  assert.match(p.status.className, /is-error/);
});

test("a new partial paste cannot retain the prior sale's price, date, link or optional details", async () => {
  const p = page({draft: {fields: {...sample, original_hammer: "3000", original_currency: "CHF"}}});
  p.paste.value = "Title: Another sale";
  await p.button("Fill fields from paste").dispatch("click");
  assert.equal(p.fields.title.value, "Another sale");
  assert.equal(p.fields.artist.value, sample.artist);
  for (const name of ["hammer_usd", "sale_date", "provider_url", "lot_number", "original_hammer", "original_currency"]) {
    assert.equal(p.fields[name].value, "", name);
  }
});

test("invalid hidden optional input is opened and focused by native validity before any add", async () => {
  let calls = 0;
  const p = page({onAdd: async () => { calls += 1; }});
  p.fields.original_hammer.valid = false;
  await p.button("Add sale for review").dispatch("click");
  assert.equal(calls, 0);
  assert.equal(p.find(node => node.className === "liveart-manual-extra").open, true);
  assert.equal(p.fields.original_hammer.reported, true);
});

test("rejected add retains all evidence and draft for correction without auto-selecting", async () => {
  const p = page({draft: {fields: sample, paste: pasteText()}, onAdd: async () => { throw new Error("The artist does not match."); }});
  p.confirmed.checked = true;
  await p.button("Add sale for review").dispatch("click");
  assert.equal(p.fields.title.value, sample.title);
  assert.equal(p.fields.hammer_usd.value, sample.hammer_usd);
  assert.equal(p.paste.value, pasteText());
  assert(p.storage.has("test-draft"));
  assert.equal(p.status.textContent, "The artist does not match.");
});

test("a pending add cannot submit twice and success clears only the entry draft", async () => {
  let calls = 0, resolve;
  const p = page({draft: {fields: sample, paste: pasteText()}, onAdd: entry => {
    calls += 1;
    assert.equal(entry.provider_url, sample.provider_url);
    assert.equal(entry.evidence_note, sample.evidence_note);
    return new Promise(done => { resolve = done; });
  }});
  p.storage.set("another-evidence-draft", "preserve");
  const add = p.button("Add sale for review");
  const pending = add.dispatch("click");
  await add.dispatch("click");
  assert.equal(calls, 1);
  resolve();
  await pending;
  assert.equal(p.fields.artist.value, sample.artist);
  assert.equal(p.fields.title.value, "");
  assert.equal(p.paste.value, "");
  assert.equal(p.confirmed.checked, false);
  assert.equal(p.storage.has("test-draft"), false);
  assert.equal(p.storage.get("another-evidence-draft"), "preserve");
  assert.match(p.status.textContent, /Select.*Use in resale bid.*save selected evidence/);
});

test("a repeated source uses the existing sale and tells the user it was already present", async () => {
  const p = page({draft: {fields: sample}, onAdd: async () => ({duplicate: true})});
  await p.button("Add sale for review").dispatch("click");
  assert.match(p.status.textContent, /already/i);
  assert.equal(p.fields.title.value, "");
});

function integration({response = {}, failure = null, busy = false} = {}) {
  const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
  const start = template.indexOf("    const applyManualResearch = (payload) => {");
  const end = template.indexOf("    registerLotInstance(liveartAnalysisInstances", start);
  assert(start !== -1 && end > start, "Production manual entry integration must be present");
  const requests = [];
  const originalCandidates = [{id: "old-api", provider: "LiveArt"}];
  const webGroup = {};
  const context = vm.createContext({
    window: {LiveArtManualEntry: {mount(_section, options) { context.entryOptions = options; }}},
    document: {createElement: tag => new Element(tag)},
    section: {}, lot: {id: 3588, artist: sample.artist, liveart_analysis_url: "/calendar/lots/3588/liveart-analysis/"},
    options: {idPrefix: "research-"},
    archiveDraftKey: (id, key) => `${id}:${key}`, csrfToken: "local-csrf", load: async () => {},
    loaded: true, busy, pendingSourceRefresh: false, currentResearchId: "previous-token",
    selectedIds: new Set(["old-api"]), currentCandidates: originalCandidates,
    researchRetrievedAt: "old-time", hasResearch: true, currentSearchInfo: {}, subjectNeedsChoice: false,
    setBusy(value) { context.busy = value; },
    async requestAnalysisJson(url, options) { requests.push({url, options}); if (failure) throw failure; return response; },
    sourceMeta: {}, describeSources: () => "Sources", renderCandidates(matches) { context.renderedMatches = matches; },
    candidateResults: {querySelector: () => webGroup},
    markAnalysisPending(message) { context.pendingMessage = message; }, setStatus(message, tone) { context.statusMessage = message; context.statusTone = tone; },
  });
  vm.runInContext(template.slice(start, end), context);
  const mountRemove = (candidate, confirmed = true) => {
    const removeStart = template.indexOf('      if (candidate.entry_method === "manual_web") {');
    const removeEnd = template.indexOf("      if (!selectable && subjectNeedsChoice)", removeStart);
    assert(removeStart > 0 && removeEnd > removeStart, "Production removal control must be present");
    context.candidate = candidate;
    context.top = new Element("div");
    context.window.confirm = message => { context.confirmationMessage = message; return confirmed; };
    vm.runInContext(template.slice(removeStart, removeEnd), context);
    return context.top.children[0];
  };
  return Object.assign(context, {requests, originalCandidates, webGroup, mountRemove});
}

test("Workbench add submits current selections/token to manual analysis without an API search or automatic save", async () => {
  const payload = {
    candidates: [{id: "old-api"}, {id: "manual-new", entry_method: "manual_web"}],
    selected_ids: ["old-api"], research_id: "new-token", retrieved_at: "new-time",
    subject_matches: [], added_id: "manual-new", data_units_spent: 0,
  };
  const p = integration({response: payload});
  const result = await p.entryOptions.onAdd(sample);
  assert.equal(p.requests.length, 1);
  assert.equal(p.requests[0].url, "/calendar/lots/3588/liveart-analysis/");
  const request = JSON.parse(p.requests[0].options.body);
  assert.equal(request.action, "add_manual");
  assert.equal(request.confirmed, true);
  assert.deepEqual(request.selected_ids, ["old-api"]);
  assert.equal(request.research_id, "previous-token");
  assert.deepEqual(request.entry, {...sample, price_basis: "hammer", currency: "USD", category: "prints_and_multiples", status: "sold"});
  assert.equal(p.currentResearchId, "new-token");
  assert.deepEqual([...p.selectedIds], ["old-api"]);
  assert.equal(p.webGroup.open, true);
  assert.match(p.pendingMessage, /not saved yet/);
  assert.equal(p.busy, false);
  assert.equal(result, payload);
});

test("failed manual request preserves prior evidence and token, and always re-enables controls", async () => {
  const p = integration({failure: new Error("This research was replaced in another tab.")});
  await assert.rejects(p.entryOptions.onAdd(sample), /another tab/);
  assert.equal(p.currentCandidates, p.originalCandidates);
  assert.equal(p.currentResearchId, "previous-token");
  assert.deepEqual([...p.selectedIds], ["old-api"]);
  assert.equal(p.pendingMessage, undefined);
  assert.equal(p.busy, false);
});

test("Workbench sends the explicit drawing category without substituting prints", async () => {
  const p = integration();
  await p.entryOptions.onAdd({...sample, category: "works_on_paper", medium: "Pencil on paper"});
  const request = JSON.parse(p.requests[0].options.body);
  assert.equal(request.entry.category, "works_on_paper");
  assert.equal(request.entry.medium, "Pencil on paper");
  assert.equal(request.entry.price_basis, "hammer");
  assert.equal(request.entry.currency, "USD");
  assert.equal(request.entry.category_id, undefined);
});

test("evidence checkboxes accept verified manual drawings while keeping API categories print-only", () => {
  const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
  const start = template.indexOf("    const legacyManualReview = (candidate) => {");
  const end = template.indexOf("    const textValue", start);
  const context = vm.createContext({isArtpriceCandidate: candidate => candidate.provider === "Artprice"});
  vm.runInContext(template.slice(start, end) + "globalThis.canSelect = canSelectCandidate;", context);
  const drawing = {provider: "LiveArt", status: "sold", hammer_usd: "3305.00", entry_method: "manual_web",
    category: "works_on_paper", category_id: null, source_confirmed: true,
    price_basis: "hammer", hammer_currency: "USD", credible: false, manual_selectable: true};
  assert.equal(context.canSelect(drawing), true);
  assert.equal(context.canSelect({...drawing, category: "prints_and_multiples", category_id: 2}), true);
  assert.equal(context.canSelect({provider: "LiveArt", status: "sold", hammer_usd: "1000", category_id: 2, credible: true}), true);
  for (const change of [{category_id: 2}, {entry_method: "api"}, {source_confirmed: false},
    {category: "painting"}, {price_basis: "premium_inclusive"}, {hammer_currency: "CHF"},
    {manual_selectable: false}, {status: "unsold"}, {hammer_usd: "0"}]) {
    assert.equal(context.canSelect({...drawing, ...change}), false, JSON.stringify(change));
  }
});

test("busy evidence does not accept a manual entry until it can be preserved safely", async () => {
  const p = integration({busy: true});
  await assert.rejects(p.entryOptions.onAdd(sample), /finish loading/);
  assert.equal(p.requests.length, 0);
  assert.equal(p.currentCandidates, p.originalCandidates);
});

test("only manually entered sales expose a removal control", () => {
  const p = integration();
  assert.equal(p.mountRemove({id: "api-sale", provider: "LiveArt"}), undefined);
  assert.equal(p.mountRemove({id: "artprice:1", provider: "Artprice"}), undefined);
  const button = p.mountRemove({id: "manual-new", entry_method: "manual_web", title: sample.title});
  assert.equal(button.type, "button");
  assert.equal(button.textContent, "Remove entered sale");
  assert.equal(button.attributes["aria-label"], `Remove entered sale: ${sample.title}`);
});

test("removing an entered sale stages a new research token and selection without saving automatically", async () => {
  const p = integration({response: {
    candidates: [{id: "old-api"}], selected_ids: ["old-api"], research_id: "removal-token",
    retrieved_at: "removal-time", message: "Sale removed from the review list. Save to apply.",
  }});
  p.selectedIds = new Set(["old-api", "manual-new"]);
  const button = p.mountRemove({id: "manual-new", entry_method: "manual_web", title: sample.title});
  await button.dispatch("click");
  assert.equal(p.requests.length, 1);
  assert.equal(p.requests[0].url, "/calendar/lots/3588/liveart-analysis/");
  assert.equal(p.requests[0].options.method, "POST");
  assert.equal(p.requests[0].options.headers["X-CSRFToken"], "local-csrf");
  assert.deepEqual(JSON.parse(p.requests[0].options.body), {
    action: "remove_manual", candidate_id: "manual-new", selected_ids: ["old-api", "manual-new"], research_id: "previous-token",
  });
  assert.match(p.confirmationMessage, /Save selected evidence to apply/);
  assert.equal(p.currentResearchId, "removal-token");
  assert.deepEqual([...p.selectedIds], ["old-api"]);
  assert.match(p.pendingMessage, /not saved yet/);
  assert.match(p.statusMessage, /Save to apply/);
  assert.equal(p.busy, false);
});

test("removal refuses busy or refreshing evidence and respects cancellation", async () => {
  for (const mode of ["busy", "refreshing", "parent-busy", "cancel"]) {
    const p = integration({busy: mode === "busy"});
    p.pendingSourceRefresh = mode === "refreshing";
    p.options.isParentBusy = () => mode === "parent-busy";
    const button = p.mountRemove({id: "manual-new", entry_method: "manual_web", title: sample.title}, mode !== "cancel");
    await button.dispatch("click");
    assert.equal(p.requests.length, 0, mode);
    assert.equal(p.currentCandidates, p.originalCandidates, mode);
    assert.equal(p.currentResearchId, "previous-token", mode);
  }
});

test("failed removal preserves evidence and selections and makes the error visible", async () => {
  const p = integration({failure: new Error("This research was replaced in another tab.")});
  p.selectedIds = new Set(["old-api", "manual-new"]);
  const button = p.mountRemove({id: "manual-new", entry_method: "manual_web", title: sample.title});
  await button.dispatch("click");
  assert.equal(p.currentCandidates, p.originalCandidates);
  assert.equal(p.currentResearchId, "previous-token");
  assert.deepEqual([...p.selectedIds], ["old-api", "manual-new"]);
  assert.equal(p.statusMessage, "This research was replaced in another tab.");
  assert.equal(p.statusTone, "error");
  assert.equal(p.busy, false);
  assert.equal(p.pendingMessage, undefined);
});

test("a pending removal is protected from a second click", async () => {
  let resolve;
  const response = new Promise(done => { resolve = done; });
  const p = integration({response});
  const button = p.mountRemove({id: "manual-new", entry_method: "manual_web", title: sample.title});
  const first = button.dispatch("click");
  await button.dispatch("click");
  assert.equal(p.requests.length, 1);
  resolve({candidates: [], selected_ids: [], research_id: "empty-token"});
  await first;
  assert.equal(p.busy, false);
  assert.equal(p.currentCandidates.length, 0);
  assert.match(p.pendingMessage, /not saved yet/);
});
