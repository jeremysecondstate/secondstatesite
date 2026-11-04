"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");
const { searchSpec, matchingRequests, makeSnapshot, inspectCapture, snapshotIsCurrent, snapshotFromCandidate, observeCatalog } = require("./invaluable_export_snapshot.js");

const PAGE = "https://www.invaluable.com/search?artistName=Josef%2520Albers&Fine%20Art=Prints&query=fine%2520art&keyword=fine%2520art&sort=endDateAsc";
const ENDPOINT = "https://www.invaluable.com/catResults";
const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false AND closed:false AND NOT subcategoryRef:7IA742QGM5";
const STAMP = "2026-10-16T18:00:00.000Z";
// Exact public BULK 1 / BULK 2 URLs retained in artist-links.html's OLD folders.
const BULK_URLS = [
  "https://www.invaluable.com/search?artistName=George%2520Rodrigue&artistName=Joan%2520Mir%25C3%25B3&artistName=Francisco%2520de%2520Goya&artistName=Banksy&artistName=Andy%2520Warhol&artistName=Victor%2520Vasarely&artistName=Giovanni%2520Battista%2520Piranesi&artistName=Antoni%2520T%25C3%25A0pies&artistName=Auguste%2520Renoir&artistName=Paul%2520Delvaux&artistName=Shepard%2520Fairey&artistName=Georges%2520Braque&artistName=Thomas%2520Hart%2520Benton&artistName=Alexander%2520%281898%29%2520Calder&artistName=Christo&artistName=Pablo%2520Picasso&artistName=David%2520Hockney&artistName=Wou-Ki%2520Zao&artistName=Roy%2520Lichtenstein&artistName=Henri%2520Matisse&artistName=Lovis%2520Corinth&artistName=Sonia%2520Delaunay&artistName=Damien%2520Hirst&artistName=Josef%2520Albers&artistName=Pierre%2520Alechinsky&artistName=Arman&artistName=Romare%2520Howard%2520Bearden&artistName=Fernando%2520Botero&artistName=Chuck%2520Close&artistName=Marc%2520Chagall&artistName=Henry%2520%281898%29%2520Moore&artistName=Albrecht%2520%281471%29%2520D%25C3%25BCrer&artistName=Peter%2520Max&artistName=Henri%2520de%2520Toulouse-Lautrec&artistName=CHARLY%2520ROCKS&artistName=Elisabeth%2520Frink&artistName=Alphonse%2520Mucha&artistName=David%2520Shrigley&artistName=Keith%2520Haring&artistName=Wifredo%2520Lam&artistName=Rembrandt&artistName=James%2520Rosenquist&artistName=Sam%2520Francis&artistName=Mel%2520Ramos&artistName=Salvador%2520Dal%25C3%25AD&artistName=James%2520Rizzi&Fine%20Art=Prints&sort=endDateAsc&query=fine%2520art&keyword=fine%2520art",
  "https://www.invaluable.com/search?artistName=Elizabeth%2520Catlett&artistName=Willem%2520De%2520Kooning&artistName=Max%2520Ernst&artistName=Richard%2520Estes&artistName=Pedro%2520Friedeberg&artistName=Adolph%2520Gottlieb&artistName=Friedensreich%2520Hundertwasser&artistName=Alex%2520Katz&artistName=Ellsworth%2520Kelly&artistName=Rockwell%2520Kent&artistName=Fernand%2520L%25C3%25A9ger&artistName=Martin%2520Lewis&artistName=Max%2520Liebermann&artistName=Ren%25C3%25A9%2520Magritte&artistName=Alonzo%2520Megargee&artistName=Robert%2520Motherwell&artistName=Takashi%2520Murakami&artistName=Leroy%2520Neimann&artistName=Robert%2520Rauschenberg&artistName=Norman%2520Rockwell&artistName=John%2520%281871%29%2520Sloan&artistName=Frank%2520Stella&artistName=Rufino%2520Tamayo&artistName=Grant%2520Wood&artistName=Francisco%2520Z%25C3%25BA%25C3%25B1iga&artistName=John%2520W%2520Nieto&artistName=Yayoi%2520Kusama&artistName=Louis%2520Icart&artistName=K%25C3%25A4the%2520Kollwitz&artistName=Jerry%2520Garcia&artistName=Derrick%2520Adams&artistName=Will%2520Barnet&artistName=Mr%2520Brainwash&artistName=Jim%2520Dine&artistName=Karel%2520Appel&artistName=Wayne%2520Thiebaud&Fine%20Art=Prints&sort=endDateAsc&query=fine%2520art&keyword=fine%2520art"
];
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

test("extension core loads before a document exists without accessing UI or making requests", () => {
  const context = { __SECONDSTATE_SNAPSHOT_CORE_ONLY__: true, URL, URLSearchParams,
    document: new Proxy({}, { get() { throw new Error("Core touched the page"); } }),
    fetch() { throw new Error("Core made a network request"); } };
  vm.runInNewContext(fs.readFileSync(require.resolve("./invaluable_export_snapshot.js"), "utf8"), context);
  assert.equal(context.SecondStateInvaluableSnapshot.searchSpec(PAGE).artist, "Josef Albers");
  assert.ok(Object.isFrozen(context.SecondStateInvaluableSnapshot));
  assert.equal(context.__SECONDSTATE_SNAPSHOT_CORE_ONLY__, undefined);
  assert.equal(context.SecondStateInvaluableSnapshot.makeSnapshot(fixture()).results[0].nbHits, 1);
});

test("repeatedly encoded artist/search URL becomes verified public source URL", () => {
  const spec = searchSpec(PAGE + "&utm_source=private-tracker");
  assert.equal(spec.artist, "Josef Albers");
  assert.deepEqual(spec.artists, ["Josef Albers"]);
  assert.equal(spec.query, "fine art");
  assert.equal(spec.page, 0);
  assert.deepEqual(spec.facets, [["artistName:Josef Albers"], ["Fine Art:Prints"]]);
  assert.equal(new URL(spec.sourceURL).searchParams.get("artistName"), "Josef Albers");
  assert.ok(!spec.sourceURL.includes("private-tracker"));
  assert.throws(() => searchSpec(PAGE + "&numericFilters=currentBid%3E1000"), /unsupported URL/);
  assert.deepEqual(searchSpec(PAGE + "&artistName=Other").artists, ["Josef Albers", "Other"]);
});

function bulkFixture(pageURL) {
  const data = fixture();
  const spec = searchSpec(pageURL);
  data.pageURL = pageURL;
  data.body.requests[0].params.facetFilters = structuredClone(spec.facets);
  data.body.requests[0].params.query = spec.query;
  data.body.requests[0].indexName = spec.index;
  data.payload.results[0].hits = [spec.artists[0], spec.artists.at(-1)].map((artistName, index) => ({
    ...structuredClone(data.payload.results[0].hits[0]), objectID: String(12345 + index), lotRef: `REF${index}`,
    artistName, lotTitle: `${artistName} print`,
  }));
  data.payload.results[0].nbHits = data.payload.results[0].hits.length;
  return data;
}

test("the supplied 46-artist and 36-artist bulk URLs preserve exact sorted artist sets", () => {
  for (const [index, expected] of [46, 36].entries()) {
    const spec = searchSpec(BULK_URLS[index]);
    assert.equal(spec.artists.length, expected);
    assert.equal(spec.artist, `${expected} artists`);
    assert.deepEqual(spec.artists, [...spec.artists].sort());
    assert.deepEqual(new URL(spec.sourceURL).searchParams.getAll("artistName"), spec.artists);
    assert.deepEqual(spec.facets, [spec.artists.map((name) => `artistName:${name}`), ["Fine Art:Prints"]]);
    assert.equal(spec.query, "fine art");
    const reordered = new URL(spec.sourceURL);
    reordered.searchParams.delete("artistName");
    for (const artist of [...spec.artists].reverse()) reordered.searchParams.append("artistName", artist);
    reordered.searchParams.append("artistName", spec.artists[0]);
    assert.equal(searchSpec(reordered.href).sourceURL, spec.sourceURL);
  }
  assert.ok(searchSpec(BULK_URLS[0]).artists.includes("James Rizzi"));
});

test("bulk snapshots retain each explicit member artist rather than attributing lots to a group", () => {
  for (const url of BULK_URLS) {
    const data = bulkFixture(url);
    const expected = data.payload.results[0].hits.map((hit) => hit.artistName);
    const snapshot = makeSnapshot(data);
    assert.deepEqual(snapshot.results[0].hits.map((hit) => hit.artistName), expected);
    assert.equal(snapshot.source_url, searchSpec(url).sourceURL);
    assert.equal(snapshot.captured_at, STAMP);
    assert.ok(!JSON.stringify(snapshot).includes("never-export"));
    assert.ok(!snapshot.results[0].hits.some((hit) => /\d+ artists/.test(hit.artistName)));
    data.payload.results[0].hits[0].artistName = expected[0].toUpperCase();
    assert.equal(makeSnapshot(data).results[0].hits[0].artistName, expected[0]);
  }
});

const highlight = (value, extra = {}) => ({ value, matchLevel: "none", matchedWords: [], ...extra });

test("natural bulk responses identify artists and public text from Algolia highlight objects", () => {
  for (const url of BULK_URLS) {
    const data = bulkFixture(url);
    const expected = data.payload.results[0].hits.map((hit) => hit.artistName);
    Object.assign(data.body.requests[0].params, {
      attributesToRetrieve: ["lotRef", "lotTitle", "dateTimeUTCUnix"],
      highlightPreTag: "<ais-highlight-0000000000>", highlightPostTag: "</ais-highlight-0000000000>",
    });
    for (const hit of data.payload.results[0].hits) {
      hit._highlightResult = {
        artistName: highlight(hit.artistName), categoryName: highlight("Prints"),
        lotDescription: highlight("A <ais-highlight-0000000000>fine</ais-highlight-0000000000> art print.",
          { matchLevel: "partial", matchedWords: ["fine"], fullyHighlighted: false }),
        supercategoryName: highlight("<ais-highlight-0000000000>Fine Art</ais-highlight-0000000000>",
          { matchLevel: "full", matchedWords: ["fine", "art"], fullyHighlighted: true }),
        account: highlight("never-export-highlight-account"),
      };
      delete hit.artistName;
    }
    const snapshot = makeSnapshot(data);
    assert.deepEqual(snapshot.results[0].hits.map((hit) => hit.artistName), expected);
    assert.equal(snapshot.results[0].hits[0].lotDescription, "A fine art print.");
    assert.equal(snapshot.results[0].hits[0].categoryName, "Prints");
    assert.equal(snapshot.results[0].hits[0].supercategoryName, "Fine Art");
    assert.ok(!JSON.stringify(snapshot).includes("highlight"));
    assert.ok(!JSON.stringify(snapshot).includes("never"));
    assert.equal(inspectCapture(data).accepted, true);
    assert.deepEqual(inspectCapture(data).requests[0].reasons, []);
  }
});

test("token-style source highlights preserve category and description text without markup", () => {
  const data = bulkFixture(BULK_URLS[0]);
  Object.assign(data.body.requests[0].params, {
    highlightPreTag: "__ais-highlight__", highlightPostTag: "__/ais-highlight__",
  });
  const hit = data.payload.results[0].hits[0];
  const artist = hit.artistName;
  hit._highlightResult = {
    artistName: highlight(`__ais-highlight__${artist}__/ais-highlight__`),
    supercategoryName: highlight("__ais-highlight__Fine__/ais-highlight__ __ais-highlight__Art__/ais-highlight__"),
    categoryName: highlight("Prints"),
    lotDescription: highlight("A __ais-highlight__fine art__/ais-highlight__ print."),
  };
  delete hit.artistName;
  const saved = makeSnapshot(data).results[0].hits[0];
  assert.equal(saved.artistName, artist);
  assert.equal(saved.supercategoryName, "Fine Art");
  assert.equal(saved.categoryName, "Prints");
  assert.equal(saved.lotDescription, "A fine art print.");
  assert.ok(!JSON.stringify(saved).includes("ais-highlight"));
});

test("highlight artist text decodes known entities once and strips only balanced known markers", () => {
  const data = bulkFixture(BULK_URLS[0]);
  const hit = data.payload.results[0].hits[0];
  delete hit.artistName;
  for (const value of [
    "Albrecht (1471) D&#252;rer", "Albrecht&#32;(1471) D&#xFC;rer",
    "<ais-highlight-0000000000>Albrecht</ais-highlight-0000000000> (1471) Dürer",
    "<em>Albrecht</em>&nbsp;(1471) Dürer",
    "__ais-highlight__Albrecht__/ais-highlight__ (1471) Dürer",
  ]) {
    hit._highlightResult = { artistName: highlight(value) };
    assert.equal(makeSnapshot(data).results[0].hits[0].artistName, "Albrecht (1471) Dürer", value);
  }
  const entities = bulkFixture("https://www.invaluable.com/search?artistName=Tom%20%26%20Jerry&artistName=Other&Fine%20Art=Prints&sort=enddateasc&query=fine%20art");
  const entityHit = entities.payload.results[0].hits.find((item) => item.artistName === "Tom & Jerry");
  delete entityHit.artistName;
  entityHit._highlightResult = { artistName: highlight("Tom &amp; Jerry") };
  assert.equal(makeSnapshot(entities).results[0].hits.find((item) => item.lotRef === entityHit.lotRef).artistName, "Tom & Jerry");
});

test("direct artist identity has priority but malformed or contradictory highlight identity is rejected", () => {
  const data = bulkFixture(BULK_URLS[0]);
  const hit = data.payload.results[0].hits[0];
  const name = hit.artistName;
  hit._highlightResult = { artistName: highlight(name.toUpperCase()), lotDescription: highlight("Highlight description") };
  hit.lotDescription = "Direct description";
  assert.equal(makeSnapshot(data).results[0].hits[0].artistName, name);
  assert.equal(makeSnapshot(data).results[0].hits[0].lotDescription, "Direct description");
  hit._highlightResult.artistName = highlight(data.payload.results[0].hits[1].artistName);
  assert.equal(makeSnapshot(data), null);
  assert.ok(inspectCapture(data).reasons.includes("hit_artist_conflict"));
  hit._highlightResult.artistName = [highlight(name)];
  assert.equal(makeSnapshot(data), null);
  assert.ok(inspectCapture(data).reasons.includes("hit_artist_highlight_invalid"));
  hit._highlightResult.artistName = highlight(name);
  hit.artistName = null;
  assert.equal(makeSnapshot(data), null);
  assert.ok(inspectCapture(data).reasons.includes("hit_artist_invalid"));
});

test("bulk highlight attribution rejects ambiguous arrays, malformed objects, unsafe markup and foreign names", () => {
  const data = bulkFixture(BULK_URLS[0]);
  const hit = data.payload.results[0].hits[0];
  const name = hit.artistName;
  delete hit.artistName;
  const invalid = [
    null, name, [highlight(name)], { value: name }, highlight([name]),
    highlight(name, { matchLevel: "unknown" }), highlight(name, { matchedWords: name }),
    highlight(name, { matchedWords: [{}] }), highlight(name, { fullyHighlighted: "yes" }),
    highlight(`<strong>${name}</strong>`), highlight(`<em>${name}`), highlight(`${name}</em>`),
    highlight(`<em><em>${name}</em></em>`), highlight(`<em>${name}</ais-highlight-0000000000>`),
    highlight(`__ais-highlight__${name}`), highlight(`${name}__/ais-highlight__`),
    highlight(`__ais-highlight____ais-highlight__${name}__/ais-highlight____/ais-highlight__`),
    highlight(`__ais-highlight__${name}</em>`), highlight(`<em>${name}__/ais-highlight__`),
    highlight(`&lt;em&gt;${name}&lt;/em&gt;`), highlight(`&#0;${name}`),
    highlight(`&#xD800;${name}`), highlight(`&#x110000;${name}`), highlight(`&unknown;${name}`),
  ];
  for (const artist of invalid) {
    hit._highlightResult = { artistName: artist };
    assert.equal(makeSnapshot(data), null, JSON.stringify(artist));
    assert.ok(inspectCapture(data).reasons.includes("hit_artist_highlight_invalid"));
  }
  hit._highlightResult = { artistName: highlight("Unselected artist") };
  assert.equal(makeSnapshot(data), null);
  assert.ok(inspectCapture(data).reasons.includes("hit_artist_not_selected"));
  for (const container of [[{ artistName: highlight(name) }], "not an object"]) {
    hit._highlightResult = container;
    assert.equal(makeSnapshot(data), null);
  }
});

test("single artist fallback stays compatible but verifies any supplied highlighted identity", () => {
  const data = fixture();
  const hit = data.payload.results[0].hits[0];
  assert.equal(makeSnapshot(data).results[0].hits[0].artistName, "Josef Albers");
  hit._highlightResult = { artistName: highlight("Josef Albers"), lotDescription: [highlight("ambiguous")] };
  const snapshot = makeSnapshot(data);
  assert.equal(snapshot.results[0].hits[0].artistName, "Josef Albers");
  assert.ok(!Object.hasOwn(snapshot.results[0].hits[0], "lotDescription"));
  hit._highlightResult.artistName = highlight("Wrong artist");
  assert.equal(makeSnapshot(data), null);
});

test("bulk matching requires the complete artist OR group and separate category AND filter", () => {
  for (const url of BULK_URLS) {
    const spec = searchSpec(url);
    const artists = spec.artists.map((name) => `artistName:${name}`);
    const wrongFilters = [
      [artists.slice(1), ["Fine Art:Prints"]],
      [[...artists.slice(1), "artistName:Unselected artist"], ["Fine Art:Prints"]],
      [...artists.map((artist) => [artist]), ["Fine Art:Prints"]],
      [[...artists, "Fine Art:Prints"]],
      [artists, ["Fine Art:Paintings"]],
    ];
    for (const facetFilters of wrongFilters) {
      const data = bulkFixture(url);
      data.body.requests[0].params.facetFilters = facetFilters;
      assert.equal(makeSnapshot(data), null, JSON.stringify(facetFilters));
    }
    const reordered = bulkFixture(url);
    reordered.body.requests[0].params.facetFilters = [["Fine Art:Prints"], [...artists].reverse()];
    assert.ok(makeSnapshot(reordered));
    const params = reordered.body.requests[0].params;
    reordered.body.requests[0].params = new URLSearchParams({ ...params, facetFilters: JSON.stringify(params.facetFilters) }).toString();
    assert.ok(makeSnapshot(reordered));
  }
});

test("bulk hits with missing, foreign, ambiguous, or non-scalar artist attribution are rejected", () => {
  const member = searchSpec(BULK_URLS[0]).artists[0];
  for (const artistName of [undefined, null, "", "Unselected artist", [member], { name: member }, 0, false]) {
    const data = bulkFixture(BULK_URLS[0]);
    data.payload.results[0].hits[0].artistName = artistName;
    assert.equal(makeSnapshot(data), null, JSON.stringify(artistName));
  }
  const single = fixture();
  assert.equal(makeSnapshot(single).results[0].hits[0].artistName, "Josef Albers");
  single.payload.results[0].hits[0].artistName = ["Josef Albers"];
  assert.equal(makeSnapshot(single), null);
});

test("bulk all-category zero requires the same complete OR artist set and cannot hide narrowed searches", () => {
  const data = bulkFixture(BULK_URLS[0]);
  const artistGroup = searchSpec(data.pageURL).facets[0];
  data.body.requests[0].params.facetFilters = [artistGroup];
  Object.assign(data.payload.results[0], { hits: [], nbHits: 0, nbPages: 0 });
  assert.equal(makeSnapshot(data).results[0].nbHits, 0);
  data.body.requests[0].params.facetFilters = [artistGroup.slice(1)];
  assert.equal(makeSnapshot(data), null);
  data.body.requests[0].params.facetFilters = [artistGroup];
  data.body.requests[0].params.numericFilters = ["currentBid>1000000"];
  assert.equal(makeSnapshot(data), null);
});

test("capture diagnostics expose verified counts and coarse reasons without account or source payload values", () => {
  const data = fixture();
  const report = inspectCapture(data);
  assert.equal(report.accepted, true);
  assert.deepEqual(report.reasons, []);
  assert.equal(report.requests[0].matched, true);
  assert.deepEqual(report.requests[0].requested, { page: 0, hitsPerPage: 96, artist_count: 1 });
  assert.deepEqual(report.requests[0].result, { page: 0, nbPages: 1, nbHits: 1, hitsPerPage: 96, hits_count: 1 });
  const serialized = JSON.stringify(report);
  for (const sensitive of ["never", "Josef", "fine art", "https:", "ABC123", "house/example", "account", "userToken"]) assert.ok(!serialized.includes(sensitive), sensitive);
});

test("diagnostics distinguish capped-looking pagination while leaving acceptance unchanged", () => {
  const data = bulkFixture(BULK_URLS[0]);
  const result = data.payload.results[0];
  result.hits = Array.from({ length: 96 }, (_, index) => ({ ...structuredClone(result.hits[index % 2]), objectID: String(index + 1), lotRef: `ref${index + 1}` }));
  Object.assign(result, { page: 0, nbPages: 11, nbHits: 1527, hitsPerPage: 96 });
  const report = inspectCapture(data);
  assert.equal(report.accepted, false);
  assert.equal(report.requests[0].matched, true);
  assert.deepEqual(report.requests[0].reasons, ["pagination_total_mismatch"]);
  assert.deepEqual(report.requests[0].result, { page: 0, nbPages: 11, nbHits: 1527, hitsPerPage: 96, hits_count: 96 });
  assert.equal(makeSnapshot(data), null);
});

test("diagnostics separate query, artist OR, category, upcoming filter, and unsupported parameter failures", () => {
  const data = bulkFixture(BULK_URLS[0]);
  const params = data.body.requests[0].params;
  params.query = "never-private-query";
  params.facetFilters = [["artistName:never-private-name"], ["Fine Art:Paintings"]];
  params.filters = "never-private-filter";
  params.numericFilters = ["never-private-value"];
  params["never private key"] = "never-private-value";
  const report = inspectCapture(data);
  assert.equal(report.accepted, false);
  for (const code of ["no_matching_request", "query_mismatch", "artist_group_mismatch", "category_group_mismatch", "upcoming_filter_mismatch", "unsupported_request_params"]) assert.ok(report.reasons.includes(code), code);
  assert.deepEqual(report.requests[0].unknown_params, ["numericFilters", "unrecognized_parameter"]);
  assert.ok(!JSON.stringify(report).includes("never"));
});

test("diagnostics identify explicit bulk attribution failures and bound requests", () => {
  const data = bulkFixture(BULK_URLS[0]);
  delete data.payload.results[0].hits[0].artistName;
  assert.ok(inspectCapture(data).reasons.includes("bulk_hit_artist_missing"));
  data.body.requests = Array.from({ length: 30 }, () => structuredClone(data.body.requests[0]));
  const report = inspectCapture(data);
  assert.equal(report.requests.length, 10);
  assert.ok(report.reasons.includes("diagnostic_request_limit"));
  assert.deepEqual(inspectCapture({ pageURL: "https://example.com/private?token=never" }), { accepted: false, reasons: ["page_scope_invalid"], requests: [] });
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

test("Newly Listed Items URL matches the observed catalog sort and exports its lots", () => {
  const data = fixture();
  data.pageURL = PAGE.replace("endDateAsc", "postDateDesc");
  data.body.requests[0].indexName = "upcoming_lots_postDateTime_desc_prod";
  const snapshot = makeSnapshot(data);
  assert.equal(new URL(snapshot.source_url).searchParams.get("sort"), "postdatedesc");
  assert.equal(snapshot.results[0].hits[0].lotRef, "ABC123");
  data.body.requests[0].indexName = "upcoming_lots_dateTimeUTCUnix_asc_prod";
  assert.equal(makeSnapshot(data), null);
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
