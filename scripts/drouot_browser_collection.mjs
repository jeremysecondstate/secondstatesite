/* Observe Drouot's own supported-browser navigation and public responses.
 * Supply documented CUA tab/CDP handles and fs/promises. No request replay,
 * interception, browser-session access, or Calendar access is performed here.
 */
"use strict";

const METHODS = ["Network.requestWillBeSent", "Network.responseReceived",
  "Network.loadingFinished", "Network.loadingFailed"];
const PAGE_SIZE = 100;
const ENDPOINT = "https://api.drouot.com/drouot/gingolem/neoGingo/lot/search";
const BASE = "https://drouot.com/en/c/50/lithographs";
const PUBLIC_FIELDS = new Set(["id", "num", "lowEstim", "highEstim", "currentBid", "nextBid",
  "result", "date", "saleType", "saleStatus", "saleId", "auctioneerId", "saleFees",
  "displayStartingPrice", "bidEndDate", "description", "timezone", "currencyId", "slug"]);

const scalar = (value) => value === null || ["string", "boolean"].includes(typeof value)
  || (typeof value === "number" && Number.isFinite(value));
const id = (value) => (typeof value === "string" || typeof value === "number")
  && /^[1-9][0-9]*$/.test(String(value)) ? String(value) : "";

export function searchSpec(entry) {
  const source = entry?.source_url || entry?.url;
  if (typeof source !== "string") throw new Error("A Drouot bookmark URL is required");
  const url = new URL(source);
  const keys = [...url.searchParams.keys()];
  if (url.origin !== "https://drouot.com" || url.pathname !== "/en/c/50/lithographs"
      || url.username || url.password || url.hash || keys.length !== 1 || keys[0] !== "query"
      || !url.searchParams.get("query")?.trim()) throw new Error("Unsupported Drouot bookmark scope");
  const query = url.searchParams.get("query");
  if (entry.query !== undefined && entry.query !== query) throw new Error("Bookmark query conflicts with its URL");
  const artist = entry.artist || (entry.title || "").split(":")[0].trim();
  if (typeof artist !== "string" || !artist.trim()) throw new Error("Drouot bookmark artist is required");
  return { artist: artist.trim(), query, source_url: source };
}

export function pageMatches(value, spec, page) {
  let url;
  try { url = new URL(value); } catch { return false; }
  const keys = [...url.searchParams.keys()];
  return url.origin === "https://drouot.com" && url.pathname === "/en/c/50/lithographs"
    && !url.username && !url.password && !url.hash
    && keys.every((key) => ["query", "page"].includes(key))
    && url.searchParams.getAll("query").length === 1 && url.searchParams.get("query") === spec.query
    && url.searchParams.getAll("page").length <= 1
    && (page === 1 ? [null, "1"].includes(url.searchParams.get("page")) : url.searchParams.get("page") === String(page));
}

export function requestMatches(event, spec, page) {
  if (event.method !== "Network.requestWillBeSent" || event.params?.request?.method !== "GET") return false;
  let url;
  try { url = new URL(event.params.request.url); } catch { return false; }
  if (`${url.origin}${url.pathname}` !== ENDPOINT || url.username || url.password || url.hash) return false;
  const expected = { lang: "en", q: spec.query, cat: "50", page: String(page) };
  const facets = url.searchParams.getAll("facet");
  if (facets.length !== 1 || !(page === 1 ? ["true", "false"] : ["false"]).includes(facets[0])) return false;
  return [...url.searchParams.keys()].length === Object.keys(expected).length + 1
    && Object.entries(expected).every(([key, value]) => url.searchParams.getAll(key).length === 1
      && url.searchParams.get(key) === value);
}

export function publicPayload(payload, page) {
  if (!payload || typeof payload !== "object"
      || !Number.isSafeInteger(payload.numFound) || payload.numFound < 0) throw new Error("Invalid Drouot lot-search response");
  // The live API represents a genuine empty first-page search with lots:null.
  // No other missing/non-array result collection is evidence of an empty scope.
  const sourceLots = payload.lots === null && payload.numFound === 0 && page === 1 ? [] : payload.lots;
  if (!Array.isArray(sourceLots)) throw new Error("Invalid Drouot lot-search response");
  const expected = Math.max(0, Math.min(PAGE_SIZE, payload.numFound - (page - 1) * PAGE_SIZE));
  if (sourceLots.length !== expected || (page > 1 && !expected)) throw new Error("Truncated or inconsistent Drouot page");
  const seen = new Set();
  const lots = sourceLots.map((lot) => {
    const lotID = id(lot?.id);
    if (!lotID || seen.has(lotID)) throw new Error("Missing or duplicate Drouot source lot ID");
    seen.add(lotID);
    const result = Object.fromEntries(Object.entries(lot).filter(([key, value]) => PUBLIC_FIELDS.has(key) && scalar(value)));
    if (lot.photo && typeof lot.photo === "object" && !Array.isArray(lot.photo)) {
      result.photo = Object.fromEntries(Object.entries(lot.photo)
        .filter(([key, value]) => ["path", "w", "h"].includes(key) && scalar(value)));
    }
    return result;
  });
  return { lots, numFound: payload.numFound };
}

async function readEvents(cdp, cursor, timeoutMs = 1000) {
  let chunk = await cdp.readEvents({ afterSequence: cursor, methods: METHODS, limit: 1000, timeoutMs });
  const events = [...chunk.events];
  let truncated = !!chunk.truncated;
  while (chunk.hasMore) {
    chunk = await cdp.readEvents({ afterSequence: chunk.cursor, methods: METHODS, limit: 1000 });
    events.push(...chunk.events);
    truncated ||= !!chunk.truncated;
  }
  return { events, cursor: chunk.cursor, truncated };
}

function completedTriplets(events, spec, page) {
  return events.filter((event) => requestMatches(event, spec, page)).flatMap((request) => {
    const response = events.find((event) => event.method === "Network.responseReceived"
      && event.params.requestId === request.params.requestId && event.sequence > request.sequence);
    const finished = response && events.find((event) => event.method === "Network.loadingFinished"
      && event.params.requestId === request.params.requestId && event.sequence > response.sequence);
    return response && finished ? [{ request, response, finished }] : [];
  });
}

function sameIDs(left, right) {
  return left.length === right.length && new Set(left).size === left.length
    && new Set(right).size === right.length && left.every((value) => right.includes(value));
}

export default ({ fs, runDir, tab, cdp, selected, startDate, endDate,
  timezone = "America/New_York", timeoutMs = 15000, pollIntervalMs = 100 }) => {
  if (!fs || !tab || !cdp || !runDir || !Array.isArray(selected) || !selected.length)
    throw new Error("Drouot collection requires fs, runDir, tab, cdp and selected bookmarks");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(startDate || "") || !/^\d{4}-\d{2}-\d{2}$/.test(endDate || "")
      || startDate > endDate || timezone !== "America/New_York") throw new Error("Invalid Drouot collection window");
  const specs = selected.map(searchSpec);
  if (new Set(specs.map((spec) => spec.query)).size !== specs.length) throw new Error("Duplicate Drouot search scopes");
  const capture = { format: "secondstate-drouot-browser-capture", version: 1, exported_at: new Date().toISOString(),
    window: { start_date: startDate, end_date: endDate, time_zone: timezone }, auctioneers: {}, searches: [] };
  const failed = new Map();
  let initialized = false, busy = false;
  const pause = async (deadline) => {
    const delay = Math.min(1000, Math.max(1, pollIntervalMs), Math.max(1, deadline - Date.now()));
    await new Promise((resolve) => setTimeout(resolve, delay));
  };
  const file = (name) => `${runDir}/${name}`;
  const write = (name, value) => fs.writeFile(file(name), JSON.stringify(value, null, 2));
  async function append(name, value) {
    let records;
    try { records = JSON.parse(await fs.readFile(file(name), "utf8")); }
    catch (error) { if (error.code !== "ENOENT") throw error; records = []; }
    if (!Array.isArray(records)) throw new Error(`Invalid Drouot evidence journal: ${name}`);
    records.push(value);
    await write(name, records);
  }

  async function readVisible() {
    const pageURL = await tab.url();
    const visible = await tab.playwright.evaluate(() => {
      const text = document.body.innerText;
      const match = text.match(/\b([0-9][0-9\s,.]*)\s+results?\b/i);
      const total = match ? Number(match[1].replace(/[\s,.]/g, "")) : /\bno results\b/i.test(text) ? 0 : null;
      const cards = [...document.querySelectorAll("a[href]")].flatMap((anchor) => {
        const heading = anchor.querySelector("h3");
        const match = anchor.getAttribute("href")?.match(/^\/en\/l\/([0-9]+)(?:[-/]|$)/);
        if (!heading || !match) return [];
        const image = anchor.querySelector("img");
        return [{ id: match[1], url: anchor.href, heading: heading.textContent.trim(),
          description: image?.alt || "", text: anchor.innerText, image_url: image?.src || "" }];
      });
      return { total_results: total, cards };
    });
    return { page_url: pageURL, ...visible };
  }

  async function cursorBefore() {
    return (await cdp.readEvents({ methods: METHODS })).cursor;
  }

  async function prepareCategory() {
    // The live site can retain page=2 after both a query edit and a click on
    // page one. Reset through this already verified category URL, then trigger
    // the requested page-one response with the visible search input.
    await tab.goto(BASE);
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await tab.playwright.domSnapshot();
      const settled = new URL(await tab.url());
      if (settled.origin === "https://drouot.com" && settled.pathname === "/en/c/50/lithographs"
          && !settled.searchParams.get("query")
          && [null, "1"].includes(settled.searchParams.get("page"))) return;
      await readEvents(cdp, await cursorBefore(), 250);
      await pause(deadline);
    }
    throw new Error("Drouot did not reset its category page before changing query");
  }

  async function initialize() {
    if (initialized) return { scopes: specs.length, auction_houses: Object.keys(capture.auctioneers).length };
    await fs.mkdir(runDir, { recursive: true });
    try {
      await write("scope-manifest.json", { start_date: startDate, end_date: endDate, timezone, selected: specs });
      // A prior query may genuinely have no auction-house checkboxes. Start
      // from the verified full category so its mapping covers the run's scope.
      await prepareCategory();
      await collectAuctioneers();
      initialized = true;
      return { scopes: specs.length, auction_houses: Object.keys(capture.auctioneers).length };
    } catch (error) {
      await write("setup-failure.json", { captured_at: new Date().toISOString(), error: String(error.message || error) });
      throw error;
    }
  }

  async function collectAuctioneers() {
    await tab.playwright.getByRole("button", { name: "Auction houses", exact: true }).click();
    await tab.playwright.domSnapshot();
    const houses = await tab.playwright.getByRole("checkbox").evaluateAll((nodes) => nodes.map((node) => ({
      id: node.value, name: node.parentElement.textContent.replace(/\s*\([0-9\s,.]+\)\s*$/, "").trim(), checked: node.checked,
    })));
    if (!houses.length || houses.some((house) => !/^[1-9][0-9]*$/.test(house.id) || !house.name || house.checked))
      throw new Error("Drouot auction-house filter is unreadable or already narrowed");
    for (const house of houses) {
      if (capture.auctioneers[house.id] && capture.auctioneers[house.id] !== house.name)
        throw new Error("Conflicting Drouot auction-house names");
      capture.auctioneers[house.id] = house.name;
    }
    await tab.playwright.getByRole("button", { name: /Show lots/ }).click();
    await tab.playwright.domSnapshot();
    await write("auction-houses.json", capture.auctioneers);
  }

  async function capturePage(spec, page, cursor, name) {
    const events = [], deadline = Date.now() + timeoutMs;
    let triplets = [], truncated = false;
    while (Date.now() < deadline) {
      const observed = await readEvents(cdp, cursor, Math.min(1000, Math.max(1, deadline - Date.now())));
      events.push(...observed.events); cursor = observed.cursor; truncated ||= observed.truncated;
      if (events.some((event) => event.method === "Network.loadingFailed"
          && events.some((request) => requestMatches(request, spec, page) && request.params.requestId === event.params.requestId)))
        throw new Error("Drouot source request failed");
      triplets = completedTriplets(events, spec, page);
      if (triplets.length) break;
      await pause(deadline);
    }
    if (!triplets.length) throw new Error("No completed exact-scope Drouot response triplet");
    const candidates = [];
    for (const { request, response, finished } of triplets) {
      const observedAt = new Date().toISOString();
      const metadata = { artist: spec.artist, query: spec.query, page_number: page,
        request_url: request.params.request.url, method: "GET", request_id: request.params.requestId,
        request_sequence: request.sequence, response_sequence: response.sequence, finished_sequence: finished.sequence,
        status: response.params.response.status, content_type: response.params.response.mimeType,
        captured_at: observedAt, scope_checked_before_body_access: true, event_buffer_truncated: truncated };
      await append("source-request-metadata.json", metadata);
      if (metadata.status !== 200 || !metadata.content_type?.toLowerCase().includes("json"))
        throw new Error("Drouot source response was not successful JSON");
      const body = await cdp.send("Network.getResponseBody", { requestId: request.params.requestId });
      let decoded;
      try { decoded = JSON.parse(body.base64Encoded ? Buffer.from(body.body, "base64").toString("utf8") : body.body); }
      catch { throw new Error("Drouot source response was not valid JSON"); }
      const payload = publicPayload(decoded, page);
      const envelope = { ...metadata, payload };
      await append(`${name}-response-evidence.json`, envelope);
      candidates.push(envelope);
    }
    if (candidates.some((candidate) => JSON.stringify(candidate.payload) !== JSON.stringify(candidates[0].payload)))
      throw new Error("Conflicting repeated Drouot responses require a separate recapture");
    const envelope = candidates.at(-1), wanted = envelope.payload.lots.map((lot) => String(lot.id));
    let visible;
    while (Date.now() < deadline) {
      visible = await readVisible();
      if (pageMatches(visible.page_url, spec, page) && visible.total_results === envelope.payload.numFound
          && sameIDs(wanted, visible.cards.map((card) => card.id))) {
        return { page_url: visible.page_url, captured_at: envelope.captured_at,
          page, total_pages: Math.max(1, Math.ceil(envelope.payload.numFound / PAGE_SIZE)),
          total_results: envelope.payload.numFound,
          request_url: envelope.request_url, status: envelope.status,
          content_type: envelope.content_type,
          lots: envelope.payload.lots, cards: visible.cards };
      }
      await tab.playwright.domSnapshot();
      await readEvents(cdp, cursor, 250);
      await pause(deadline);
    }
    await write(`${name}-unsettled-dom.json`, visible || {});
    throw new Error("Drouot visible page did not match response IDs, count and scope");
  }

  async function collectSearch(entry) {
    if (!initialized) throw new Error("Initialize Drouot collection before collecting a search");
    const requested = searchSpec(entry), index = specs.findIndex((spec) => spec.query === requested.query);
    if (index < 0 || requested.artist !== specs[index].artist) throw new Error("Search is outside the selected Drouot manifest");
    const spec = specs[index], name = `search-${String(index + 1).padStart(3, "0")}`;
    if (capture.searches.some((search) => search.source_url === spec.source_url)) throw new Error("Drouot search already collected; retain attempts separately");
    if (failed.has(spec.source_url)) throw new Error("Drouot search failed in this attempt; recapture in a separate attempt directory");
    const search = { artist: spec.artist, source_url: spec.source_url, pages: [] };
    try {
      await prepareCategory();
      const cursor = await cursorBefore();
      const input = tab.playwright.locator('[data-cy="category-search"]');
      await input.fill(spec.query);
      await input.press("Enter");
      const first = await capturePage(spec, 1, cursor, name);
      search.pages.push(first);
      await write(`${name}.json`, search);
      const pages = Math.max(1, Math.ceil(first.total_results / PAGE_SIZE));
      if (pages > 100) throw new Error("Drouot pagination exceeds the bounded per-search limit");
      const allIDs = new Set(first.lots.map((lot) => String(lot.id)));
      for (let page = 2; page <= pages; page += 1) {
        const link = tab.playwright.getByRole("link", { name: String(page), exact: true });
        if (await link.count() !== 1) throw new Error("Drouot next numbered pagination link is missing or ambiguous");
        const href = await link.getAttribute("href");
        if (!pageMatches(new URL(href, BASE).href, spec, page)) throw new Error("Drouot pagination left the original scope");
        const before = await cursorBefore();
        await link.click();
        const observed = await capturePage(spec, page, before, name);
        if (observed.total_results !== first.total_results) throw new Error("Drouot result total changed during pagination");
        if (observed.lots.some((lot) => allIDs.has(String(lot.id)))) throw new Error("Drouot repeated a source lot across pages");
        observed.lots.forEach((lot) => allIDs.add(String(lot.id)));
        search.pages.push(observed);
        await write(`${name}.json`, search);
      }
      if (allIDs.size !== first.total_results) throw new Error("Drouot complete result count is inconsistent");
      const missingHouses = [...new Set(search.pages.flatMap((page) => page.lots.map((lot) => String(lot.auctioneerId))))]
        .filter((houseID) => houseID !== "undefined" && !capture.auctioneers[houseID]);
      if (missingHouses.length) {
        await collectAuctioneers();
        if (missingHouses.some((houseID) => !capture.auctioneers[houseID]))
          throw new Error("Drouot auction-house mapping is incomplete for the captured search");
      }
      capture.searches.push(search);
      await write(`${name}.json`, search);
      await writeCapture();
      return { artist: spec.artist, pages: search.pages.length, results: allIDs.size, complete: true };
    } catch (error) {
      const failure = { artist: spec.artist, query: spec.query, source_url: spec.source_url,
        captured_at: new Date().toISOString(), completed_pages: search.pages.length, error: String(error.message || error) };
      failed.set(spec.source_url, failure);
      await write(`${name}-failure.json`, failure);
      await writeCapture();
      throw error;
    }
  }

  async function writeCapture() {
    capture.exported_at = new Date().toISOString();
    await write("capture.json", capture);
    await write("collection-progress.json", { ...summary(), failures: [...failed.values()],
      pending: specs.filter((spec) => !capture.searches.some((search) => search.source_url === spec.source_url)
        && !failed.has(spec.source_url)) });
    return { path: file("capture.json"), ...summary() };
  }

  function summary() {
    return { selected: specs.length, completed: capture.searches.length, failed: failed.size,
      complete: capture.searches.length === specs.length && !failed.size,
      pages: capture.searches.reduce((total, search) => total + search.pages.length, 0),
      observations: capture.searches.reduce((total, search) => total + search.pages.reduce((sum, page) => sum + page.lots.length, 0), 0) };
  }
  const exclusive = (operation) => async (...args) => {
    if (busy) throw new Error("Run Drouot browser operations sequentially");
    busy = true;
    try { return await operation(...args); } finally { busy = false; }
  };
  return { initialize: exclusive(initialize), collectSearch: exclusive(collectSearch),
    writeCapture: exclusive(writeCapture), summary };
};

