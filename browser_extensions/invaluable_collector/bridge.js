(function () {
  "use strict";
  if (location.pathname.replace(/\/$/, "") !== "/search") return;
  const channel = "secondstate-invaluable-collector-v1";
  const MAX_BYTES = 2 * 1024 * 1024;
  let nonce = null;
  let queued = null;
  let lastSent = "";
  let active = true;
  let sending = false;
  let greeting = false;
  let grantedPage = null;
  let grantedSource = "";
  let advancedNonce = null;
  let submittedPage = null;
  let submittedRefs = [];
  function matchesGrant(snapshot) {
    return snapshot?.source_url === grantedSource && snapshot?.results?.[0]?.page === grantedPage;
  }
  function loadMore() {
    if (!active || !nonce || grantedPage <= 0 || advancedNonce === nonce || sending) return;
    // The next page grant acknowledges our previous submission, including when
    // its reply was lost. Wait for every accepted lot's card to render; unrelated
    // anchors and a partially appended page cannot satisfy this gate.
    if (submittedPage !== grantedPage - 1 || !submittedRefs.length) return;
    const visibleRefs = new Set();
    for (const link of document.querySelectorAll('a[href*="/auction-lot/"]')) {
      if (!link.getClientRects().length || getComputedStyle(link).visibility === "hidden") continue;
      try {
        const url = new URL(link.href, location.href);
        const match = decodeURIComponent(url.pathname).match(/\/auction-lot\/[^/]*-c-([^/]+)\/?$/i);
        if (url.origin === location.origin && match) visibleRefs.add(match[1].toLowerCase());
      } catch { /* Unrelated or malformed links cannot establish lot readiness. */ }
    }
    if (submittedRefs.some((ref) => !visibleRefs.has(ref))) return;
    const buttons = Array.from(document.querySelectorAll("button.load-more-btn")).filter((button) => {
      const style = getComputedStyle(button);
      return button.textContent.trim().replace(/\s+/g, " ") === "Load more"
        && !button.disabled && button.getAttribute("aria-disabled") !== "true"
        && style.display !== "none" && style.visibility !== "hidden" && button.getClientRects().length > 0;
    });
    if (buttons.length !== 1) return;
    advancedNonce = nonce;
    buttons[0].click();
  }
  async function sendCapture() {
    if (!active || !nonce || !queued || sending) return;
    if (queued.page_url !== location.href || !matchesGrant(queued.snapshot)) { queued = null; return; }
    const key = queued.snapshot?.source_url + queued.snapshot?.captured_at;
    if (lastSent === key) return;
    const capture = queued;
    const attemptNonce = nonce;
    const hits = capture.snapshot.results[0].hits;
    submittedPage = grantedPage;
    submittedRefs = Array.isArray(hits) && hits.length <= 1000
      && hits.every((hit) => hit && typeof hit.lotRef === "string" && hit.lotRef.trim())
      ? [...new Set(hits.map((hit) => hit.lotRef.trim().toLowerCase()))] : [];
    sending = true;
    lastSent = key;
    try {
      const reply = await chrome.runtime.sendMessage({ type: "capture", nonce: attemptNonce,
        page_url: capture.page_url, snapshot: capture.snapshot });
      if (!reply?.ok) {
        lastSent = "";
        if (nonce === attemptNonce) nonce = null;
      }
    } catch {
      lastSent = "";
      if (nonce === attemptNonce) nonce = null;
    } finally { sending = false; }
  }
  window.addEventListener("message", (event) => {
    if (!active || event.source !== window || event.origin !== location.origin || event.data?.channel !== channel
        || event.data.type !== "snapshot" || event.data.page_url !== location.href || !matchesGrant(event.data.snapshot)) return;
    try {
      if (new TextEncoder().encode(JSON.stringify(event.data)).length > MAX_BYTES) return;
      queued = { page_url: event.data.page_url, snapshot: event.data.snapshot };
      sendCapture();
    } catch { /* Malformed page messages never reach extension storage. */ }
  });
  async function hello() {
    if (!active || greeting || sending) return;
    greeting = true;
    const pageURL = location.href;
    try {
      const reply = await chrome.runtime.sendMessage({ type: "hello", page_url: pageURL });
      if (!active || pageURL !== location.href) { nonce = null; return; }
      const permitted = reply?.ok && typeof reply.nonce === "string" && Number.isSafeInteger(reply.expected_page)
        && reply.expected_page >= 0 && reply.expected_page < 100 && typeof reply.source_url === "string";
      const pageChanged = permitted && (grantedPage !== reply.expected_page || grantedSource !== reply.source_url);
      nonce = permitted ? reply.nonce : null;
      if (nonce) {
        grantedPage = reply.expected_page;
        grantedSource = reply.source_url;
        if (pageChanged) { queued = null; lastSent = ""; }
        // MAIN and isolated scripts can attach in either order. Repeat the
        // grant locally so a late observer also learns the expected page.
        window.postMessage({ channel, type: "expected-page", page_url: pageURL,
          expected_page: grantedPage, source_url: grantedSource }, location.origin);
        window.postMessage({ channel, type: "bridge-ready" }, location.origin);
        sendCapture();
        loadMore();
      }
    } catch { nonce = null; }
    finally { greeting = false; }
  }
  hello();
  const poll = setInterval(() => {
    if (!active) return;
    if (nonce) {
      const heading = [document.title, ...Array.from(document.querySelectorAll("h1")).map((node) => node.textContent)].join(" ").toLowerCase();
      if (/access denied|verify you are human|just a moment|javascript is disabled/.test(heading)) {
        chrome.runtime.sendMessage({ type: "blocked", nonce, page_url: location.href,
          reason: "The source is showing an access or verification screen. Complete any normal browser verification yourself, then Resume." }).catch(() => {});
        nonce = null;
        return;
      }
    }
    hello();
  }, 2000);
  window.addEventListener("pagehide", () => { active = false; nonce = null; queued = null; clearInterval(poll); }, { once: true });
})();
