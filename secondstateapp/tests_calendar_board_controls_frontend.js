// Run with node --test. Exercise the actual shared controls, renderers and board events.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function block(start, end) {
  const a = template.indexOf(start), b = template.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, `Missing production block: ${start}`);
  return template.slice(a, b);
}
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
let currentDocument;
class Element {
  constructor(tag = "div") {
    Object.assign(this, {tag, children: [], dataset: {}, attributes: {}, events: {}, style: {}, hidden: false, className: ""});
    this.classList = {toggle() {}, remove() {}};
  }
  append(...children) { children.forEach(child => {child.parentElement = this; this.children.push(child);}); }
  appendChild(child) { this.append(child); return child; }
  replaceChildren(...children) { this.children.forEach(child => {child.parentElement = null;}); this.children = []; this.append(...children); }
  contains(node) { return this === node || this.children.some(child => child.contains(node)); }
  matches(selector) {
    if (selector === "[data-gallery-filter]") return Boolean(this.dataset.galleryFilter);
    return selector.startsWith(".") ? this.className.split(/\s+/).includes(selector.slice(1)) : this.tag === selector;
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.events[name] = callback; }
  querySelectorAll(selector) {
    const matches = selector.split(",").map(part => part.trim());
    return descendants(this).filter(node => matches.some(part => node.matches(part)));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { currentDocument.activeElement = this; }
}
const board = amount => ({qualifying_bid: amount, include_in_email: false});
const lot = (id, overrides = {}) => ({id, title: `Print ${id}`, artist: "Artist", source: "Source", saved_bid_board: null,
  research_queue_selected: false, research_queue_update_url: `/queue/${id}`, research_url: `/research/${id}`, ...overrides});

function page(source, retainedResearchLot = null) {
  const listeners = new Map(), requests = [];
  const document = {createElement: tag => new Element(tag), activeElement: null, body: new Element("body"), querySelectorAll: () => []};
  currentDocument = document;
  const window = {document, fetch: (...args) => {requests.push(args); throw new Error("Rendering must not write selections");},
    addEventListener: (event, callback) => listeners.set(event, callback),
    SavedBidBoard: {mountSummary(root, {lot: owner}) {
      root.className = "sb-catalog-summary";
      root.dataset.savedBidBoardLotId = String(owner.id);
      root.append(Object.assign(new Element("button"), {textContent: "Delete Bid Board"}));
      root.updateSavedBoard = summary => {root.summary = summary;};
      root.updateSavedBoard(owner.saved_bid_board);
    }},
  };
  const context = vm.createContext({window, document, data: {"2026-11-04": [source]}, retainedResearchLot,
    csrfToken: "test-csrf", activeView: "catalog", galleryFilter: "all", selectedDay: "2026-11-04",
    dayLots: () => [retainedResearchLot || source], isGalleryView: () => context.activeView === "catalog",
    renderGalleryFilters: () => {
      context.filterRefreshes += 1;
      const filter = new Element("button"); filter.dataset.galleryFilter = context.galleryFilter;
      context.galleryFilters.replaceChildren(filter);
    },
    renderGalleryCards: () => {context.cardRefreshes += 1; context.refreshCards?.();},
    filterRefreshes: 0, cardRefreshes: 0,
    galleryResearchUrl: item => `/research/${item.id}`, galleryImage: () => [new Element("img")],
    updateGalleryEmailButton() {}, toggleGalleryEmail() {}, appendCurrencyPrice() {},
    appendArtpriceEditor() {}, appendArtpriceAnalysis() {}, appendLotBrowserMedia: () => new Element("figure"),
    appendArchiveGallery: () => new Element("figure"), formatCalendarDay: () => "November 4, 2026",
    renderResearchRail() {}, activateArchiveStage() {}, researchLotCache: new Map(), researchDaySelection: new Map(),
    researchIndex: 0, researchRenderedKey: "", lotBrowserIndex: 0, sidebarRenderedDay: "", sidebarRenderedScope: "",
    inOliverScope: () => false,
    appendText(parent, tag, className, textContent) { return parent.appendChild(Object.assign(new Element(tag), {className, textContent})); },
  });
  for (const name of ["list", "lotBrowserCard", "lotBrowserTitle", "lotBrowserCounter", "lotBrowserProgress", "lotBrowserPrevious", "lotBrowserNext",
    "researchTitle", "researchSubtitle", "researchPrevious", "researchNext", "researchCount", "researchLotCard", "researchDaySelect",
    "galleryGrid", "galleryFilters", "galleryCatalog"])
    context[name] = new Element();
  vm.runInContext(fs.readFileSync(path.join(__dirname, "static/secondstateapp/research_queue.js"), "utf8"), context);
  vm.runInContext(block("  const hasQualifyingBid =", "  const auctionCalendar =")
    + block("  const externalLink =", "  const formatAnalysisMoney =")
    + block("  const appendRetainedSavedWork =", "  const renderGalleryCards =")
    + block("  const renderSidebarLots =", "  const updateSidebarLaunches =")
    + block("  const renderLotBrowser =", "  const moveLotBrowser =")
    + block("  const renderResearchWorkspace =", "  const openResearchWorkspace ="), context);
  context.run = code => vm.runInContext(code, context);
  context.emit = (owner, summary, focusOrigin) => {
    // Real widgets mutate their shared owner before publishing.
    owner.saved_bid_board = summary;
    listeners.get("archive-bid-board-saved")({detail: {lotId: owner.id, savedBoard: summary, focusOrigin}});
  };
  context.mount = (target, item = source, group = item) => {Object.assign(context, {target, item, group}); context.run("appendLotControls(target, item, group)");};
  Object.assign(context, {requests, source});
  return context;
}
const summaries = root => root.querySelectorAll(".sb-catalog-summary");
const selections = root => root.querySelectorAll(".research-queue-selection");

for (const surface of ["catalog", "sidebar", "browser", "archive"]) {
  test(`${surface} uses the shared saved-board controls and suppresses research selection`, () => {
    const retained = lot(11, {saved_bid_board: board("200"), source: "Invaluable"});
    const source = lot(20, {retained_saved_work: [retained], research_queue_selected: true});
    const original = JSON.stringify(source), context = page(source);
    let root;
    if (surface === "catalog") root = context.run("galleryCard(source, 0)");
    if (surface === "sidebar") { context.run("renderSidebarLots([source])"); root = context.list; }
    if (surface === "browser") { context.run("renderLotBrowser()"); root = context.lotBrowserCard; }
    if (surface === "archive") { context.run("renderResearchWorkspace()"); root = context.researchLotCard; }
    assert.equal(summaries(root).length, 1);
    assert.equal(summaries(root)[0].dataset.savedBidBoardLotId, "11");
    assert.equal(selections(root).length, 0);
    assert.equal(root.querySelector(".lot-board-provenance").href, retained.research_url);
    assert.equal(JSON.stringify(source), original);
    context.emit(retained, null);
    assert.equal(summaries(root).length, 0);
    assert.equal(selections(root).length, 1);
    assert.equal(selections(root)[0].querySelector("input").checked, true);
    assert.equal(context.requests.length, 0, "deletion display changes cannot clear or save a research selection");
  });
}

test("research selection returns only after the last direct or retained board is deleted", () => {
  const child = lot(11, {saved_bid_board: board("0")});
  const source = lot(20, {saved_bid_board: board(null), retained_saved_work: [child], research_queue_selected: true});
  const context = page(source), root = new Element(); context.mount(root);
  assert.equal(summaries(root).length, 2);
  context.emit(source, null);
  assert.equal(summaries(root).length, 1);
  assert.equal(selections(root).length, 0);
  context.emit(child, null);
  assert.equal(selections(root).length, 1);
  assert.equal(selections(root)[0].querySelector("input").checked, true);
  assert.equal(child.research_queue_selected, false);
});

test("new board hides selection, preference updates keep controls, deletion restores keyboard focus", () => {
  const source = lot(20), context = page(source), root = new Element(); context.mount(root);
  assert.equal(selections(root).length, 1);
  context.emit(source, board("100"));
  assert.equal(selections(root).length, 0);
  const saved = summaries(root)[0];
  context.emit(source, {...source.saved_bid_board, include_in_email: true});
  assert.equal(summaries(root)[0], saved, "email preferences must not discard focused controls");
  saved.querySelector("button").focus();
  context.emit(source, null);
  const input = selections(root)[0].querySelector("input");
  assert.equal(input.checked, false);
  assert.equal(context.document.activeElement, input);
});

test("cached Archive controls refresh without replacing pending research drafts", () => {
  const source = lot(20, {saved_bid_board: board("100")}), context = page(source);
  context.run("renderResearchWorkspace()");
  const content = context.researchLotCache.get("20");
  const draft = Object.assign(new Element("input"), {value: "unsaved research note"}); content.append(draft);
  context.researchLotCard.replaceChildren();
  const saved = summaries(content)[0];
  context.emit(source, {...board("225"), include_in_email: true});
  assert.equal(summaries(content)[0], saved, "cached card must update its existing controls");
  assert.equal(saved.summary.qualifying_bid, "225");
  assert.equal(saved.summary.include_in_email, true);
  context.emit(source, null);
  assert.equal(content.contains(draft), true);
  assert.equal(draft.value, "unsaved research note");
  assert.equal(selections(content).length, 1);
});

test("delete focus survives the browser blurring a disabled or hidden button", () => {
  const source = lot(20, {saved_bid_board: board("100")}), context = page(source), root = new Element(); context.mount(root);
  const origin = summaries(root)[0].querySelector("button");
  context.document.activeElement = context.document.body;
  context.emit(source, null, origin);
  assert.equal(context.document.activeElement, selections(root)[0].querySelector("input"));
});

for (const filter of ["bidboards", "qualifying"]) {
  test(`${filter} deletion moves focus to the active filter after removing the last matching card`, () => {
    const source = lot(20, {saved_bid_board: board("100")}), context = page(source);
    context.galleryFilter = filter;
    const card = context.run("galleryCard(source, 0)"); context.galleryGrid.append(card);
    const origin = summaries(card)[0].querySelector("button"); origin.focus();
    context.refreshCards = () => context.galleryGrid.replaceChildren();
    context.emit(source, null, origin);
    assert.equal(context.cardRefreshes, 1);
    assert.equal(context.document.activeElement, context.galleryFilters.children[0]);
    assert.equal(context.document.activeElement.dataset.galleryFilter, filter);
  });
}

test("filtered deletion restores focus inside a card that retains another saved board", () => {
  const retained = lot(11, {saved_bid_board: board("200")});
  const source = lot(20, {saved_bid_board: board("100"), retained_saved_work: [retained]}), context = page(source);
  context.galleryFilter = "bidboards";
  context.galleryGrid.append(context.run("galleryCard(source, 0)"));
  const origin = summaries(context.galleryGrid)[0].querySelector("button"); origin.focus();
  context.refreshCards = () => context.galleryGrid.replaceChildren(context.run("galleryCard(source, 0)"));
  context.emit(source, null, origin);
  assert.equal(context.document.activeElement, summaries(context.galleryGrid)[0].querySelector("button"));
  assert.equal(selections(context.galleryGrid).length, 0);
});

test("retained research uses canonical board ownership and updates its independent payload", () => {
  const child = lot(11, {saved_bid_board: board("100"), research_queue_selected: true});
  const canonical = lot(20, {retained_saved_work: [child]});
  const retained = {...child, retained_listing: {canonical_id: 20, canonical_url: "/current", source: "Invaluable"}};
  const context = page(canonical, retained); context.run("renderResearchWorkspace()");
  assert.equal(selections(context.researchLotCard).length, 0);
  context.emit(child, null);
  assert.equal(retained.saved_bid_board, null);
  assert.equal(selections(context.researchLotCard)[0].querySelector("input").checked, true);
});

test("retained source controls respect a board saved on its current canonical listing", () => {
  const child = lot(11, {research_queue_selected: true});
  const canonical = lot(20, {saved_bid_board: board("200"), retained_saved_work: [child]});
  const retained = {...child, retained_listing: {canonical_id: 20}};
  const context = page(canonical, retained), root = new Element(); context.mount(root, retained);
  assert.equal(selections(root).length, 0);
  assert.equal(summaries(root)[0].dataset.savedBidBoardLotId, "20");
  context.emit(canonical, null);
  assert.equal(selections(root)[0].querySelector("input").checked, true);
  assert.equal(canonical.research_queue_selected, false);
});
