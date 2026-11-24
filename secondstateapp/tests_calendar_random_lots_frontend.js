const assert = require("node:assert/strict");
const {setImmediate: completeRequests} = require("node:timers/promises");
const {test} = require("node:test");
const {createRandomLotsGallery} = require("./static/secondstateapp/calendar_random_lots.js");
const CalendarCurrency = require("./static/secondstateapp/calendar_currency.js");

function gallery(search, fetchPage) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const node = new EventTarget();
      Object.assign(node, {
        hidden: true,
        dataset: {},
        classList: {toggle() {}},
        setAttribute(name, value) { this[name] = value; },
        replaceChildren(...children) { this.children = children; },
        focus() { this.focused = true; },
      });
      elements.set(id, node);
    }
    return elements.get(id);
  }
  element("random-lots-panel").dataset.url = "/calendar/random-lots/";
  const location = new URL("/calendar/?" + search, "https://secondstate.art");
  const navigate = (_state, _title, url) => { location.href = url; };
  const window = {location, history: {pushState: navigate, replaceState: navigate}, fetch: fetchPage, CalendarCurrency};
  const prices = [];
  const controller = createRandomLotsGallery({getElementById: element}, window, lot => lot.id,
    (_grid, lots, quotes) => prices.push({lots, quotes}));
  return {
    element, location, controller, prices,
    click: id => element(id).dispatchEvent(new Event("click")),
  };
}

function response(day, page, total = 25) {
  return {ok: true, json: async () => ({
    day, page, total, pages: Math.max(1, Math.ceil(total / 24)),
    lots: total ? [{id: page === 1 ? 31796 : 31342}] : [],
  })};
}

test("opening and paging the saved collection preserves the selected catalog day and house", async () => {
  const search = "view=catalog&day=2026-11-24&house=AZ+Auction&hide_attributed=1";
  const requests = [];
  const g = gallery(search, async url => {
    const day = url.searchParams.get("day");
    const page = Number(url.searchParams.get("page"));
    requests.push([day, page]);
    return response(day, page);
  });
  g.controller.syncView("catalog", "2026-11-24", 25);
  assert.equal(g.element("random-lots-open").hidden, false);
  assert.equal(String(g.element("random-lots-count").textContent), "25");
  assert.equal(g.element("random-lots-panel").hidden, true);
  assert.equal(requests.length, 0);

  g.click("random-lots-open");
  await completeRequests();
  assert.equal(g.element("random-lots-panel").hidden, false);
  assert.deepEqual(g.element("random-lots-grid").children, [31796]);
  assert.equal(g.element("random-lots-previous").disabled, true);
  assert.equal(g.location.searchParams.get("collection"), "random");

  g.click("random-lots-next");
  await completeRequests();
  assert.deepEqual(requests, [["2026-11-24", 1], ["2026-11-24", 2]]);
  assert.deepEqual(g.element("random-lots-grid").children, [31342]);
  assert.equal(g.element("random-lots-next").disabled, true);
  assert.equal(g.location.searchParams.get("collection_page"), "2");
  g.click("random-lots-back");
  assert.equal(g.element("random-lots-panel").hidden, true);
  assert.equal(g.location.searchParams.toString(), search);
});

test("cards are usable before USD conversion and a late quote cannot change the next page", async () => {
  const day = "2026-11-26";
  const savedLots = [1, 2].map(id => ({id, currency: "EUR", estimate_low: "30.00"}));
  const pendingPrices = new Map();
  const g = gallery(`view=catalog&day=${day}&collection=random`, async url => {
    const page = Number(url.searchParams.get("page"));
    if (url.searchParams.get("prices") === "usd") {
      return new Promise(resolve => pendingPrices.set(page, resolve));
    }
    return {ok: true, json: async () => ({day, page, pages: 2, total: 25, lots: [savedLots[page - 1]]})};
  });
  g.controller.syncView("catalog", day, 25);
  await completeRequests();
  assert.deepEqual(g.element("random-lots-grid").children, [1]);
  assert.equal(g.element("random-lots-grid")["aria-busy"], "false");
  g.click("random-lots-next");
  await completeRequests();
  assert.deepEqual(g.element("random-lots-grid").children, [2]);
  pendingPrices.get(1)({ok: true, json: async () => ({day, page: 1, lots: [{id: 1}]})});
  pendingPrices.get(2)({ok: true, json: async () => ({day, page: 2, lots: [{id: 2}]})});
  await completeRequests();
  assert.deepEqual(g.prices, [{lots: [savedLots[1]], quotes: [{id: 2}]}]);
  assert.deepEqual(g.controller.lots, [savedLots[1]]);
});

test("a direct page link supports retry and safely discards a response after leaving the gallery", async () => {
  let attempts = 0;
  let resolveRetry;
  const g = gallery("view=catalog&day=2026-11-26&collection=random&collection_page=2", async url => {
    assert.equal(url.searchParams.get("day"), "2026-11-26");
    assert.equal(url.searchParams.get("page"), "2");
    if (++attempts === 1) return {ok: false};
    return new Promise(resolve => { resolveRetry = resolve; });
  });
  g.controller.syncView("catalog", "2026-11-26", 25);
  await completeRequests();
  assert.equal(g.element("random-lots-retry").hidden, false);
  g.click("random-lots-retry");
  assert.equal(attempts, 2);
  g.click("random-lots-back");
  resolveRetry(response("2026-11-26", 2));
  await completeRequests();
  assert.equal(g.element("random-lots-panel").hidden, true);
  assert.deepEqual(g.element("random-lots-grid").children, []);
});

test("changing the date with an open gallery replaces its count and ignores the previous day's late response", async () => {
  const oldDay = "2026-11-26";
  const newDay = "2026-11-27";
  let finishOldRequest;
  const requests = [];
  const g = gallery(`day=${oldDay}&view=catalog&collection=random`, async url => {
    const day = url.searchParams.get("day");
    requests.push([day, url.searchParams.get("page")]);
    if (day === oldDay) return new Promise(resolve => { finishOldRequest = resolve; });
    return response(day, 1, 0);
  });
  g.controller.syncView("catalog", oldDay, 25, "November 26, 2026");
  g.location.searchParams.set("day", newDay);
  g.controller.syncView("catalog", newDay, 0, "November 27, 2026");
  await completeRequests();
  assert.deepEqual(requests, [[oldDay, "1"], [newDay, "1"]]);
  assert.equal(String(g.element("random-lots-count").textContent), "0");
  assert.match(g.element("random-lots-date").textContent, /November 27/);
  finishOldRequest(response(oldDay, 1));
  await completeRequests();
  assert.deepEqual(g.element("random-lots-grid").children, []);
  assert.match(g.element("random-lots-status").textContent, /no saved lots/i);
  assert.equal(g.element("random-lots-pagination").hidden, true);
  assert.equal(g.element("random-lots-retry").hidden, true);
});
