"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const PAGE = "https://www.invaluable.com/search?artistName=Josef+Albers&sort=endDateAsc";
const settle = () => new Promise(setImmediate);
function setup(respond, dom = {}) {
  const calls = [], listeners = {}, posted = [];
  let interval;
  const location = { href: PAGE, origin: "https://www.invaluable.com", pathname: "/search" };
  const window = { addEventListener: (type, fn) => { listeners[type] = fn; }, postMessage: (data) => posted.push(data) };
  const context = { window, location, URL, TextEncoder, document: { title: "Auction lots", querySelectorAll: dom.querySelectorAll || (() => []) },
    getComputedStyle: () => ({ display: "block", visibility: "visible" }),
    setInterval: (fn) => { interval = fn; return 1; }, clearInterval() {},
    chrome: { runtime: { sendMessage: async (message) => {
      calls.push(message); const response = await respond(message);
      return message.type === "hello" && response?.ok ? { expected_page: 0, source_url: PAGE, ...response } : response;
    } } } };
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, "../bridge.js"), "utf8"), context);
  const emit = (pageURL = location.href, snapshot = {}) => listeners.message({ source: window, origin: location.origin,
    data: { channel: "secondstate-invaluable-collector-v1", type: "snapshot", page_url: pageURL,
      snapshot: { source_url: PAGE, captured_at: "2026-10-21T12:00:00Z", results: [{ page: 0 }], ...snapshot } } });
  return { calls, location, posted, emit, tick: () => interval(), hide: () => listeners.pagehide() };
}

test("a transient capture transport failure revalidates the document and retries its queued snapshot", async () => {
  let attempts = 0, greetings = 0;
  const h = setup((message) => {
    if (message.type === "hello") return { ok: true, nonce: `nonce-${++greetings}` };
    if (message.type === "capture" && ++attempts === 1) throw new Error("Worker temporarily unavailable");
    return { ok: true };
  });
  await settle(); h.emit(); await settle();
  assert.equal(attempts, 1);
  h.tick(); await settle();
  assert.equal(attempts, 2);
  const captures = h.calls.filter((message) => message.type === "capture");
  assert.deepEqual(captures.map((message) => message.nonce), ["nonce-1", "nonce-2"]);
  assert.deepEqual(captures[0].snapshot, captures[1].snapshot);
  h.tick(); await settle(); assert.equal(attempts, 2, "an acknowledged capture is not repeated");
});

test("ignored capture is not retried unless the worker authorizes a fresh hello", async () => {
  let greetings = 0;
  const h = setup((message) => message.type === "hello"
    ? (++greetings === 1 ? { ok: true, nonce: "old" } : { ok: false, ignored: true })
    : { ok: false, ignored: true });
  await settle(); h.emit(); await settle();
  for (let i = 0; i < 3; i += 1) { h.tick(); await settle(); }
  assert.equal(h.calls.filter((message) => message.type === "capture").length, 1);
  assert.equal(greetings, 4);
});

test("malformed hit entries reach worker validation without breaking bridge delivery", async () => {
  const h = setup((message) => message.type === "hello" ? { ok: true, nonce: "current" }
    : { ok: false, ignored: true });
  await settle();
  h.emit(PAGE, { results: [{ page: 0, hits: [null] }] });
  await settle();
  assert.equal(h.calls.filter((message) => message.type === "capture").length, 1);
});

test("duplicate page messages and polling cannot send parallel captures", async () => {
  let finish;
  const h = setup((message) => message.type === "hello" ? { ok: true, nonce: "current" }
    : new Promise((resolve) => { finish = resolve; }));
  await settle(); h.emit(); h.emit(); h.tick();
  assert.equal(h.calls.filter((message) => message.type === "capture").length, 1);
  finish({ ok: true }); await settle(); h.tick(); await settle();
  assert.equal(h.calls.filter((message) => message.type === "capture").length, 1);
});

test("queued captures cannot cross a visible URL change or survive pagehide", async () => {
  const h = setup((message) => {
    if (message.type === "hello") return { ok: true, nonce: "current" };
    throw new Error("Disconnected");
  });
  await settle(); h.emit(); await settle();
  h.location.href = PAGE.replace("Josef+Albers", "Banksy");
  h.tick(); await settle();
  assert.equal(h.calls.filter((message) => message.type === "capture").length, 1);
  h.hide(); const count = h.calls.length; h.tick(); h.emit(); await settle();
  assert.equal(h.calls.length, count);
});

test("Load more waits for every accepted lot ref, ignores unrelated/partial append and clicks once per grant", async () => {
  let expectedPage = 0, visibleRefs = ["unrelated"], clicks = 0;
  const button = { textContent: "Load more", disabled: false, getAttribute: () => null,
    getClientRects: () => [{}], click: () => { clicks += 1; } };
  const h = setup((message) => message.type === "hello" ? ({ ok: true, nonce: `page-${expectedPage}`, expected_page: expectedPage,
    source_url: expectedPage ? `${PAGE}&page=${expectedPage + 1}` : PAGE }) : { ok: true }, {
    querySelectorAll: (selector) => selector === "button.load-more-btn" ? [button]
      : selector.startsWith("a[") ? visibleRefs.map((ref) => ({ href: `https://www.invaluable.com/auction-lot/print-c-${ref}`,
        getClientRects: () => [{}] })) : [],
  });
  await settle(); assert.equal(clicks, 0);
  h.emit(PAGE, { results: [{ page: 0, hits: [{ lotRef: "one" }, { lotRef: "two" }] }] }); await settle();
  expectedPage = 1; h.tick(); await settle(); assert.equal(clicks, 0, "initial cards must render too");
  visibleRefs.push("one", "another-unrelated"); h.tick(); await settle(); assert.equal(clicks, 0);
  visibleRefs.push("two"); h.tick(); await settle(); assert.equal(clicks, 1);
  h.tick(); await settle(); assert.equal(clicks, 1, "one grant cannot click twice");
  h.emit(PAGE, { source_url: `${PAGE}&page=2`, results: [{ page: 1, hits: [{ lotRef: "three" }, { lotRef: "four" }] }] }); await settle();
  expectedPage = 2; h.tick(); await settle(); assert.equal(clicks, 1, "response before DOM append waits");
  visibleRefs.push("three"); h.tick(); await settle(); assert.equal(clicks, 1, "partial append cannot advance");
  visibleRefs.push("four"); h.tick(); await settle(); assert.equal(clicks, 2);
  assert.equal(h.posted.filter((message) => message.type === "expected-page").at(-1).expected_page, 2);
});

test("a delayed prior-page snapshot cannot be sent under the next page's nonce", async () => {
  let page = 0;
  const h = setup(() => ({ ok: true, nonce: `page-${page}`, expected_page: page,
    source_url: page ? `${PAGE}&page=${page + 1}` : PAGE }));
  await settle();
  page = 1; h.tick(); await settle();
  h.emit(); await settle();
  assert.equal(h.calls.filter((message) => message.type === "capture").length, 0);
  h.emit(PAGE, { source_url: `${PAGE}&page=2`, results: [{ page: 1 }] }); await settle();
  const captures = h.calls.filter((message) => message.type === "capture");
  assert.equal(captures.length, 1);
  assert.equal(captures[0].nonce, "page-1");
});

test("a lost successful capture reply can advance only after the worker grants the next page and its lot renders", async () => {
  let page = 0, clicks = 0;
  const button = { textContent: "Load more", disabled: false, getAttribute: () => null,
    getClientRects: () => [{}], click: () => { clicks += 1; } };
  const h = setup((message) => {
    if (message.type === "hello") return { ok: true, nonce: `page-${page}`, expected_page: page,
      source_url: page ? `${PAGE}&page=2` : PAGE };
    page = 1; throw new Error("Worker accepted the page but the reply was lost");
  }, { querySelectorAll: (selector) => selector === "button.load-more-btn" ? [button]
    : selector.startsWith("a[") ? [{ href: "https://www.invaluable.com/auction-lot/print-c-one", getClientRects: () => [{}] }] : [] });
  await settle(); h.emit(PAGE, { results: [{ page: 0, hits: [{ lotRef: "one" }] }] }); await settle();
  assert.equal(clicks, 0);
  h.tick(); await settle(); assert.equal(clicks, 1);
  h.tick(); await settle(); assert.equal(clicks, 1);
});
