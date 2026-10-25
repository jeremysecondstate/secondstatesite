// Run with node --test. Execute the real inline loader with controlled async responses.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const CalendarCurrency = require("./static/secondstateapp/calendar_currency.js");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const loaderCode = template.slice(template.indexOf("  const applyCurrencyPrice ="),
  template.indexOf("  const externalLink ="));

class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.dataset = {}; this.hidden = false; }
  appendChild(node) { this.children.push(node); return node; }
  addEventListener(type, action) { this[type] = action; }
  querySelectorAll(selector) {
    return this.children.flatMap(node => [
      ...(selector === "[data-calendar-price-lot-id]" && node.dataset.calendarPriceLotId ? [node] : []),
      ...node.querySelectorAll(selector),
    ]);
  }
  closest() { return null; }
  focus() { this.focused = true; }
}

const dayA = "2026-10-21";
const dayB = "2026-10-22";
const foreignLot = (id, amount = "100.00") => ({
  id, currency: "EUR", estimate_low: amount, estimate_high: null,
  estimate: `€${Number(amount)} estimate`, bid: "Current bid: No bids", bid_count: 0,
});
const convertedLot = (lot, amount = "110.00") => ({id: lot.id, estimate_low: {
  source_currency: lot.currency, source_amount: lot.estimate_low, usd_amount: amount,
  rate: "1.10", rate_date: "2026-10-21", provider: "Frankfurter",
}, estimate_high: null, current_bid: null, sold_price: null});
const response = (day, lots) => ({ok: true, json: async () => ({day, lots})});

function page(data) {
  const pending = [];
  const timers = new Set();
  const document = new Element("document");
  document.createElement = tag => new Element(tag);
  document.activeElement = null;
  const renders = [];
  const context = vm.createContext({
    window: {CalendarCurrency}, document, data, selectedDay: Object.keys(data)[0], activeView: "catalog",
    currencyLotsById: new Map(Object.values(data).flat().map(lot => [String(lot.id), lot])),
    currencyDays: new Map(), researchLotCache: new Map(),
    currencyStatus: new Element(), currencyMessage: new Element(), currencyRetry: new Element("button"),
    gallerySort: Object.assign(new Element("select"), {value: "price_asc"}), galleryGrid: new Element(),
    URLSearchParams, AbortController,
    setTimeout(callback) { timers.add(callback); return callback; },
    clearTimeout(callback) { timers.delete(callback); },
    fetch(url, options) {
      return new Promise((resolve, reject) => pending.push({url, options, resolve, reject}));
    },
    renderGalleryCards() { renders.push(context.selectedDay); },
    isGalleryView() { return ["catalog", "oliver"].includes(context.activeView); },
    dayLots(day = context.selectedDay) { return context.data[day] || []; },
  });
  vm.runInContext(`${loaderCode}\nthis.load = loadCurrencyPrices; this.appendPrice = appendCurrencyPrice; this.refresh = refreshCurrencyPrices;`, context);
  return Object.assign(context, {pending, timers, renders});
}

test("one request per day stays in flight; completed conversions are reused", async () => {
  const lot = foreignLot(1);
  const context = page({[dayA]: [lot]});
  const first = context.load(dayA);
  const repeated = context.load(dayA, {force: true});
  assert.equal(context.pending.length, 1);
  assert.equal(context.currencyStatus.hidden, false);
  assert.equal(context.currencyRetry.hidden, true);
  assert.equal(lot.usd_status, "loading");
  assert.equal(context.pending[0].options.credentials, "same-origin");
  assert.equal(new URLSearchParams(context.pending[0].url.split("?")[1]).get("day"), dayA);
  context.pending[0].resolve(response(dayA, [convertedLot(lot)]));
  await Promise.all([first, repeated]);
  assert.equal(CalendarCurrency.sortPrice(lot), 110);
  assert.equal(lot.usd_status, "ready");
  assert.equal(context.currencyStatus.hidden, true);
  assert.equal(context.timers.size, 0);
  await context.load(dayA);
  assert.equal(context.pending.length, 1);
});

test("a late response for the previous day cannot reorder the current day or replace its status", async () => {
  const oldLot = foreignLot(1);
  const currentLot = foreignLot(2, "200.00");
  const context = page({[dayA]: [oldLot], [dayB]: [currentLot]});
  const oldRequest = context.load(dayA);
  context.selectedDay = dayB;
  const currentRequest = context.load(dayB);
  context.pending[1].resolve(response(dayB, [convertedLot(currentLot, "220.00")]));
  await currentRequest;
  const rendered = context.renders.length;
  const status = context.currencyStatus.hidden;
  const message = context.currencyMessage.textContent;
  context.pending[0].resolve(response(dayA, [convertedLot(oldLot)]));
  await oldRequest;
  assert.equal(context.renders.length, rendered);
  assert.equal(context.currencyStatus.hidden, status);
  assert.equal(context.currencyMessage.textContent, message);
  assert.equal(CalendarCurrency.sortPrice(currentLot), 220);
  assert.equal(oldLot.usd_status, "ready");
  assert.equal(CalendarCurrency.sortPrice(oldLot), 110);
});

test("missing and failed responses show unavailable prices and Retry requests a fresh conversion", async () => {
  for (const outcome of ["missing-lot", "network-error", "wrong-day", "http-error"]) {
    const lot = foreignLot(1);
    const context = page({[dayA]: [lot]});
    context.appendPrice(context.document, lot, "estimate", "lot-estimate");
    const initial = context.load(dayA);
    if (outcome === "network-error") context.pending[0].reject(new Error("Offline"));
    else if (outcome === "wrong-day") context.pending[0].resolve(response(dayB, [convertedLot(lot)]));
    else if (outcome === "http-error") context.pending[0].resolve({ok: false});
    else context.pending[0].resolve(response(dayA, []));
    await initial;
    assert.equal(lot.usd_status, "unavailable", outcome);
    assert.equal(CalendarCurrency.sortPrice(lot), null, outcome);
    assert.equal(context.currencyRetry.hidden, false, outcome);
    assert.match(context.document.children[0].textContent, /€100 estimate · USD conversion unavailable/, outcome);
    const retry = context.currencyRetry.click();
    assert.equal(context.pending.length, 2, outcome);
    assert.equal(context.currencyRetry.hidden, true, outcome);
    context.pending[1].resolve(response(dayA, [convertedLot(lot)]));
    await retry;
    assert.equal(CalendarCurrency.sortPrice(lot), 110, outcome);
    assert.equal(context.currencyStatus.hidden, true, outcome);
    assert.equal(context.timers.size, 0, outcome);
  }
});

test("price refresh updates visible and cached research nodes while preserving draft controls and focus", async () => {
  const lot = foreignLot(1);
  const context = page({[dayA]: [lot]});
  context.activeView = "research";
  const cached = new Element();
  const input = new Element("input");
  input.value = "Unsaved research note";
  cached.appendChild(input);
  context.researchLotCache.set(String(lot.id), cached);
  context.appendPrice(cached, lot, "estimate", "research-estimate");
  context.appendPrice(context.document, lot, "estimate", "sidebar-estimate");
  const cachedPrice = cached.children[1];
  const visiblePrice = context.document.children[0];
  context.document.activeElement = input;
  const load = context.load(dayA);
  context.pending[0].resolve(response(dayA, [convertedLot(lot)]));
  await load;
  assert.equal(cached.children[0], input);
  assert.equal(cached.children[1], cachedPrice);
  assert.equal(context.document.children[0], visiblePrice);
  assert.equal(input.value, "Unsaved research note");
  assert.equal(context.document.activeElement, input);
  assert.match(cachedPrice.textContent, /≈ \$110 USD estimate · Original: €100 estimate/);
  assert.equal(cachedPrice.textContent, visiblePrice.textContent);
  assert.match(cachedPrice.title, /Frankfurter · 2026-10-21 · 1 EUR = 1.10 USD/);
  assert.equal(context.renders.length, 0);
});

test("USD-only and empty days need no exchange-rate request", async () => {
  const lot = {...foreignLot(1), currency: "USD", estimate: "$100 estimate"};
  const context = page({[dayA]: [lot], [dayB]: []});
  await context.load(dayA);
  assert.equal(context.pending.length, 0);
  assert.equal(CalendarCurrency.sortPrice(lot), 100);
  assert.equal(context.currencyStatus.hidden, true);
  context.selectedDay = dayB;
  await context.load(dayB);
  assert.equal(context.pending.length, 0);
  assert.equal(context.currencyStatus.hidden, true);
  assert.equal(context.timers.size, 0);
});

test("Oliver price sorting refreshes after the shared USD conversion completes", async () => {
  const lot = {...foreignLot(1), oliver_house: true};
  const context = page({[dayA]: [lot]});
  context.activeView = "oliver";
  const load = context.load(dayA);
  const before = context.renders.length;
  context.pending[0].resolve(response(dayA, [convertedLot(lot, "125.00")]));
  await load;
  assert.equal(CalendarCurrency.sortPrice(lot), 125);
  assert(context.renders.length > before);
  assert.equal(context.renders.at(-1), dayA);
});
