"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
globalThis.SecondStateInvaluableSnapshot = require("../../../scripts/invaluable_export_snapshot.js");
const rules = require("../state.js");
const URL_A = "https://www.invaluable.com/search?artistName=Josef%2520Albers&Fine%20Art=Prints&query=fine%2520art&keyword=fine%2520art&sort=endDateAsc";
const URL_B = "https://www.invaluable.com/search?artistName=Banksy&Fine%20Art=Prints&sort=bidsDesc";
const WINDOW = { start_date: "2026-10-21", end_date: "2026-11-01", time_zone: "America/New_York" };
const NOW = "2026-10-21T12:00:00.000Z";
const LATER = "2026-10-21T12:00:01.000Z";
function pending(urls = [URL_A]) {
  const run = rules.prepareTarget(rules.makeRun(urls, WINDOW, "run-1", NOW), "nonce-1", NOW);
  run.tab_id = 42; return run;
}
function hit(id, day = "2026-10-25T12:00:00Z", extras = {}) {
  return { objectID: id, lotRef: `ref${id}`, lotTitle: `Print ${id}`, artistName: "Josef Albers",
    dateTimeUTCUnix: Date.parse(day) / 1000, currentBid: 100, ...extras };
}
function message(run, hits = [hit("1")], total = hits.length, perPage = hits.length || 1) {
  return { nonce: run.target.nonce, page_url: run.target.url,
    snapshot: { source_url: run.target.url, captured_at: LATER,
      results: [{ page: run.target.page, nbHits: total, nbPages: Math.ceil(total / perPage), hitsPerPage: perPage, hits }] } };
}
test("bookmark normalization excludes unrelated/private URLs and coalesces encoding and sort variants", () => {
  const watches = rules.normalizeWatches([URL_A, rules.normalizeSearch(URL_A).url, URL_B,
    "https://drive.google.com/drive/folders/private", "https://www.invaluable.com/search?artistName=A&token=secret",
    "https://user:pass@www.invaluable.com/search?artistName=A", "http://www.invaluable.com/search?artistName=A"]);
  assert.equal(watches.length, 2);
  assert.equal(watches[0].artist, "Banksy");
  assert.match(watches[0].url, /sort=endDateAsc/);
  assert.equal(watches[1].artist, "Josef Albers");
});
test("window requires real calendar dates, an IANA zone, ordered dates and at most 90 inclusive days", () => {
  assert.deepEqual(rules.validateWindow(WINDOW), WINDOW);
  for (const invalid of [{ ...WINDOW, start_date: "2026-02-30" }, { ...WINDOW, time_zone: "bad/zone" },
    { ...WINDOW, end_date: "2026-10-20" }, { ...WINDOW, end_date: "2027-02-01" }]) assert.throws(() => rules.validateWindow(invalid));
});
test("stale recognized bookmark date filters are removed while the artist and print scope survive", () => {
  const watch = rules.normalizeSearch("https://invaluable.com/search?artistName=Jim%2520Dine&Fine%20Art=Prints&query=fine%2520art&sort=endDateAsc&dateTimeUTCUnix[max]=1792565999&dateType=Custom");
  assert.equal(watch.artist, "Jim Dine");
  const url = new URL(watch.url);
  assert.equal(url.hostname, "www.invaluable.com");
  assert.equal(url.searchParams.get("Fine Art"), "Prints");
  assert.equal(url.searchParams.get("query"), "fine art");
  assert.equal(url.searchParams.has("dateTimeUTCUnix[max]"), false);
  assert.equal(url.searchParams.has("dateType"), false);
});
test("unrelated tab, nonce, artist, page, and earlier capture are rejected without mutating the run", () => {
  const run = pending(); const original = JSON.stringify(run); const item = message(run);
  assert.throws(() => rules.acceptCapture(run, item, 43, LATER), /unrelated/);
  assert.throws(() => rules.acceptCapture(run, { ...item, nonce: "old" }, 42, LATER), /unrelated/);
  assert.throws(() => rules.acceptCapture(run, { ...item, page_url: URL_B }, 42, LATER), /unrelated/);
  assert.throws(() => rules.acceptCapture(run, { ...item, snapshot: { ...item.snapshot, captured_at: "2026-10-20T12:00:00Z" } }, 42, LATER), /predates/);
  assert.equal(JSON.stringify(run), original);
});
test("capture preserves source time, strips account fields and reaches complete after all pages", () => {
  const run = pending(); const item = message(run, [hit("1", undefined, { userToken: "never", account: { email: "never" } })]);
  item.snapshot.extra = "never";
  const accepted = rules.acceptCapture(run, item, 42, LATER);
  assert.equal(accepted.current_index, 1);
  assert.equal(accepted.progress[0].status, "captured");
  assert.equal(accepted.snapshots[0].captured_at, LATER);
  assert.equal(JSON.stringify(accepted.snapshots).includes("never"), false);
  const finished = rules.prepareTarget(accepted, "nonce-2", LATER);
  assert.equal(finished.status, "complete");
  const bundle = rules.exportBundle(finished, LATER);
  assert.equal(bundle.format, "secondstate-invaluable-capture");
  assert.equal(bundle.version, 1);
  assert.equal(bundle.progress[0].captured_pages[0], 1);
  assert.equal(Object.hasOwn(bundle, "tab_id"), false);
});
test("pagination checks result shape and does not advance when a page has malformed cardinality", () => {
  const run = pending(); const item = message(run, [hit("1")], 4, 2);
  assert.throws(() => rules.acceptCapture(run, item, 42, LATER), /pagination/);
  assert.equal(run.snapshots.length, 0);
});
test("zero is a captured page, not authority to delete or end existing lots", () => {
  const accepted = rules.acceptCapture(pending(), message(pending(), [], 0), 42, LATER);
  assert.equal(accepted.progress[0].status, "captured");
  assert.match(accepted.progress[0].note, /retains unobserved/);
  assert.equal(accepted.snapshots[0].results[0].hits.length, 0);
});
test("changing result totals and duplicate lot identities across pages stop capture conservatively", () => {
  let run = pending(); run = rules.acceptCapture(run, message(run, [hit("1")], 2, 1), 42, LATER);
  run = rules.prepareTarget(run, "nonce-2", NOW); run.tab_id = 42;
  assert.throws(() => rules.acceptCapture(run, message(run, [hit("2")], 3, 1), 42, LATER), /totals/);
  assert.throws(() => rules.acceptCapture(run, message(run, [hit("1")], 2, 1), 42, LATER), /more than one/);
  const accepted = rules.acceptCapture(run, message(run, [hit("2")], 2, 1), 42, LATER);
  assert.equal(accepted.progress[0].captured_lots, 2);
});
test("source sort dates beyond the window do not skip later pages with potentially different effective end dates", () => {
  const run = pending();
  const accepted = rules.acceptCapture(run, message(run, [hit("1", "2026-11-01T22:00:00Z"), hit("2", "2026-11-02T06:00:00Z")], 10, 2), 42, LATER);
  assert.equal(accepted.progress[0].status, "queued");
  assert.equal(accepted.snapshots[0].results[0].hits.length, 2);
  assert.equal(accepted.current_index, 0);
  const second = rules.prepareTarget(accepted, "nonce-2", NOW);
  const later = rules.acceptCapture(second, message(second, [hit("3", "2026-11-03T12:00:00Z", { endTimeUTCUnix: Date.parse("2026-10-30T12:00:00Z") / 1000 }), hit("4", "2026-11-04T12:00:00Z")], 10, 2), 42, LATER);
  assert.equal(later.snapshots.length, 2);
  assert.equal(later.snapshots[1].results[0].hits[0].endTimeUTCUnix, Date.parse("2026-10-30T12:00:00Z") / 1000);
});
test("pause invalidates the pending nonce and resume retains captures", () => {
  const run = pending(); const item = message(run); const paused = rules.pause(run, "User paused");
  assert.throws(() => rules.acceptCapture(paused, item, 42, LATER), /unrelated/);
  const resumed = rules.prepareTarget(paused, "new-nonce", NOW); resumed.tab_id = 42;
  assert.throws(() => rules.acceptCapture(resumed, item, 42, LATER), /unrelated/);
  const skipped = rules.skip(resumed);
  assert.equal(skipped.current_index, 1);
  assert.equal(skipped.progress[0].status, "skipped");
});
test("per-page, total snapshot, storage and page limits fail without silently discarding data", () => {
  const run = pending(); const oversized = message(run, [hit("1", undefined, { lotDescription: "x".repeat(rules.MAX_MESSAGE_BYTES) })]);
  assert.throws(() => rules.acceptCapture(run, oversized, 42, LATER), /size limit/);
  const full = pending();
  full.snapshots = Array.from({ length: rules.MAX_SNAPSHOTS }, (_, index) => ({ source_url: `${URL_B}&page=${index + 2}`, captured_at: NOW,
    results: [{ hits: [] }] }));
  assert.throws(() => rules.acceptCapture(full, message(full), 42, LATER), /snapshot limit/);
  assert.throws(() => rules.pageURL(run.watches[0], 25), /page limit/);
  const storage = pending(); storage.note = "x".repeat(rules.MAX_BYTES);
  assert.throws(() => rules.acceptCapture(storage, message(storage), 42, LATER), /storage limit/);
});
