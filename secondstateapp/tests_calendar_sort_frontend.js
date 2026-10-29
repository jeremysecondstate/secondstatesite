// Run with node --test. Exercise the actual catalog functions without a browser or network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const CalendarCurrency = require("./static/secondstateapp/calendar_currency.js");
const CalendarArtists = require("./static/secondstateapp/calendar_artists.js");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const sortFunctions = template.slice(template.indexOf("  const galleryPrice ="),
  template.indexOf("  const renderGalleryFilters ="));
const renderFunction = template.slice(template.indexOf("  const renderGalleryCards ="),
  template.indexOf("  const renderGalleryCatalog ="));
const sortListener = template.slice(template.indexOf('  gallerySort.addEventListener("change"'),
  template.indexOf('  galleryMore.addEventListener("click"'));

function catalog(lots, sort = "price_asc", filter = "all") {
  const context = vm.createContext({
    window: {CalendarCurrency, CalendarArtists},
    data: {"2026-10-22": lots.map(lot => ({currency: "USD", ...lot}))}, selectedDay: "2026-10-22", galleryFilter: filter,
    galleryVisibleCount: 24,
    activeView: "catalog",
    gallerySort: {value: sort, addEventListener(type, callback) { this[type] = callback; }},
    gallerySortNote: {}, galleryDescription: {}, galleryResults: {}, galleryMore: {},
    galleryArtistClear: {},
    galleryGrid: {cards: [], replaceChildren() { this.cards = []; }, appendChild(card) { this.cards.push(card); }},
    galleryCard: (lot, index) => ({id: lot.id, index}), appendText() {},
    loadCurrencyPrices() {},
  });
  context.dayLots = () => context.data[context.selectedDay] || [];
  context.inOliverScope = () => false;
  vm.runInContext(`${sortFunctions}\n${renderFunction}\n${sortListener}`, context);
  context.visible = () => Array.from(vm.runInContext("visibleGalleryLots()", context), ({lot, index}) => ({id: lot.id, index}));
  context.render = () => vm.runInContext("renderGalleryCards()", context);
  return context;
}

test("prices sort numerically in both directions, preserve ties and place missing prices last", () => {
  const lots = [
    {id: "unknown", estimate_low: null},
    {id: "1200", estimate_low: "1200.00"},
    {id: "90", estimate_low: "90.00"},
    {id: "900-first", estimate_low: "900.00"},
    {id: "900-second", estimate_low: "900.00"},
    {id: "invalid", estimate_low: "NaN", estimate_high: "Infinity"},
    {id: "zero", estimate_low: "0.00", estimate_high: "-10"},
  ];
  const before = JSON.stringify(lots);
  const page = catalog(lots);
  assert.deepEqual(page.visible().map(item => item.id), ["90", "900-first", "900-second", "1200", "unknown", "invalid", "zero"]);
  page.gallerySort.value = "price_desc";
  assert.deepEqual(page.visible().map(item => item.id), ["1200", "900-first", "900-second", "90", "unknown", "invalid", "zero"]);
  assert.equal(JSON.stringify(lots), before);
  for (const item of page.visible()) assert.equal(lots[item.index].id, item.id);
});

test("auction estimates determine order regardless of bids, sold prices or auction status", () => {
  const page = catalog([
    {id: "sold", sold_price: "400.00", current_bid: "20.00", estimate_low: "30.00", estimate_high: "10000.00", ended: true},
    {id: "bid", current_bid: "100.00", bid_count: 2, estimate_low: "9000.00"},
    {id: "no-bids", current_bid: "10.00", bid_count: 0, estimate_low: "200.00"},
    {id: "ended", current_bid: "15.00", ended: true, estimate_low: "300.00"},
    {id: "high-only", estimate_low: null, estimate_high: "500.00"},
    {id: "zero-low", estimate_low: "0.00", estimate_high: "600.00"},
    {id: "unknown-count", current_bid: "150.00", bid_count: null, estimate_low: "900.00"},
    {id: "unpriced-ended", ended: true, current_bid: "5.00"},
    {id: "sold-without-estimate", sold_price: "10.00", ended: true},
    {id: "bid-without-estimate", current_bid: "1.00", bid_count: 1},
  ]);
  assert.deepEqual(page.visible().map(item => item.id),
    ["sold", "no-bids", "ended", "high-only", "zero-low", "unknown-count", "bid", "unpriced-ended", "sold-without-estimate", "bid-without-estimate"]);
  page.gallerySort.value = "price_desc";
  assert.deepEqual(page.visible().map(item => item.id),
    ["bid", "unknown-count", "zero-low", "high-only", "ended", "no-bids", "sold", "unpriced-ended", "sold-without-estimate", "bid-without-estimate"]);
});

test("filters and Show more keep price order across the full day and retain research indices", () => {
  const lots = Array.from({length: 60}, (_, index) => ({
    id: index, auction_house: index % 2 ? "House B" : "House A",
    email_tray_selected: index % 3 === 0, estimate_low: String(60 - index),
  }));
  const page = catalog(lots, "price_asc", "house:House A");
  page.render();
  assert.equal(page.galleryGrid.cards.length, 24);
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), Array.from({length: 24}, (_, i) => 58 - 2 * i));
  assert.equal(page.galleryMore.hidden, false);
  assert.equal(page.gallerySortNote.hidden, false);
  page.galleryVisibleCount += 24;
  page.render();
  assert.equal(page.galleryGrid.cards.length, 30);
  assert.equal(page.galleryMore.hidden, true);
  for (const card of page.galleryGrid.cards) assert.equal(lots[card.index].id, card.id);

  page.gallerySort.value = "price_desc";
  page.gallerySort.change();
  assert.equal(page.galleryVisibleCount, 24);
  assert.equal(page.galleryGrid.cards[0].id, 0);
  page.galleryFilter = "tray";
  page.render();
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), Array.from({length: 20}, (_, i) => i * 3));
  page.selectedDay = "2026-10-23";
  page.render();
  assert.equal(page.galleryGrid.cards.length, 0);
  assert.equal(page.galleryResults.textContent, "0 watched lots");
});

test("Bid Boards retains every saved outcome through all catalog sorts and preserves research indices", () => {
  const lots = [
    {id: "unsaved", artist: "A", auction_house: "A", lot_number: "1", estimate_low: "1", event_at: "2026-10-22T00:00:00Z", saved_bid_board: null},
    {id: "qualifying", artist: "Z", auction_house: "C", lot_number: "100", estimate_low: "900", event_at: "2026-10-22T18:00:00Z", saved_bid_board: {qualifies: true, qualifying_bid: "300"}},
    {id: "no-bid", artist: "A", auction_house: "A", lot_number: "2", estimate_low: "90", event_at: "2026-10-22T15:00:00Z", saved_bid_board: {qualifies: false, qualifying_bid: null}},
    {id: "unavailable", artist: "M", auction_house: "B", lot_number: "10A", estimate_low: null, event_at: null, saved_bid_board: {qualifies: null, qualifying_bid: null}},
    {id: "research-only", artist: "A", auction_house: "A", saved_bid_board_url: "/saved/5/", liveart_research: {selected_ids: ["example"]}},
  ];
  const page = catalog(lots, "catalog", "bidboards");
  const before = JSON.stringify(page.data);
  const expected = {
    catalog: ["qualifying", "no-bid", "unavailable"],
    artist: ["no-bid", "unavailable", "qualifying"],
    house: ["no-bid", "unavailable", "qualifying"],
    lot_asc: ["no-bid", "unavailable", "qualifying"],
    lot_desc: ["qualifying", "unavailable", "no-bid"],
    price_asc: ["no-bid", "qualifying", "unavailable"],
    price_desc: ["qualifying", "no-bid", "unavailable"],
    time_asc: ["no-bid", "qualifying", "unavailable"],
    time_desc: ["qualifying", "no-bid", "unavailable"],
  };
  for (const [sort, ids] of Object.entries(expected)) {
    page.gallerySort.value = sort;
    page.render();
    assert.deepEqual(page.galleryGrid.cards.map(card => card.id), ids, sort);
    for (const card of page.galleryGrid.cards) assert.equal(lots[card.index].id, card.id);
  }
  assert.equal(JSON.stringify(page.data), before, "filtering cannot modify saved outcomes or source order");
});

test("Bid Boards sorts the complete saved set before pagination and resets Show more on sort changes", () => {
  const lots = Array.from({length: 60}, (_, index) => ({
    id: index, estimate_low: String(60 - index),
    saved_bid_board: index % 3 === 0 ? null : {qualifies: index % 2 === 0, qualifying_bid: null},
  }));
  const page = catalog(lots, "price_asc", "bidboards");
  const saved = lots.filter(lot => lot.saved_bid_board).map(lot => lot.id);
  page.render();
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), [...saved].reverse().slice(0, 24));
  assert.equal(page.galleryResults.textContent, "Showing 24 of 40 watched lots");
  assert.equal(page.galleryMore.hidden, false);
  page.galleryVisibleCount += 24;
  page.render();
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), [...saved].reverse());
  assert.equal(page.galleryMore.hidden, true);
  page.gallerySort.value = "price_desc";
  page.gallerySort.change();
  assert.equal(page.galleryFilter, "bidboards");
  assert.equal(page.galleryVisibleCount, 24);
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), saved.slice(0, 24));
  for (const card of page.galleryGrid.cards) assert.equal(lots[card.index].id, card.id);
});

test("existing catalog, artist and auction-house orders are unchanged", () => {
  const page = catalog([
    {id: "first", artist: "Z", auction_house: "B"},
    {id: "second", artist: "A", auction_house: "B"},
    {id: "third", artist: "A", auction_house: "A"},
  ], "catalog");
  assert.deepEqual(page.visible().map(item => item.id), ["first", "second", "third"]);
  page.gallerySort.value = "artist";
  assert.deepEqual(page.visible().map(item => item.id), ["second", "third", "first"]);
  page.gallerySort.value = "house";
  assert.deepEqual(page.visible().map(item => item.id), ["third", "first", "second"]);
  page.render();
  assert.equal(page.gallerySortNote.hidden, true);
});

test("auction times sort chronologically across offsets, preserve ties, and keep TBA last in both directions", () => {
  const lots = [
    {id: "tba", event_at: null, time: "Time TBA"},
    {id: "noon", event_at: "2026-10-22T12:00:00-07:00", time: "12:00 PM"},
    {id: "midnight", event_at: "2026-10-22T00:00:00-07:00", time: "12:00 AM", ended: true},
    {id: "morning-first", event_at: "2026-10-22T14:00:00+02:00", time: "5:00 AM"},
    {id: "morning-second", event_at: "2026-10-22T12:00:00Z", time: "5:00 AM"},
    {id: "late", event_at: "2026-10-23T06:59:00Z", time: "11:59 PM"},
    {id: "invalid", event_at: "invalid", time: "Time TBA"},
    {id: "missing", time: "Time TBA"},
    {id: "empty", event_at: "", time: "Time TBA"},
  ];
  const before = JSON.stringify(lots);
  const page = catalog(lots, "time_asc");
  assert.deepEqual(page.visible().map(item => item.id),
    ["midnight", "morning-first", "morning-second", "noon", "late", "tba", "invalid", "missing", "empty"]);
  page.gallerySort.value = "time_desc";
  assert.deepEqual(page.visible().map(item => item.id),
    ["late", "noon", "morning-first", "morning-second", "midnight", "tba", "invalid", "missing", "empty"]);
  assert.equal(JSON.stringify(lots), before);
  for (const item of page.visible()) assert.equal(lots[item.index].id, item.id);
});

test("time sorting covers the full filtered day before pagination and resets Show more on sort changes", () => {
  const lots = Array.from({length: 60}, (_, index) => ({
    id: index, auction_house: index % 2 ? "House B" : "House A",
    email_tray_selected: index % 3 === 0,
    event_at: `2026-10-22T12:${String(59 - index).padStart(2, "0")}:00Z`,
  }));
  const page = catalog(lots, "time_asc", "house:House A");
  page.render();
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), Array.from({length: 24}, (_, i) => 58 - 2 * i));
  assert.equal(page.galleryMore.hidden, false);
  assert.equal(page.gallerySortNote.hidden, false);
  assert.match(page.gallerySortNote.textContent, /start or end time/);
  assert.match(page.gallerySortNote.textContent, /Time TBA appear last/);
  page.galleryVisibleCount += 24;
  page.render();
  assert.equal(page.galleryGrid.cards.length, 30);
  assert.equal(page.galleryMore.hidden, true);
  for (const card of page.galleryGrid.cards) assert.equal(lots[card.index].id, card.id);
  page.gallerySort.value = "time_desc";
  page.gallerySort.change();
  assert.equal(page.galleryVisibleCount, 24);
  assert.equal(page.galleryGrid.cards[0].id, 0);
  page.galleryFilter = "tray";
  page.render();
  assert.deepEqual(page.galleryGrid.cards.map(card => card.id), Array.from({length: 20}, (_, i) => i * 3));
  page.gallerySort.value = "price_asc";
  page.render();
  assert.match(page.gallerySortNote.textContent, /auction estimate in USD/);
  page.gallerySort.value = "catalog";
  page.render();
  assert.equal(page.gallerySortNote.hidden, true);
});

test("artist order uses supplied surname keys, includes mononyms, and retains lot identity", () => {
  const lots = [
    {id: "miro", artist: "Joan Miró", artist_sort_key: "miro joan"},
    {id: "josef", artist: "Josef Albers", artist_sort_key: "albers josef"},
    {id: "banksy", artist: "Banksy", artist_sort_key: "banksy"},
    {id: "durer", artist: "Albrecht Dürer", artist_sort_key: "durer albrecht"},
    {id: "anni", artist: "Anni Albers", artist_sort_key: "albers anni"},
    {id: "eluard", artist: "Éluard, Paul", artist_sort_key: "eluard paul"},
  ];
  const page = catalog(lots, "artist");
  const before = JSON.stringify(page.data);
  assert.deepEqual(page.visible().map(item => item.id), ["anni", "josef", "banksy", "durer", "eluard", "miro"]);
  page.render();
  for (const card of page.galleryGrid.cards) assert.equal(lots[card.index].id, card.id);
  assert.equal(JSON.stringify(page.data), before, "sorting must not rewrite source names or reorder research data");
  assert.equal(page.gallerySortNote.hidden, true);
});

test("artist keys and legacy names compare without accents or case, preserving catalog ties", () => {
  const page = catalog([
    {id: "accent-first", artist: "Éluard, Paul", artist_sort_key: ""},
    {id: "miro", artist: "Miró, Joan", artist_sort_key: null},
    {id: "plain-second", artist: "Paul Eluard", artist_sort_key: "eluard, paul"},
    {id: "banksy", artist: "Banksy"},
    {id: "case-third", artist: "ELUARD, PAUL"},
    {id: "accent-key-fourth", artist: "Other display label", artist_sort_key: "Éluard, Paul"},
  ], "artist");
  assert.deepEqual(page.visible().map(item => item.id),
    ["banksy", "accent-first", "plain-second", "case-third", "accent-key-fourth", "miro"]);
});

test("research searches match original and surname-first artist names and retain matching navigation", () => {
  const searchFunction = template.slice(template.indexOf("  const matchesResearchSearch ="),
    template.indexOf("  const renderResearchRail ="));
  const moveFunction = template.slice(template.indexOf("  const moveResearchLot ="),
    template.indexOf("  const renderLotBrowser ="));
  const lots = [
    {id: "first", artist: "Miró, Joan", artist_source: "Joan Miró", title: "Bleu", auction_house: "House A", lot_number: "42"},
    {id: "second", artist: "Miró, Joan", artist_source: "Joan Miró", title: "Soleil", auction_house: "House B"},
    {id: "third", artist: "Banksy", title: "Flower Thrower", auction_house: "House C"},
  ];
  const context = vm.createContext({
    data: {"2026-10-22": lots}, selectedDay: "2026-10-22", researchIndex: 0,
    researchSearch: {value: " Joan Miró "}, researchLotCard: {querySelector: () => null},
    renderResearchWorkspace() {}, updateCalendarLocation() {},
  });
  context.dayLots = () => context.data[context.selectedDay] || [];
  vm.runInContext(`${searchFunction}\n${moveFunction}`, context);
  const matches = (query) => {
    context.query = query.toLocaleLowerCase();
    return Array.from(vm.runInContext('data[selectedDay].filter(lot => matchesResearchSearch(lot, query)).map(lot => lot.id)', context));
  };
  assert.deepEqual(matches("Joan Miró"), ["first", "second"]);
  assert.deepEqual(matches("Miró, Joan"), ["first", "second"]);
  assert.deepEqual(matches("Banksy"), ["third"]);
  assert.deepEqual(matches("Bleu"), ["first"]);
  assert.deepEqual(matches("House B"), ["second"]);
  assert.deepEqual(matches("42"), ["first"]);
  assert.deepEqual(matches(""), ["first", "second", "third"]);
  vm.runInContext("moveResearchLot(1)", context);
  assert.equal(context.researchIndex, 1);
  assert.equal(context.researchSearch.value, " Joan Miró ", "original-name search survives moving to another matching lot");
  vm.runInContext("moveResearchLot(1)", context);
  assert.equal(context.researchIndex, 2);
  assert.equal(context.researchSearch.value, "", "moving outside the search still clears it");
});
