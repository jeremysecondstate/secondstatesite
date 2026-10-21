(function () {
  "use strict";
  if (location.pathname.replace(/\/$/, "") !== "/search") return;
  const channel = "secondstate-invaluable-collector-v1";
  const MAX_BYTES = 2 * 1024 * 1024;
  let nonce = null;
  let queued = null;
  let lastSent = "";
  let active = true;
  async function sendCapture() {
    if (!active || !nonce || !queued) return;
    const key = queued.snapshot?.source_url + queued.snapshot?.captured_at;
    if (lastSent === key) return;
    lastSent = key;
    try {
      const reply = await chrome.runtime.sendMessage({ type: "capture", nonce, page_url: queued.page_url, snapshot: queued.snapshot });
      if (!reply?.ok) lastSent = "";
    } catch { lastSent = ""; }
  }
  window.addEventListener("message", (event) => {
    if (!active || event.source !== window || event.origin !== location.origin || event.data?.channel !== channel
        || event.data.type !== "snapshot" || event.data.page_url !== location.href) return;
    try {
      if (new TextEncoder().encode(JSON.stringify(event.data)).length > MAX_BYTES) return;
      queued = { page_url: event.data.page_url, snapshot: event.data.snapshot };
      sendCapture();
    } catch { /* Malformed page messages never reach extension storage. */ }
  });
  async function hello() {
    try {
      const reply = await chrome.runtime.sendMessage({ type: "hello", page_url: location.href });
      nonce = reply?.ok ? reply.nonce : null;
      if (nonce) { window.postMessage({ channel, type: "bridge-ready" }, location.origin); sendCapture(); }
    } catch { nonce = null; }
  }
  hello();
  const poll = setInterval(() => {
    if (!active) return;
    if (!nonce) hello();
    else {
      const heading = [document.title, ...Array.from(document.querySelectorAll("h1")).map((node) => node.textContent)].join(" ").toLowerCase();
      if (/access denied|verify you are human|just a moment|javascript is disabled/.test(heading)) {
        chrome.runtime.sendMessage({ type: "blocked", nonce, page_url: location.href,
          reason: "The source is showing an access or verification screen. Complete any normal browser verification yourself, then Resume." }).catch(() => {});
        nonce = null;
      }
    }
  }, 2000);
  window.addEventListener("pagehide", () => { active = false; clearInterval(poll); }, { once: true });
})();
