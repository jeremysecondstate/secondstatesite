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
  const catalogLinks = [
    {href: "https://secondstate.art/calendar/?month=2026-11&day=2026-11-05&view=catalog"},
    {href: "https://secondstate.art/calendar/?month=2026-12&day=2026-12-01&view=catalog&hide_attributed=1"},
  ];
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
      querySelectorAll: selector => selector === ".month-nav a" ? monthLinks
        : selector === ".day-catalog-link" ? catalogLinks : [],
    },
    galleryGroup: Object.assign(new Element("select"), {value: ""}),
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
  vm.runInContext(["hasQualifyingBid", "savedBoardFilterMembership", "isGalleryView", "inOliverScope", "dayLots"].map(declaration).join("\n"), context);
  vm.runInContext(between("  const galleryPrice =", "  const renderGalleryFilters ="), context);
  vm.runInContext(["renderGalleryFilters", "renderGalleryArtists", "renderGalleryCards", "galleryResearchUrl", "updateCalendarLocation"].map(declaration).join("\n"), context);
  context.run = expression => vm.runInContext(expression, context);
  context.ids = expression => Array.from(context.run(expression), source => source.id);
  context.visible = () => Array.from(context.run("visibleGalleryLots()"), entry => ({id: entry.lot.id, index: entry.index}));
  context.render = () => context.run("renderGalleryFilters(); renderGalleryArtists(); renderGalleryCards()");
  context.listeners = listeners;
  context.monthLinks = monthLinks;
  context.catalogLinks = catalogLinks;
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
  assert.deepEqual(filters, {all: "1", tray: "1", bidboards: "0", qualifying: "0"});
  assert.equal(p.galleryHouseFilters.children.length, 2, "All auction houses plus the visible house");
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

for (const view of ["catalog", "oliver", "oliver-calendar", "calendar", "research"]) {
  test(`${view} day catalog links preserve attribution browsing state and their own destination`, () => {
    const lots = [lot(1, {attribution_label: "After", email_tray_selected: true}),
      lot(2, {saved_bid_board: {qualifies: true}})];
    const before = JSON.stringify(lots);
    const p = page(lots, view);
    const destinations = p.catalogLinks.map(link => {
      const url = new URL(link.href);
      url.searchParams.delete("hide_attributed");
      url.searchParams.set("view", ["oliver", "oliver-calendar"].includes(view) ? "oliver" : "catalog");
      return url.href;
    });
    for (const filter of ["house:Phillips", "artist:artist 1", "tray", "bidboards"]) {
      p.galleryFilter = filter;
      for (const hidden of [true, false, true]) {
        p.galleryHideAttributed = hidden;
        p.run("updateCalendarLocation()");
        p.catalogLinks.forEach((link, index) => {
          const url = new URL(link.href);
          assert.equal(url.searchParams.get("hide_attributed"), hidden ? "1" : null);
          url.searchParams.delete("hide_attributed");
          assert.equal(url.href, destinations[index], "retain the target day and catalog view without copying filters");
        });
        const destination = page(lots);
        destination.window.location.search = new URL(p.catalogLinks[0].href).search;
        vm.runInContext(between("  const initialParams =", "  const requestedView ="), destination);
        assert.deepEqual(destination.visible().map(entry => entry.id), hidden ? [2] : [1, 2]);
        assert.equal(p.galleryFilter, filter);
        assert.equal(JSON.stringify(lots), before, "navigation must preserve saved selections");
      }
    }
  });
}

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
    p.catalogLinks.forEach(link => assert.equal(new URL(link.href).searchParams.has("hide_attributed"), pressed === "true"));
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

test("qualifying bids use the saved ceiling, independently of the selected bid outcome", () => {
  const amounts = ["1542.61", 250, "0.00", 0, null, undefined, "", "  ", "NaN", "Infinity", Infinity, -1, "-0.01", true, {}, []];
  const lots = amounts.map((qualifying_bid, index) => lot(index + 1, {
    saved_bid_board: {qualifying_bid, qualifies: index >= 4, selected_bid: "9000.00", include_in_email: index % 2 === 0},
  }));
  lots.push(lot(50, {saved_bid_board: null}), lot(51, {saved_bid_board: {qualifies: true}}));
  const before = JSON.stringify(lots);
  const p = page(lots);
  assert.equal(p.galleryFilter, "all", "qualified-only browsing is opt-in");
  assert.equal(p.visible().length, lots.length);
  p.galleryFilter = "qualifying";
  assert.deepEqual(p.visible(), [{id: 1, index: 0}, {id: 2, index: 1}, {id: 3, index: 2}, {id: 4, index: 3}]);
  p.render();
  const button = p.galleryFilters.children.find(button => button.dataset.galleryFilter === "qualifying");
  assert.equal(button.children[1].textContent, "4");
  assert.equal(button.attributes["aria-pressed"], "true");
  assert.equal(JSON.stringify(lots), before, "filtering must not recalculate or change saved selections");
});

for (const view of ["catalog", "oliver"]) {
  test(`${view} qualifying bids compose with attribution hiding and retain original source actions`, () => {
    const lots = [
      lot(1, {attribution_label: "After", won_by_us: true, email_tray_selected: true,
        saved_bid_board: {qualifying_bid: "100.00", qualifies: false, qualifying_coverage_limited: true}}),
      lot(2, {saved_bid_board: {qualifying_bid: null, qualifies: true}}),
      lot(3, {retained_saved_work: [
        {id: 30, saved_bid_board: {qualifying_bid: "300.00", qualifies: false}, saved_bid_board_url: "/original/30/"},
        {id: 31, saved_bid_board: {qualifying_bid: "400.00", qualifies: true}, saved_bid_board_url: "/original/31/"},
      ]}),
      lot(4, {oliver_house: false, auction_house: "Other", saved_bid_board: {qualifying_bid: "200.00"}}),
    ];
    const before = JSON.stringify(lots);
    const p = page(lots, view);
    p.galleryFilter = "qualifying";
    p.renderGalleryCatalog = () => p.render();
    p.render();
    const expected = view === "oliver" ? [1, 3] : [1, 3, 4];
    assert.deepEqual(p.visible().map(entry => entry.id), expected);
    const count = () => p.galleryFilters.children.find(button => button.dataset.galleryFilter === "qualifying").children[1].textContent;
    assert.equal(count(), String(expected.length), "multiple retained boards count as one canonical card");
    vm.runInContext(between('  galleryAttributionToggle.addEventListener("click"', '  gallerySort.addEventListener("change"'), p);
    p.galleryAttributionToggle.events.click();
    assert.equal(p.galleryFilter, "qualifying");
    assert.deepEqual(p.visible().map(entry => entry.id), expected.filter(id => id !== 1));
    assert.equal(count(), String(expected.length - 1));
    p.galleryAttributionToggle.events.click();
    assert.deepEqual(p.visible().map(entry => entry.id), expected);
    for (const {id, index} of p.visible()) assert.equal(p.run("dayLots()")[index].id, id);
    assert.equal(JSON.stringify(lots), before);
  });
}

test("qualifying filter is carried on month and day catalog links and removed after choosing all lots", () => {
  const p = page([lot(1, {saved_bid_board: {qualifying_bid: "100.00"}})]);
  p.galleryFilter = "qualifying";
  p.galleryHideAttributed = true;
  p.run("updateCalendarLocation()");
  for (const href of [p.window.history.url, ...p.monthLinks.map(link => link.href), ...p.catalogLinks.map(link => link.href)]) {
    const url = new URL(href);
    assert.equal(url.searchParams.get("filter"), "qualifying");
    assert.equal(url.searchParams.get("hide_attributed"), "1");
  }
  p.galleryFilter = "all";
  p.run("updateCalendarLocation()");
  for (const href of [p.window.history.url, ...p.monthLinks.map(link => link.href), ...p.catalogLinks.map(link => link.href)]) {
    assert.equal(new URL(href).searchParams.has("filter"), false);
  }
});

const organizedLots = () => [
  lot(1, {auction_house: "Z House", oliver_house: false, artist_sort_key: "a", lot_number: "1", event_at: `${day}T00:00:00Z`, estimate_low: "1", saved_bid_board: {qualifying_bid: "100"}}),
  lot(2, {artist_sort_key: "z", lot_number: "100", event_at: `${day}T18:00:00Z`, estimate_low: "900", saved_bid_board: {qualifying_bid: "300", qualifies: false}}),
  lot(3, {auction_house: "Bonhams", artist_sort_key: "a", lot_number: "2", event_at: `${day}T15:00:00Z`, estimate_low: "90", retained_saved_work: [{id: 30, saved_bid_board: {qualifying_bid: "400"}, saved_bid_board_url: "/original/30/"}]}),
  lot(4, {artist_sort_key: "m", lot_number: "10A", event_at: null, estimate_low: null, saved_bid_board: {qualifying_bid: "0"}}),
  lot(5, {artist_sort_key: "a", lot_number: "3", event_at: `${day}T15:00:00Z`, estimate_low: "100", attribution_label: "After", saved_bid_board: {qualifying_bid: "500"}}),
  lot(6, {auction_house: "Bonhams", saved_bid_board: {qualifying_bid: null, qualifies: true}}),
  lot(7),
];

for (const view of ["catalog", "oliver"]) {
  test(`${view} qualifying sorts and house grouping preserve all canonical/retained identities`, () => {
    const lots = organizedLots(), before = JSON.stringify(lots), p = page(lots, view);
    p.galleryFilter = "qualifying";
    const expected = {
      catalog: [1, 2, 3, 4, 5], artist: [1, 3, 5, 4, 2], artist_desc: [2, 4, 1, 3, 5],
      house: [3, 2, 4, 5, 1], lot_asc: [1, 3, 5, 4, 2], lot_desc: [2, 4, 5, 3, 1],
      time_asc: [1, 3, 5, 2, 4], time_desc: [2, 3, 5, 1, 4],
      arrival_asc: [1, 3, 5, 2, 4], arrival_desc: [2, 5, 3, 1, 4],
      price_asc: [1, 3, 5, 2, 4], price_desc: [2, 5, 3, 1, 4],
    };
    for (const [sort, allIds] of Object.entries(expected)) {
      const ids = allIds.filter(id => view !== "oliver" || id !== 1);
      p.gallerySort.value = sort;
      p.run('galleryOrganization.group = ""');
      assert.deepEqual(p.visible().map(item => item.id), ids, sort);
      p.run('galleryOrganization.group = "house"');
      const grouped = [3, ...ids.filter(id => [2, 4, 5].includes(id)), ...(view === "catalog" ? [1] : [])];
      assert.deepEqual(p.visible().map(item => item.id), grouped, `${sort} within houses`);
      for (const item of p.visible()) assert.equal(p.run("dayLots()")[item.index].id, item.id);
    }
    p.render();
    assert.deepEqual(p.galleryGrid.children.filter(node => node.className === "day-gallery-house-heading").map(node => node.textContent),
      ["Bonhams · 1 lot", "Phillips · 3 lots", ...(view === "catalog" ? ["Z House · 1 lot"] : [])]);
    assert.equal(JSON.stringify(lots), before);
  });

  test(`${view} selecting a house retains qualifying and attribution filters with accurate house counts`, () => {
    const lots = organizedLots(), before = JSON.stringify(lots), p = page(lots, view);
    p.galleryFilter = "qualifying";
    p.galleryHideAttributed = true;
    p.render();
    const house = name => p.galleryHouseFilters.children.find(node => node.dataset.galleryFilter === `house:${name}`);
    assert.equal(house("Phillips").children[1].textContent, "2");
    assert.equal(house("Bonhams").children[1].textContent, "1", "unsuitable saved board is excluded from house count");
    house("Phillips").events.click();
    assert.equal(p.galleryFilter, "qualifying");
    assert.equal(p.galleryHideAttributed, true);
    assert.deepEqual(p.visible().map(item => item.id), [2, 4]);
    const counts = () => Object.fromEntries(p.galleryFilters.children.map(node => [node.dataset.galleryFilter, node.children[1].textContent]));
    assert.deepEqual(counts(), {all: "3", tray: "0", bidboards: "2", qualifying: "2"}, "top chips count prospective results within selected house and attribution state");
    p.galleryHideAttributed = false;
    p.render();
    assert.deepEqual(p.visible().map(item => item.id), [2, 4, 5]);
    assert.deepEqual(counts(), {all: "4", tray: "0", bidboards: "3", qualifying: "3"});
    house("Bonhams").events.click();
    assert.deepEqual(p.visible().map(item => item.id), [3], "retained board keeps canonical card");
    assert.deepEqual(counts(), {all: "2", tray: "0", bidboards: "2", qualifying: "1"});
    house("").events.click();
    assert.equal(p.galleryFilter, "qualifying");
    assert.deepEqual(p.visible().map(item => item.id), view === "oliver" ? [2, 3, 4, 5] : [1, 2, 3, 4, 5]);
    assert.equal(JSON.stringify(lots), before);
  });

  test(`${view} organization round-trips URL, month/day links and history without changing saved state`, () => {
    const lots = organizedLots(), before = JSON.stringify(lots), p = page(lots, view);
    const params = new URLSearchParams({house: "Phillips", group: "house", sort: "price_desc", hide_attributed: "1"});
    p.window.location.search = `?${params}`;
    vm.runInContext(between("  const initialParams =", "  const requestedView ="), p);
    p.galleryFilter = "qualifying";
    p.run("updateCalendarLocation()");
    for (const value of [p.window.history.url, ...p.monthLinks.map(x => x.href), ...p.catalogLinks.map(x => x.href)]) {
      const url = new URL(value);
      assert.equal(url.searchParams.get("sort"), "price_desc");
      assert.equal(url.searchParams.get("group"), "house");
      assert.equal(url.searchParams.get("house"), "Phillips");
      assert.equal(url.searchParams.get("filter"), "qualifying");
      assert.equal(url.searchParams.get("hide_attributed"), "1");
    }
    p.setCalendarView = value => { p.activeView = value || "calendar"; p.render(); };
    p.showDay = value => { p.selectedDay = value; };
    vm.runInContext(between('  window.addEventListener("popstate"', '  researchPrevious.addEventListener("click"'), p);
    for (const [sort, house, ids] of [["price_desc", "Phillips", [2, 4]], ["artist", "Bonhams", [3]], ["price_desc", "Phillips", [2, 4]]]) {
      p.window.location.search = `?day=${day}&view=${view}&filter=qualifying&hide_attributed=1&group=house&sort=${sort}&house=${house}`;
      p.listeners.get("popstate")();
      assert.equal(p.gallerySort.value, sort);
      assert.equal(p.galleryGroup.value, "house");
      assert.equal(p.run("galleryOrganization.house"), house);
      assert.deepEqual(p.visible().map(item => item.id), ids);
      assert.equal(p.restoringHistory, false);
    }
    p.run('restoreGalleryOrganization(new URLSearchParams("sort=invalid&group=invalid"))');
    assert.equal(p.gallerySort.value, "catalog");
    assert.equal(p.run("galleryOrganization.group"), "");
    assert.equal(p.run("galleryOrganization.house"), "");
    assert.equal(JSON.stringify(lots), before);
  });
}

test("grouped qualifying results sort the complete set before pagination and preserve stable ties", () => {
  const lots = Array.from({length: 70}, (_, index) => lot(index + 1, {
    auction_house: index % 2 ? "Phillips" : "Bonhams", estimate_low: String(100 - index),
    saved_bid_board: index % 3 === 0 ? null : {qualifying_bid: "100"},
  }));
  const p = page(lots), before = JSON.stringify(lots);
  p.galleryFilter = "qualifying";
  p.gallerySort.value = "price_asc";
  p.run('galleryOrganization.group = "house"');
  const expected = ["Bonhams", "Phillips"].flatMap(house => lots.filter(l => l.auction_house === house && l.saved_bid_board).reverse().map(l => l.id));
  p.render();
  assert.deepEqual(p.galleryGrid.children.filter(node => node.id).map(node => node.id), expected.slice(0, 24));
  assert.equal(p.galleryMore.hidden, false);
  p.galleryVisibleCount = 72;
  p.render();
  assert.deepEqual(p.galleryGrid.children.filter(node => node.id).map(node => node.id), expected);
  assert.equal(p.galleryMore.hidden, true);
  for (const node of p.galleryGrid.children.filter(node => node.id)) assert.equal(lots[node.index].id, node.id);
  assert.equal(JSON.stringify(lots), before);
});


const regionalLots = () => [
  lot(1, {sale_region: "us", attribution_label: "After", won_by_us: true, email_tray_selected: true, saved_bid_board: {qualifying_bid: "100"}}),
  lot(2, {sale_region: "us", email_tray_selected: true, saved_bid_board: {qualifying_bid: "0"}}),
  lot(3, {sale_region: "outside_us", auction_house: "Bonhams", email_tray_selected: true,
    retained_saved_work: [{id: 30, saved_bid_board: {qualifying_bid: "250"}, email_tray_selected: true, saved_bid_board_url: "/saved/30/"}]}),
  lot(4, {sale_region: "outside_us", attribution_label: "Attributed to"}),
  lot(5, {sale_region: "unknown", email_tray_selected: true, saved_bid_board: {qualifying_bid: "75"}}),
  lot(6),
  lot(7, {sale_region: "us", oliver_house: false, auction_house: "Other"}),
];
const regionButtons = p => p.document.getElementById("day-gallery-region-filters").children;
const selectRegion = (p, region) => regionButtons(p).find(button => button.dataset.saleRegion === region).events.click();
const regionCounts = p => Object.fromEntries(regionButtons(p).map(button => [button.dataset.saleRegion, button.children[1].textContent]));

for (const view of ["catalog", "oliver"]) {
  test(`${view} location browsing composes with attribution and preserves unknown lots and research indices`, () => {
    const lots = regionalLots(), before = JSON.stringify(lots), p = page(lots, view);
    p.render();
    assert.deepEqual(regionCounts(p), {"": view === "oliver" ? "6" : "7", us: view === "oliver" ? "2" : "3", outside_us: "2"});
    assert.equal(regionButtons(p)[0].attributes["aria-pressed"], "true");
    assert.match(p.document.getElementById("day-gallery-location-status").textContent, /2 lots have an unconfirmed sale location/);
    p.galleryHideAttributed = true;
    p.render();
    selectRegion(p, "us");
    assert.deepEqual(p.visible().map(x => x.id), view === "oliver" ? [2] : [2, 7]);
    assert.match(p.galleryAttributionStatus.textContent, /^1 After \/ Attributed work hidden for this sale location/);
    assert.equal(p.galleryAttributionToggle.attributes["aria-pressed"], "true");
    selectRegion(p, "outside_us");
    assert.deepEqual(p.visible(), [{id: 3, index: 2}]);
    assert.match(p.galleryAttributionStatus.textContent, /^1 After \/ Attributed work hidden/);
    selectRegion(p, "");
    assert.deepEqual(p.visible().map(x => x.id), view === "oliver" ? [2, 3, 5, 6] : [2, 3, 5, 6, 7]);
    assert.match(p.galleryAttributionStatus.textContent, /^2 After \/ Attributed works hidden for this day/);
    p.galleryHideAttributed = false;
    p.render();
    assert.deepEqual(p.visible().map(x => x.id), view === "oliver" ? [1, 2, 3, 4, 5, 6] : [1, 2, 3, 4, 5, 6, 7]);
    for (const item of p.visible()) assert.equal(p.run("dayLots()")[item.index].id, item.id);
    assert.equal(JSON.stringify(lots), before);
  });

  test(`${view} location changes retain independent house, artist and saved-work selections`, () => {
    const lots = regionalLots(), before = JSON.stringify(lots), p = page(lots, view);
    p.galleryHideAttributed = true;
    for (const filter of ["tray", "bidboards", "qualifying"]) {
      p.galleryFilter = filter;
      p.run('galleryOrganization.house = "Phillips"');
      p.render();
      assert.deepEqual(regionCounts(p), {"": "2", us: "1", outside_us: "0"});
      p.galleryVisibleCount = 72;
      selectRegion(p, "outside_us");
      assert.equal(p.galleryVisibleCount, 24);
      assert.equal(p.galleryFilter, filter);
      assert.equal(p.run("galleryOrganization.house"), "Phillips");
      assert.deepEqual(p.visible(), []);
      assert.match(p.galleryGrid.textContent, /Choose All locations or change another filter/);
      p.galleryHouseFilters.children.find(button => button.dataset.galleryFilter === "house:").events.click();
      assert.deepEqual(p.visible(), [{id: 3, index: 2}], "retained saved work remains reachable via the canonical card");
      assert.equal(p.galleryFilter, filter);
      selectRegion(p, "us");
      assert.deepEqual(p.visible(), [{id: 2, index: 1}]);
      selectRegion(p, "");
      assert.deepEqual(p.visible().map(x => x.id), [2, 3, 5]);
    }
    p.galleryFilter = `artist:${CalendarArtists.artistKey(lots[2])}`;
    p.render();
    selectRegion(p, "us");
    assert.deepEqual(p.visible(), []);
    assert.equal(p.galleryFilter, `artist:${CalendarArtists.artistKey(lots[2])}`);
    selectRegion(p, "outside_us");
    assert.deepEqual(p.visible(), [{id: 3, index: 2}]);
    assert.equal(JSON.stringify(lots), before);
  });
}

test("location and attribution preferences round-trip day, month, research, and history URLs", () => {
  const lots = regionalLots(), before = JSON.stringify(lots), p = page(lots);
  p.galleryFilter = "qualifying";
  p.galleryHideAttributed = true;
  p.run('galleryOrganization.region = "outside_us"');
  p.run('galleryOrganization.house = "Bonhams"');
  p.run("updateCalendarLocation()");
  for (const href of [p.window.history.url, ...p.monthLinks.map(x => x.href), ...p.catalogLinks.map(x => x.href), p.run("galleryResearchUrl(dayLots()[2])")]) {
    const url = new URL(href);
    assert.equal(url.searchParams.get("sale_region"), "outside_us");
    assert.equal(url.searchParams.get("hide_attributed"), "1");
    assert.equal(url.searchParams.get("house"), "Bonhams");
    assert.equal(url.searchParams.get("filter"), "qualifying");
  }
  p.activeView = "research";
  p.researchIndex = 0;
  assert.deepEqual(p.ids("dayLots()"), [1, 2, 3, 4, 5, 6, 7], "location cannot hide an explicitly opened or saved research record");
  p.run("updateCalendarLocation()");
  assert.equal(new URL(p.window.history.url).searchParams.get("lot"), "1");
  assert.equal(new URL(p.window.history.url).searchParams.get("sale_region"), "outside_us");
  p.setCalendarView = value => { p.activeView = value || "calendar"; p.render(); };
  p.showDay = value => { p.selectedDay = value; };
  vm.runInContext(between('  window.addEventListener("popstate"', '  researchPrevious.addEventListener("click"'), p);
  for (const [region, ids] of [["us", [2]], ["outside_us", [3]], ["", [2, 3, 5]], ["invalid", [2, 3, 5]]]) {
    p.window.location.search = `?day=${day}&view=catalog&filter=qualifying&hide_attributed=1&sale_region=${region}`;
    p.window.location.href = `https://secondstate.art/calendar/${p.window.location.search}`;
    p.listeners.get("popstate")();
    assert.deepEqual(p.visible().map(x => x.id), ids);
    assert.equal(p.run("galleryOrganization.region"), region === "invalid" ? "" : region);
    assert.equal(p.restoringHistory, false);
    const expected = ["us", "outside_us"].includes(region) ? region : null;
    for (const link of [...p.monthLinks, ...p.catalogLinks]) assert.equal(new URL(link.href).searchParams.get("sale_region"), expected);
  }
  assert.equal(JSON.stringify(lots), before);
});

test("initial location is opt-in and only explicit supported regions narrow the catalog", () => {
  const lots = regionalLots();
  for (const [value, expected] of [["us", [1, 2, 7]], ["outside_us", [3, 4]], ["", [1, 2, 3, 4, 5, 6, 7]], ["unknown", [1, 2, 3, 4, 5, 6, 7]], ["US", [1, 2, 3, 4, 5, 6, 7]]]) {
    const p = page(lots);
    p.window.location.search = `?sale_region=${value}`;
    vm.runInContext(between("  const initialParams =", "  const requestedView ="), p);
    assert.deepEqual(p.visible().map(x => x.id), expected);
  }
});

test("location filtering precedes grouping, sorting and pagination without changing original lot identities", () => {
  const lots = Array.from({length: 90}, (_, index) => lot(index + 1, {
    sale_region: index % 3 === 0 ? "outside_us" : "us", auction_house: index % 2 ? "Phillips" : "Bonhams",
    estimate_low: String(100 - index), email_tray_selected: true,
  }));
  const p = page(lots), before = JSON.stringify(lots);
  p.galleryFilter = "tray";
  p.gallerySort.value = "price_asc";
  p.run('galleryOrganization.group = "house"; galleryOrganization.region = "us"');
  const expected = ["Bonhams", "Phillips"].flatMap(house => lots.filter(l => l.sale_region === "us" && l.auction_house === house).reverse().map(l => l.id));
  p.render();
  assert.deepEqual(p.galleryGrid.children.filter(x => x.id).map(x => x.id), expected.slice(0, 24));
  p.galleryVisibleCount = 72;
  p.render();
  assert.deepEqual(p.galleryGrid.children.filter(x => x.id).map(x => x.id), expected);
  assert.equal(p.galleryMore.hidden, true);
  for (const item of p.visible()) assert.equal(lots[item.index].id, item.id);
  assert.equal(JSON.stringify(lots), before);
});


test("location controls preserve keyboard focus when their counts refresh", () => {
  const p = page(regionalLots());
  p.render();
  for (const region of ["", "us", "outside_us"]) {
    const focused = regionButtons(p).find(button => button.dataset.saleRegion === region);
    p.document.activeElement = {closest: selector => selector === "[data-sale-region]" ? focused : null};
    p.render();
    const replacement = regionButtons(p).find(button => button.dataset.saleRegion === region);
    assert.notEqual(replacement, focused);
    assert.equal(replacement.focused, true);
  }
});
