const assert = require("node:assert/strict");
const {setImmediate: completeRequests} = require("node:timers/promises");
const {test} = require("node:test");
const {createRandomLotsGallery} = require("./static/secondstateapp/calendar_random_lots.js");
const CalendarCurrency = require("./static/secondstateapp/calendar_currency.js");

function gallery(search, fetchPage) {
  const elements = new Map();
  function createElement() {
    const node = new EventTarget();
    return Object.assign(node, {
      value: "",
      dataset: {},
      children: [],
      classList: {toggle() {}},
      setAttribute(name, value) { this[name] = value; },
      replaceChildren(...children) { this.children = children; },
      append(...children) { this.children.push(...children); },
      contains(target) { return this === target || this.children.some(child => child?.contains?.(target)); },
      focus() { this.focused = true; document.activeElement = this; },
    });
  }
  function element(id) {
    if (!elements.has(id)) {
      const node = createElement();
      node.hidden = true;
      elements.set(id, node);
    }
    return elements.get(id);
  }
  const document = {getElementById: element, createElement, activeElement: null};
  element("random-lots-panel").dataset.url = "/calendar/random-lots/";
  const location = new URL("/calendar/?" + search, "https://secondstate.art");
  const navigate = (_state, _title, url) => { location.href = url; };
  const window = {location, history: {pushState: navigate, replaceState: navigate}, fetch: fetchPage, CalendarCurrency};
  const prices = [];
  const controller = createRandomLotsGallery(document, window, lot => lot.id,
    (_grid, lots, quotes) => prices.push({lots, quotes}));
  return {
    element, location, controller, prices, document,
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

test("changing the saved-lot sort resets pagination and keeps cards and quotes in the selected order", async () => {
  const day = "2026-11-30";
  const catalogQuery = `view=catalog&day=${day}&sort=artist-desc`;
  const requests = [];
  let finishOldQuotes;
  const g = gallery(`${catalogQuery}&collection=random&collection_page=2&collection_sort=artist`, async url => {
    const sort = url.searchParams.get("sort");
    const page = Number(url.searchParams.get("page"));
    const isQuote = url.searchParams.get("prices") === "usd";
    const id = sort === "artist" ? 12 : page + 20;
    requests.push([sort, page, isQuote]);
    const payload = {day, page, pages: 2, total: 26, lots: [{id, currency: "EUR", estimate_low: "75"}]};
    if (isQuote && sort === "artist") {
      return new Promise(resolve => { finishOldQuotes = () => resolve({ok: true, json: async () => payload}); });
    }
    return {ok: true, json: async () => payload};
  });
  g.controller.syncView("catalog", day, 26);
  await completeRequests();
  const sort = g.element("random-lots-sort");
  assert.equal(sort.value, "artist");
  sort.value = "estimate-desc";
  sort.dispatchEvent(new Event("change"));
  await completeRequests();
  finishOldQuotes();
  await completeRequests();
  assert.deepEqual(requests, [
    ["artist", 2, false], ["artist", 2, true],
    ["estimate-desc", 1, false], ["estimate-desc", 1, true],
  ]);
  assert.equal(g.location.searchParams.get("collection_page"), null);
  assert.equal(g.location.searchParams.get("collection_sort"), "estimate-desc");
  assert.deepEqual(g.element("random-lots-grid").children, [21]);
  assert.deepEqual(g.prices.map(result => result.quotes[0].id), [21]);
  g.click("random-lots-next");
  await completeRequests();
  assert.deepEqual(requests.slice(-2), [["estimate-desc", 2, false], ["estimate-desc", 2, true]]);
  g.click("random-lots-back");
  assert.equal(g.location.searchParams.toString(), catalogQuery);
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

function choice(g, name, key) {
  return g.element(`random-lots-${name}-filters`).children.find(node => node.dataset.key === key);
}

function showChoices(g, name) {
  const details = g.element(`random-lots-${name}s`);
  details.open = true;
  details.dispatchEvent(new Event("toggle"));
}

function choose(g, name, key) {
  const button = choice(g, name, key);
  assert.ok(button, `Missing ${name} choice ${key}`);
  button.focus();
  button.dispatchEvent(new Event("click"));
}

test("saved-lot facets combine across pages, preserve catalog settings and search accented artist names", async () => {
  const day = "2026-11-30";
  const catalog = `view=catalog&day=${day}&house=Main+House&artist=Main+Artist&sort=time_asc`;
  const requests = [];
  const houses = [{key: "h:2 / α", label: "House Two", count: 27}, {key: "h1", label: "House One", count: 25}];
  const artists = [{key: "a:é", label: "Müller, Émilie", count: 25}, {key: "other", label: "Marc", count: 27}];
  const g = gallery(catalog + "&collection=random&collection_page=2&collection_sort=estimate-desc", async url => {
    const params = url.searchParams;
    const house = params.get("collection_house");
    const artist = params.get("collection_artist");
    const prices = params.has("prices");
    const page = Number(params.get("page"));
    requests.push({house, artist, prices, page});
    assert.equal(params.has("house") || params.has("artist"), false);
    assert.equal(params.get("facets"), prices ? null : "1");
    assert.equal(params.get("sort"), "estimate-desc");
    const total = house && artist ? 17 : house ? 27 : artist ? 25 : 52;
    return {ok: true, json: async () => ({
      day, page, total, day_total: 52, pages: Math.ceil(total / 24),
      lots: [{id: 7, currency: "EUR", estimate_low: "100"}],
      facets: prices ? undefined : {
        houses: artist ? [{...houses[0], count: 17}, {...houses[1], count: 8}] : houses,
        artists: house ? [{...artists[0], count: 17}, {...artists[1], count: 10}] : artists,
      },
    })};
  });
  g.controller.syncView("catalog", day, 52);
  await completeRequests();
  assert.equal(g.element("random-lots-houses-summary").textContent, "2 houses · All houses");
  assert.equal(g.element("random-lots-artists-summary").textContent, "2 artists · All artists");
  assert.equal(choice(g, "artist", ""), undefined);
  showChoices(g, "house");
  showChoices(g, "artist");
  assert.equal(choice(g, "house", "")["aria-pressed"], "true");
  assert.equal(choice(g, "artist", "").children[1].textContent, "52");
  choose(g, "house", houses[0].key);
  await completeRequests();
  assert.equal(choice(g, "house", houses[0].key)["aria-pressed"], "true");
  assert.equal(g.document.activeElement, choice(g, "house", houses[0].key));
  assert.equal(g.location.searchParams.get("collection_page"), null);
  assert.equal(g.location.searchParams.get("house"), "Main House");
  assert.equal(g.location.searchParams.get("sort"), "time_asc");
  assert.equal(choice(g, "artist", "").children[1].textContent, "27");

  const search = g.element("random-lots-artist-search");
  const numberOfRequests = requests.length;
  search.value = "emilie muller";
  search.focus();
  search.dispatchEvent(new Event("input"));
  assert.ok(choice(g, "artist", artists[0].key));
  assert.equal(choice(g, "artist", "other"), undefined);
  assert.equal(g.document.activeElement, search);
  assert.equal(requests.length, numberOfRequests);
  choose(g, "artist", artists[0].key);
  await completeRequests();
  assert.equal(g.location.searchParams.get("artist"), "Main Artist");
  assert.equal(g.location.searchParams.get("collection_artist"), artists[0].key);
  assert.equal(g.element("random-lots-artists-summary").textContent, "2 artists · " + artists[0].label);
  assert.equal(g.element("random-lots-count").textContent, "52");
  assert.match(g.element("random-lots-status").textContent, /17 matching/);
  assert.deepEqual(requests.slice(-2), [
    {house: houses[0].key, artist: artists[0].key, prices: false, page: 1},
    {house: houses[0].key, artist: artists[0].key, prices: true, page: 1},
  ]);
  choose(g, "house", "");
  await completeRequests();
  assert.equal(g.location.searchParams.has("collection_house"), false);
  assert.equal(g.location.searchParams.get("collection_artist"), artists[0].key);
  g.click("random-lots-back");
  assert.equal(g.location.searchParams.toString(), catalog);
});

test("restoring filter history cancels stale cards and keeps zero-match filters clearable on a nonempty day", async () => {
  const day = "2026-11-30";
  const nextDay = "2026-12-01";
  let finishStale;
  const g = gallery(`view=catalog&collection=random&day=${day}&collection_artist=stale`, async url => {
    const params = url.searchParams;
    if (params.get("collection_artist") === "stale") return new Promise(resolve => { finishStale = resolve; });
    const date = params.get("day");
    const hasArtist = params.has("collection_artist");
    return {ok: true, json: async () => ({
      day: date, page: 1, pages: 1, total: hasArtist || date === nextDay ? 0 : 2,
      day_total: date === day ? 2 : 0, lots: [],
      facets: {houses: [{key: "h", label: "House", count: hasArtist ? 0 : 2}], artists: []},
    })};
  });
  g.controller.syncView("catalog", day, 2);
  showChoices(g, "artist");
  g.location.searchParams.set("collection_artist", "gone");
  g.controller.syncView("catalog", day, 2);
  await completeRequests();
  finishStale({ok: true, json: async () => ({
    day, page: 1, pages: 1, total: 90, day_total: 90, lots: [{id: 9}],
    facets: {houses: [], artists: [{key: "stale", label: "Late artist", count: 90}]},
  })});
  await completeRequests();
  assert.equal(g.element("random-lots-count").textContent, "2");
  assert.match(g.element("random-lots-status").textContent, /No saved lots match/);
  assert.equal(choice(g, "artist", "stale"), undefined);
  assert.equal(choice(g, "artist", "")["aria-pressed"], "false");
  assert.deepEqual(g.element("random-lots-grid").children, []);
  choose(g, "artist", "");
  await completeRequests();
  assert.equal(g.element("random-lots-status").textContent, "2 saved lots for this date");
  assert.equal(choice(g, "artist", "")["aria-pressed"], "true");
  g.location.searchParams.set("day", nextDay);
  g.location.searchParams.set("collection_artist", "gone");
  g.controller.syncView("catalog", nextDay, 0);
  await completeRequests();
  assert.equal(g.element("random-lots-count").textContent, "0");
  assert.equal(g.element("random-lots-status").textContent, "No saved lots for this date.");
});
