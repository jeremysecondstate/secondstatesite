// Run with node --test. Exercise the shipped artwork gallery without network access.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const start = template.indexOf("  const appendArchiveGallery =");
const end = template.indexOf("  const activateArchiveStage =", start);
assert.ok(start >= 0 && end > start, "production archive gallery function must be present");

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.events = {};
    this.attributes = {};
    this.dataset = {};
  }
  append(...children) {
    for (const child of children) {
      child.parent = this;
      this.children.push(child);
    }
  }
  appendChild(child) { this.append(child); return child; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { (this.events[name] ||= []).push(listener); }
  querySelectorAll(selector) {
    const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll("*")]);
    return descendants.filter(child => selector === "*"
      || (selector === "button" && child.tagName === "button")
      || (selector === "[data-image-direction]" && child.dataset.imageDirection !== undefined));
  }
  dispatch(name, event = {}) {
    event.target ||= this;
    for (const listener of this.events[name] || []) listener(event);
    if (event.bubbles && !event.stopped) this.parent?.dispatch(name, event);
  }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch("close"); }
  focus(options) { this.focusOptions = options; }
}

const document = {
  createElement: tag => new Element(tag),
  createTextNode: text => Object.assign(new Element("#text"), {textContent: text}),
};
const appendText = (parent, tag, className, textContent) => {
  const child = Object.assign(new Element(tag), {className, textContent});
  return parent.appendChild(child);
};
const makeGallery = new Function("document", "appendText", "externalLink",
  `${template.slice(start, end)}\nreturn appendArchiveGallery;`)(document, appendText, () => new Element("a"));
const images = ["https://example.test/one.jpg", "https://example.test/two.jpg", "https://example.test/three.jpg"];

function gallery() {
  const figure = makeGallery({title: "Test artwork", image_urls: images});
  const descendants = figure.querySelectorAll("*");
  const dialog = descendants.find(child => child.tagName === "dialog");
  const artwork = descendants.find(child => child.tagName === "img");
  const expanded = dialog.children.find(child => child.tagName === "img");
  const opener = figure.children.find(child => child.tagName === "button");
  return {figure, dialog, artwork, expanded, opener};
}

function key(target, value, options = {}) {
  const event = {
    key: value, bubbles: true, defaultPrevented: false, preventCalls: 0, stopCalls: 0,
    preventDefault() { this.defaultPrevented = true; this.preventCalls += 1; },
    stopPropagation() { this.stopped = true; this.stopCalls += 1; },
    ...options,
  };
  target.dispatch("keydown", event);
  return event;
}

test("ordinary arrows, Home and End navigate supplied images within their boundaries", () => {
  const page = gallery();
  for (const [value, index] of [["ArrowRight", 1], ["ArrowLeft", 0], ["End", 2],
    ["ArrowRight", 2], ["Home", 0], ["ArrowLeft", 0]]) {
    const event = key(page.opener, value);
    assert.equal(page.artwork.src, images[index]);
    assert.equal(page.expanded.src, images[index]);
    assert.equal(event.defaultPrevented, true);
    assert.equal(event.stopCalls, 1);
  }
});

for (const modifier of ["altKey", "ctrlKey", "metaKey"]) {
  test(`${modifier} shortcuts pass through the gallery and its open image dialog`, () => {
    for (const inDialog of [false, true]) {
      const page = gallery();
      key(page.opener, "ArrowRight");
      if (inDialog) page.opener.dispatch("click");
      const target = inDialog ? page.expanded : page.opener;
      for (const value of ["ArrowLeft", "ArrowRight", "Home", "End"]) {
        const event = key(target, value, {[modifier]: true});
        assert.equal(page.artwork.src, images[1], `${modifier}+${value} must not change the image`);
        assert.equal(page.expanded.src, images[1]);
        assert.equal(event.defaultPrevented, false, `${modifier}+${value} must keep its default action`);
        assert.equal(event.stopCalls, 0);
      }
    }
  });
}

test("already handled keys and unrelated keys leave the gallery untouched", () => {
  const page = gallery();
  key(page.opener, "ArrowRight");
  for (const value of ["ArrowLeft", "ArrowRight", "Home", "End"]) {
    const event = key(page.opener, value, {defaultPrevented: true});
    assert.equal(page.artwork.src, images[1]);
    assert.equal(event.preventCalls, 0);
    assert.equal(event.stopCalls, 0);
  }
  for (const value of ["Tab", "Enter", "Escape", "PageDown"]) {
    const event = key(page.opener, value);
    assert.equal(page.artwork.src, images[1]);
    assert.equal(event.defaultPrevented, false);
    assert.equal(event.stopCalls, 0);
  }
});

test("image navigation works inside the dialog and closing returns focus to its opener", () => {
  const page = gallery();
  page.opener.dispatch("click");
  assert.equal(page.dialog.open, true);
  key(page.expanded, "End");
  assert.equal(page.artwork.src, images[2]);
  assert.equal(page.expanded.src, images[2]);
  const close = page.dialog.querySelectorAll("button").find(button => button.textContent === "Close ×");
  close.dispatch("click");
  assert.equal(page.dialog.open, false);
  assert.deepEqual(page.opener.focusOptions, {preventScroll: true});
});
