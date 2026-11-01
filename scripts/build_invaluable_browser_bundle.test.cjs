"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");
const { buildBundle } = require("./build_invaluable_browser_bundle.cjs");
const { searchSpec } = require("./invaluable_export_snapshot.js");

const PAGE = "https://www.invaluable.com/search?artistName=Alice%20Example&artistName=Bob%20Example&Fine%20Art=Prints&sort=enddateasc&query=fine%20art";
const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false AND closed:false AND NOT subcategoryRef:7IA742QGM5";
const STAMP = "2020-01-01T12:00:00.000Z";

function envelope(page = 0, count = 3, size = 2, offset = page * size) {
  const spec = searchSpec(PAGE);
  const hits = Array.from({ length: Math.min(size, Math.max(0, count - page * size)) }, (_, index) => ({
    objectID: `ID${offset + index}`, lotRef: `REF${offset + index}`, lotTitle: `Lot ${offset + index}`,
    _highlightResult: { artistName: { value: spec.artists[index % 2], matchLevel: "none", matchedWords: [] } },
    account: "private-response-value",
  }));
  return { pageURL: PAGE, requestURL: "https://www.invaluable.com/catResults", method: "POST", capturedAt: STAMP,
    body: { isCatalogPageRequest: false, requests: [{ indexName: spec.index, params: {
      query: spec.query, facetFilters: spec.facets, filters: FILTERS, page, hitsPerPage: size, userToken: "private-request-value",
    } }] },
    payload: { results: [{ page, nbPages: Math.ceil(count / size), nbHits: count, hitsPerPage: size, hits }] },
  };
}

function observations(t, rows, name = "observed.json") {
  const temporaryRoot = fs.realpathSync(os.tmpdir());
  const folder = fs.mkdtempSync(path.join(temporaryRoot, "secondstate-browser-bundle-"));
  t.after(() => {
    const resolved = fs.realpathSync(folder);
    assert.equal(path.dirname(resolved), temporaryRoot);
    assert.ok(path.basename(resolved).startsWith("secondstate-browser-bundle-"));
    fs.rmSync(resolved, { recursive: true, force: true });
  });
  const file = path.join(folder, name);
  fs.writeFileSync(file, JSON.stringify(rows));
  return file;
}

function build(files, start = "2026-10-21", end = "2026-11-01", zone = "America/New_York") {
  return buildBundle(files, start, end, zone);
}

test("maps natural Load more request pages to source locators without changing source observations", (t) => {
  const first = envelope();
  // An unrelated hydration request must neither establish a page nor shift
  // the result index of the exact selected search.
  const distractor = structuredClone(first.body.requests[0]);
  distractor.params.query = "other query";
  distractor.params.page = 19;
  first.body.requests.unshift(distractor);
  first.payload.results.unshift({ page: 19, nbPages: 20, nbHits: 40, hitsPerPage: 2, hits: [] });
  const second = envelope(1);
  second.body = JSON.stringify(second.body);
  const file = observations(t, [second, first]);
  const original = fs.readFileSync(file, "utf8");
  const { bundle, summaries } = build([file]);
  assert.deepEqual(bundle.snapshots.map((item) => item.results[0].page), [0, 1]);
  assert.equal(new URL(bundle.snapshots[1].source_url).searchParams.get("page"), "2");
  assert.equal(new URL(bundle.snapshots[0].source_url).searchParams.get("page"), null);
  assert.equal(bundle.snapshots[1].captured_at, STAMP);
  assert.deepEqual(summaries, [{ file, pages: 2, lots: 3 }]);
  assert.ok(!JSON.stringify(bundle).includes("private-"));
  assert.equal(fs.readFileSync(file, "utf8"), original);
});

test("scope mismatches and missing pages cannot become complete capture bundles", (t) => {
  const wrong = envelope(1);
  wrong.body.requests[0].params.facetFilters[0].pop();
  assert.throws(() => build([observations(t, [envelope(), wrong])]), /Incomplete/);
  const mixed = envelope(1);
  mixed.pageURL += "&artistName=Third";
  assert.throws(() => build([observations(t, [envelope(), mixed])]), /Mixed search scopes/);
  const mismatch = envelope(1);
  mismatch.payload.results[0].page = 0;
  assert.throws(() => build([observations(t, [envelope(), mismatch])]), /Incomplete/);
});

test("selects the newest duplicate page and rejects contradictory equal-time captures", (t) => {
  const old = envelope();
  const newer = structuredClone(old);
  newer.capturedAt = "2020-01-01T12:00:01.000Z";
  newer.payload.results[0].hits[0].lotTitle = "Updated lot title";
  const { bundle } = build([observations(t, [newer, old, envelope(1), structuredClone(newer)])]);
  assert.equal(bundle.snapshots[0].results[0].hits[0].lotTitle, "Updated lot title");
  assert.equal(bundle.snapshots[0].captured_at, newer.capturedAt);
  const supersededConflict = structuredClone(old);
  supersededConflict.payload.results[0].hits[0].lotTitle = "An older conflicting capture";
  assert.doesNotThrow(() => build([observations(t, [old, supersededConflict, newer, envelope(1)])]));
  newer.capturedAt = old.capturedAt;
  assert.throws(() => build([observations(t, [old, newer, envelope(1)])]), /same timestamp/);
});

test("rejects duplicate lot references even when object IDs differ, both within and across pages", (t) => {
  const across = envelope(1);
  across.payload.results[0].hits[0].lotRef = "REF0";
  assert.throws(() => build([observations(t, [envelope(), across])]), /Repeated lot/);
  const within = envelope();
  within.payload.results[0].hits[1].lotRef = " REF0 ";
  assert.throws(() => build([observations(t, [within, envelope(1)])]), /Repeated lot/);
  const sameId = envelope(1);
  sameId.payload.results[0].hits[0].objectID = "ID0";
  assert.throws(() => build([observations(t, [envelope(), sameId])]), /Repeated lot/);
});

test("requires stable page sizes as well as counts and rejects repeated source files", (t) => {
  // All three pages individually have 20 hits/3 pages; their lengths add to 20.
  // Different page sizes still cannot prove that this is one complete search.
  const file = observations(t, [envelope(0, 20, 7, 0), envelope(1, 20, 9, 7), envelope(2, 20, 8, 16)]);
  assert.throws(() => build([file]), /changing pagination/);
  const complete = observations(t, [envelope(), envelope(1)]);
  assert.throws(() => build([complete, complete]), /Repeated search source/);
});

test("retains verified empty results and enforces importer date/timezone limits", (t) => {
  const file = observations(t, [envelope(0, 0)]);
  const result = build([file]);
  assert.equal(result.bundle.snapshots.length, 1);
  assert.equal(result.summaries[0].lots, 0);
  for (const [start, end] of [["2026-02-30", "2026-03-01"], ["2026-11-02", "2026-11-01"],
    ["2026-10-21", "2027-01-19"], ["0000-01-01", "0000-01-02"]]) {
    assert.throws(() => build([file], start, end), /valid inclusive ISO/);
  }
  assert.doesNotThrow(() => build([file], "2026-10-21", "2027-01-18"));
  assert.equal(build([file], undefined, undefined, "america/new_york").bundle.window.time_zone, "America/New_York");
  assert.throws(() => build([file], undefined, undefined, "Unknown/Nowhere"), /time zone/);
  assert.throws(() => build([]), /at least one/);
});

test("rejects invalid, ambiguous, or future capture timestamps without replacing them", (t) => {
  for (const stamp of [undefined, "not-a-time", "2020-01-01T12:00:00", "2020-02-30T12:00:00Z", "2020-01-01T24:00:00Z",
    new Date(Date.now() + 86400000).toISOString()]) {
    const data = envelope(0, 1);
    data.capturedAt = stamp;
    assert.throws(() => build([observations(t, [data])]), /capture timestamp/);
  }
});

test("enforces importer page and serialized byte bounds", (t) => {
  const many = Array.from({ length: 501 }, (_, page) => envelope(page, 501, 1));
  assert.throws(() => build([observations(t, many)]), /at most 500 pages/);
  const large = envelope(0, 1);
  large.payload.results[0].hits[0].lotDescription = "a".repeat(20 * 1024 * 1024);
  assert.throws(() => build([observations(t, [large])]), /at most 20 MiB/);
});

test("CLI refuses to overwrite its raw source observation file", (t) => {
  const file = observations(t, [envelope(), envelope(1)]);
  const original = fs.readFileSync(file, "utf8");
  const run = spawnSync(process.execPath, [path.join(__dirname, "build_invaluable_browser_bundle.cjs"),
    "2026-10-21", "2026-11-01", file, file], { encoding: "utf8" });
  assert.equal(run.status, 1);
  assert.match(run.stderr, /must not overwrite/);
  assert.equal(fs.readFileSync(file, "utf8"), original);
});
