"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const core = require("../../../scripts/invaluable_export_snapshot.js");
const PAGE = "https://www.invaluable.com/search?artistName=Josef+Albers&sort=endDateAsc";
const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false AND closed:false AND NOT subcategoryRef:7IA742QGM5";
function setup() {
  let onResponse, onRequest, interval;
  const sent = [], listeners = {};
  const window = { addEventListener: (type, fn) => { listeners[type] = fn; }, postMessage: (data) => sent.push(data) };
  const location = { href: PAGE, origin: "https://www.invaluable.com", pathname: "/search" };
  const context = { globalThis: null, URL, URLSearchParams, Date, location, window,
    setInterval: (fn) => { interval = fn; },
    SecondStateInvaluableSnapshot: { ...core, observeCatalog: (_win, response, request) => { onResponse = response; onRequest = request; } } };
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../observer-main.js"), "utf8"), context);
  const grant = (page = 0, sourceURL = location.href) => {
    const url = new URL(sourceURL); if (page) url.searchParams.set("page", String(page + 1));
    listeners.message({ source: window, origin: location.origin, data: { channel: "secondstate-invaluable-collector-v1",
      type: "expected-page", page_url: location.href, expected_page: page, source_url: url.href } });
  };
  grant();
  return { sent, listeners, window, location, grant, request: (...args) => onRequest(...args), response: (...args) => onResponse(...args), tick: () => interval() };
}
function resultEnvelope(hitsPerPage = 1) {
  return { pageURL: PAGE, requestURL: "https://www.invaluable.com/catResults", method: "POST", status: 200, contentType: "application/json",
    body: { isCatalogPageRequest: false, requests: [{ indexName: "upcoming_lots_dateTimeUTCUnix_asc_prod", params: {
      facetFilters: [["artistName:Josef Albers"]], filters: FILTERS, query: "", page: 0, hitsPerPage,
    } }] }, payload: { results: [{ page: 0, nbPages: 1, nbHits: 1, hitsPerPage: 1,
      hits: [{ objectID: "1", lotRef: "ref1", lotTitle: "Print", artistName: "Josef Albers" }] }] } };
}
test("late facet-only request cannot discard the initial natural results response", () => {
  const h = setup(); const results = resultEnvelope(); const facets = resultEnvelope(0);
  h.request(results.body, 1); h.request(facets.body, 2); h.response(results, 1); h.response(facets, 2);
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].snapshot.results[0].hits[0].objectID, "1");
});
test("observer replays only sanitized ready capture when the isolated bridge attaches late", () => {
  const h = setup(); const response = resultEnvelope(); response.payload.account = "never";
  response.payload.results[0].hits[0].userToken = "never";
  h.request(response.body, 1); h.response(response, 1);
  h.listeners.message({ source: h.window, origin: h.location.origin,
    data: { channel: "secondstate-invaluable-collector-v1", type: "bridge-ready" } });
  assert.equal(h.sent.length, 2);
  assert.equal(JSON.stringify(h.sent).includes("never"), false);
  h.tick(); assert.equal(h.sent.length, 2);
});
test("a newer real request prevents an older response being exported", () => {
  const h = setup(); const older = resultEnvelope(); const newer = resultEnvelope();
  newer.payload.results[0].hits[0].objectID = "2";
  h.request(older.body, 1); h.request(newer.body, 2); h.response(older, 1);
  assert.equal(h.sent.length, 0);
  h.response(newer, 2);
  assert.equal(h.sent.length, 1); assert.equal(h.sent[0].snapshot.results[0].hits[0].objectID, "2");
});

test("catalog-page hydration cannot supersede a pending artist-search response", () => {
  const h = setup(); const search = resultEnvelope(); const catalog = resultEnvelope();
  catalog.body.isCatalogPageRequest = true;
  h.request(search.body, 1); h.request(catalog.body, 2);
  h.response(catalog, 2); h.response(search, 1);
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].snapshot.results[0].hits[0].objectID, "1");
});

test("a transient unsupported page URL does not throw or lose the current response", () => {
  const h = setup(); const response = resultEnvelope();
  h.request(response.body, 1);
  h.location.href = "https://www.invaluable.com/search";
  assert.doesNotThrow(() => h.response(response, 1));
  assert.doesNotThrow(() => h.tick());
  assert.equal(h.sent.length, 0);
  h.location.href = PAGE; h.tick();
  assert.equal(h.sent.length, 1);
});

test("equivalent URL rewriting re-emits the same observation for the current bridge URL", () => {
  const h = setup(); const response = resultEnvelope();
  h.request(response.body, 1); h.response(response, 1);
  const initial = h.sent[0];
  h.location.href = PAGE.replace("Josef+Albers", "Josef%2520Albers");
  h.tick();
  assert.equal(h.sent.length, 2);
  assert.equal(h.sent[1].page_url, h.location.href);
  assert.deepEqual(h.sent[1].snapshot, initial.snapshot);
  h.tick(); assert.equal(h.sent.length, 2);
});

test("new artist-search scope still invalidates the old result before its URL changes", () => {
  const h = setup(); const older = resultEnvelope(); const newer = resultEnvelope();
  newer.body.requests[0].params.facetFilters = [["artistName:Banksy"]];
  newer.payload.results[0].hits[0].artistName = "Banksy";
  h.request(older.body, 1); h.request(newer.body, 2); h.response(older, 1); h.response(newer, 2);
  assert.equal(h.sent.length, 0);
  h.location.href = PAGE.replace("Josef+Albers", "Banksy"); h.tick();
  assert.equal(h.sent.length, 0, "a changed visible scope does not satisfy the original grant");
  h.grant();
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].snapshot.results[0].hits[0].artistName, "Banksy");
});

test("Load more response is captured only for the worker's exact page with the visible URL unchanged", () => {
  const h = setup(); const response = resultEnvelope();
  response.body.requests[0].params.page = 1;
  Object.assign(response.payload.results[0], { page: 1, nbPages: 2, nbHits: 2 });
  h.request(response.body, 1); h.response(response, 1);
  assert.equal(h.sent.length, 0, "page one cannot satisfy an expected page zero");
  h.grant(1);
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].page_url, PAGE);
  assert.equal(new URL(h.sent[0].snapshot.source_url).searchParams.get("page"), "2");
  h.grant(2);
  assert.equal(h.sent.length, 1, "page one cannot satisfy an expected page two");
});
