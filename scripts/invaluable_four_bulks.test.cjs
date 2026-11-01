"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const core = require("./invaluable_export_snapshot.js");
globalThis.SecondStateInvaluableSnapshot = core;
const rules = require("../browser_extensions/invaluable_collector/state.js");
const names = ["BULK-1A", "BULK-1B", "BULK-2A", "BULK-2B"];
function bookmarks(file) {
  return [...fs.readFileSync(path.join(__dirname, "../docs", file), "utf8")
    .matchAll(/<A\b[^>]*HREF="([^"]+)"[^>]*>([^<]+)<\/A>/gi)]
    .map((match) => ({ url: match[1].replaceAll("&amp;", "&"), title: match[2] }));
}
const exported = bookmarks("artist-links.html");
const selected = names.map((name) => exported.find((entry) => entry.title === name));
const legacy = ["BULK 1", "BULK 2"].map((name) => exported.find((entry) => entry.title === name));

test("the full export queues only the four requested searches, preserving all media and old artists", () => {
  const urls = rules.selectIntakeBookmarks(exported);
  assert.deepEqual(urls, selected.map((entry) => entry.url));
  const watches = rules.normalizeWatches(urls);
  assert.deepEqual(watches.map((watch) => watch.artists.length), [22, 23, 33, 26]);
  const artists = new Set(watches.flatMap((watch) => watch.artists));
  assert.equal(artists.size, 104);
  for (const watch of watches) {
    const spec = core.searchSpec(watch.url);
    assert.deepEqual(spec.facets[1], ["Fine Art:Drawings", "Fine Art:Mixed Media", "Fine Art:Prints"]);
    assert.equal(spec.query, "fine art");
    assert.equal(spec.index, "upcoming_lots_dateTimeUTCUnix_asc_prod");
    assert.ok(new URL(watch.url).searchParams.getAll("artistName").some((name) => name.includes("%20")));
  }
  const old = rules.normalizeWatches(rules.selectIntakeBookmarks(legacy));
  assert.deepEqual(old.map((watch) => watch.artists.length), [46, 36]);
  for (const watch of old) for (const artist of watch.artists) assert.ok(artists.has(artist), artist);
});

test("missing, conflicting, invalid, or identical named searches cannot silently fall back to older bulks", () => {
  assert.throws(() => rules.selectIntakeBookmarks(exported.filter((entry) => entry.title !== "BULK-2B")), /incomplete/);
  assert.throws(() => rules.selectIntakeBookmarks([...exported, { ...selected[0], url: selected[1].url }]), /Conflicting/);
  assert.throws(() => rules.selectIntakeBookmarks(selected.map((entry, i) => i ? entry : { ...entry, url: entry.url + "&token=private" })), /unsupported/);
  assert.throws(() => rules.selectIntakeBookmarks(selected.map((entry) => ({ ...entry, url: selected[0].url }))), /distinct/);
  assert.equal(rules.selectIntakeBookmarks([...exported, selected[0]]).length, 4);
  for (const url of ["not-a-url", "https://example.com/search"])
    assert.throws(() => rules.selectIntakeBookmarks([...selected.map((entry) => ({ ...entry, url })),
      ...legacy]), /search URL/);
});

test("category order and duplicates canonicalize, but request narrowing, widening and AND groups are rejected", () => {
  const spec = core.searchSpec(selected[0].url);
  const reordered = new URL(selected[0].url);
  reordered.searchParams.delete("Fine Art");
  for (const category of ["Drawings", "Prints", "Mixed Media", "Prints"]) reordered.searchParams.append("Fine Art", category);
  assert.equal(core.searchSpec(reordered.href).sourceURL, spec.sourceURL);
  const params = { query: "fine art", page: 0, hitsPerPage: 96, facetFilters: spec.facets,
    filters: "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false AND closed:false AND NOT subcategoryRef:7IA742QGM5" };
  const body = { isCatalogPageRequest: false, requests: [{ indexName: spec.index, params }] };
  assert.equal(core.matchingRequests(body, spec)[0].zeroOnly, false);
  for (const facets of [
    [spec.facets[0], ["Fine Art:Prints"]],
    [spec.facets[0], [...spec.facets[1], "Fine Art:Painting"]],
    [spec.facets[0], ...spec.facets[1].map((value) => [value])],
    [[...spec.facets[0], ...spec.facets[1]]],
  ]) assert.deepEqual(core.matchingRequests({ ...body, requests: [{ indexName: spec.index, params: { ...params, facetFilters: facets } }] }, spec), []);
});
