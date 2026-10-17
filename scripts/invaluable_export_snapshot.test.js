"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const { searchSpec, matchingRequests, makeSnapshot, snapshotIsCurrent, snapshotFromCandidate, observeCatalog } = require("./invaluable_export_snapshot.js");

const PAGE = "https://www.invaluable.com/search?artistName=Josef%2520Albers&Fine%20Art=Prints&query=fine%2520art&keyword=fine%2520art&sort=endDateAsc";
const ENDPOINT = "https://www.invaluable.com/catResults";
const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false AND closed:false AND NOT subcategoryRef:7IA742QGM5";
const STAMP = "2026-10-16T18:00:00.000Z";
function fixture() {
  const params = { facetFilters: [["artistName:Josef Albers"], ["Fine Art:Prints"]], query: "fine art",
    filters: FILTERS, page: 0, hitsPerPage: 96, facets: ["*"], clickAnalytics: true, userToken: "never-export-token" };
  const body = { isCatalogPageRequest: false, requests: [{ indexName: "upcoming_lots_dateTimeUTCUnix_asc_prod", params }] };
  const result = { page: 0, nbPages: 1, nbHits: 1, hitsPerPage: 96, params: "userToken=never-export-token",
    hits: [{ objectID: "12345", lotRef: "ABC123", lotTitle: "Josef Albers print", lotNumber: "12",
      dateTimeUTCUnix: 1792432800, estimateLow: 500, estimateHigh: 1000, currentBid: 400,
      houseName: "Example House", photoPath: "house/example.jpg", currencyCode: "USD",
      userToken: "never-export-token", account: { email: "never@example.test" }, _highlightResult: { secret: "never" } }] };
  return { pageURL: PAGE, requestURL: ENDPOINT, method: "POST", body, payload: { results: [result], account: "never" }, capturedAt: STAMP };
}
const settle = () => new Promise(setImmediate);

test("repeatedly encoded artist/search URL becomes verified public source URL", () => {
  const spec = searchSpec(PAGE + "&utm_source=private-tracker");
  assert.equal(spec.artist, "Josef Albers");
  assert.equal(spec.query, "fine art");
  assert.equal(spec.page, 0);
  assert.deepEqual(spec.facets, [["artistName:Josef Albers"], ["Fine Art:Prints"]]);
  assert.equal(new URL(spec.sourceURL).searchParams.get("artistName"), "Josef Albers");
  assert.ok(!spec.sourceURL.includes("private-tracker"));
  assert.throws(() => searchSpec(PAGE + "&numericFilters=currentBid%3E1000"), /unsupported URL/);
  assert.throws(() => searchSpec(PAGE + "&artistName=Other"), /one artist/);
});

test("exports only allowlisted scalar public fields and verified artist", () => {
  const data = fixture();
  data.payload.results[0].hits[0].lotDescription = { cookie: "never-export-cookie" };
  const snapshot = makeSnapshot(data);
  assert.deepEqual(Object.keys(snapshot).sort(), ["captured_at", "results", "source_url"]);
  assert.equal(snapshot.captured_at, STAMP);
  assert.equal(snapshot.results[0].hits[0].artistName, "Josef Albers");
  assert.equal(snapshot.results[0].hits[0].dateTimeUTCUnix, 1792432800);
  assert.equal(snapshot.results[0].hits[0].currentBid, 400);
  assert.ok(!JSON.stringify(snapshot).includes("never"));
  assert.ok(!Object.hasOwn(snapshot.results[0].hits[0], "lotDescription"));
  assert.deepEqual(Object.keys(snapshot.results[0]).sort(), ["hits", "hitsPerPage", "nbHits", "nbPages", "page"]);
});

test("exports the category hierarchy needed to distinguish prints from their subjects", () => {
  const data = fixture();
  Object.assign(data.payload.results[0].hits[0], {
    supercategoryName: "Fine Art", categoryName: "Prints", subcategoryName: "Genre",
  });
  const hit = makeSnapshot(data).results[0].hits[0];
  assert.equal(hit.supercategoryName, "Fine Art");
  assert.equal(hit.categoryName, "Prints");
  assert.equal(hit.subcategoryName, "Genre");
  data.payload.results[0].hits[0].categoryName = { account: "never-export" };
  assert.ok(!Object.hasOwn(makeSnapshot(data).results[0].hits[0], "categoryName"));
});

test("matches results by request index and ignores facet-only responses", () => {
  const data = fixture();
  data.body.requests.unshift({ ...structuredClone(data.body.requests[0]), params: { ...data.body.requests[0].params, hitsPerPage: 0 } });
  data.payload.results.unshift({ ...structuredClone(data.payload.results[0]), nbHits: 70000, hitsPerPage: 0, nbPages: 0 });
  assert.equal(makeSnapshot(data).results[0].nbHits, 1);
  data.body.requests[1].params.facetFilters = [["artistName:Josef Albers"]];
  assert.equal(makeSnapshot(data), null);
});

test("exact-artist all-category zero is valid, malformed zero is rejected", () => {
  const data = fixture();
  data.body.requests[0].params.facetFilters = [["artistName:Josef Albers"]];
  const result = data.payload.results[0];
  Object.assign(result, { hits: [], nbHits: 0, nbPages: 0 });
  assert.equal(makeSnapshot(data).results[0].nbHits, 0);
  result.nbHits = 1;
  assert.equal(makeSnapshot(data), null);
  result.nbHits = 0;
  result.nbPages = 1;
  assert.equal(makeSnapshot(data), null);
});

test("artist/category/query/sort/page/upcoming scope must match", () => {
  for (const [key, value] of [["query", "other"], ["facetFilters", [["artistName:Other"], ["Fine Art:Prints"]]],
    ["facetFilters", [["artistName:Josef Albers", "artistName:Other"], ["Fine Art:Prints"]]],
    ["facetFilters", [["artistName:Josef Albers"], ["Fine Art:Paintings"]]], ["filters", "closed:true"], ["page", 1]]) {
    const data = fixture();
    data.body.requests[0].params[key] = value;
    assert.equal(makeSnapshot(data), null, key);
  }
  const data = fixture();
  data.body.requests[0].indexName = "past_lots_prod";
  assert.equal(makeSnapshot(data), null);
});

test("hidden narrowing controls cannot create a valid zero snapshot", () => {
  for (const [key, value] of Object.entries({ numericFilters: ["currentBid>10000000"], tagFilters: ["private"],
    aroundLatLng: "40,-73", aroundLatLngViaIP: true, insideBoundingBox: [[1, 2, 3, 4]],
    insidePolygon: [[1, 2, 3, 4, 5, 6]], restrictSearchableAttributes: ["title"], distinct: 1,
    ruleContexts: ["limited"], enableRules: true, unknownControl: "narrow" })) {
    const data = fixture();
    data.body.requests[0].params[key] = value;
    Object.assign(data.payload.results[0], { hits: [], nbHits: 0, nbPages: 0 });
    assert.equal(makeSnapshot(data), null, key);
  }
});

test("page count, cardinality, identities, and scalar required fields are verified", () => {
  for (const change of [{ nbHits: 2 }, { nbPages: 0 }, { page: 1 }, { hitsPerPage: 0 }, { nbHits: true },
    { nbHits: 200, nbPages: 1 }, { hits: [{}] }, { hits: [{ lotRef: {}, lotTitle: "No" }] }]) {
    const data = fixture();
    Object.assign(data.payload.results[0], change);
    assert.equal(makeSnapshot(data), null, JSON.stringify(change));
  }
  const data = fixture();
  data.payload.results[0].hits.push(structuredClone(data.payload.results[0].hits[0]));
  data.payload.results[0].nbHits = 2;
  assert.equal(makeSnapshot(data), null);
});

test("second page retains its own complete metadata without claiming the whole artist", () => {
  const data = fixture();
  data.pageURL += "&page=2";
  data.body.requests[0].params.page = 1;
  Object.assign(data.payload.results[0], { page: 1, nbPages: 2, nbHits: 97 });
  const result = makeSnapshot(data);
  assert.equal(result.results[0].hits.length, 1);
  assert.equal(result.results[0].nbHits, 97);
  assert.equal(new URL(result.source_url).searchParams.get("page"), "2");
});

test("status, origin, explicit artist, encoded params and stale URL checks", () => {
  const data = fixture();
  assert.equal(makeSnapshot({ ...data, status: 202 }), null);
  assert.equal(makeSnapshot({ ...data, contentType: "text/html" }), null);
  assert.throws(() => makeSnapshot({ ...data, requestURL: "https://example.com/catResults" }));
  assert.equal(makeSnapshot({ ...data, requestURL: "https://invaluable.com/catResults" }), null);
  data.payload.results[0].hits[0].artistName = "Other";
  assert.equal(makeSnapshot(data), null);
  delete data.payload.results[0].hits[0].artistName;
  data.body.requests[0].params = new URLSearchParams({ ...data.body.requests[0].params,
    facetFilters: JSON.stringify(data.body.requests[0].params.facetFilters) }).toString();
  assert.ok(makeSnapshot(data));
  const capture = { pageURL: PAGE, data: makeSnapshot(fixture()) };
  assert.equal(snapshotIsCurrent(capture, PAGE), true);
  assert.equal(snapshotIsCurrent(capture, PAGE + "&page=2"), false);
  assert.equal(snapshotIsCurrent(capture, PAGE.replace("endDateAsc", "priceDesc")), false);
  assert.equal(snapshotIsCurrent(capture, PAGE.replace("Albers", "Other")), false);
});

test("a response arriving before the sort URL changes is revalidated after the URL settles", () => {
  const response = fixture();
  response.body.requests[0].indexName = "upcoming_lots_currentBid_asc_prod";
  const candidate = { response, serial: 4, receivedAt: 1000, capturedAt: STAMP };
  assert.equal(snapshotFromCandidate(candidate, PAGE, 4, 1100), null);
  const nextURL = PAGE.replace("endDateAsc", "priceAsc");
  const capture = snapshotFromCandidate(candidate, nextURL, 4, 1200);
  assert.equal(capture.data.results[0].hits.length, 1);
  assert.equal(capture.data.captured_at, STAMP);
  assert.equal(snapshotIsCurrent(capture, nextURL), true);
  // A subsequent equivalent URL rewrite still verifies the same response.
  const rewritten = nextURL.replace("Josef%2520Albers", "Josef+Albers");
  assert.ok(snapshotFromCandidate(candidate, rewritten, 4, 1300));
});

test("pending candidate cannot survive a newer results request, another scope, or its short lifetime", () => {
  const candidate = { response: fixture(), serial: 4, receivedAt: 1000, capturedAt: STAMP };
  assert.equal(snapshotFromCandidate(candidate, PAGE, 5, 1200), null);
  assert.equal(snapshotFromCandidate(candidate, PAGE, 4, 16001), null);
  assert.equal(snapshotFromCandidate(candidate, PAGE.replace("Albers", "Other"), 4, 1200), null);
  assert.equal(snapshotFromCandidate(candidate, PAGE + "&page=2", 4, 1200), null);
  assert.equal(snapshotFromCandidate(candidate, PAGE.replace("Prints", "Paintings"), 4, 1200), null);
  assert.equal(snapshotFromCandidate(candidate, PAGE.replaceAll("fine%2520art", "other"), 4, 1200), null);
});

function fakeWindow() {
  class XHR extends EventTarget {
    constructor() { super(); this.listeners = new Set(); }
    addEventListener(type, listener, options) { this.listeners.add(listener); return super.addEventListener(type, listener, options); }
    removeEventListener(type, listener) { this.listeners.delete(listener); return super.removeEventListener(type, listener); }
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.sent = body; }
    getResponseHeader() { return "application/json"; }
    complete(payload) { this.status = 200; this.responseURL = ENDPOINT; this.responseType = "json"; this.response = payload; this.dispatchEvent(new Event("loadend")); }
  }
  const data = fixture();
  let calls = 0;
  const response = { status: 200, url: ENDPOINT, headers: { get: () => "application/json" }, clone: () => ({ json: () => Promise.resolve(data.payload) }) };
  const promise = Promise.resolve(response);
  const win = { location: { href: PAGE }, XMLHttpRequest: XHR, fetch: function () { calls += 1; return promise; } };
  return { win, data, promise, getCalls: () => calls };
}

test("observer makes no request, preserves fetch return, and restores original methods", async () => {
  const { win, data, promise, getCalls } = fakeWindow();
  const originals = [win.fetch, win.XMLHttpRequest.prototype.open, win.XMLHttpRequest.prototype.send];
  const responses = [];
  const requests = [];
  const restore = observeCatalog(win, (response) => responses.push(response), (body) => requests.push(body));
  assert.equal(getCalls(), 0);
  assert.equal(win.fetch(ENDPOINT, { method: "POST", body: JSON.stringify(data.body) }), promise);
  await settle();
  assert.equal(getCalls(), 1);
  assert.equal(requests.length, 1);
  assert.equal(makeSnapshot({ ...responses[0], pageURL: PAGE, capturedAt: STAMP }).results[0].nbHits, 1);
  restore();
  assert.deepEqual([win.fetch, win.XMLHttpRequest.prototype.open, win.XMLHttpRequest.prototype.send], originals);
  await win.fetch(ENDPOINT, { method: "POST", body: JSON.stringify(data.body) });
  await settle();
  assert.equal(responses.length, 1);
});

test("observer captures normal XHR and removes pending listeners when restored", async () => {
  const { win, data } = fakeWindow();
  const responses = [];
  const restore = observeCatalog(win, (response) => responses.push(response), () => {});
  const xhr = new win.XMLHttpRequest();
  xhr.open("POST", ENDPOINT);
  xhr.send(JSON.stringify(data.body));
  xhr.complete(data.payload);
  await settle();
  assert.equal(responses.length, 1);
  const pending = new win.XMLHttpRequest();
  pending.open("POST", ENDPOINT);
  pending.send(JSON.stringify(data.body));
  assert.equal(pending.listeners.size, 1);
  restore();
  assert.equal(pending.listeners.size, 0);
  pending.complete(data.payload);
  await settle();
  assert.equal(responses.length, 1);
});

test("unrelated and foreign requests are forwarded without reading bodies", async () => {
  const { win, getCalls } = fakeWindow();
  let cloned = false;
  const responses = [];
  const restore = observeCatalog(win, (response) => responses.push(response), () => {});
  const input = { url: "https://example.com/catResults", method: "POST", clone() { cloned = true; throw new Error("Never read foreign body"); } };
  await win.fetch(input);
  await settle();
  assert.equal(getCalls(), 1);
  assert.equal(cloned, false);
  assert.equal(responses.length, 0);
  restore();
});

test("restore preserves wrappers installed later and disables in-flight observation", async () => {
  const { win, data } = fakeWindow();
  const responses = [];
  const restore = observeCatalog(win, (response) => responses.push(response), () => {});
  const observed = win.fetch;
  const laterWrapper = function () { return observed.apply(this, arguments); };
  win.fetch = laterWrapper;
  const pending = win.fetch(ENDPOINT, { method: "POST", body: JSON.stringify(data.body) });
  restore();
  assert.equal(win.fetch, laterWrapper);
  await pending;
  await settle();
  assert.equal(responses.length, 0);
  let clonedAfterRestore = false;
  await win.fetch({ url: ENDPOINT, method: "POST", clone() {
    clonedAfterRestore = true;
    return { text: () => Promise.resolve(JSON.stringify(data.body)) };
  } });
  await settle();
  assert.equal(clonedAfterRestore, false, "retained wrapper stops reading request bodies after Restore");
});

test("panel handles late URL updates, facet-only responses, original timestamps, and newer-scope invalidation", async () => {
  const { win, data } = fakeWindow();
  class Element {
    constructor(tag) { this.tag = tag; this.style = {}; this.children = []; this.handlers = new Map(); }
    setAttribute() {}
    append(...items) { for (const item of items) { item.parent = this; this.children.push(item); } }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((item) => item !== this); }
    addEventListener(name, handler) { this.handlers.set(name, handler); }
    click() { this.handlers.get("click")?.(); }
  }
  const document = { body: new Element("body"), createElement: (tag) => new Element(tag), getElementById: () => null };
  win.addEventListener = () => {};
  win.removeEventListener = () => {};
  let clock = Date.parse(STAMP);
  class ClockDate extends Date {
    constructor(value) { super(value === undefined ? clock : value); }
    static now() { return clock; }
  }
  const blobs = [];
  class LocalURL extends URL {
    static createObjectURL(blob) { blobs.push(blob); return `blob:test-${blobs.length}`; }
    static revokeObjectURL() {}
  }
  let poll;
  const context = { document, window: win, location: win.location, URL: LocalURL, Blob, Date: ClockDate, console,
    setInterval(callback) { poll = callback; return 1; }, clearInterval() {}, setTimeout() {} };
  vm.runInNewContext(fs.readFileSync(require.resolve("./invaluable_export_snapshot.js"), "utf8"), context);
  const panel = document.body.children[0];
  const [status, download, close] = panel.children;
  assert.equal(download.disabled, true);

  const changedRequest = structuredClone(data.body);
  changedRequest.requests[0].indexName = "upcoming_lots_currentBid_asc_prod";
  await win.fetch(ENDPOINT, { method: "POST", body: JSON.stringify(changedRequest) });
  await settle();
  assert.equal(download.disabled, true, "new sort result cannot be used with the old URL");
  const facetOnly = structuredClone(changedRequest);
  facetOnly.requests[0].params.hitsPerPage = 0;
  await win.fetch(ENDPOINT, { method: "POST", body: JSON.stringify(facetOnly) });
  await settle();
  clock += 2000;
  win.location.href = PAGE.replace("endDateAsc", "priceAsc");
  poll();
  assert.equal(download.disabled, false, "facet-only response did not displace the full result waiting for its URL");
  assert.match(status.textContent, /Josef Albers: 1 lots ready/);
  download.click();
  assert.equal(blobs.length, 1);
  const snapshot = JSON.parse(await blobs[0].text());
  assert.equal(snapshot.captured_at, STAMP, "URL revalidation preserves response time");
  assert.equal(new URL(snapshot.source_url).searchParams.get("sort"), "priceasc");
  assert.ok(!JSON.stringify(snapshot).includes("never"));

  const newer = structuredClone(changedRequest);
  newer.requests[0].params.facetFilters = [["artistName:Other"], ["Fine Art:Prints"]];
  await win.fetch(ENDPOINT, { method: "POST", body: JSON.stringify(newer) });
  await settle();
  assert.equal(download.disabled, true, "new request invalidates earlier downloadable snapshot even before URL changes");
  win.location.href = PAGE;
  poll();
  assert.equal(download.disabled, true, "returning to an old URL cannot revive the older request");
  download.click();
  assert.equal(blobs.length, 1, "stale click creates no download");
  close.click();
  assert.equal(document.body.children.length, 0);
});
