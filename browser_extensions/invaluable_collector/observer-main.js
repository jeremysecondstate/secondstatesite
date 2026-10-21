(function () {
  "use strict";
  if (location.pathname.replace(/\/$/, "") !== "/search") return;
  const core = globalThis.SecondStateInvaluableSnapshot;
  if (!core) return;
  let candidate = null;
  let newestRequest = 0;
  let sent = "";
  let pending = null;
  const channel = "secondstate-invaluable-collector-v1";
  function deliver() {
    const capture = core.snapshotFromCandidate(candidate, location.href, newestRequest);
    if (!capture) return;
    const key = capture.data.source_url + capture.data.captured_at;
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
    const hasResults = Array.isArray(body?.requests) && body.requests.some((request) => {
      let params = request?.params;
      if (typeof params === "string") params = Object.fromEntries(new URLSearchParams(params));
      return Number(params?.hitsPerPage) > 0;
    });
    if (hasResults && serial > newestRequest) { newestRequest = serial; candidate = null; pending = null; }
  });
  // The isolated bridge can arrive after a fast initial response.
  window.addEventListener("message", (event) => {
    if (event.source === window && event.origin === location.origin && event.data?.channel === channel
        && event.data.type === "bridge-ready" && pending) window.postMessage(pending, location.origin);
  });
  setInterval(deliver, 250);
})();
