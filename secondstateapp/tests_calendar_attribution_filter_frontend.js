// Run with node --test. Exercise the production attribution filter and URL behavior.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const CalendarArtists = require("./static/secondstateapp/calendar_artists.js");
const CalendarCurrency = require("./static/secondstateapp/calendar_currency.js");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function declaration(name) {
  const start = template.indexOf(`  const ${name} =`);
  assert(start >= 0, `Missing production function: ${name}`);
  let depth = 0, quote = "", escaped = false;
  for (let i = start; i < template.length; i += 1) {
    const character = template[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
      continue;
    }
    if (["\"", "'", "`"].includes(character)) { quote = character; continue; }
    if ("({[".includes(character)) depth += 1;
    if (")}]".includes(character)) depth -= 1;
    if (character === ";" && depth === 0) return template.slice(start, i + 1);
  }
  throw new Error(`Unterminated production function: ${name}`);
}
function between(start, end) {
  const first = template.indexOf(start);
  const last = template.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `Missing production snippet: ${start}`);
  return template.slice(first, last);
}

class Element {
  constructor(tag = "div") {
    Object.assign(this, {tag, children: [], attributes: {}, dataset: {}, hidden: false, events: {}});
    this._text = "";
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(node => node.textContent || "").join(""); }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.events[name] = callback; }
  focus() { this.focused = true; }
  querySelectorAll() { return []; }
}

const day = "2026-11-18";
const lot = (id, overrides = {}) => ({
  id, artist: `Artist ${id}`, artist_sort_key: `artist ${id}`, title: `Work ${id}`,
  auction_house: "Phillips", oliver_house: true, currency: "USD", attribution_label: "",
  lot_number: String(id), time: "Time TBA", estimate_low: String(id + 1), ...overrides,
});
function page(lots, view = "catalog") {
  const elements = new Map();
  const listeners = new Map();
  const monthLinks = [{href: "https://secondstate.art/calendar/?month=2026-12"}];
  const context = vm.createContext({
    URL, URLSearchParams, data: {[day]: lots}, selectedDay: day, activeView: view,
    researchScope: "", researchIndex: 0, researchLook: "dossier", restoringHistory: false,
    galleryFilter: "all", galleryHideAttributed: false, galleryVisibleCount: 24,
    galleryArtistsDay: "", galleryArtistsExpanded: false,
    oliverHouseNames: ["Phillips", "Bonhams"],
    window: {
      CalendarArtists, CalendarCurrency,
      location: {href: `https://secondstate.art/calendar/?month=2026-11&day=${day}&view=${view}`, pathname: "/calendar/", origin: "https://secondstate.art", search: ""},
      history: {state: {}, replaceState(state, _title, url) { this.state = state; this.url = String(url); }},
      addEventListener: (name, callback) => listeners.set(name, callback),
    },
    document: {
      createElement: tag => new Element(tag),
      getElementById: id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
      },
      querySelectorAll: selector => selector === ".month-nav a" ? monthLinks : [],
    },
    gallerySort: Object.assign(new Element("select"), {value: "catalog"}),
    galleryArtistSort: Object.assign(new Element("select"), {value: "count_desc"}),
    galleryGrid: new Element(), galleryMore: new Element(), gallerySortNote: new Element(),
    galleryDescription: new Element(), galleryResults: new Element(), galleryCatalog: new Element(),
    galleryFilters: new Element(), galleryHouseFilters: new Element(), galleryHousesSummary: new Element(),
    gallerySendLaunch: new Element("button"), galleryAttributionToggle: new Element("button"),
    galleryAttributionStatus: new Element(),
    galleryArtists: Object.assign(new Element(), {dataset: {timeZone: "America/New_York"}}),
    galleryArtistSummary: new Element(), galleryArtistList: new Element(), galleryArtistsMore: new Element(),
    galleryArtistClear: new Element(), researchWorkspace: new Element(), researchLookButtons: [],
    researchTitle: new Element(), calendarViewToggle: new Element(), dayButtons: [],
    galleryCard: (source, index) => ({id: source.id, index}),
    chooseGalleryArtist() {}, loadCurrencyPrices() {},
    appendText(parent, tag, className, text) {
      const element = Object.assign(new Element(tag), {className, textContent: text});
      return parent.appendChild(element);
    },
  });
  vm.runInContext(["isGalleryView", "inOliverScope", "dayLots"].map(declaration).join("\n"), context);
  vm.runInContext(between("  const galleryPrice =", "  const renderGalleryFilters ="), context);
  vm.runInContext(["renderGalleryFilters", "renderGalleryArtists", "renderGalleryCards", "galleryResearchUrl", "updateCalendarLocation"].map(declaration).join("\n"), context);
  context.run = expression => vm.runInContext(expression, context);
  context.ids = expression => Array.from(context.run(expression), source => source.id);
  context.visible = () => Array.from(context.run("visibleGalleryLots()"), entry => ({id: entry.lot.id, index: entry.index}));
  context.render = () => context.run("renderGalleryFilters(); renderGalleryArtists(); renderGalleryCards()");
  context.listeners = listeners;
  context.monthLinks = monthLinks;
  return context;
}

test("the toggle hides only the authoritative After and Attributed to labels", () => {
  const lots = [lot(1, {attribution_label: "After"}), lot(2, {attribution_label: "Attributed to"}),
    lot(3, {title: "After the Party"}), lot(4, {attribution_label: undefined}), lot(5, {attribution_label: "Unknown"})];
  const before = JSON.stringify(lots);
  const p = page(lots);
  assert.deepEqual(p.visible().map(entry => entry.id), [1, 2, 3, 4, 5]);
  p.galleryHideAttributed = true;
  assert.deepEqual(p.visible(), [{id: 3, index: 2}, {id: 4, index: 3}, {id: 5, index: 4}]);
  assert.deepEqual(p.ids("dayLots()"), [1, 2, 3, 4, 5], "research scope must still retain every lot");
  p.galleryHideAttributed = false;
  assert.deepEqual(p.visible().map(entry => entry.id), [1, 2, 3, 4, 5]);
  assert.equal(JSON.stringify(lots), before);
});

for (const view of ["catalog", "oliver"]) {
  test(`${view} composes attribution with house, artist, tray and Bid Boards while retaining research indices`, () => {
    const lots = [
      lot(1, {attribution_label: "After", email_tray_selected: true, saved_bid_board: {qualifies: true}}),
      lot(2, {artist: "Miro, Joan", email_tray_selected: true, saved_bid_board: {qualifies: false}}),
      lot(3, {auction_house: "Bonhams", artist: "Miro, Joan", attribution_label: "Attributed to"}),
      lot(4, {auction_house: "Bonhams", artist: "Miro, Joan", saved_bid_board: {qualifies: null}}),
      lot(5, {auction_house: "Other", oliver_house: false, email_tray_selected: true}),
    ];
    const before = JSON.stringify(lots);
    const p = page(lots, view);
    p.galleryHideAttributed = true;
    const expected = {all: view === "oliver" ? [2, 4] : [2, 4, 5], tray: view === "oliver" ? [2] : [2, 5], bidboards: [2, 4], "house:Bonhams": [4]};
    expected[`artist:${CalendarArtists.artistKey(lots[1])}`] = [2, 4];
    for (const [filter, ids] of Object.entries(expected)) {
      p.galleryFilter = filter;
      assert.deepEqual(p.visible().map(entry => entry.id), ids, filter);
      for (const entry of p.visible()) assert.equal(p.run("dayLots()")[entry.index], lots.find(source => source.id === entry.id));
    }
    p.galleryFilter = "all";
    p.gallerySort.value = "lot_desc";
    assert.deepEqual(p.visible().map(entry => entry.id), [...expected.all].reverse());
    assert.equal(JSON.stringify(lots), before, "hiding must preserve saved selections and bid boards");
  });
}

test("artist summaries and filter counts reflect browsable lots with an explicit hidden count", () => {
  const p = page([lot(1, {attribution_label: "After", email_tray_selected: true}),
    lot(2, {artist: "Miro, Joan", email_tray_selected: true}),
    lot(3, {auction_house: "Bonhams", attribution_label: "Attributed to", saved_bid_board: {qualifies: true}})]);
  p.galleryHideAttributed = true;
  p.render();
  const filters = Object.fromEntries(p.galleryFilters.children.map(button => [button.dataset.galleryFilter, button.children[1].textContent]));
  assert.deepEqual(filters, {all: "1", tray: "1", bidboards: "0"});
  assert.equal(p.galleryHouseFilters.children.length, 1);
  assert.equal(p.galleryArtistSummary.textContent, "1 artist · 1 watched lot");
  assert.equal(p.galleryAttributionToggle.attributes["aria-pressed"], "true");
  assert.equal(p.galleryAttributionStatus.hidden, false);
  assert.match(p.galleryAttributionStatus.textContent, /2 After \/ Attributed works hidden/);
  assert.match(p.galleryAttributionStatus.textContent, /Saved selections are kept/);
  p.galleryHideAttributed = false;
  p.render();
  assert.equal(p.galleryAttributionToggle.attributes["aria-pressed"], "false");
  assert.equal(p.galleryAttributionStatus.hidden, true);
  assert.equal(p.galleryAttributionStatus.textContent, "", "an inactive toggle must not announce hidden works");
  assert.equal(p.galleryArtistSummary.textContent, "3 artists · 3 watched lots");
});

test("all-hidden results explain how to restore works and recover without data loss", () => {
  const p = page([lot(1, {attribution_label: "After"}), lot(2, {attribution_label: "Attributed to"})]);
  p.galleryHideAttributed = true;
  p.render();
  assert.equal(p.galleryResults.textContent, "0 watched lots");
  assert.equal(p.galleryMore.hidden, true);
  assert.match(p.galleryGrid.textContent, /After & Attributed/);
  assert.match(p.galleryGrid.textContent, /Try showing After & Attributed works or changing the selected filter/);
  p.galleryHideAttributed = false;
  p.render();
  assert.deepEqual(p.galleryGrid.children.map(card => card.id), [1, 2]);
  assert.equal(p.galleryResults.textContent, "Showing 2 of 2 watched lots");
});

test("Show more paginates the filtered sequence while retaining original card indices", () => {
  const lots = Array.from({length: 90}, (_, index) => lot(index, {attribution_label: index % 3 === 0 ? "After" : ""}));
  const p = page(lots);
  p.galleryHideAttributed = true;
  p.render();
  assert.equal(p.galleryGrid.children.length, 24);
  assert.equal(p.galleryMore.hidden, false);
  p.galleryVisibleCount += 24;
  p.render();
  assert.equal(p.galleryGrid.children.length, 48);
  for (const card of p.galleryGrid.children) assert.equal(lots[card.index].id, card.id);
  p.galleryVisibleCount += 24;
  p.render();
  assert.equal(p.galleryGrid.children.length, 60);
  assert.equal(p.galleryMore.hidden, true);
});

test("attribution URL state survives month and research links independently of tray and artist filters", () => {
  const p = page([lot(1, {email_tray_selected: true})], "oliver");
  p.galleryHideAttributed = true;
  p.galleryFilter = "tray";
  p.run("updateCalendarLocation()");
  let url = new URL(p.window.history.url);
  assert.equal(url.searchParams.get("hide_attributed"), "1");
  assert.equal(url.searchParams.get("filter"), "tray");
  assert.equal(new URL(p.monthLinks[0].href).searchParams.get("hide_attributed"), "1");
  const research = new URL(p.run("galleryResearchUrl(dayLots()[0])"));
  assert.equal(research.searchParams.get("hide_attributed"), "1");
  assert.equal(research.searchParams.get("scope"), "oliver");
  assert.equal(research.searchParams.get("lot"), "1");
  p.galleryFilter = `artist:${CalendarArtists.artistKey(p.data[day][0])}`;
  p.run("updateCalendarLocation()");
  url = new URL(p.window.history.url);
  assert.equal(url.searchParams.get("hide_attributed"), "1");
  assert.ok(url.searchParams.has("artist"));
  p.galleryHideAttributed = false;
  p.run("updateCalendarLocation()");
  assert.equal(new URL(p.window.history.url).searchParams.has("hide_attributed"), false);
  assert.equal(new URL(p.monthLinks[0].href).searchParams.has("hide_attributed"), false);
  assert.equal(new URL(p.run("galleryResearchUrl(dayLots()[0])")).searchParams.has("hide_attributed"), false);
});

test("clicking the actual toggle resets pagination, composes with the current filter and restores selected lots", () => {
  const lots = [lot(1, {attribution_label: "After", email_tray_selected: true}), lot(2, {email_tray_selected: true})];
  const before = JSON.stringify(lots);
  const p = page(lots);
  p.renderGalleryCatalog = () => p.render();
  p.galleryFilter = "tray";
  p.galleryVisibleCount = 72;
  vm.runInContext(between('  galleryAttributionToggle.addEventListener("click"', '  gallerySort.addEventListener("change"'), p);
  p.galleryAttributionToggle.events.click();
  assert.equal(p.galleryVisibleCount, 24);
  assert.equal(p.galleryFilter, "tray");
  assert.deepEqual(p.galleryGrid.children.map(card => card.id), [2]);
  assert.equal(p.galleryAttributionToggle.attributes["aria-pressed"], "true");
  assert.equal(new URL(p.window.history.url).searchParams.get("hide_attributed"), "1");
  p.galleryAttributionToggle.events.click();
  assert.deepEqual(p.galleryGrid.children.map(card => card.id), [1, 2]);
  assert.equal(p.galleryAttributionToggle.attributes["aria-pressed"], "false");
  assert.equal(new URL(p.window.history.url).searchParams.has("hide_attributed"), false);
  assert.equal(JSON.stringify(lots), before);
});

test("initial URL loading accepts the explicit hide setting and defaults to showing all works", () => {
  const initialization = between("  const initialParams =", "  const requestedView =");
  for (const [search, expected] of [["?hide_attributed=1", true], ["?hide_attributed=0", false], ["?hide_attributed=true", false], ["", false]]) {
    const p = page([lot(1, {attribution_label: "After"}), lot(2)]);
    p.window.location.search = search;
    vm.runInContext(initialization, p);
    assert.equal(p.galleryHideAttributed, expected);
    assert.deepEqual(p.visible().map(entry => entry.id), expected ? [2] : [1, 2]);
  }
});

test("Back and Forward restore the hide state before rendering without changing stored selections", () => {
  const lots = [lot(1, {attribution_label: "After", email_tray_selected: true}), lot(2)];
  const before = JSON.stringify(lots);
  const p = page(lots);
  p.setCalendarView = view => { p.activeView = view || "calendar"; p.render(); };
  p.showDay = value => { p.selectedDay = value; };
  vm.runInContext(between('  window.addEventListener("popstate"', '  researchPrevious.addEventListener("click"'), p);
  for (const [query, ids, pressed] of [["&hide_attributed=1", [2], "true"], ["", [1, 2], "false"], ["&hide_attributed=1", [2], "true"]]) {
    p.window.location.search = `?month=2026-11&day=${day}&view=catalog${query}`;
    p.window.location.href = `https://secondstate.art/calendar/${p.window.location.search}`;
    p.listeners.get("popstate")();
    assert.deepEqual(p.galleryGrid.children.map(card => card.id), ids);
    assert.equal(p.galleryAttributionToggle.attributes["aria-pressed"], pressed);
    assert.equal(p.restoringHistory, false);
  }
  assert.equal(JSON.stringify(lots), before);
});

test("retained saved boards and tray selections keep a single canonical card discoverable in filters", () => {
  const lots = [lot(1, {retained_saved_work: [
    {id: 10, saved_bid_board: true, email_tray_selected: true},
    {id: 11, saved_bid_board: true, email_tray_selected: false},
  ]}), lot(2)];
  const before = JSON.stringify(lots);
  const p = page(lots);
  p.render();
  const counts = Object.fromEntries(p.galleryFilters.children.map(button => [button.dataset.galleryFilter, button.children[1].textContent]));
  assert.equal(counts.bidboards, "1");
  assert.equal(counts.tray, "1");
  for (const filter of ["bidboards", "tray"]) {
    p.galleryFilter = filter;
    assert.deepEqual(p.visible().map(entry => entry.id), [1]);
  }
  assert.equal(JSON.stringify(lots), before);
});

test("only explicit retained research replaces its canonical slot and preserves original action IDs", () => {
  const lots = [lot(1), lot(2)];
  const p = page(lots);
  const retained = lot(10, {retained_listing: {canonical_id: 1}, artprice_analysis_url: "/calendar/lots/10/artprice-analysis/"});
  p.retainedResearchLot = retained;
  p.retainedResearchId = 10;
  p.activeView = "research";
  assert.deepEqual(p.ids("dayLots()"), [10, 2]);
  assert.equal(p.run("dayLots()[0]"), retained);
  assert.equal(p.run("dayLots()[0].artprice_analysis_url"), "/calendar/lots/10/artprice-analysis/");
  p.researchIndex = 0;
  p.run("updateCalendarLocation()");
  assert.equal(new URL(p.window.history.url).searchParams.get("lot"), "10");
  p.researchIndex = 1;
  p.run("updateCalendarLocation()");
  assert.equal(new URL(p.window.history.url).searchParams.get("lot"), "2");
  p.activeView = "catalog";
  assert.deepEqual(p.ids("dayLots()"), [1, 2]);
  p.activeView = "research";
  p.retainedResearchId = null;
  assert.deepEqual(p.ids("dayLots()"), [1, 2]);
  assert.deepEqual(lots.map(source => source.id), [1, 2]);
});
