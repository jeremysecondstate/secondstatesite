// Run with node --test. Exercise the shipped thumbnail controls without network access.
const assert = require("node:assert/strict");
const {test} = require("node:test");
const {safeImageUrl, create} = require("./static/secondstateapp/calendar_research_images.js");

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.events = {}; this.attributes = {}; this.hidden = false; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { (this.events[name] ||= []).push(callback); }
  dispatch(name, event = {}) { for (const callback of this.events[name] || []) callback({target: this, ...event}); }
  showModal() { this.open = true; this.showCount = (this.showCount || 0) + 1; }
  close() { this.open = false; this.dispatch("close"); }
  focus(options) { this.focusOptions = options; }
}
const document = {createElement: tag => new Element(tag)};
const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
const find = (element, tag) => descendants(element).find(child => child.tagName === tag);
const record = {
  provider: "Artprice", title: "Sleeping Dancer", artist: "Henri Matisse",
  auction_house: "Auction House", sale_date: "2020-01-12",
  image_url: "https://imgprivate2.artprice.com/lots/artwork/xl",
};

test("image URLs require HTTPS and reject credentials, local targets and nonstandard ports", () => {
  assert.equal(safeImageUrl(record.image_url), record.image_url);
  assert.equal(safeImageUrl("https://images.liveart.ai/work.jpg?signature=a%2Fb"),
    "https://images.liveart.ai/work.jpg?signature=a%2Fb");
  for (const value of [null, {}, "", "/image.jpg", "//example.com/image.jpg", "file:///tmp/image.jpg",
    "javascript:alert(1)", "data:image/png;base64,AAAA", "http://example.com/image.jpg",
    "https://name:secret@example.com/image.jpg", "https://example.com:444/image.jpg",
    "https://localhost/image.jpg", "https://service.local/image.jpg", "https://metadata.internal/image.jpg",
    "https://127.0.0.1/image.jpg", "https://127.1/image.jpg", "https://[::1]/image.jpg",
    "https://2130706433/image.jpg", "https://example.com/" + "x".repeat(4096)]) {
    assert.equal(safeImageUrl(value), "", String(value));
  }
});

test("missing images create a visible placeholder without a clickable image or dialog", () => {
  const figure = create(document, {...record, image_url: null});
  assert.equal(figure.children.length, 1);
  assert.equal(figure.children[0].textContent, "Image unavailable");
  assert.equal(figure.children[0].hidden, false);
  assert.equal(find(figure, "button"), undefined);
  assert.equal(find(figure, "img"), undefined);
  assert.equal(find(figure, "dialog"), undefined);
});

test("thumbnail load failures retain the evidence placeholder and hide the enlarge control", () => {
  const figure = create(document, record);
  const button = find(figure, "button");
  const image = find(figure, "img");
  assert.equal(button.type, "button");
  assert.equal(image.loading, "lazy");
  assert.equal(image.referrerPolicy, "no-referrer");
  assert.equal(image.src, record.image_url);
  assert.equal(figure.children[0].hidden, true);
  image.dispatch("error");
  assert.equal(button.hidden, true);
  assert.equal(figure.children[0].hidden, false);
  assert.equal(find(figure, "dialog"), undefined);
});

test("enlargement is lazy, reuses its dialog, recovers from failure and returns focus without form submission", () => {
  const figure = create(document, record);
  const opener = find(figure, "button");
  assert.equal(find(figure, "dialog"), undefined);
  opener.dispatch("click");
  const dialog = find(figure, "dialog");
  assert.equal(dialog.open, true);
  assert.match(dialog.attributes["aria-label"], /Sleeping Dancer/);
  assert.match(opener.attributes["aria-label"], /Enlarge image/);
  const expanded = find(dialog, "img");
  assert.equal(expanded.src, record.image_url);
  assert.equal(expanded.referrerPolicy, "no-referrer");
  expanded.dispatch("error");
  assert.equal(expanded.hidden, true);
  assert.match(find(dialog, "p").textContent, /currently unavailable/);
  const closer = find(dialog, "button");
  assert.equal(closer.type, "button");
  closer.dispatch("click");
  assert.equal(dialog.open, false);
  assert.deepEqual(opener.focusOptions, {preventScroll: true});
  opener.dispatch("click");
  assert.equal(descendants(figure).filter(child => child.tagName === "dialog").length, 1);
  assert.equal(dialog.showCount, 2);
  dialog.dispatch("click");
  assert.equal(dialog.open, false);
});
