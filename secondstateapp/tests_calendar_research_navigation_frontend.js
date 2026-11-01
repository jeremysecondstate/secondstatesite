// Run with node --test. Exercise production research navigation without network access.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function productionBlock(startMarker, endMarker) {
  const start = template.indexOf(startMarker);
  const end = template.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `Missing production block: ${startMarker}`);
  assert.equal(template.indexOf(startMarker, start + startMarker.length), -1,
    `Production start marker must be unique: ${startMarker}`);
  assert.equal(template.indexOf(endMarker, end + endMarker.length), -1,
    `Production end marker must be unique: ${endMarker}`);
  return template.slice(start, end);
}

class Control {
  constructor(document) {
    this.document = document;
    this.attributes = {};
    this.events = {};
    this.dataset = {};
    this.focusCalls = 0;
    this.clickCalls = 0;
  }
  addEventListener(name, listener) { this.events[name] = listener; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.document.activeElement = this; this.focusCalls += 1; }
  click() { this.clickCalls += 1; this.events.click?.(); }
}

function key(target, value, options = {}) {
  const event = {
    key: value, defaultPrevented: false, preventCalls: 0, stopCalls: 0,
    preventDefault() { this.defaultPrevented = true; this.preventCalls += 1; },
    stopPropagation() { this.stopCalls += 1; },
    ...options,
  };
  target.events.keydown(event);
  return event;
}

const tabSource = productionBlock("      const activateTab = () => {",
  "      panel.replaceChildren(tabs, sourcePanel, liveartSection);");
function researchTabs() {
  const document = {};
  const target = new Control(document);
  const keys = ["sources", "comps", "bids"];
  const panels = Object.fromEntries(keys.map(name => [name, {}]));
  const buttons = Object.fromEntries(keys.map(name => [name, new Control(document)]));
  const readSelected = new Function("tabs", "panels", "buttons", "bidBoard",
    `let researchTab = "comps";\n${tabSource}\nactivateTab();\nreturn () => researchTab;`)(
    target, panels, buttons, null,
  );
  document.activeElement = buttons.comps;
  return {
    target, controls: keys.map(name => buttons[name]), document,
    selectedIndex: () => keys.indexOf(readSelected()),
    assertSelection(index) {
      keys.forEach((name, position) => {
        assert.equal(panels[name].hidden, position !== index);
        assert.equal(buttons[name].attributes["aria-selected"], String(position === index));
        assert.equal(buttons[name].tabIndex, position === index ? 0 : -1);
      });
    },
    stopCallsForNavigation: 0,
  };
}

const conceptSource = productionBlock('  researchLookButtons.forEach((button) => button.addEventListener("click", () => {',
  '  researchWorkspace.addEventListener("keydown", (event) => {');
function researchConceptSwitch() {
  const document = {};
  const target = new Control(document);
  const keys = ["dossier", "workbench", "bidboard"];
  const controls = keys.map(name => Object.assign(new Control(document), {dataset: {researchLook: name}}));
  const researchWorkspace = {querySelector(selector) {
    assert.equal(selector, ".research-concept-switch");
    return target;
  }};
  const state = new Function("researchWorkspace", "researchLookButtons", "document",
    `let researchLook = "workbench";
     let activations = 0;
     let locationUpdates = 0;
     const activateArchiveStage = () => { activations += 1; };
     const updateCalendarLocation = () => { locationUpdates += 1; };
     ${conceptSource}
     return {selected: () => researchLook, calls: () => [activations, locationUpdates]};`)(
    researchWorkspace, controls, document,
  );
  document.activeElement = controls[1];
  return {
    target, controls, document,
    selectedIndex: () => keys.indexOf(state.selected()),
    assertSelection(index) {
      assert.equal(state.selected(), keys[index]);
      assert.deepEqual(state.calls(), [controls.reduce((count, button) => count + button.clickCalls, 0),
        controls.reduce((count, button) => count + button.clickCalls, 0)]);
    },
    stopCallsForNavigation: 1,
  };
}

function snapshot(page) {
  return {
    selected: page.selectedIndex(), activeElement: page.document.activeElement,
    focusCalls: page.controls.map(control => control.focusCalls),
    clickCalls: page.controls.map(control => control.clickCalls),
  };
}

for (const [label, createPage] of [["research tabs", researchTabs], ["research stage switch", researchConceptSwitch]]) {
  test(`${label}: ordinary arrows wrap and Home/End select and focus their endpoint`, () => {
    const page = createPage();
    for (const [value, index] of [["ArrowRight", 2], ["ArrowRight", 0], ["ArrowLeft", 2],
      ["Home", 0], ["ArrowLeft", 2], ["End", 2], ["ArrowLeft", 1]]) {
      const event = key(page.target, value);
      assert.equal(page.selectedIndex(), index);
      assert.equal(page.document.activeElement, page.controls[index]);
      page.assertSelection(index);
      assert.equal(event.defaultPrevented, true);
      assert.equal(event.preventCalls, 1);
      assert.equal(event.stopCalls, page.stopCallsForNavigation);
    }
  });

  for (const modifier of ["altKey", "ctrlKey", "metaKey"]) {
    test(`${label}: ${modifier} shortcuts preserve selection, focus, and event handling`, () => {
      const page = createPage();
      const before = snapshot(page);
      for (const value of ["ArrowLeft", "ArrowRight", "Home", "End"]) {
        const event = key(page.target, value, {[modifier]: true});
        assert.deepEqual(snapshot(page), before, `${modifier}+${value} must preserve the current control`);
        page.assertSelection(before.selected);
        assert.equal(event.defaultPrevented, false);
        assert.equal(event.preventCalls, 0);
        assert.equal(event.stopCalls, 0);
      }
    });
  }

  test(`${label}: already-prevented events leave controls and propagation untouched`, () => {
    const page = createPage();
    const before = snapshot(page);
    for (const value of ["ArrowLeft", "ArrowRight", "Home", "End"]) {
      const event = key(page.target, value, {defaultPrevented: true});
      assert.deepEqual(snapshot(page), before, `Handled ${value} must preserve the current control`);
      page.assertSelection(before.selected);
      assert.equal(event.defaultPrevented, true);
      assert.equal(event.preventCalls, 0);
      assert.equal(event.stopCalls, 0);
    }
  });

  test(`${label}: unrelated keys pass through without changing selection or focus`, () => {
    const page = createPage();
    const before = snapshot(page);
    for (const value of ["Tab", "Enter", "Escape", "PageDown", "ArrowUp", "ArrowDown"]) {
      const event = key(page.target, value);
      assert.deepEqual(snapshot(page), before);
      page.assertSelection(before.selected);
      assert.equal(event.defaultPrevented, false);
      assert.equal(event.preventCalls, 0);
      assert.equal(event.stopCalls, 0);
    }
  });
}
