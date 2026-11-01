(function () {
  "use strict";
  if (location.pathname.replace(/\/$/, "") !== "/search") return;
  const core = globalThis.SecondStateInvaluableSnapshot;
  if (!core) return;
  let candidate = null;
  let newestRequest = 0;
  let sent = "";
  let pending = null;
  let expected = null;
  const channel = "secondstate-invaluable-collector-v1";
  function validationURL() {
    if (!expected) return null;
    const url = new URL(location.href);
    for (const key of [...url.searchParams.keys()]) if (key.toLowerCase() === "page") url.searchParams.delete(key);
    if (expected.page) url.searchParams.set("page", String(expected.page + 1));
    return core.searchSpec(url.href).sourceURL === expected.sourceURL ? url.href : null;
  }
  function deliver() {
    let capture;
    try {
      const url = validationURL();
      if (!url) return;
      capture = core.snapshotFromCandidate(candidate, url, newestRequest);
    }
    catch { return; } // A temporary URL rewrite must not break later validation.
    if (!capture) return;
    // An equivalent URL can be rewritten between postMessage and delivery.
    // Re-emit for the new visible URL while preserving the original capture.
    const key = capture.data.source_url + capture.data.captured_at + location.href;
    if (key === sent) return;
    sent = key;
    pending = { channel, type: "snapshot", page_url: location.href, snapshot: capture.data };
    window.postMessage(pending, location.origin);
  }
  core.observeCatalog(window, (response, serial) => {
    if (serial !== newestRequest) return;
    candidate = { response, serial, receivedAt: Date.now(), capturedAt: new Date().toISOString() };
    deliver();
  }, (body, serial) => {
    // A lot's catalog hydration cannot replace an artist-search response.
    // Other positive-hit requests still invalidate older candidates, including
    // requests for a newly selected search scope before its URL has changed.
    if (body?.isCatalogPageRequest === true) return;
    const hasResults = Array.isArray(body?.requests) && body.requests.some((request) => {
      let params = request?.params;
      if (typeof params === "string") params = Object.fromEntries(new URLSearchParams(params));
      return Number(params?.hitsPerPage) > 0;
    });
    if (hasResults && serial > newestRequest) { newestRequest = serial; candidate = null; pending = null; }
  });
  // The isolated bridge can arrive after a fast initial response.
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== channel) return;
    if (event.data.type === "expected-page" && event.data.page_url === location.href
        && Number.isSafeInteger(event.data.expected_page) && event.data.expected_page >= 0 && event.data.expected_page < 100) {
      try {
        const source = core.searchSpec(event.data.source_url);
        if (source.page !== event.data.expected_page) return;
        if (expected?.sourceURL !== source.sourceURL) {
          expected = { page: source.page, sourceURL: source.sourceURL };
          pending = null; sent = "";
        }
        deliver();
      } catch { /* Only a complete source URL can establish the expected page. */ }
    } else if (event.data.type === "bridge-ready") {
      deliver();
      if (pending?.page_url === location.href) window.postMessage(pending, location.origin);
    }
  });
  setInterval(deliver, 250);
})();
