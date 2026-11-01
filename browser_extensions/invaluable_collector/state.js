/* Pure collector rules. No network, browser, or storage access. */
(function (root) {
  "use strict";
  const MAX_BYTES = 7 * 1024 * 1024;
  const MAX_WATCHES = 250;
  const MAX_PAGES = 25;
  const MAX_BULK_PAGES = 100;
  const MAX_SNAPSHOTS = 500;
  const MAX_MESSAGE_BYTES = 2 * 1024 * 1024;
  const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false "
    + "AND closed:false AND NOT subcategoryRef:7IA742QGM5";
  const byteSize = (value) => new TextEncoder().encode(JSON.stringify(value)).length;
  const clone = (value) => JSON.parse(JSON.stringify(value));
  function core() {
    if (!root.SecondStateInvaluableSnapshot) throw new Error("Snapshot validator is unavailable. Rebuild the extension.");
    return root.SecondStateInvaluableSnapshot;
  }
  function validateWindow(window) {
    if (!window || !/^\d{4}-\d{2}-\d{2}$/.test(window.start_date || "")
        || !/^\d{4}-\d{2}-\d{2}$/.test(window.end_date || "")) throw new Error("Choose valid start and end dates.");
    for (const value of [window.start_date, window.end_date]) {
      const stamp = new Date(`${value}T00:00:00Z`);
      if (!Number.isFinite(stamp.getTime()) || stamp.toISOString().slice(0, 10) !== value) throw new Error("Choose valid calendar dates.");
    }
    if (window.end_date < window.start_date) throw new Error("The end date must follow the start date.");
    if ((Date.parse(window.end_date) - Date.parse(window.start_date)) / 86400000 + 1 > 90) throw new Error("Choose a date window of at most 90 days.");
    if (typeof window.time_zone !== "string" || window.time_zone.length > 100) throw new Error("Choose a valid time zone.");
    try { new Intl.DateTimeFormat("en", { timeZone: window.time_zone }).format(); }
    catch { throw new Error("Choose a valid IANA time zone, such as America/New_York."); }
    return { start_date: window.start_date, end_date: window.end_date, time_zone: window.time_zone };
  }
  function normalizeSearch(value) {
    if (typeof value !== "string" || value.length > 8192) throw new Error("Invalid artist search URL.");
    const original = new URL(value);
    if (original.pathname.replace(/\/$/, "") !== "/search") throw new Error("Only artist search bookmarks are supported.");
    for (const key of [...original.searchParams.keys()]) {
      if (["datetimeutcunix[min]", "datetimeutcunix[max]", "datetype"].includes(key.toLowerCase())) original.searchParams.delete(key);
    }
    // Validate the supplied scope before normalizing the sort and first page.
    core().searchSpec(original.href);
    const navigation = new URL(original.href);
    // Keep the working bookmark's artist order and repeated URL encoding.
    // Canonical evidence keys are separate from actual browser navigation.
    for (const key of [...navigation.searchParams.keys()]) {
      if (["sort", "page"].includes(key.toLowerCase())) navigation.searchParams.delete(key);
    }
    navigation.searchParams.set("sort", "endDateAsc");
    navigation.hostname = "www.invaluable.com";
    navigation.hash = "";
    const checked = core().searchSpec(navigation.href);
    return { artist: checked.artist, artists: checked.artists, url: navigation.href };
  }
  function normalizeWatches(values) {
    if (!Array.isArray(values) || values.length > 10000) throw new Error("Too many bookmark entries.");
    const watches = new Map();
    for (const value of values) {
      try { const watch = normalizeSearch(value); const key = core().searchSpec(watch.url).sourceURL;
        if (!watches.has(key)) watches.set(key, watch); }
      catch { /* Unrelated and unsupported bookmarks are not imported. */ }
    }
    if (!watches.size) throw new Error("No supported Invaluable artist-search bookmarks were found.");
    const bulk = [...watches.values()].filter((watch) => watch.artists.length > 1);
    const selected = bulk.length ? bulk : [...watches.values()];
    if (selected.length > MAX_WATCHES) throw new Error(`Choose at most ${MAX_WATCHES} searches.`);
    if (bulk.length) return selected.map((watch, index) => ({ ...watch, artist: `Bulk ${index + 1} · ${watch.artists.length} artists` }));
    return selected.sort((a, b) => a.artist.localeCompare(b.artist) || a.url.localeCompare(b.url));
  }
  function selectIntakeBookmarks(entries) {
    if (!Array.isArray(entries) || entries.length > 10000) throw new Error("Too many bookmark entries.");
    const names = ["BULK-1A", "BULK-1B", "BULK-2A", "BULK-2B"];
    const selected = new Map();
    for (const entry of entries) {
      const title = String(entry.title || "").trim().toUpperCase();
      if (!names.includes(title)) continue;
      let url;
      try { url = new URL(entry.url); } catch { throw new Error(`${title} has an invalid search URL.`); }
      if (!["invaluable.com", "www.invaluable.com"].includes(url.hostname)) throw new Error(`${title} must use an Invaluable search URL.`);
      const watch = normalizeSearch(entry.url);
      if (watch.artists.length < 2) throw new Error(`${title} must contain a bulk artist search.`);
      const key = core().searchSpec(watch.url).sourceURL;
      if (selected.has(title) && selected.get(title).key !== key) throw new Error(`Conflicting ${title} bookmarks.`);
      selected.set(title, { url: entry.url, key });
    }
    if (!selected.size) return entries.map((entry) => entry.url);
    const missing = names.filter((name) => !selected.has(name));
    if (missing.length) throw new Error(`The four-list export is incomplete. Missing ${missing.join(", ")}.`);
    if (new Set([...selected.values()].map((entry) => entry.key)).size !== names.length) {
      throw new Error("The four bulk bookmarks must contain distinct searches.");
    }
    return names.map((name) => selected.get(name).url);
  }
  function pageLimit(watch) {
    return (watch.artists || core().searchSpec(watch.url).artists).length > 1 ? MAX_BULK_PAGES : MAX_PAGES;
  }
  function pageURL(watch, page) {
    if (!Number.isSafeInteger(page) || page < 0 || page >= pageLimit(watch)) throw new Error("The page limit was reached.");
    const url = new URL(watch.url);
    if (page) url.searchParams.set("page", String(page + 1));
    core().searchSpec(url.href);
    return url.href;
  }
  function makeRun(urls, window, id, now) {
    const watches = normalizeWatches(urls);
    return { version: 1, id, created_at: now, status: "ready", window: validateWindow(window), watches,
      current_index: 0, target: null, tab_id: null, snapshots: [],
      progress: watches.map((watch) => ({ artist: watch.artist, source_url: watch.url, status: "queued",
        next_page: 0, captured_pages: [], reported_pages: null, reported_lots: null, hits_per_page: null, captured_lots: 0,
        last_captured_at: "", note: "" })), note: "Ready to start." };
  }
  function prepareTarget(state, nonce, now) {
    const next = clone(state);
    if (next.current_index >= next.watches.length) {
      next.status = "complete"; next.target = null; next.note = "Queue finished. Export the captured results."; return next;
    }
    const row = next.progress[next.current_index];
    if (row.next_page >= pageLimit(next.watches[next.current_index])) throw new Error("The search page limit was reached. Skip this search or export partial results.");
    next.status = "running"; row.status = "loading"; row.note = "Waiting for the page's own catalog response.";
    next.target = { url: next.watches[next.current_index].url,
      source_url: pageURL(next.watches[next.current_index], row.next_page), nonce,
      started_at: now, index: next.current_index, page: row.next_page };
    next.note = `Loading ${row.artist}, page ${row.next_page + 1}.`;
    return next;
  }
  function pause(state, note, rowStatus = "paused") {
    const next = clone(state);
    next.status = "paused"; next.target = null; next.note = note;
    const row = next.progress[next.current_index];
    if (row) { row.status = rowStatus; row.note = note; }
    return next;
  }
  function sameSearch(left, right) {
    try { return core().searchSpec(left).sourceURL === core().searchSpec(right).sourceURL; }
    catch { return false; }
  }
  function sameScope(left, right) {
    try {
      const base = (value) => {
        const url = new URL(value);
        for (const key of [...url.searchParams.keys()]) if (key.toLowerCase() === "page") url.searchParams.delete(key);
        return core().searchSpec(url.href).sourceURL;
      };
      return base(left) === base(right);
    } catch { return false; }
  }
  function validatedSnapshot(snapshot, targetURL, now) {
    if (!snapshot || typeof snapshot !== "object" || byteSize(snapshot) > MAX_MESSAGE_BYTES) throw new Error("Snapshot is missing or exceeds the size limit.");
    if (!sameSearch(snapshot.source_url, targetURL)) throw new Error("Snapshot does not match the current artist, filters, or page.");
    if (!Array.isArray(snapshot.results) || snapshot.results.length !== 1) throw new Error("Snapshot must contain one results page.");
    if (typeof snapshot.captured_at !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(snapshot.captured_at)) throw new Error("Snapshot lacks an original zoned capture time.");
    const stamp = Date.parse(snapshot.captured_at);
    if (!Number.isFinite(stamp) || stamp > Date.parse(now) + 300000) throw new Error("Snapshot capture time is invalid.");
    const spec = core().searchSpec(targetURL);
    const result = snapshot.results[0];
    // Reapply the shared field/cardinality validator to the public snapshot.
    // This reconstructed validation envelope is never sent to Invaluable.
    const verified = core().makeSnapshot({ pageURL: targetURL, requestURL: `${spec.origin}/catResults`, method: "POST",
      body: { isCatalogPageRequest: false, requests: [{ indexName: spec.index, params: {
        query: spec.query, facetFilters: spec.facets, filters: FILTERS, page: spec.page, hitsPerPage: result?.hitsPerPage,
      } }] }, payload: { results: [result] }, capturedAt: snapshot.captured_at });
    if (!verified) throw new Error("Snapshot fields, artist, or pagination could not be verified.");
    return verified;
  }
  function acceptCapture(state, message, senderTabId, now) {
    const target = state.target;
    if (state.status !== "running" || !target || senderTabId !== state.tab_id
        || message.nonce !== target.nonce || !sameScope(message.page_url, target.url)) throw new Error("Stale or unrelated capture ignored.");
    const snapshot = validatedSnapshot(message.snapshot, target.source_url || target.url, now);
    if (Date.parse(snapshot.captured_at) < Date.parse(target.started_at) - 1000) throw new Error("Capture predates this navigation.");
    const next = clone(state);
    const result = snapshot.results[0];
    const row = next.progress[target.index];
    if (row.reported_pages !== null && (row.reported_pages !== result.nbPages || row.reported_lots !== result.nbHits
        || row.hits_per_page !== result.hitsPerPage)) {
      throw new Error("The source's result totals or page size changed during capture. Export partial results and start a new run.");
    }
    const previousIds = new Set();
    for (const prior of next.snapshots) {
      const url = new URL(prior.source_url); url.searchParams.delete("page");
      if (!sameSearch(url.href, next.watches[target.index].url) || prior.source_url === snapshot.source_url) continue;
      for (const hit of prior.results[0].hits) previousIds.add(String(hit.objectID || hit.lotRef));
    }
    if (result.hits.some((hit) => previousIds.has(String(hit.objectID || hit.lotRef)))) {
      throw new Error("A lot appeared on more than one results page. Export partial results and restart this artist's capture.");
    }
    const oldIndex = next.snapshots.findIndex((old) => old.source_url === snapshot.source_url);
    if (oldIndex >= 0) {
      if (Date.parse(next.snapshots[oldIndex].captured_at) > Date.parse(snapshot.captured_at)) throw new Error("A newer capture is already saved.");
      next.snapshots[oldIndex] = snapshot;
    } else {
      if (next.snapshots.length >= MAX_SNAPSHOTS) throw new Error(`The ${MAX_SNAPSHOTS}-snapshot limit was reached. Export this run before starting another.`);
      next.snapshots.push(snapshot);
    }
    row.captured_pages = [...new Set([...row.captured_pages, result.page])].sort((a, b) => a - b);
    row.reported_pages = result.nbPages; row.reported_lots = result.nbHits; row.hits_per_page = result.hitsPerPage; row.last_captured_at = snapshot.captured_at;
    row.captured_lots = next.snapshots.filter((item) => {
      const url = new URL(item.source_url); url.searchParams.delete("page");
      return sameSearch(url.href, next.watches[target.index].url);
    }).reduce((total, item) => total + item.results[0].hits.length, 0);
    row.next_page = result.page + 1;
    next.target = null;
    if (!result.nbPages || row.next_page >= result.nbPages) {
      row.status = "captured"; row.note = "All reported pages captured; import retains unobserved cached lots.";
      next.current_index += 1;
    } else if (row.next_page >= pageLimit(next.watches[target.index])) {
      next.status = "paused"; row.status = "partial"; row.note = `Stopped at the ${pageLimit(next.watches[target.index])}-page limit. Export or skip this search.`;
      next.note = row.note;
    } else { row.status = "queued"; row.note = "Page saved. Continuing to the next page."; }
    if (byteSize(next) > MAX_BYTES) throw new Error("Local capture storage limit reached. Export this run before starting another.");
    return next;
  }
  function skip(state) {
    if (!state || state.current_index >= state.watches.length) throw new Error("There is no current search to skip.");
    const next = clone(state); const row = next.progress[next.current_index];
    row.status = "skipped"; row.note = "Skipped by user; captured pages are retained.";
    next.current_index += 1; next.target = null; next.status = "paused"; next.note = "Search skipped. Resume when ready.";
    return next;
  }
  function exportBundle(state, now) {
    if (!state) throw new Error("Start a capture run first.");
    return { format: "secondstate-invaluable-capture", version: 1, exported_at: now,
      window: clone(state.window), snapshots: clone(state.snapshots),
      progress: state.progress.map((row) => ({ artist: row.artist, source_url: row.source_url, status: row.status,
        captured_pages: row.captured_pages.map((page) => page + 1), reported_pages: row.reported_pages,
        reported_lots: row.reported_lots, captured_lots: row.captured_lots, last_captured_at: row.last_captured_at, note: row.note })) };
  }
  const api = { MAX_BYTES, MAX_WATCHES, MAX_PAGES, MAX_BULK_PAGES, MAX_SNAPSHOTS, MAX_MESSAGE_BYTES, byteSize, normalizeSearch, normalizeWatches, selectIntakeBookmarks,
    validateWindow, pageLimit, pageURL, makeRun, prepareTarget, pause, sameSearch, sameScope, validatedSnapshot, acceptCapture, skip, exportBundle };
  root.SecondStateCollector = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
