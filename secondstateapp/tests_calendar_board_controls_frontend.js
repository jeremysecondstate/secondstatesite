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
  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
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
  const window = {CalendarArtists: require("./static/secondstateapp/calendar_artists.js"), document, fetch: (...args) => {requests.push(args); throw new Error("Rendering must not write selections");},
    addEventListener: (event, callback) => listeners.set(event, callback),
    SavedBidBoard: {mountSummary(root, {lot: owner}) {
      root.className = "sb-catalog-summary";
      root.dataset.savedBidBoardLotId = String(owner.id);
      root.append(Object.assign(new Element("button"), {textContent: "Delete Bid Board"}));
      root.updateSavedBoard = summary => {root.summary = summary;};
      root.updateSavedBoard(owner.saved_bid_board);
    }},
  };
  const context = vm.createContext({window, document, galleryArtists: {dataset: {timeZone: "America/Los_Angeles"}}, data: {"2026-11-04": [source]}, retainedResearchLot,
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
    + block("  const hasSelectedOrSavedResearch =", "  const matchesGalleryAttribution =")
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

test("queue selections refresh Bid Boards counts and return focus to the tab when a card leaves", async () => {
  const source = lot(20), context = page(source);
  context.window.fetch = async (_, {body}) => ({ok: true, json: async () => ({ok: true, selected: JSON.parse(body).selected})});
  const card = context.run("galleryCard(source, 0)"); context.galleryGrid.append(card);
  const checkbox = selections(card)[0].querySelector("input");
  checkbox.checked = true;
  checkbox.focus();
  await checkbox.events.change();
  assert.equal(context.filterRefreshes, 1);
  assert.equal(context.cardRefreshes, 0, "adding from All lots preserves the visible card");
  assert.equal(context.document.activeElement, checkbox);
  assert.equal(source.research_queue_selected, true);

  context.galleryFilter = "bidboards";
  context.refreshCards = () => context.galleryGrid.replaceChildren();
  checkbox.checked = false;
  await checkbox.events.change();
  assert.equal(context.filterRefreshes, 2);
  assert.equal(context.cardRefreshes, 1);
  assert.equal(context.document.activeElement, context.galleryFilters.children[0]);
  assert.equal(context.document.activeElement.dataset.galleryFilter, "bidboards");
  assert.equal(source.research_queue_selected, false);
});

test("saving a retained listing's selection updates its canonical catalog membership", async () => {
  const child = lot(11);
  const canonical = lot(20, {retained_saved_work: [child]});
  const retained = {...child, retained_listing: {canonical_id: 20}};
  const context = page(canonical, retained);
  context.activeView = "research";
  context.window.fetch = async () => ({ok: true, json: async () => ({ok: true, selected: true})});
  const root = new Element(); context.mount(root, retained);
  const checkbox = selections(root)[0].querySelector("input");
  checkbox.checked = true;
  await checkbox.events.change();
  assert.equal(retained.research_queue_selected, true);
  assert.equal(child.research_queue_selected, true);
  assert.equal(canonical.research_queue_selected, false);
  assert.equal(context.run("lotHasBidBoardResearch(source)"), true);
  assert.equal(context.filterRefreshes, 0);
});

test("sidebar pages append all lots in order while keeping the existing editors", () => {
  const source = lot(1), context = page(source);
  context.lots = Array.from({length: 50}, (_, i) => lot(i + 1));
  context.run("renderSidebarLots(lots)");
  const rows = () => context.list.querySelectorAll("article");
  const first = rows()[0];
  first.draft = "unsaved";
  assert.equal(rows().length, 24);
  const more = context.list.children.at(-1);
  assert.match(more.textContent, /24 of 50/);
  more.events.click();
  assert.equal(rows().length, 48);
  assert.equal(rows()[0], first);
  assert.equal(first.draft, "unsaved");
  assert.equal(currentDocument.activeElement, rows()[24]);
  assert.match(more.textContent, /Show 2 more/);
  more.events.click();
  assert.equal(rows().length, 50);
  assert.equal(context.list.contains(more), false);
  assert.deepEqual(rows().map(row => row.querySelector(".lot-title").textContent), context.lots.map(item => item.title));
});

test("closed sidebar research mounts once on opening, while quick research opens immediately", () => {
  const source = lot(4), context = page(source);
  Object.assign(context, {
    liveartAnalysisCache: new Map(), artpriceAnalysisCache: new Map([["4", {}]]),
    artpriceAnalysisInstances: new Map(), liveartAnalysisInstances: new Map(),
    registerLotInstance() {}, builds: 0, loads: 0,
    buildArtpriceAnalysisPanel() { context.builds++; return () => context.loads++; },
  });
  context.run(block("  const appendArtpriceAnalysis =", "  const buildArtpriceAnalysisPanel ="));
  context.run("appendArtpriceAnalysis(list, source)");
  const details = context.list.children[0];
  assert.equal(context.builds, 0);
  assert.equal(details.querySelector(".artprice-analysis-badge").textContent, "Saved");
  details.open = true;
  details.events.toggle();
  details.open = false;
  details.events.toggle();
  details.open = true;
  details.events.toggle();
  assert.equal(context.builds, 1);
  assert.equal(context.loads, 2);
  context.run("appendArtpriceAnalysis(list, source, {quick: true})");
  assert.equal(context.list.children[1].open, true);
  assert.equal(context.builds, 2);
  assert.equal(context.loads, 3);
});

function useResearchNavigation(context) {
  Object.assign(context, {URL, URLSearchParams, researchScope: "", researchLook: "dossier",
    galleryHideAttributed: false, writeGalleryOrganization() {}});
  context.window.location = {pathname: "/calendar/", origin: "https://secondstate.art"};
  context.run(block("  const inOliverScope =", "  // Filtering shares")
    + block("  const galleryResearchUrl =", "  const appendRetainedSavedWork ="));
}

const ownerViews = [["calendar", ""], ["catalog", ""], ["oliver-calendar", ""], ["oliver", ""],
  ["research", "oliver"], ["research", ""]];
function assertResearchDestination(link, id, scope) {
  const url = new URL(link.href);
  assert.equal(url.origin, "https://secondstate.art");
  assert.equal(url.pathname, "/calendar/");
  assert.equal(url.searchParams.get("view"), "research");
  assert.equal(url.searchParams.get("lot"), String(id));
  assert.equal(url.searchParams.get("day"), "2026-11-04");
  assert.equal(url.searchParams.get("look"), "workbench");
  assert.equal(url.searchParams.get("scope"), scope || null);
}

test("retained board and research links follow the current owner after switching views", () => {
  const saved = lot(11, {saved_bid_board: board("200")});
  const researched = lot(12, {email_tray_selected: true});
  const source = lot(20, {retained_saved_work: [saved, researched]});
  const before = JSON.stringify(source), context = page(source);
  useResearchNavigation(context);
  for (const [view, scope] of ownerViews) {
    context.activeView = view;
    context.researchScope = scope;
    const root = new Element(); context.mount(root);
    const expectedScope = view.startsWith("oliver") ? "oliver" : scope;
    assertResearchDestination(root.querySelector(".lot-board-provenance"), 11, expectedScope);
    assertResearchDestination(root.querySelector(".lot-retained-link"), 12, expectedScope);
  }
  assert.equal(JSON.stringify(source), before, "navigation must not change saved records");
});

test("cached retained research keeps the current owner when returning to its canonical lot", () => {
  const child = lot(11, {saved_bid_board: board("200")});
  const other = lot(12, {email_tray_selected: true});
  const canonical = lot(20, {retained_saved_work: [child, other]});
  const retained = {...child, retained_listing: {canonical_id: 20, source: "Drouot", canonical_house: "Phillips",
    canonical_url: "/calendar/?view=research&lot=20", canonical_source_url: "https://example.com/lot/20"}};
  const before = JSON.stringify([canonical, retained]), context = page(canonical, retained);
  useResearchNavigation(context);
  context.activeView = "research";
  let cached;
  for (const scope of ["oliver", "", "oliver"]) {
    context.researchScope = scope;
    context.run("renderResearchWorkspace()");
    const content = context.researchLotCache.get("11");
    if (cached) assert.equal(content, cached, "scope changes preserve the cached research form");
    cached = content;
    assertResearchDestination(content.querySelector(".lot-canonical-link"), 20, scope);
    assertResearchDestination(content.querySelector(".lot-retained-link"), 12, scope);
    assert.equal(content.querySelectorAll(".lot-auction-link")[1].href, "https://example.com/lot/20");
  }
  assert.equal(JSON.stringify([canonical, retained]), before);
});

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

test("Catalog market review links open the source that owns each review, with or without other saved work", () => {
  const children = [
    lot(11, {source: "Drouot", has_market_review: true}),
    lot(12, {source: "Forum", has_market_review: true, saved_bid_board: board("100")}),
    lot(13, {source: "Invaluable", email_tray_selected: true}),
  ];
  const canonical = lot(20, {retained_saved_work: children});
  const context = page(canonical);
  const card = context.run("galleryCard(source, 0)");
  const reviewLinks = card.querySelectorAll("a").filter(link => /market review/i.test(link.textContent));
  assert.deepEqual(reviewLinks.map(link => link.href).sort(), ["/research/11", "/research/12"]);
  for (const link of reviewLinks) assert.match(link.attributes["aria-label"], /market review/i);
  assert.equal(card.querySelector("details"), null);
});

test("Archive shows the retained review status, currency of the evidence, and original citations", () => {
  for (const [status, label, current] of [["clear", "Clear", true], ["uncertain", "Inconclusive", true], ["mismatch", "Mismatch", false]]) {
    const child = lot(11, {source: "Drouot", has_market_review: true});
    const canonical = lot(20, {retained_saved_work: [child]});
    const retained = {...child, retained_listing: {canonical_id: 20, source: "Drouot"},
      retained_market_review: {status, current, reason: "Source-specific catalog evidence.", sources: [
        {label: "Original catalog", url: "https://drouot.example/lot/11"},
      ]}};
    const context = page(canonical, retained);
    context.run("renderResearchWorkspace()");
    const details = context.researchLotCard.querySelector("details");
    assert.ok(details);
    const summary = details.querySelector("summary").textContent;
    assert.ok(summary.includes(`Drouot market review · ${label}`));
    assert.equal(/out of date/i.test(summary), !current);
    assert.ok(details.querySelectorAll("p").some(p => p.textContent === retained.retained_market_review.reason));
    assert.equal(details.querySelector("a").href, retained.retained_market_review.sources[0].url);
  }
});
