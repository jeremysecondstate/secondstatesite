/* Paste this entire file into DevTools on an Invaluable artist search.
 * Change Sort By once, then use Download lot snapshot. The helper observes
 * only requests made by the page; it never requests auction data itself.
 */
(() => {
  "use strict";

  const PANEL_ID = "secondstate-invaluable-snapshot";
  const FILTERS = "banned:false AND channelIDs:1 AND unlotted:false AND onlineOnly:false "
    + "AND closed:false AND NOT subcategoryRef:7IA742QGM5";
  const CATEGORIES = new Map(["Asian Art", "Collectibles", "Decorative Art", "Fine Art", "Furniture", "Jewelry"]
    .map((value) => [value.toLowerCase(), value]));
  const SORTS = {
    "": "upcoming_lots_prod", enddateasc: "upcoming_lots_dateTimeUTCUnix_asc_prod",
    newlylisted: "upcoming_lots_postDateTime_desc_prod", postdatetimedesc: "upcoming_lots_postDateTime_desc_prod",
    postdatedesc: "upcoming_lots_postDateTime_desc_prod",
    priceasc: "upcoming_lots_currentBid_asc_prod", pricedesc: "upcoming_lots_currentBid_desc_prod",
    bidcountasc: "upcoming_lots_bidCount_asc_prod", bidcountdesc: "upcoming_lots_bidCount_desc_prod",
    bidsdesc: "upcoming_lots_bidCount_desc_prod",
  };
  const SAFE_PARAMS = new Set([
    "query", "facetFilters", "filters", "page", "hitsPerPage", "attributesToRetrieve",
    "attributesToHighlight", "attributesToSnippet", "highlightPreTag", "highlightPostTag",
    "snippetEllipsisText", "restrictHighlightAndSnippetArrays", "facets", "maxValuesPerFacet",
    "facetingAfterDistinct", "getRankingInfo", "responseFields", "analytics", "analyticsTags",
    "clickAnalytics", "userToken",
  ]);
  const PUBLIC_FIELDS = [
    "bidCount", "catalogRef", "categoryName", "countryName", "currencyCode", "currencySymbol", "currentBid",
    "dateTimeLocal", "dateTimeUTCUnix", "endTimeUTCUnix", "estimateHigh", "estimateLow",
    "houseName", "location", "lotDescription", "lotNumber", "lotRef", "lotTitle", "objectID",
    "photoPath", "soldPrice", "soldCurrencyCode", "stateName", "subcategoryName", "supercategoryName",
  ];
  const text = (value) => String(value ?? "").trim().replace(/\s+/g, " ");
  const artistKey = (value) => text(value).normalize("NFKC").toLowerCase();

  function decodeRepeated(value) {
    let current = text(value);
    for (let round = 0; round < 6; round += 1) {
      let decoded;
      try { decoded = decodeURIComponent(current.replace(/\+/g, " ")); }
      catch { throw new Error("The search URL contains invalid encoding."); }
      if (decoded === current) break;
      current = decoded;
    }
    return text(current);
  }

  function invaluableURL(value, base) {
    const url = new URL(value, base);
    if (url.protocol !== "https:" || !["www.invaluable.com", "invaluable.com"].includes(url.hostname)
        || url.port || url.username || url.password) throw new Error("Open an HTTPS Invaluable artist search.");
    return url;
  }

  function searchSpec(value) {
    const url = invaluableURL(value);
    if (url.pathname.replace(/\/$/, "") !== "/search") throw new Error("Open an Invaluable artist search first.");
    const artists = new Set();
    const queries = new Set();
    const categories = new Map();
    const sorts = new Set();
    const pages = new Set();
    for (const [rawKey, rawValue] of url.searchParams) {
      const key = decodeRepeated(rawKey).toLowerCase();
      const item = decodeRepeated(rawValue);
      if (!item) continue;
      if (["artistname", "artist"].includes(key)) artists.add(item);
      else if (["query", "keyword", "q"].includes(key)) queries.add(item);
      else if (CATEGORIES.has(key)) {
        if (categories.has(key) && categories.get(key) !== item) throw new Error("Conflicting category filters.");
        categories.set(key, item);
      } else if (key === "sort") sorts.add(item.toLowerCase());
      else if (key === "page") pages.add(item);
      else if (["view", "pagesize", "page_size", "hitsperpage", "perpage", "fbclid", "gclid", "ref", "referrer"].includes(key)
          || key.startsWith("utm_")) continue;
      else throw new Error("This search has unsupported URL filters. Use the bookmarked artist search.");
    }
    if (artists.size !== 1 || queries.size > 1 || sorts.size > 1 || pages.size > 1) {
      throw new Error("Use one artist and consistent search filters.");
    }
    const artist = [...artists][0];
    const query = [...queries][0] || "";
    const sort = [...sorts][0] || "";
    if (!Object.hasOwn(SORTS, sort)) throw new Error("Choose a supported Sort By option, such as Ending Soon.");
    const pageText = [...pages][0] || "1";
    if (!/^\d+$/.test(pageText) || Number(pageText) < 1) throw new Error("The results page number is invalid.");
    const page = Number(pageText) - 1;
    const source = new URL("/search", url.origin);
    source.searchParams.set("artistName", artist);
    if (query) source.searchParams.set("query", query);
    if (sort) source.searchParams.set("sort", sort);
    if (page) source.searchParams.set("page", String(page + 1));
    const facets = [[`artistName:${artist}`]];
    for (const [key, item] of categories) {
      source.searchParams.set(CATEGORIES.get(key), item);
      facets.push([`${CATEGORIES.get(key)}:${item}`]);
    }
    source.searchParams.sort();
    return { artist, query, page, index: SORTS[sort], facets, origin: url.origin, sourceURL: source.href };
  }

  function requestParams(request) {
    if (!request || typeof request !== "object") return null;
    let params = request.params;
    if (typeof params === "string") {
      params = Object.fromEntries(new URLSearchParams(params));
      if (params.facetFilters) {
        try { params.facetFilters = JSON.parse(params.facetFilters); } catch { return null; }
      }
    }
    return params && typeof params === "object" && !Array.isArray(params) ? params : null;
  }

  function facetKey(value) {
    if (!Array.isArray(value)) return null;
    const groups = [];
    for (const group of value) {
      const items = typeof group === "string" ? [group] : group;
      if (!Array.isArray(items) || !items.length || items.some((item) => typeof item !== "string")) return null;
      groups.push(JSON.stringify([...new Set(items)].sort()));
    }
    return JSON.stringify([...new Set(groups)].sort());
  }

  function emptyOption(value) {
    return value == null || value === "" || value === false || value === 0
      || (Array.isArray(value) && value.length === 0)
      || (typeof value === "object" && Object.keys(value).length === 0);
  }

  function matchingRequests(body, spec) {
    if (!body || body.isCatalogPageRequest !== false || !Array.isArray(body.requests)) return [];
    return body.requests.flatMap((request, index) => {
      const params = requestParams(request);
      if (!params || request.indexName !== spec.index || Number(params.page || 0) !== spec.page
          || !Number.isSafeInteger(Number(params.hitsPerPage)) || Number(params.hitsPerPage) <= 0
          || Number(params.hitsPerPage) > 1000 || (params.query || "") !== spec.query
          || text(params.filters) !== FILTERS
          || Object.entries(params).some(([key, value]) => !SAFE_PARAMS.has(key) && !emptyOption(value))) return [];
      const actualFacets = facetKey(params.facetFilters || []);
      const exact = actualFacets === facetKey(spec.facets);
      const zeroOnly = !exact && actualFacets === facetKey([[`artistName:${spec.artist}`]]);
      return exact || zeroOnly ? [{ index, params, zeroOnly }] : [];
    });
  }

  function validResult(result, params) {
    if (!result || !Array.isArray(result.hits)
        || ["page", "nbPages", "nbHits", "hitsPerPage"].some((key) => !Number.isSafeInteger(result[key]) || result[key] < 0)) return false;
    const { page, nbPages, nbHits, hitsPerPage, hits } = result;
    if (!hitsPerPage || page !== Number(params.page || 0) || hitsPerPage !== Number(params.hitsPerPage)
        || nbPages !== Math.ceil(nbHits / hitsPerPage) || (nbHits ? page >= nbPages : page !== 0)
        || hits.length !== Math.min(hitsPerPage, Math.max(0, nbHits - page * hitsPerPage))) return false;
    const identities = new Set();
    for (const hit of hits) {
      if (!hit || typeof hit !== "object" || Array.isArray(hit)
          || typeof hit.lotRef !== "string" || !text(hit.lotRef)
          || typeof (hit.lotTitle || hit.title) !== "string" || !text(hit.lotTitle || hit.title)
          || (hit.objectID !== undefined && typeof hit.objectID !== "string"
              && !(typeof hit.objectID === "number" && Number.isFinite(hit.objectID)))) return false;
      const identity = text(hit.objectID || hit.lotRef);
      if (!identity || identities.has(identity)) return false;
      identities.add(identity);
    }
    return true;
  }

  function makeSnapshot({ pageURL, requestURL, method, body, payload, capturedAt, status = 200, contentType = "application/json" }) {
    const spec = searchSpec(pageURL);
    const endpoint = invaluableURL(requestURL, pageURL);
    if (endpoint.origin !== spec.origin || endpoint.pathname.replace(/\/$/, "") !== "/catResults"
        || method !== "POST" || status !== 200 || !contentType.toLowerCase().includes("json")) return null;
    if (!payload || !Array.isArray(payload.results)) return null;
    for (const { index, params, zeroOnly } of matchingRequests(body, spec)) {
      const result = payload.results[index];
      if (!validResult(result, params) || (zeroOnly && result.nbHits !== 0)) continue;
      if (result.hits.some((hit) => hit.artistName && artistKey(hit.artistName) !== artistKey(spec.artist))) continue;
      const hits = result.hits.map((hit) => {
        const publicHit = {};
        for (const key of PUBLIC_FIELDS) {
          const value = hit[key];
          if (typeof value === "string" || (typeof value === "number" && Number.isFinite(value))) publicHit[key] = value;
        }
        if (!publicHit.lotTitle) publicHit.lotTitle = text(hit.title);
        publicHit.artistName = spec.artist;
        return publicHit;
      });
      return { source_url: spec.sourceURL, captured_at: capturedAt,
        results: [{ page: result.page, nbPages: result.nbPages, nbHits: result.nbHits, hitsPerPage: result.hitsPerPage, hits }] };
    }
    return null;
  }

  function snapshotIsCurrent(capture, currentURL) {
    if (!capture || capture.pageURL !== currentURL) return false;
    try { return capture.data.source_url === searchSpec(currentURL).sourceURL; } catch { return false; }
  }

  function snapshotFromCandidate(candidate, currentURL, newestRequest, now = Date.now()) {
    // The site can replace its URL just after the matching response arrives.
    // Keep only that latest response briefly, then verify against the new URL.
    if (!candidate || candidate.serial !== newestRequest || now - candidate.receivedAt > 15000) return null;
    const data = makeSnapshot({ ...candidate.response, pageURL: currentURL, capturedAt: candidate.capturedAt });
    return data ? { data, pageURL: currentURL } : null;
  }

  function parseBody(value) {
    if (typeof value !== "string") return null;
    try { return JSON.parse(value); } catch { return null; }
  }

  function observeCatalog(win, onResponse, onRequest) {
    const originalFetch = win.fetch;
    const prototype = win.XMLHttpRequest.prototype;
    const originalOpen = prototype.open;
    const originalSend = prototype.send;
    const opened = new WeakMap();
    const listening = new Map();
    let active = true;
    let serial = 0;
    function descriptor(url, method, body) {
      try {
        const endpoint = invaluableURL(url, win.location.href);
        if (endpoint.origin !== new URL(win.location.href).origin
            || endpoint.pathname.replace(/\/$/, "") !== "/catResults" || method !== "POST") return null;
        const item = { requestURL: endpoint.href, method, serial: ++serial, body: Promise.resolve(body).then(parseBody) };
        item.body.then((value) => { if (active) onRequest(value, item.serial); }).catch(() => {});
        return item;
      } catch { return null; }
    }
    function deliver(item, payload, status, contentType) {
      item.body.then((body) => {
        if (active) onResponse({ requestURL: item.requestURL, method: item.method, body, payload, status, contentType }, item.serial);
      }).catch(() => {});
    }
    function wrappedFetch(input, options) {
      if (!active) return originalFetch.apply(this, arguments);
      let item = null;
      try {
        const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
        const method = String(options?.method || input?.method || "GET").toUpperCase();
        const endpoint = invaluableURL(url, win.location.href);
        if (endpoint.origin === new URL(win.location.href).origin
            && endpoint.pathname.replace(/\/$/, "") === "/catResults" && method === "POST") {
          let body = options?.body;
          // Reading a clone consumes no network and leaves the page's Request intact.
          if (body === undefined && typeof input?.clone === "function") body = input.clone().text();
          item = descriptor(endpoint.href, method, body);
        }
      } catch { /* Observation must never change the page's request behavior. */ }
      const promise = originalFetch.apply(this, arguments);
      if (active && item) Promise.resolve(promise).then((response) => {
        if (!active || response.status !== 200 || response.url !== item.requestURL) return;
        const type = response.headers.get("content-type") || "";
        if (!type.toLowerCase().includes("json")) return;
        response.clone().json().then((payload) => deliver(item, payload, response.status, type)).catch(() => {});
      }).catch(() => {});
      return promise;
    }
    function wrappedOpen(method, url) {
      if (!active) return originalOpen.apply(this, arguments);
      if (listening.has(this)) this.removeEventListener("loadend", listening.get(this));
      listening.delete(this);
      const result = originalOpen.apply(this, arguments);
      opened.set(this, { method: String(method).toUpperCase(), url });
      return result;
    }
    function wrappedSend(body) {
      if (!active) return originalSend.apply(this, arguments);
      const request = opened.get(this);
      const item = active && request ? descriptor(request.url, request.method, body) : null;
      if (item) {
        const listener = () => {
          listening.delete(this);
          if (!active || this.status !== 200 || this.responseURL !== item.requestURL) return;
          try {
            const type = this.getResponseHeader("content-type") || "";
            if (!type.toLowerCase().includes("json")) return;
            const payload = this.responseType === "json" ? this.response : parseBody(this.responseText);
            deliver(item, payload, this.status, type);
          } catch { /* Ignore an unreadable response; never retry it. */ }
        };
        listening.set(this, listener);
        this.addEventListener("loadend", listener, { once: true });
      }
      try { return originalSend.apply(this, arguments); }
      catch (error) {
        if (listening.has(this)) this.removeEventListener("loadend", listening.get(this));
        listening.delete(this);
        throw error;
      }
    }
    win.fetch = wrappedFetch;
    prototype.open = wrappedOpen;
    prototype.send = wrappedSend;
    return () => {
      active = false;
      if (win.fetch === wrappedFetch) win.fetch = originalFetch;
      if (prototype.open === wrappedOpen) prototype.open = originalOpen;
      if (prototype.send === wrappedSend) prototype.send = originalSend;
      for (const [xhr, listener] of listening) xhr.removeEventListener("loadend", listener);
      listening.clear();
    };
  }

  if (typeof document === "undefined") {
    if (typeof module !== "undefined") module.exports = { searchSpec, matchingRequests, makeSnapshot, snapshotIsCurrent, snapshotFromCandidate, observeCatalog };
    return;
  }
  searchSpec(location.href);
  if (document.getElementById(PANEL_ID)) {
    console.info("The snapshot helper is already open. Use Restore and close before running it again.");
    return;
  }
  const panel = document.createElement("div");
  panel.id = PANEL_ID;
  panel.setAttribute("role", "status");
  panel.style.cssText = "position:fixed;left:12px;right:12px;bottom:12px;z-index:2147483647;"
    + "padding:14px 18px;background:#102534;color:#fff;border:2px solid #e2bd70;border-radius:8px;"
    + "font:15px/1.5 system-ui,sans-serif;box-shadow:0 4px 24px #0007;";
  const status = document.createElement("span");
  const download = document.createElement("button");
  const close = document.createElement("button");
  download.type = close.type = "button";
  download.textContent = "Download lot snapshot";
  close.textContent = "Restore and close";
  for (const button of [download, close]) button.style.cssText = "margin-left:14px;padding:7px 12px;cursor:pointer;";
  panel.append(status, download, close);
  document.body.append(panel);
  let currentURL = location.href;
  let capture = null;
  let candidate = null;
  let newestRequest = 0;
  let closed = false;
  const objectURLs = new Set();
  function reset(message = "Change Sort By once, wait for results, then download this page's snapshot.") {
    capture = null;
    download.disabled = true;
    status.textContent = message;
  }
  function checkURL() {
    if (candidate && Date.now() - candidate.receivedAt > 15000) candidate = null;
    if (location.href !== currentURL) {
      currentURL = location.href;
      reset("Search changed. Waiting for its new results; change Sort By once if needed.");
      applyCandidate();
    }
  }
  function applyCandidate() {
    try {
      const verified = snapshotFromCandidate(candidate, location.href, newestRequest);
      if (!verified) return;
      capture = verified;
      const result = verified.data.results[0];
      download.disabled = false;
      status.textContent = `${searchSpec(location.href).artist}: ${result.hits.length} lots ready`
        + ` (page ${result.page + 1} of ${Math.max(1, result.nbPages)}; ${result.nbHits} total). `
        + "Download, then import the JSON in Studio. Each snapshot covers this results page only.";
    } catch {
      reset("This search cannot be verified. Return to the bookmarked artist search and change Sort By once.");
    }
  }
  reset();
  const restore = observeCatalog(window, (response, serial) => {
    if (closed || serial !== newestRequest) return;
    candidate = { response, serial, receivedAt: Date.now(), capturedAt: new Date().toISOString() };
    checkURL();
    applyCandidate();
  }, (body, serial) => {
    checkURL();
    if (Array.isArray(body?.requests) && body.requests.some((request) => Number(requestParams(request)?.hitsPerPage) > 0)
        && serial > newestRequest) {
      newestRequest = serial;
      candidate = null;
      reset("Waiting for this page's verified artist results…");
    }
  });
  const interval = setInterval(checkURL, 250);
  window.addEventListener("popstate", checkURL);
  window.addEventListener("hashchange", checkURL);
  download.addEventListener("click", () => {
    checkURL();
    if (!snapshotIsCurrent(capture, location.href)) {
      reset("Search changed. Change Sort By once to capture the current page.");
      return;
    }
    const result = capture.data.results[0];
    const slug = searchSpec(location.href).artist.normalize("NFKD").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
    const blobURL = URL.createObjectURL(new Blob([JSON.stringify(capture.data, null, 2)], { type: "application/json" }));
    objectURLs.add(blobURL);
    const anchor = document.createElement("a");
    anchor.href = blobURL;
    anchor.download = `invaluable-${slug}-page-${result.page + 1}-${capture.data.captured_at.replace(/[:.]/g, "-")}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => { URL.revokeObjectURL(blobURL); objectURLs.delete(blobURL); }, 1000);
  });
  close.addEventListener("click", () => {
    closed = true;
    capture = null;
    candidate = null;
    restore();
    clearInterval(interval);
    window.removeEventListener("popstate", checkURL);
    window.removeEventListener("hashchange", checkURL);
    for (const value of objectURLs) URL.revokeObjectURL(value);
    objectURLs.clear();
    panel.remove();
  });
})();
