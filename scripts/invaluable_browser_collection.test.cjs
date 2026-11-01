"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const core = require("./invaluable_export_snapshot.js");
const createCollector = require("./invaluable_browser_collection.cjs");

const URL = "https://www.invaluable.com/search?artistName=Alice%2520Example&artistName=Bob%2520Example"
  + "&Fine%20Art=Prints&sort=endDateAsc&query=fine%2520art&keyword=fine%2520art";
const JOB = { name: "BULK-1A", url: URL };
const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false "
  + "AND closed:false AND NOT subcategoryRef:7IA742QGM5";

function fixture(page = 0, count = 1, size = 1) {
  const spec = core.searchSpec(URL);
  return {
    body: { isCatalogPageRequest: false, requests: [{ indexName: spec.index, params: {
      query: spec.query, facetFilters: spec.facets, filters: FILTERS, page, hitsPerPage: size,
      userToken: "PRIVATE_TOKEN",
    } }] },
    payload: { results: [{ page, nbPages: Math.ceil(count / size), nbHits: count, hitsPerPage: size,
      hits: Array.from({ length: Math.min(size, count - page * size) }, (_, index) => ({
        objectID: `ID${page * size + index}`, lotRef: `REF${page * size + index}`, lotTitle: "Offline print",
        _highlightResult: { artistName: { value: "Alice Example", matchLevel: "none", matchedWords: [] },
          account: { value: "PRIVATE_HIGHLIGHT" } }, account: "PRIVATE_ACCOUNT", _rankingInfo: "PRIVATE_RANKING",
      })) }] },
  };
}

function triplet(data, id, start) {
  return [
    { method: "Network.requestWillBeSent", sequence: start, params: { requestId: id, request: {
      url: "https://www.invaluable.com/catResults", method: "POST", postData: JSON.stringify(data.body),
      headers: { Cookie: "PRIVATE_COOKIE" },
    } } },
    { method: "Network.responseReceived", sequence: start + 1,
      params: { requestId: id, response: { status: 200, mimeType: "application/json" } } },
    { method: "Network.loadingFinished", sequence: start + 2, params: { requestId: id } },
  ];
}

function setup(rows, { failRead, failWrite, chunks, base64 = false } = {}) {
  const saved = new Map();
  const bodyReads = [];
  let eventReads = 0;
  const events = rows.flatMap((row, index) => triplet(row, `request-${index}`, index * 3 + 1));
  const fs = {
    readFile: async (path) => {
      if (saved.has(path)) return saved.get(path);
      const error = new Error("Missing offline evidence"); error.code = "ENOENT"; throw error;
    },
    writeFile: async (path, value) => {
      if (failWrite?.(path)) throw new Error("Offline evidence write failed");
      saved.set(path, value);
    },
  };
  const cdp = {
    readEvents: async ({ afterSequence = 0 } = {}) => {
      const result = chunks ? chunks[eventReads++] : { events, cursor: events.at(-1)?.sequence || 0, hasMore: false };
      return result && { ...result, events: result.events.filter((event) => event.sequence > afterSequence) };
    },
    send: async (method, { requestId }) => {
      assert.equal(method, "Network.getResponseBody");
      assert(saved.has("offline/source-request-metadata.json"), "metadata is durable before reading");
      bodyReads.push(requestId);
      if (failRead?.(requestId)) throw new Error("Offline supported-body rejection");
      const body = JSON.stringify(rows[Number(requestId.split("-").at(-1))].payload);
      return { body: base64 ? Buffer.from(body).toString("base64") : body, base64Encoded: base64 };
    },
  };
  const dom = rows.flatMap((row) => row.payload.results[0].hits)
    .map((hit) => `/url: https://www.invaluable.com/auction-lot/offline-c-${hit.lotRef}`).join("\n");
  const tab = { url: async () => URL, playwright: {
    domSnapshot: async () => dom,
    getByRole: () => ({ count: async () => 0, click: async () => {} }),
  } };
  const collector = createCollector({ fs, runDir: "offline", core, selected: [JOB] });
  const read = (name) => JSON.parse(saved.get(`offline/${name}`));
  return { saved, bodyReads, cdp, tab, collector, read, invoke: () => collector.retainFirst(tab, cdp, JOB, 0) };
}

test("rejects the original unsupported narrowing filter before sanitizing or reading a body", async () => {
  const data = fixture();
  data.body.requests[0].params.numericFilters = ["currentBid>1000"];
  assert.deepEqual(core.matchingRequests(data.body, core.searchSpec(URL)), []);
  const x = setup([data]);
  await assert.rejects(x.invoke(), /Incomplete first response triplet/);
  assert.deepEqual(x.bodyReads, []);
  assert.equal(x.read("source-request-metadata.json")[0].body_read_status, "skipped_unmatched_scope");
  assert.equal(x.saved.has("offline/bulk-1a-envelopes.json"), false);
  assert.equal(x.saved.has("offline/bulk-1a-response-evidence.json"), false);
});

test("privacy filtering cannot introduce an additional matching request index", async () => {
  const data = fixture();
  const narrowed = structuredClone(data.body.requests[0]);
  narrowed.params.numericFilters = "currentBid>1000";
  data.body.requests.unshift(narrowed);
  data.payload.results.unshift(structuredClone(data.payload.results[0]));
  assert.deepEqual(core.matchingRequests(data.body, core.searchSpec(URL)).map((match) => match.index), [1]);
  const x = setup([data]);
  await assert.rejects(x.invoke(), /scope changed during privacy filtering/);
  assert.deepEqual(x.bodyReads, []);
  assert.equal(x.saved.has("offline/bulk-1a-envelopes.json"), false);
});

test("skips unrelated hydration bodies and preserves exact public capture and triplet compatibility", async () => {
  const unrelated = fixture(); unrelated.body.requests[0].params.query = "unrelated";
  const x = setup([unrelated, fixture()], { failRead: (id) => id === "request-0", base64: true });
  const result = await x.invoke();
  assert.deepEqual(x.bodyReads, ["request-1"]);
  assert.deepEqual({ ...result, truncated: false }, { total: 1, pages: 1, candidates: 1, truncated: false });
  const env = x.read("bulk-1a-envelopes.json")[0];
  assert.equal(env.pageURL, URL);
  assert.equal(core.makeSnapshot(env).results[0].hits[0].artistName, "Alice Example");
  assert.equal(x.read("network-observation-metadata.json")[0].capturedAt, env.capturedAt);
  assert.deepEqual(x.read("source-request-metadata.json").map((record) => record.body_read_status),
    ["skipped_unmatched_scope", "available"]);
  assert(![...x.saved.values()].join("").includes("PRIVATE_"));
});

test("each successful envelope and ordered triplet survive a later matching body-read rejection", async () => {
  const x = setup([fixture(), fixture()], { failRead: (id) => id === "request-1" });
  await assert.rejects(x.invoke(), /Offline supported-body rejection/);
  const evidence = x.read("bulk-1a-response-evidence.json");
  const initial = x.read("bulk-1a-initial-response-evidence.json");
  const metadata = x.read("network-observation-metadata.json");
  assert.equal(evidence.length, 1); assert.deepEqual(initial, evidence);
  assert(core.makeSnapshot(evidence[0]));
  assert.equal(metadata.length, 1); assert.equal(metadata[0].capturedAt, evidence[0].capturedAt);
  assert.deepEqual([metadata[0].requestSequence, metadata[0].responseSequence, metadata[0].finishedSequence], [1, 2, 3]);
  assert.deepEqual(x.read("source-request-metadata.json").map((record) => record.body_read_status), ["available", "rejected"]);
  assert.equal(x.saved.has("offline/bulk-1a-envelopes.json"), false, "evidence is not complete canonical capture");
});

test("public hit and highlight schemas cannot retain nested private fields", async () => {
  const data = fixture();
  const hit = data.payload.results[0].hits[0];
  hit._highlightResult.artistName.userToken = "PRIVATE_NESTED_HIGHLIGHT";
  hit._highlightResult.artistName.account = { email: "PRIVATE_NESTED_EMAIL" };
  hit._highlightResult.artistNames = [{ value: "Alice Example", matchLevel: "none", matchedWords: [],
    account: "PRIVATE_NESTED_ARRAY_HIGHLIGHT" }];
  hit.currentBid = { account: "PRIVATE_NESTED_BID" };
  hit.artistNames = [{ account: "PRIVATE_NESTED_ARTISTS" }];
  data.payload.results.push({ page: { account: "PRIVATE_AUX_PAGE" }, nbPages: 1,
    nbHits: { account: "PRIVATE_AUX_COUNT" }, hitsPerPage: 1, hits: [] });
  const x = setup([data]);
  assert.equal((await x.invoke()).total, 1);
  const saved = x.read("bulk-1a-envelopes.json")[0].payload.results[0].hits[0];
  assert.deepEqual(saved._highlightResult.artistName,
    { value: "Alice Example", matchLevel: "none", matchedWords: [] });
  assert.equal(saved.currentBid, undefined); assert.equal(saved.artistNames, undefined);
  assert.equal(x.read("bulk-1a-envelopes.json")[0].payload.results[1].nbHits, null);
  assert(![...x.saved.values()].join("").includes("PRIVATE_"));
});

test("allowlisted request params and unmatched metadata cannot retain nested private objects", async () => {
  const data = fixture();
  data.body.requests[0].params.analyticsTags = [{ userToken: "PRIVATE_NESTED_REQUEST" }];
  const x = setup([data]);
  assert.equal((await x.invoke()).total, 1);
  assert.equal(x.read("bulk-1a-envelopes.json")[0].body.requests[0].params.analyticsTags, undefined);
  assert(![...x.saved.values()].join("").includes("PRIVATE_"));

  const unmatched = fixture();
  unmatched.body.requests[0].params.query = { account: "PRIVATE_UNMATCHED_QUERY" };
  unmatched.body.requests[0].indexName = { account: "PRIVATE_UNMATCHED_INDEX" };
  const y = setup([unmatched]);
  await assert.rejects(y.invoke(), /Incomplete first response triplet/);
  assert.deepEqual(y.bodyReads, []);
  assert(![...y.saved.values()].join("").includes("PRIVATE_"));
});

test("privacy filtering cannot repair an invalid artist identity into an accepted capture", async () => {
  const data = fixture();
  data.payload.results[0].hits[0].artistName = { account: "PRIVATE_MALFORMED_ARTIST" };
  const x = setup([data]);
  await assert.rejects(x.invoke(), /Capture changed during privacy filtering/);
  assert.equal(x.saved.has("offline/bulk-1a-response-evidence.json"), false);
  assert.equal(x.saved.has("offline/bulk-1a-envelopes.json"), false);
  assert(![...x.saved.values()].join("").includes("PRIVATE_"));
});

test("metadata write failure stops before body access", async () => {
  const x = setup([fixture()], { failWrite: (path) => path.endsWith("source-request-metadata.json") });
  await assert.rejects(x.invoke(), /Offline evidence write failed/);
  assert.deepEqual(x.bodyReads, []);
});

test("credential-bearing or noncanonical source endpoint URLs never persist", async () => {
  const data = fixture();
  for (const url of ["https://www.invaluable.com/catResults?apiKey=PRIVATE_URL_KEY",
    "https://www.invaluable.com/catResults#PRIVATE_FRAGMENT", "https://user:PRIVATE_PASSWORD@www.invaluable.com/catResults"]) {
    const events = triplet(data, "request-0", 1);
    events[0].params.request.url = url;
    const x = setup([data], { chunks: [
      { events, cursor: 3, hasMore: false },
      { events: [], cursor: 3, hasMore: false },
    ] });
    await assert.rejects(x.invoke(), /Incomplete first response triplet/);
    assert.deepEqual(x.bodyReads, []);
    assert.equal(x.saved.size, 0);
  }
});

test("request scope survives string-encoded params and unrelated response indexes", async () => {
  const data = fixture();
  const distractor = structuredClone(data.body.requests[0]); distractor.params.query = "other";
  data.body.requests.unshift(distractor);
  data.payload.results.unshift({ page: 9, nbPages: 10, nbHits: 10, hitsPerPage: 1, hits: [] });
  for (const request of data.body.requests) {
    request.params.facetFilters = JSON.stringify(request.params.facetFilters);
    request.params = new URLSearchParams(request.params).toString();
  }
  const x = setup([data]);
  assert.equal((await x.invoke()).total, 1);
  assert.deepEqual(core.matchingRequests(x.read("bulk-1a-envelopes.json")[0].body, core.searchSpec(URL))
    .map((match) => match.index), [1]);
  assert.equal((await x.collector.finishSearch(x.tab, JOB)).lots, 1);
});

test("timestamps remain unique across responses and an existing metadata file", async () => {
  const x = setup([fixture(), fixture(), fixture()]);
  x.saved.set("offline/network-observation-metadata.json", JSON.stringify([{ capturedAt: new Date().toISOString() }]));
  await x.invoke();
  const stamps = x.read("network-observation-metadata.json").map((record) => record.capturedAt);
  assert.equal(new Set(stamps).size, stamps.length);
});

test("requires an ordered completed exact-scope triplet and drains event chunks", async () => {
  const data = fixture(), events = triplet(data, "request-0", 1);
  const x = setup([data], { chunks: [
    { events: events.slice(0, 1), cursor: 1, hasMore: true },
    { events: events.slice(1), cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
  ] });
  assert.equal((await x.invoke()).candidates, 1);
  const unordered = [events[0], { ...events[1], sequence: 0 }, events[2]];
  const y = setup([data], { chunks: [
    { events: unordered, cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
  ] });
  await assert.rejects(y.invoke(), /Incomplete first response triplet/);
  assert.deepEqual(y.bodyReads, []);
});

test("first-page capture preserves a completed triplet when the buffer rolls during the DOM read", async () => {
  const data = fixture(), events = triplet(data, "request-0", 1);
  const x = setup([data]);
  let buffered = events;
  x.cdp.readEvents = async ({ afterSequence = 0 } = {}) => ({
    events: buffered.filter((event) => event.sequence > afterSequence), cursor: 3, hasMore: false,
  });
  x.tab.playwright.domSnapshot = async () => {
    buffered = events.slice(1);
    return "/url: https://www.invaluable.com/auction-lot/offline-c-REF0";
  };
  assert.equal((await x.invoke()).candidates, 1);
  assert.deepEqual(x.bodyReads, ["request-0"]);
  assert.deepEqual(x.read("network-observation-metadata.json")
    .map(({ requestSequence, responseSequence, finishedSequence }) => [requestSequence, responseSequence, finishedSequence]),
  [[1, 2, 3]]);
});

test("first-page capture joins a request with its response and finish arriving during the DOM read", async () => {
  const data = fixture(), events = triplet(data, "request-0", 1);
  const x = setup([data]);
  let buffered = events.slice(0, 1);
  x.cdp.readEvents = async ({ afterSequence = 0 } = {}) => ({
    events: buffered.filter((event) => event.sequence > afterSequence),
    cursor: buffered.at(-1).sequence, hasMore: false,
  });
  x.tab.playwright.domSnapshot = async () => {
    buffered = events;
    return "/url: https://www.invaluable.com/auction-lot/offline-c-REF0";
  };
  assert.equal((await x.invoke()).candidates, 1);
  assert.deepEqual(x.bodyReads, ["request-0"]);
  assert.deepEqual(x.read("network-observation-metadata.json")
    .map(({ requestSequence, responseSequence, finishedSequence }) => [requestSequence, responseSequence, finishedSequence]),
  [[1, 2, 3]]);
});

test("Load more advances the real request page and retains final DOM coverage", async () => {
  const first = fixture(0, 2), second = fixture(1, 2);
  const x = setup([first, second], { chunks: [
    { events: triplet(first, "request-0", 1), cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
    { events: triplet(second, "request-1", 4), cursor: 6, hasMore: false },
  ] });
  assert.equal((await x.invoke()).pages, 2);
  assert.deepEqual(await x.collector.stepDurable(x.tab, x.cdp, JOB, 3), [{ page: 2, nbPages: 2, displayed: 2, missing: 0 }]);
  assert.deepEqual(x.read("bulk-1a-envelopes.json").map((env) => env.payload.results[0].page), [0, 1]);
  const coverage = await x.collector.finishSearch(x.tab, JOB);
  assert.deepEqual({ pages: coverage.pages, lots: coverage.lots, missing: coverage.missing,
    extra: coverage.extra, load_more: coverage.load_more }, { pages: 2, lots: 2, missing: [], extra: [], load_more: 0 });
});

test("Load more waits through unrelated immediate event batches for the matching completed response", async () => {
  const first = fixture(0, 2), second = fixture(1, 2);
  const next = triplet(second, "request-1", 20);
  const x = setup([first, second], { chunks: [
    { events: triplet(first, "request-0", 1), cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
    { events: next.slice(0, 1), cursor: 20, hasMore: false },
    ...Array.from({ length: 12 }, (_, index) => ({ events: [{
      method: "Network.loadingFinished", sequence: 21 + index, params: { requestId: `unrelated-${index}` },
    }], cursor: 21 + index, hasMore: false })),
    { events: [{ ...next[1], sequence: 40 }, { ...next[2], sequence: 41 }], cursor: 41, hasMore: false },
  ] });
  let clicks = 0;
  x.tab.playwright.getByRole = () => ({ click: async () => { clicks += 1; }, count: async () => 0 });
  await x.invoke();
  assert.deepEqual(await x.collector.stepDurable(x.tab, x.cdp, JOB, 1),
    [{ page: 2, nbPages: 2, displayed: 2, missing: 0 }]);
  assert.equal(clicks, 1);
  assert.deepEqual(x.bodyReads, ["request-0", "request-1"]);
  assert.deepEqual(x.read("bulk-1a-envelopes.json").map((env) => env.payload.results[0].page), [0, 1]);
  assert.deepEqual(x.read("network-observation-metadata.json").slice(-1)
    .map(({ requestSequence, responseSequence, finishedSequence }) => [requestSequence, responseSequence, finishedSequence]),
  [[20, 40, 41]]);
});

test("Load more remains bounded by elapsed time and never accepts an incomplete or unordered triplet", async (t) => {
  let clock = 0;
  t.mock.method(Date, "now", () => clock);
  const first = fixture(0, 2), second = fixture(1, 2);
  const next = triplet(second, "request-1", 20);
  for (const pending of [
    next.slice(0, 1),
    [next[0], next[2]],
    [next[0], { ...next[2], sequence: 21 }, { ...next[1], sequence: 22 }],
  ]) {
    clock = 0;
    const x = setup([first, second], { chunks: [
      { events: triplet(first, "request-0", 1), cursor: 3, hasMore: false },
      { events: [], cursor: 3, hasMore: false },
      { events: [], cursor: 3, hasMore: false },
      { events: pending, cursor: 22, hasMore: false },
      ...Array.from({ length: 7 }, () => ({ events: [], cursor: 22, hasMore: false })),
    ] });
    let clicks = 0;
    const waits = [], originalRead = x.cdp.readEvents;
    x.tab.playwright.getByRole = () => ({ click: async () => { clicks += 1; }, count: async () => 0 });
    x.cdp.readEvents = async (options) => {
      if (clicks) { waits.push(options.timeoutMs); clock += 1500; }
      return originalRead(options);
    };
    await x.invoke();
    await assert.rejects(x.collector.stepDurable(x.tab, x.cdp, JOB, 1), /Canonical response incomplete/);
    assert.equal(clock, 12000);
    assert.deepEqual(waits, Array(8).fill(1500));
    assert.equal(clicks, 1);
    assert.deepEqual(x.bodyReads, ["request-0"]);
    assert.equal(x.read("bulk-1a-envelopes.json").length, 1);
  }
});

test("Load more still rejects multiple matching completed responses and retains their evidence", async () => {
  const first = fixture(0, 2), second = fixture(1, 2);
  const x = setup([first, second, second], { chunks: [
    { events: triplet(first, "request-0", 1), cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
    { events: [], cursor: 3, hasMore: false },
    { events: [...triplet(second, "request-1", 20), ...triplet(second, "request-2", 23)], cursor: 25, hasMore: false },
  ] });
  await x.invoke();
  await assert.rejects(x.collector.stepDurable(x.tab, x.cdp, JOB, 1), /Canonical response incomplete/);
  assert.deepEqual(x.bodyReads, ["request-0", "request-1", "request-2"]);
  assert.equal(x.read("bulk-1a-envelopes.json").length, 1);
  assert.equal(x.read("bulk-1a-response-evidence.json").length, 3);
});
