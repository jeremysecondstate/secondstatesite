"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const DIR = path.resolve(__dirname, "..");
const PAGE = "https://www.invaluable.com/search?artistName=Josef%20Albers&sort=endDateAsc";
const WINDOW = { start_date: "2026-10-21", end_date: "2026-11-01", time_zone: "America/New_York" };
function harness(shared = {}) {
  const listeners = {}; const navigations = []; const alarms = new Map(); let sequence = 0;
  const context = { TextEncoder, URL, URLSearchParams, Intl, Date, console,
    crypto: { randomUUID: () => `nonce-${++sequence}` },
    chrome: { runtime: { id: "collector", getURL: (name) => `chrome-extension://collector/${name}`,
      onMessage: { addListener: (fn) => { listeners.message = fn; } }, onStartup: { addListener: (fn) => { listeners.startup = fn; } } },
    storage: { local: { get: async (key) => ({ [key]: structuredClone(shared[key]) }),
      set: async (value) => { Object.assign(shared, structuredClone(value)); }, remove: async (key) => { delete shared[key]; } } },
    alarms: { create: async (name, spec) => { alarms.set(name, spec); }, clear: async (name) => alarms.delete(name),
      onAlarm: { addListener: (fn) => { listeners.alarm = fn; } } },
    tabs: { create: async (spec) => { navigations.push({ kind: "create", ...spec }); return { id: 42 }; },
      update: async (id, spec) => { navigations.push({ kind: "update", id, ...spec }); },
      reload: async (id) => { navigations.push({ kind: "reload", id }); },
      onRemoved: { addListener: (fn) => { listeners.removed = fn; } } } } };
  vm.createContext(context);
  context.importScripts = (...files) => files.forEach((name) => {
    const file = name === "snapshot-core.js" ? path.resolve(DIR, "../../scripts/invaluable_export_snapshot.js") : path.join(DIR, name);
    vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: name });
  });
  vm.runInContext(fs.readFileSync(path.join(DIR, "worker.js"), "utf8"), context);
  const ui = { id: "collector", url: "chrome-extension://collector/collector.html" };
  const send = (message, sender = ui) => new Promise((resolve) => listeners.message(message, sender, resolve));
  const source = (documentId = "doc-1") => ({ id: "collector", tab: { id: 42 }, frameId: 0,
    documentId, url: shared.secondstateCollectorRun.target?.url || PAGE });
  return { send, source, shared, listeners, navigations, alarms };
}
async function start(h) {
  assert.equal((await h.send({ type: "configure", urls: [PAGE], window: WINDOW })).ok, true);
  assert.equal((await h.send({ type: "start" })).ok, true);
}
function capture(h, nonce) {
  const run = h.shared.secondstateCollectorRun;
  return { type: "capture", nonce, page_url: run.target.url, snapshot: {
    source_url: run.target.url, captured_at: new Date().toISOString(), results: [{ page: 0, nbPages: 1, nbHits: 1, hitsPerPage: 1,
      hits: [{ lotRef: "ref1", objectID: "1", lotTitle: "A print", artistName: "Josef Albers", dateTimeUTCUnix: 1792929600 }] }] } };
}
test("worker opens one normal tab and rejects UI controls from site content", async () => {
  const h = harness(); await start(h);
  assert.equal(h.navigations.length, 1); assert.equal(h.navigations[0].kind, "create");
  assert.equal((await h.send({ type: "reset" }, h.source())).ok, false);
  assert.equal((await h.send({ type: "hello", page_url: PAGE }, { ...h.source(), frameId: 1 })).ok, false);
  assert.equal((await h.send({ type: "hello", page_url: PAGE }, { ...h.source(), tab: { id: 99 } })).ok, false);
});
test("worker serializes duplicate capture messages and accepts only one current document capture", async () => {
  const h = harness(); await start(h); const source = h.source();
  const hello = await h.send({ type: "hello", page_url: source.url }, source);
  assert.equal(hello.ok, true);
  const item = capture(h, hello.nonce);
  const replies = await Promise.all([h.send(item, source), h.send(item, source)]);
  assert.equal(replies[0].ok, true); assert.equal(replies[1].ok, false);
  assert.equal(h.shared.secondstateCollectorRun.snapshots.length, 1);
  assert.equal(h.shared.secondstateCollectorRun.status, "complete");
  assert.equal(h.navigations.length, 1);
});
test("pause/resume reloads the owned tab and rejects old document messages", async () => {
  const h = harness(); await start(h); const source = h.source();
  const hello = await h.send({ type: "hello", page_url: source.url }, source); const old = capture(h, hello.nonce);
  await h.send({ type: "pause" }); await h.send({ type: "resume" });
  assert.equal(h.navigations[1].kind, "reload");
  assert.equal((await h.send(old, source)).ok, false);
  assert.equal((await h.send({ type: "hello", page_url: source.url }, source)).ok, false);
  const fresh = h.source("doc-2");
  assert.equal((await h.send({ type: "hello", page_url: fresh.url }, fresh)).ok, true);
});
test("worker restart loads captured state and browser startup pauses unfinished work", async () => {
  const first = harness(); await start(first);
  const second = harness(first.shared);
  assert.equal((await second.send({ type: "status" })).run.status, "running");
  second.listeners.startup();
  const status = await second.send({ type: "status" });
  assert.equal(status.run.status, "paused"); assert.match(status.run.note, /restarted/);
  assert.equal(second.navigations.length, 0);
});
test("expired timeout and closed owned tab pause while keeping local captures", async () => {
  const h = harness(); await start(h);
  h.shared.secondstateCollectorRun.target.deadline_at = 0;
  h.listeners.alarm({ name: "secondstate-collector-page-timeout" });
  const timeout = await h.send({ type: "status" });
  assert.equal(timeout.run.status, "paused"); assert.match(timeout.run.note, /90 seconds/);
  await h.send({ type: "resume" }); h.listeners.removed(42);
  const closed = await h.send({ type: "status" });
  assert.equal(closed.run.status, "paused"); assert.match(closed.run.note, /closed/);
});
