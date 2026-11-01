/* Convert observed, privacy-filtered browser response envelopes into a capture.
 * No network access. The source envelopes retain the real visible page URL.
 * Invaluable's Load more leaves that URL unchanged: a snapshot's page locator
 * is therefore normalized from the page number in its actual request/response.
 */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const core = require("./invaluable_export_snapshot.js");
const MAX_CAPTURE_PAGES = 500;
const MAX_CAPTURE_BYTES = 20 * 1024 * 1024;

function calendarDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return NaN;
  const stamp = Date.parse(`${value}T00:00:00.000Z`);
  return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 10) === value ? stamp : NaN;
}

function capturedTime(value, exportedTime, file) {
  const stamp = typeof value === "string" ? Date.parse(value) : NaN;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      || !Number.isFinite(calendarDate(value.slice(0, 10))) || Number(value.slice(11, 13)) > 23
      || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59
      || !Number.isFinite(stamp) || stamp > exportedTime) {
    throw new Error(`Invalid or future capture timestamp in ${file}`);
  }
  return stamp;
}

function buildBundle(files, startDate, endDate, timeZone = "America/New_York") {
  const start = calendarDate(startDate), end = calendarDate(endDate);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start || end - start >= 90 * 86400000) {
    throw new Error("Use valid inclusive ISO start/end dates spanning at most 90 days.");
  }
  if (typeof timeZone !== "string" || !/^[A-Za-z][A-Za-z0-9_+\-/]*$/.test(timeZone)) throw new Error("Use a valid IANA time zone.");
  try { timeZone = new Intl.DateTimeFormat("en", { timeZone }).resolvedOptions().timeZone; }
  catch { throw new Error("Use a valid IANA time zone."); }
  if (!Array.isArray(files) || !files.length) throw new Error("Supply at least one observation file.");
  const exportedTime = Date.now();
  const snapshots = new Map();
  const summaries = [];
  for (const file of files) {
    const envelopes = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!Array.isArray(envelopes) || !envelopes.length) throw new Error(`No observations in ${file}`);
    const pages = new Map();
    const pageConflicts = new Set();
    let sourceKey;
    for (const envelope of envelopes) {
      const actualSpec = core.searchSpec(envelope.pageURL);
      const base = new URL(actualSpec.sourceURL);
      base.searchParams.delete("page");
      if (sourceKey && sourceKey !== base.href) throw new Error(`Mixed search scopes in ${file}`);
      sourceKey = base.href;
      const body = typeof envelope.body === "string" ? JSON.parse(envelope.body) : envelope.body;
      for (const request of body?.requests || []) {
        const params = typeof request.params === "string"
          ? Object.fromEntries(new URLSearchParams(request.params)) : request.params;
        const page = Number(params?.page || 0);
        if (!Number.isSafeInteger(page) || page < 0 || Number(params?.hitsPerPage) <= 0) continue;
        const locator = new URL(base);
        if (page) locator.searchParams.set("page", String(page + 1));
        const snapshot = core.makeSnapshot({ ...envelope, body, pageURL: locator.href });
        if (!snapshot) continue; // Reject unrelated initial hydration requests.
        const timestamp = capturedTime(snapshot.captured_at, exportedTime, file);
        const result = snapshot.results[0];
        if (result.page !== page) throw new Error(`Request/result page mismatch in ${file}`);
        const prior = pages.get(page);
        const priorTime = prior && Date.parse(prior.captured_at);
        if (prior && timestamp === priorTime && JSON.stringify(snapshot.results) !== JSON.stringify(prior.results)) {
          pageConflicts.add(page);
        }
        if (!prior || timestamp > priorTime) {
          pages.set(page, snapshot);
          pageConflicts.delete(page);
        }
      }
    }
    if (pageConflicts.size) throw new Error(`Contradictory captures have the same timestamp in ${file}, page ${[...pageConflicts][0] + 1}`);
    if (!pages.has(0)) throw new Error(`Missing verified first page in ${file}`);
    const first = pages.get(0).results[0];
    const expectedPages = Math.max(1, first.nbPages);
    const seen = new Set();
    const seenRefs = new Set();
    for (let page = 0; page < expectedPages; page++) {
      const snapshot = pages.get(page);
      const result = snapshot?.results[0];
      if (!result || result.nbHits !== first.nbHits || result.nbPages !== first.nbPages || result.hitsPerPage !== first.hitsPerPage) {
        throw new Error(`Incomplete or changing pagination in ${file}, page ${page + 1}`);
      }
      for (const hit of result.hits) {
        const id = String(hit.objectID || hit.lotRef).trim();
        const ref = hit.lotRef.trim();
        if (seen.has(id) || seenRefs.has(ref)) throw new Error(`Repeated lot in ${file}`);
        seen.add(id);
        seenRefs.add(ref);
      }
      if (snapshots.has(snapshot.source_url)) throw new Error(`Repeated search source in ${file}`);
      snapshots.set(snapshot.source_url, snapshot);
      if (snapshots.size > MAX_CAPTURE_PAGES) throw new Error(`A capture may contain at most ${MAX_CAPTURE_PAGES} pages.`);
    }
    if (seen.size !== first.nbHits || pages.size !== expectedPages) throw new Error(`Incomplete search in ${file}`);
    summaries.push({ file, pages: expectedPages, lots: seen.size });
  }
  const bundle = { format: "secondstate-invaluable-capture", version: 1, exported_at: new Date(exportedTime).toISOString(),
    window: { start_date: startDate, end_date: endDate, time_zone: timeZone }, snapshots: [...snapshots.values()] };
  if (Buffer.byteLength(JSON.stringify(bundle, null, 2), "utf8") > MAX_CAPTURE_BYTES) throw new Error("A capture must be at most 20 MiB.");
  return { bundle, summaries };
}

module.exports = { buildBundle };
if (require.main === module) {
  try {
    const [start, end, output, ...files] = process.argv.slice(2);
    if (!output || !files.length) throw new Error("Usage: node build_invaluable_browser_bundle.cjs START END OUTPUT ENVELOPES...");
    const canonicalPath = (file) => {
      const resolved = fs.existsSync(file) ? fs.realpathSync(file) : path.resolve(file);
      return process.platform === "win32" ? resolved.toLowerCase() : resolved;
    };
    if (files.some((file) => canonicalPath(file) === canonicalPath(output))) throw new Error("Output must not overwrite a source observation file.");
    const { bundle, summaries } = buildBundle(files, start, end);
    fs.writeFileSync(output, JSON.stringify(bundle, null, 2));
    process.stdout.write(JSON.stringify({ output, sources: summaries, pages: bundle.snapshots.length }, null, 2) + "\n");
  } catch (error) {
    process.stderr.write(error.message + "\n");
    process.exitCode = 1;
  }
}
