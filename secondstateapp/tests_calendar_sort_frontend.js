// Run with node --test. Exercise the actual catalog functions without a browser or network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const sortFunctions = template.slice(template.indexOf("  const galleryPrice ="),
  template.indexOf("  const renderGalleryFilters ="));
const renderFunction = template.slice(template.indexOf("  const renderGalleryCards ="),
  template.indexOf("  const renderGalleryCatalog ="));
const sortListener = template.slice(template.indexOf('  gallerySort.addEventListener("change"'),
  template.indexOf('  galleryMore.addEventListener("click"'));

function catalog(lots, sort = "price_asc", filter = "all") {
  const context = vm.createContext({
    data: {"2026-10-22": lots}, selectedDay: "2026-10-22", galleryFilter: filter,
    galleryVisibleCount: 24,
    gallerySort: {value: sort, addEventListener(type, callback) { this[type] = callback; }},
    gallerySortNote: {}, galleryDescription: {}, galleryResults: {}, galleryMore: {},
    galleryGrid: {cards: [], replaceChildren() { this.cards = []; }, appendChild(card) { this.cards.push(card); }},
    galleryCard: (lot, index) => ({id: lot.id, index}), appendText() {},
  });
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
