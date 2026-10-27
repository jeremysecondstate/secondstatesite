// Exercise the shipped recovery handler with controlled state and responses.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const start = template.indexOf("    const recover = async () => {");
const end = template.indexOf("    if (window.LiveArtManualEntry)", start);
const recoveryCode = template.slice(start, end);

function page({draft = false, pending = false, error = null} = {}) {
  const requests = [], statuses = [], restored = [], busyChanges = [];
  const saved = {selected_ids: ["saved-sale"]};
  const context = vm.createContext({
    busy: false, options: {}, lot: {liveart_research_url: "/calendar/lots/7/liveart-research/"},
    hasUnsavedChanges: draft, loaded: false, currentAnalysis: saved,
    setStatus: (...args) => statuses.push(args),
    setBusy(value) { context.busy = value; busyChanges.push(value); },
    async requestAnalysisJson(url, options) {
      requests.push({url, options});
      if (error) throw new Error(error);
      return {pending_found: pending, research_id: "receipt", data_units_spent: 8.5,
        candidates: [{id: "pending-sale"}], selected_ids: [], message: "Recovery result"};
    },
    applyManualResearch(payload) { restored.push(payload); context.hasUnsavedChanges = true; },
  });
  vm.runInContext(`${recoveryCode}\nthis.recover = recover;`, context);
  return {context, requests, statuses, restored, busyChanges, saved};
}

test("recovery uses only GET and restores pending receipt without changing saved analysis", async () => {
  const p = page({pending: true});
  await p.context.recover();
  assert.equal(p.requests.length, 1);
  assert.equal(p.requests[0].options.method, "GET");
  assert.equal(p.requests[0].url, "/calendar/lots/7/liveart-research/");
  assert.equal(p.restored[0].data_units_spent, 8.5);
  assert.equal(p.context.currentAnalysis, p.saved);
  assert.deepEqual(p.saved.selected_ids, ["saved-sale"]);
  assert.equal(p.context.loaded, true);
  assert.deepEqual(p.busyChanges, [true, false]);
});

test("an unrelated unsaved review is preserved without a request", async () => {
  const p = page({draft: true, pending: true});
  await p.context.recover();
  assert.equal(p.requests.length, 0);
  assert.equal(p.restored.length, 0);
  assert.equal(p.context.hasUnsavedChanges, true);
  assert.match(p.statuses.at(-1)[0], /Your draft has been kept/);
});

test("no pending response and transport errors leave existing research untouched", async () => {
  for (const args of [{pending: false}, {error: "Recovery unavailable"}]) {
    const p = page(args);
    await p.context.recover();
    assert.equal(p.restored.length, 0);
    assert.equal(p.context.currentAnalysis, p.saved);
    assert.equal(p.context.hasUnsavedChanges, false);
    assert.equal(p.context.busy, false);
    assert.equal(p.requests[0].options.method, "GET");
  }
});
