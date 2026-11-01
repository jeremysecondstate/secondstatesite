// Run with node --test. No server, research, or category-policy dependencies.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const researchStart = template.indexOf("  const appendLiveArtResearch =");
assert(researchStart >= 0);
function between(startMarker, endMarker) {
  const start = template.indexOf(startMarker, researchStart);
  const end = template.indexOf(endMarker, start + startMarker.length);
  assert(start >= researchStart && end > start, `Missing production snippet: ${startMarker}`);
  return template.slice(start, end);
}
const groupCode = between("    const candidateGroupItems =", "    const updateBulkSelectionControls =");
const controlsCode = between("    const updateBulkSelectionControls =", "    const changeCandidateGroupSelection =");
const pendingCode = between("    const markAnalysisPending =", "    costDefinitions.forEach");
const checkboxCode = between('        checkbox.addEventListener("change",', "        const copy =");

function workbench(candidates, selected = []) {
  const groups = new Map(), toolbars = new Map(), drafts = [], statuses = [];
  for (const type of new Set(candidates.map(item => item.match_type))) {
    const count = candidates.filter(item => item.match_type === type && selected.includes(item.id)).length;
    const summary = {textContent: `${type} sales${count ? ` · ${count} selected` : ""}`};
    groups.set(type, {dataset: {group: type}, summary, querySelector: selector => {
      assert.equal(selector, "summary");
      return summary;
    }});
    const select = {disabled: false}, deselect = {disabled: false}, note = {textContent: ""};
    toolbars.set(type, {dataset: {group: type}, select, deselect, note, querySelector: selector => {
      if (selector === '[data-bulk-action="select"]') return select;
      if (selector === '[data-bulk-action="deselect"]') return deselect;
      assert.equal(selector, ".research-candidate-bulk-note");
      return note;
    }});
  }
  const context = vm.createContext({
    currentCandidates: candidates, selectedIds: new Set(selected),
    busy: false, pendingSourceRefresh: false, options: {}, hasUnsavedChanges: false, localRevision: 0,
    // Eligibility is intentionally a fixture: this regression changes presentation only.
    canSelectCandidate: candidate => candidate.eligible,
    candidateResults: {querySelectorAll(selector) {
      if (selector === ".research-candidate-group") return [...groups.values()];
      assert.equal(selector, ".research-candidate-bulk");
      return [...toolbars.values()];
    }},
    document: {createElement: tag => ({tag})},
    savedResults: {children: [], replaceChildren() { this.children = []; }, appendChild(node) { this.children.push(node); }},
    saveDraft() { drafts.push({selected: [...context.selectedIds], revision: context.localRevision}); },
    setStatus(message, tone) { statuses.push({message, tone}); },
    requestAnalysisJson() { throw new Error("Checkbox changes must not request research or save automatically"); },
  });
  vm.runInContext(`${groupCode}\n${controlsCode}\n${pendingCode}\nupdateBulkSelectionControls();`, context);
  return {
    context, groups, toolbars, drafts, statuses,
    change(id, checked) {
      let handler;
      context.checkbox = {value: id, checked, addEventListener(name, callback) {
        assert.equal(name, "change");
        handler = callback;
      }};
      vm.runInContext(checkboxCode, context);
      assert.equal(typeof handler, "function");
      handler();
    },
  };
}

test("unchecking one of 25 selected sales refreshes counts and enables Select all across sources", () => {
  const artprice = Array.from({length: 25}, (_, i) => ({id: `artprice:${i}`, match_type: "artprice_html", eligible: true}));
  const p = workbench([...artprice, {id: "liveart:1", match_type: "related_work", eligible: true}], artprice.map(item => item.id));
  const source = p.toolbars.get("artprice_html"), other = p.toolbars.get("related_work");
  assert.equal(source.select.disabled, true);
  assert.equal(other.select.disabled, true, "the existing 25 selections use the global allowance");
  p.change("artprice:0", false);
  assert.equal(source.select.disabled, false);
  assert.equal(source.deselect.disabled, false);
  assert.equal(other.select.disabled, false, "another source can use the newly available slot");
  assert.equal(other.deselect.disabled, true);
  assert.match(source.note.textContent, /^24 of 25 eligible selected · 24\/25 total/);
  assert.match(other.note.textContent, /^0 of 1 eligible selected · 24\/25 total/);
  assert.match(p.groups.get("artprice_html").summary.textContent, /24 selected$/);
  assert.equal(p.context.localRevision, 1);
  assert.equal(p.drafts.length, 1);
  assert.equal(p.drafts[0].selected.length, 24);
});

test("individual checking after Deselect all enables Deselect all and keeps both bulk buttons and count synchronized", () => {
  const p = workbench([
    {id: "artprice:1", match_type: "artprice_html", eligible: true},
    {id: "artprice:2", match_type: "artprice_html", eligible: true},
  ]);
  const toolbar = p.toolbars.get("artprice_html");
  assert.equal(toolbar.select.disabled, false);
  assert.equal(toolbar.deselect.disabled, true);
  p.change("artprice:1", true);
  assert.equal(toolbar.deselect.disabled, false);
  assert.equal(toolbar.select.disabled, false);
  assert.match(toolbar.note.textContent, /^1 of 2 eligible selected · 1\/25 total/);
  p.change("artprice:2", true);
  assert.equal(toolbar.select.disabled, true);
  assert.equal(toolbar.deselect.disabled, false);
  assert.match(toolbar.note.textContent, /^2 of 2 eligible selected · 2\/25 total/);
  p.change("artprice:1", false);
  p.change("artprice:2", false);
  assert.equal(toolbar.select.disabled, false);
  assert.equal(toolbar.deselect.disabled, true);
  assert.match(toolbar.note.textContent, /^0 of 2 eligible selected · 0\/25 total/);
  assert.doesNotMatch(p.groups.get("artprice_html").summary.textContent, /selected/);
  assert.equal(p.context.localRevision, 4);
  assert.equal(p.drafts.length, 4);
  assert.deepEqual(p.drafts.at(-1).selected, []);
});
