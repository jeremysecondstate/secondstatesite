"use strict";
import test from "node:test";
import assert from "node:assert/strict";
import createCollector, { searchSpec, requestMatches, publicPayload } from "./drouot_browser_collection.mjs";

const entry = (artist) => ({ artist, source_url: "https://drouot.com/en/c/50/lithographs?query=" + encodeURIComponent(artist) });
const ALICE = entry("Alice Example"), BOB = entry("Bob Example");
const endpoint = (query, page) => "https://api.drouot.com/drouot/gingolem/neoGingo/lot/search?"
  + new URLSearchParams({ lang: "en", q: query, cat: "50", page: String(page), facet: page === 1 ? "true" : "false" });

function lot(number) {
  return { id: number, num: number, description: "Alice Example\nOriginal lithograph", auctioneerId: 11,
    photo: { path: "/public/photo.jpg", w: 500, h: 400, account: "PRIVATE_PHOTO" },
    currentWinner: "PRIVATE_WINNER", attributes: { email: "PRIVATE_EMAIL" }, currentBid: 20 };
}
function payload(total, page, options = {}) {
  const length = Math.max(0, Math.min(100, total - (page - 1) * 100));
  return { numFound: total, lots: Array.from({ length }, (_, i) => lot((options.offset || 0) + (page - 1) * 100 + i + 1)),
    account: "PRIVATE_RESPONSE" };
}

function harness({ selected = [ALICE], total = 1, totalByPage = {}, wrongDOM = false, badScope = false,
  delayedFinish = false, failMetadata = false, sameQuery = false, repeatedSecondPage = false,
  initialPage = 1, preservePageOnQuery = false, emptyHousesForExistingQuery = false } = {}) {
  const saved = new Map(), bodies = new Map(), bodyReads = [], events = [];
  let query = sameQuery ? selected[0].artist : "Existing artist", page = initialPage, input = "", sequence = 0,
    houseOpen = false, pendingFinish = null, bodyAttemptedBeforeFinish = false;
  const actions = [];
  const activePayload = () => payload(totalByPage[page] ?? total, page,
    { offset: repeatedSecondPage && page === 2 ? -100 : 0 });
  function request() {
    const requestId = `request-${++sequence}`, first = sequence;
    const data = activePayload();
    const url = endpoint(query, page) + (badScope ? "&auctioneer=11" : "");
    events.push({ method: "Network.requestWillBeSent", sequence: first, params: { requestId,
      request: { method: "GET", url, headers: { Cookie: "PRIVATE_COOKIE" } } } });
    events.push({ method: "Network.responseReceived", sequence: ++sequence,
      params: { requestId, response: { status: 200, mimeType: "application/json", headers: { SetCookie: "PRIVATE_SET" } } } });
    const finished = { method: "Network.loadingFinished", sequence: ++sequence, params: { requestId } };
    if (delayedFinish) pendingFinish = finished; else events.push(finished);
    bodies.set(requestId, data);
  }
  const read = (name) => JSON.parse(saved.get(`offline/${name}`));
  const fs = {
    mkdir: async () => {},
    readFile: async (path) => {
      if (saved.has(path)) return saved.get(path);
      const error = new Error("Not found"); error.code = "ENOENT"; throw error;
    },
    writeFile: async (path, value) => {
      if (failMetadata && path.endsWith("source-request-metadata.json")) throw new Error("Metadata write failed");
      saved.set(path, value);
    },
  };
  const cdp = {
    readEvents: async (options = {}) => {
      if (pendingFinish && options.afterSequence !== undefined) {
        if (pendingFinish.ready) { events.push(pendingFinish); pendingFinish = null; }
        else pendingFinish.ready = true;
      }
      return { events: events.filter((event) => event.sequence > (options.afterSequence || 0)),
        cursor: events.at(-1)?.sequence || 0, hasMore: false };
    },
    send: async (method, { requestId }) => {
      assert.equal(method, "Network.getResponseBody");
      if (!events.some((event) => event.method === "Network.loadingFinished" && event.params.requestId === requestId))
        bodyAttemptedBeforeFinish = true;
      const metadata = read("source-request-metadata.json").find((row) => row.request_id === requestId);
      assert(metadata, "request proof is durable before reading its body");
      assert(metadata.request_sequence < metadata.response_sequence && metadata.response_sequence < metadata.finished_sequence);
      bodyReads.push(requestId);
      return { body: Buffer.from(JSON.stringify(bodies.get(requestId))).toString("base64"), base64Encoded: true };
    },
  };
  const pageURL = () => "https://drouot.com/en/c/50/lithographs"
    + (query ? "?query=" + encodeURIComponent(query) + (page > 1 ? "&page=" + page : "") : "");
  const tab = {
    url: async () => pageURL(),
    goto: async (url) => {
      assert.equal(url, "https://drouot.com/en/c/50/lithographs");
      actions.push(["goto", url]); query = ""; page = 1;
    },
    playwright: {
      domSnapshot: async () => "Offline visible Drouot search",
      evaluate: async () => ({ total_results: activePayload().numFound,
        cards: activePayload().lots.map((raw) => ({ id: String(raw.id + (wrongDOM && query === ALICE.artist ? 1000 : 0)),
          url: `https://drouot.com/en/l/${raw.id}-offline-print`, heading: query, description: raw.description,
          text: `${query} Estimation 20 - 40 EUR`, image_url: "https://cdn.drouot.com/public.jpg" })) }),
      locator: (selector) => {
        assert.equal(selector, '[data-cy="category-search"]');
        return { fill: async (value) => { input = value; actions.push(["fill", value]); },
          press: async (key) => { assert.equal(key, "Enter"); query = input; if (!preservePageOnQuery) page = 1; request(); } };
      },
      getByRole: (role, options = {}) => {
        if (role === "checkbox") return { evaluateAll: async () => {
          assert(houseOpen);
          return emptyHousesForExistingQuery && query ? [] : [{ id: "11", name: "Offline House", checked: false }];
        } };
        if (role === "button") return { click: async () => {
          if (options.name === "Auction houses") houseOpen = true;
          else { assert(options.name instanceof RegExp); houseOpen = false; }
        } };
        assert.equal(role, "link");
        const next = Number(options.name);
        return { count: async () => 1,
          getAttribute: async () => `/en/c/50/lithographs?query=${encodeURIComponent(query)}&page=${next}`,
          click: async () => { assert(next === 1 || next === page + 1); page = next; actions.push(["page", next]); request(); } };
      },
    },
  };
  const collector = createCollector({ fs, runDir: "offline", tab, cdp, selected,
    startDate: "2026-11-01", endDate: "2026-11-08", timeoutMs: 30, pollIntervalMs: 1 });
  return { collector, saved, read, bodyReads, actions, beforeFinish: () => bodyAttemptedBeforeFinish };
}

test("original request scope rejects narrowing, credentials, duplicate params and category changes", () => {
  const spec = searchSpec(ALICE);
  const request = (url) => ({ method: "Network.requestWillBeSent", params: { request: { method: "GET", url } } });
  assert(requestMatches(request(endpoint(ALICE.artist, 1)), spec, 1));
  assert(requestMatches(request(endpoint(ALICE.artist, 1).replace("facet=true", "facet=false")), spec, 1));
  assert.equal(requestMatches(request(endpoint(ALICE.artist, 2).replace("facet=false", "facet=true")), spec, 2), false);
  for (const url of [endpoint(ALICE.artist, 1) + "&auctioneer=11", endpoint(ALICE.artist, 1) + "&q=Other",
    endpoint(ALICE.artist, 1).replace("cat=50", "cat=164"), endpoint(ALICE.artist, 1).replace("https://", "https://user:secret@")])
    assert.equal(requestMatches(request(url), spec, 1), false);
  assert.throws(() => searchSpec({ ...ALICE, source_url: ALICE.source_url + "&page=2" }), /scope/);
});

test("public payload removes account fields recursively and rejects repeated IDs or truncated pages", () => {
  const safe = publicPayload(payload(1, 1), 1);
  assert(!JSON.stringify(safe).includes("PRIVATE_"));
  assert.deepEqual(Object.keys(safe.lots[0].photo).sort(), ["h", "path", "w"]);
  const truncated = payload(101, 1); truncated.lots.pop();
  assert.throws(() => publicPayload(truncated, 1), /Truncated/);
  const repeated = payload(2, 1); repeated.lots[1].id = repeated.lots[0].id;
  assert.throws(() => publicPayload(repeated, 1), /duplicate/);
});

test("only a genuine zero-result first page permits the live lots:null response", () => {
  assert.deepEqual(publicPayload({ numFound: 0, lots: null, searchId: "PRIVATE_SEARCH" }, 1), { numFound: 0, lots: [] });
  assert.throws(() => publicPayload({ numFound: 1, lots: null }, 1), /Invalid/);
  assert.throws(() => publicPayload({ numFound: 0, lots: null }, 2), /Invalid/);
  assert.throws(() => publicPayload({ numFound: 0 }, 1), /Invalid/);
});

test("visible pagination is complete, source proof precedes body reads and only public evidence persists", async () => {
  const x = harness({ total: 103 });
  await x.collector.initialize();
  assert.deepEqual(await x.collector.collectSearch(ALICE), { artist: ALICE.artist, pages: 2, results: 103, complete: true });
  assert.deepEqual(x.actions.filter(([kind]) => kind === "page"), [["page", 2]]);
  const capture = x.read("capture.json");
  assert.equal(capture.format, "secondstate-drouot-browser-capture");
  assert.equal(capture.version, 1);
  assert.deepEqual(capture.auctioneers, { "11": "Offline House" });
  assert.equal(capture.searches[0].source_url, ALICE.source_url);
  assert.deepEqual(capture.searches[0].pages.map((page) => [page.page, page.total_pages, page.lots.length]), [[1, 2, 100], [2, 2, 3]]);
  assert.equal(x.bodyReads.length, 2); assert.equal(x.beforeFinish(), false);
  assert(![...x.saved.values()].join("").includes("PRIVATE_"));
  assert.equal(x.collector.summary().complete, true);
});

test("same-query recapture resets through the verified category and zero results remain explicit complete evidence", async () => {
  const x = harness({ total: 0, sameQuery: true });
  await x.collector.initialize(); await x.collector.collectSearch(ALICE);
  assert.deepEqual(x.actions, [["goto", "https://drouot.com/en/c/50/lithographs"],
    ["goto", "https://drouot.com/en/c/50/lithographs"], ["fill", ALICE.artist]]);
  const page = x.read("capture.json").searches[0].pages[0];
  assert.deepEqual([page.total_results, page.total_pages, page.lots, page.cards], [0, 1, [], []]);
});

test("a query input that retains page two is reset through the verified category before editing", async () => {
  const x = harness({ total: 0, sameQuery: true, initialPage: 2, preservePageOnQuery: true });
  await x.collector.initialize(); await x.collector.collectSearch(ALICE);
  assert.deepEqual(x.actions, [["goto", "https://drouot.com/en/c/50/lithographs"],
    ["goto", "https://drouot.com/en/c/50/lithographs"], ["fill", ALICE.artist]]);
  assert.equal(x.read("capture.json").searches[0].pages[0].page, 1);
  assert.equal(x.collector.summary().complete, true);
});

test("initialize resets an existing zero-result query before reading the full-category auction-house map", async () => {
  const x = harness({ sameQuery: true, total: 0, emptyHousesForExistingQuery: true });
  assert.deepEqual(await x.collector.initialize(), { scopes: 1, auction_houses: 1 });
  assert.deepEqual(x.actions, [["goto", "https://drouot.com/en/c/50/lithographs"]]);
  assert.deepEqual(x.read("auction-houses.json"), { "11": "Offline House" });
});

test("response body waits for loadingFinished even when request and response arrive first", async () => {
  const x = harness({ delayedFinish: true });
  await x.collector.initialize(); await x.collector.collectSearch(ALICE);
  assert.equal(x.beforeFinish(), false); assert.equal(x.bodyReads.length, 1);
});

test("unmatched source scope is never body-read and metadata failure also stops body access", async () => {
  for (const config of [{ badScope: true }, { failMetadata: true }]) {
    const x = harness(config); await x.collector.initialize();
    await assert.rejects(x.collector.collectSearch(ALICE), config.badScope ? /exact-scope/ : /Metadata write/);
    assert.deepEqual(x.bodyReads, []);
    assert.equal(x.collector.summary().complete, false);
  }
});

test("a DOM mismatch retains response evidence, records failure and allows another artist to finish", async () => {
  const x = harness({ selected: [ALICE, BOB], wrongDOM: true });
  await x.collector.initialize();
  await assert.rejects(x.collector.collectSearch(ALICE), /visible page/);
  assert.equal(x.read("search-001-response-evidence.json").length, 1);
  assert.equal(x.read("search-001-failure.json").completed_pages, 0);
  await x.collector.collectSearch(BOB);
  assert.deepEqual(x.collector.summary(), { selected: 2, completed: 1, failed: 1, complete: false, pages: 1, observations: 1 });
  assert.equal(x.read("capture.json").searches[0].artist, BOB.artist);
});

test("changing result totals and repeated IDs across pages preserve the earlier durable page", async () => {
  for (const config of [{ total: 101, totalByPage: { 2: 102 } }, { total: 101, repeatedSecondPage: true }]) {
    const x = harness(config); await x.collector.initialize();
    await assert.rejects(x.collector.collectSearch(ALICE), /total changed|repeated a source lot/);
    assert.equal(x.read("search-001.json").pages.length, 1);
    assert.equal(x.read("search-001-response-evidence.json").length, 2);
    assert.equal(x.collector.summary().complete, false);
  }
});
