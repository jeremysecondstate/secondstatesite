/* Supported-browser orchestration. Supply documented tab/CDP handles from
 * cua_repl; this module only observes requests made by the page. It has no
 * browser/session setup, request replay, interception, or Calendar access.
 */
"use strict";

const METHODS = [
  "Network.requestWillBeSent", "Network.responseReceived",
  "Network.loadingFinished", "Network.loadingFailed",
];
const PUBLIC_FIELDS = new Set([
  "bidCount", "catalogRef", "categoryName", "countryName", "currencyCode", "currencySymbol",
  "currentBid", "dateTimeLocal", "dateTimeUTCUnix", "endTimeUTCUnix", "estimateHigh", "estimateLow",
  "houseName", "location", "lotDescription", "lotNumber", "lotRef", "lotTitle", "objectID",
  "photoPath", "soldPrice", "soldCurrencyCode", "stateName", "subcategoryName", "supercategoryName",
  "artistName", "artistNames", "title",
]);
const SAFE_PARAMS = new Set([
  "query", "facetFilters", "filters", "page", "hitsPerPage", "attributesToRetrieve",
  "attributesToHighlight", "attributesToSnippet", "highlightPreTag", "highlightPostTag",
  "snippetEllipsisText", "restrictHighlightAndSnippetArrays", "facets", "maxValuesPerFacet",
  "facetingAfterDistinct", "getRankingInfo", "responseFields", "analytics", "analyticsTags",
  "clickAnalytics",
]);

function publicParam(value) {
  if (value === null || ["string", "boolean"].includes(typeof value)
      || (typeof value === "number" && Number.isFinite(value))) return value;
  if (Array.isArray(value)) {
    const items = value.map(publicParam);
    if (items.every((item) => item !== undefined)) return items;
  }
  if (value && typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length) return {};
  return undefined;
}

function sanitizeBody(body) {
  return {
    isCatalogPageRequest: typeof body.isCatalogPageRequest === "boolean" ? body.isCatalogPageRequest : null,
    requests: body.requests.map((request) => {
      const entries = Object.entries(typeof request.params === "string"
        ? Object.fromEntries(new URLSearchParams(request.params)) : request.params || {})
        .filter(([key]) => SAFE_PARAMS.has(key))
        .map(([key, value]) => [key, publicParam(value)]).filter(([, value]) => value !== undefined);
      return { indexName: typeof request.indexName === "string" ? request.indexName : null, params: typeof request.params === "string"
        ? new URLSearchParams(entries).toString() : Object.fromEntries(entries) };
    }),
  };
}

const publicScalar = (value) => typeof value === "string" || (typeof value === "number" && Number.isFinite(value));

function sanitizeHighlight(value) {
  if (Array.isArray(value)) return value.map(sanitizeHighlight);
  if (!value || typeof value !== "object") return {};
  return Object.fromEntries(Object.entries(value).filter(([key, item]) =>
    (["value", "matchLevel"].includes(key) && typeof item === "string")
    || (key === "matchedWords" && Array.isArray(item) && item.every((word) => typeof word === "string"))
    || (key === "fullyHighlighted" && typeof item === "boolean")));
}

function sanitizeHit(hit) {
  return Object.fromEntries(Object.entries(hit).flatMap(([key, value]) => {
    if (key === "_highlightResult") return [[key, Object.fromEntries(Object.entries(value || {})
      .filter(([field]) => PUBLIC_FIELDS.has(field)).map(([field, item]) => [field, sanitizeHighlight(item)]))]];
    if (!PUBLIC_FIELDS.has(key)) return [];
    if (publicScalar(value)) return [[key, value]];
    if (key === "artistNames" && Array.isArray(value) && value.every((name) => typeof name === "string")) return [[key, value]];
    return [];
  }));
}

function sanitizePayload(payload) {
  const count = (value) => Number.isSafeInteger(value) && value >= 0 ? value : null;
  return {
    results: payload.results.map((result) => ({
      page: count(result.page), nbPages: count(result.nbPages), nbHits: count(result.nbHits), hitsPerPage: count(result.hitsPerPage),
      hits: result.hits.map(sanitizeHit),
    })),
  };
}

function visibleRefs(dom) {
  return new Set([...dom.matchAll(/\/url: (\S+)/g)]
    .map((match) => new URL(match[1], "https://www.invaluable.com").pathname
      .match(/-c-([a-z0-9]+)$/i)?.[1]?.toLowerCase())
    .filter(Boolean));
}

module.exports = ({ fs, runDir, core, selected }) => {
  const file = (name) => `${runDir}/${name}`;
  let busy = false;

  async function readArray(name) {
    try {
      const value = JSON.parse((await fs.readFile(file(name), "utf8")).replace(/^\uFEFF/, ""));
      if (!Array.isArray(value)) throw new Error(`Expected evidence array: ${name}`);
      return value;
    } catch (error) {
      if (error.code === "ENOENT") return [];
      throw error;
    }
  }

  const write = (name, value) => fs.writeFile(file(name), JSON.stringify(value, null, 2));
  async function append(name, value) {
    const records = await readArray(name);
    records.push(value);
    await write(name, records);
  }

  function requestKey(record, request, pageURL) {
    return record.requestId === request.params.requestId
      && record.requestSequence === request.sequence && record.pageURL === pageURL;
  }

  async function persistSourceRequest(request, response, finished, job, body, matches) {
    const records = await readArray("source-request-metadata.json");
    if (!records.some((record) => requestKey(record, request, job.url))) {
      records.push({
        name: job.name, observedAt: new Date().toISOString(), pageURL: job.url,
        requestURL: request.params.request.url, method: request.params.request.method,
        requestId: request.params.requestId, requestSequence: request.sequence,
        responseSequence: response.sequence, finishedSequence: finished.sequence,
        status: response.params.response.status, contentType: response.params.response.mimeType,
        body: sanitizeBody(body), request_scope_checked_before_sanitizing: true,
        request_scope_matches: matches.map(({ index, zeroOnly }) => ({ index, zeroOnly })),
        body_read_status: matches.length ? "pending" : "skipped_unmatched_scope",
      });
      await write("source-request-metadata.json", records);
    }
  }

  async function updateSourceRequest(request, pageURL, state) {
    const records = await readArray("source-request-metadata.json");
    const record = records.find((item) => requestKey(item, request, pageURL));
    if (!record) throw new Error("Missing durable source request metadata");
    Object.assign(record, state);
    await write("source-request-metadata.json", records);
  }

  async function capturedAt() {
    // Independent audits link envelopes and metadata by this exact timestamp.
    // Wait for the real clock on a collision instead of inventing a future time.
    const used = new Set((await readArray("network-observation-metadata.json")).map((row) => row.capturedAt));
    let stamp = new Date().toISOString();
    while (used.has(stamp)) {
      await new Promise((resolve) => setTimeout(resolve, 1));
      stamp = new Date().toISOString();
    }
    return stamp;
  }

  function candidateRequest(event, spec) {
    if (event.method !== "Network.requestWillBeSent") return false;
    const request = event.params.request;
    let endpoint;
    try { endpoint = new URL(request.url); } catch { return false; }
    return endpoint.origin === spec.origin && !endpoint.username && !endpoint.password && !endpoint.search && !endpoint.hash
      && endpoint.pathname.replace(/\/$/, "") === "/catResults" && request.method === "POST";
  }

  function verifiedResult(env, page) {
    const locator = new URL(env.pageURL);
    locator.searchParams.delete("page");
    if (page) locator.searchParams.set("page", String(page + 1));
    const snapshot = core.makeSnapshot({ ...env, pageURL: locator.href });
    if (!snapshot) throw new Error("Saved canonical page failed capture validation");
    return snapshot.results[0];
  }

  async function collectResponses(cdp, job, events, expectedPage, initial = false) {
    const locator = new URL(job.url);
    locator.searchParams.delete("page");
    if (expectedPage) locator.searchParams.set("page", String(expectedPage + 1));
    const spec = core.searchSpec(locator.href);
    const found = [], meta = [], incomplete = [];
    for (const request of events.filter((event) => candidateRequest(event, spec))) {
      const body = JSON.parse(request.params.request.postData);
      // Validate the ORIGINAL request. Removing an unknown narrowing filter
      // before this check could turn an out-of-scope response into a match.
      const matches = core.matchingRequests(body, spec);
      const response = events.find((event) => event.method === "Network.responseReceived"
        && event.params.requestId === request.params.requestId && event.sequence > request.sequence);
      const finished = response && events.find((event) => event.method === "Network.loadingFinished"
        && event.params.requestId === request.params.requestId && event.sequence > response.sequence);
      if (!response || !finished) {
        if (matches.length) incomplete.push(request.params.requestId);
        continue;
      }
      if (response.params.response.status !== 200
          || !response.params.response.mimeType?.toLowerCase().includes("json")) {
        if (matches.length) incomplete.push(request.params.requestId);
        continue;
      }
      await persistSourceRequest(request, response, finished, job, body, matches);
      if (!matches.length) continue;
      const safeBody = sanitizeBody(body);
      const safeMatches = core.matchingRequests(safeBody, spec);
      const matchKeys = (rows) => JSON.stringify(rows.map(({ index, zeroOnly }) => ({ index, zeroOnly })));
      if (matchKeys(matches) !== matchKeys(safeMatches)) {
        await updateSourceRequest(request, job.url, { validation_status: "scope_changed_by_sanitizing" });
        throw new Error("Request scope changed during privacy filtering");
      }

      let result;
      try {
        result = await cdp.send("Network.getResponseBody", { requestId: request.params.requestId });
      } catch (error) {
        await updateSourceRequest(request, job.url, {
          body_read_status: "rejected", body_read_completed_at: new Date().toISOString(),
        });
        throw error;
      }
      await updateSourceRequest(request, job.url, {
        body_read_status: "available", body_read_completed_at: new Date().toISOString(),
      });
      const payload = JSON.parse(result.base64Encoded ? Buffer.from(result.body, "base64").toString("utf8") : result.body);
      const stamp = await capturedAt();
      const source = { pageURL: locator.href, requestURL: request.params.request.url,
        method: request.params.request.method, body, payload, capturedAt: stamp,
        status: response.params.response.status, contentType: response.params.response.mimeType };
      const rawSnapshot = core.makeSnapshot(source);
      const env = { ...source, pageURL: job.url, body: safeBody, payload: sanitizePayload(payload) };
      const snapshot = core.makeSnapshot({ ...env, pageURL: locator.href });
      if (JSON.stringify(snapshot) !== JSON.stringify(rawSnapshot)) {
        await updateSourceRequest(request, job.url, { validation_status: "capture_changed_by_sanitizing" });
        throw new Error("Capture changed during privacy filtering");
      }
      const record = { name: job.name, requestId: request.params.requestId, capturedAt: stamp,
        requestSequence: request.sequence, responseSequence: response.sequence, finishedSequence: finished.sequence,
        page: expectedPage, matched: !!snapshot };
      // Each body and its triplet survive a later read failure in this batch.
      // The journal is evidence only; canonical pagination still passes every
      // normal collection, coverage, builder, and import gate.
      await append("network-observation-metadata.json", record);
      await append(`${job.name.toLowerCase()}-response-evidence.json`, env);
      if (initial) await append(`${job.name.toLowerCase()}-initial-response-evidence.json`, env);
      await updateSourceRequest(request, job.url, { validation_status: snapshot ? "accepted" : "rejected" });
      found.push({ env, snapshot });
      meta.push(record);
    }
    return { found, meta, incomplete };
  }

  async function readEvents(cdp, cursor, options = {}) {
    let result = await cdp.readEvents({ afterSequence: cursor, methods: METHODS, limit: 1000, ...options });
    const events = [...result.events];
    let truncated = !!result.truncated;
    while (result.hasMore) {
      result = await cdp.readEvents({ afterSequence: result.cursor, methods: METHODS, limit: 1000 });
      events.push(...result.events);
      truncated ||= !!result.truncated;
    }
    return { events, cursor: result.cursor, truncated };
  }

  async function retainFirst(tab, cdp, job, cursor) {
    // Preserve requests before a potentially slow DOM read rolls the bounded
    // event buffer, then include responses that finish while cards settle.
    const beforeDOM = await readEvents(cdp, cursor);
    const dom = await tab.playwright.domSnapshot();
    const afterDOM = await readEvents(cdp, beforeDOM.cursor);
    const observed = { events: [...beforeDOM.events, ...afterDOM.events],
      cursor: afterDOM.cursor, truncated: beforeDOM.truncated || afterDOM.truncated };
    const collected = await collectResponses(cdp, job, observed.events, 0, true);
    const exact = collected.found.filter((item) => item.snapshot);
    if (!exact.length || collected.incomplete.length) throw new Error("Incomplete first response triplet");
    await write(`${job.name.toLowerCase()}-envelopes.json`, [exact.at(-1).env]);
    await fs.writeFile(file(`${job.name.toLowerCase()}-first-visible.txt`), dom);
    const result = exact.at(-1).snapshot.results[0];
    return { total: result.nbHits, pages: result.nbPages, candidates: exact.length, truncated: observed.truncated };
  }

  async function stepDurable(tab, cdp, job, count) {
    const name = `${job.name.toLowerCase()}-envelopes.json`;
    const envs = await readArray(name);
    if (!envs.length) throw new Error("Missing verified first page");
    const steps = [];
    for (let index = 0; index < count; index += 1) {
      const previous = verifiedResult(envs.at(-1), envs.length - 1);
      if (previous.page + 1 >= previous.nbPages) break;
      let cursor = (await cdp.readEvents({ methods: METHODS })).cursor;
      await tab.playwright.getByRole("button", { name: "Load more", exact: true }).click();
      const events = [];
      const locator = new URL(job.url);
      locator.searchParams.set("page", String(previous.page + 2));
      const spec = core.searchSpec(locator.href);
      // readEvents may return immediately for unrelated page traffic. Bound
      // elapsed time rather than event batches so that traffic cannot consume
      // the wait before the requested catalog response has finished.
      const deadline = Date.now() + 12000;
      while (Date.now() < deadline) {
        const remaining = Math.max(1, deadline - Date.now());
        const observed = await readEvents(cdp, cursor, { timeoutMs: Math.min(1500, remaining) });
        events.push(...observed.events);
        cursor = observed.cursor;
        const requests = events.filter((event) => candidateRequest(event, spec)
          && core.matchingRequests(JSON.parse(event.params.request.postData), spec).length);
        if (requests.some((request) => {
          const response = events.find((event) => event.method === "Network.responseReceived"
            && event.params.requestId === request.params.requestId && event.sequence > request.sequence);
          return response && events.some((event) => event.method === "Network.loadingFinished"
            && event.params.requestId === request.params.requestId && event.sequence > response.sequence);
        })) break;
      }
      const collected = await collectResponses(cdp, job, events, previous.page + 1);
      const exact = collected.found.filter((item) => item.snapshot);
      if (exact.length !== 1 || collected.incomplete.length) throw new Error("Canonical response incomplete");
      const item = exact[0];
      if (item.snapshot.results[0].page !== previous.page + 1) throw new Error("Page skipped");
      envs.push(item.env);
      await write(name, envs);
      let dom = await tab.playwright.domSnapshot();
      let refs = visibleRefs(dom);
      const hits = envs.flatMap((env, page) => verifiedResult(env, page).hits);
      if (refs.size < hits.length) {
        await cdp.readEvents({ afterSequence: cursor, methods: ["Network.loadingFinished"], timeoutMs: 1500 });
        dom = await tab.playwright.domSnapshot();
        refs = visibleRefs(dom);
      }
      const missing = hits.map((hit) => hit.lotRef.toLowerCase()).filter((ref) => !refs.has(ref));
      await fs.writeFile(file(`${job.name.toLowerCase()}-visible-state.txt`), dom);
      steps.push({ page: previous.page + 2, nbPages: previous.nbPages, displayed: refs.size, missing: missing.length });
      if (missing.length) break;
    }
    return steps;
  }

  async function finishSearch(tab, job) {
    const envs = await readArray(`${job.name.toLowerCase()}-envelopes.json`);
    if (!envs.length) throw new Error("Missing verified first page");
    const dom = await tab.playwright.domSnapshot();
    await fs.writeFile(file(`${job.name.toLowerCase()}-visible-state.txt`), dom);
    const refs = visibleRefs(dom);
    const wanted = new Set(envs.flatMap((env, page) => verifiedResult(env, page).hits.map((hit) => hit.lotRef.toLowerCase())));
    const result = { name: job.name, pages: envs.length, lots: wanted.size, visible_refs: refs.size,
      source_url: job.url, actual_page_url: await tab.url(),
      load_more: await tab.playwright.getByRole("button", { name: "Load more", exact: true }).count(),
      missing: [...wanted].filter((ref) => !refs.has(ref)), extra: [...refs].filter((ref) => !wanted.has(ref)) };
    await append("browser-coverage.json", result);
    return result;
  }

  const exclusive = (operation) => async (...args) => {
    if (busy) throw new Error("Run browser collection operations sequentially");
    busy = true;
    try { return await operation(...args); } finally { busy = false; }
  };
  return { retainFirst: exclusive(retainFirst), stepDurable: exclusive(stepDurable), finishSearch: exclusive(finishSearch) };
};
