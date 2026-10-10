"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { largerHeritageImageURL: upgrade, isLargerWithoutDownsizing: grows } = require("./heritage_prepare_images.js");

test("only recognized HTTPS product images are upgraded, without unrelated query parameters", () => {
  assert.equal(
    upgrade("https://dyn1.heritagestatic.com/ha?p=3-5-2-5-9-35259486&w=120&h=300&token=drop"),
    "https://dyn1.heritagestatic.com/ha?p=3-5-2-5-9-35259486&w=612&h=600&it=product",
  );
  for (const input of [
    "http://dyn1.heritagestatic.com/ha?p=1-2",
    "https://dyn1.heritagestatic.com.evil.test/ha?p=1-2",
    "https://dyn1.heritagestatic.com/other?p=1-2",
    "https://dyn1.heritagestatic.com/ha?p=1-2&p=3-4",
    "https://user:secret@dyn1.heritagestatic.com/ha?p=1-2",
    "file:///private/picture.jpg", "/ha?p=1-2",
    "https://dyn1.heritagestatic.com/ha?p=arbitrary",
  ]) assert.equal(upgrade(input), null, input);
});

test("larger means decoded dimensions grow without reducing either side", () => {
  assert(grows({ width: 600, height: 400 }, { width: 120, height: 80 }));
  assert(!grows({ width: 612, height: 300 }, { width: 800, height: 400 }));
  assert(!grows({ width: 120, height: 80 }, { width: 120, height: 80 }));
  assert(!grows({ width: 600, height: 70 }, { width: 120, height: 80 }));
});

class Element {
  constructor(attributes = {}) {
    this.attributes = new Map(Object.entries(attributes));
    this.listeners = new Map();
    this.style = {};
    this.children = [];
    this.isConnected = true;
  }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name) { this.listeners.delete(name); }
  append(...children) { this.children.push(...children); }
  remove() { this.isConnected = false; }
  closest() { return null; }
}

test("an already larger src replaces stale lazy data-src and Restore puts both back", async () => {
  const large = "https://dyn1.heritagestatic.com/ha?p=1-2-345&w=1000&h=1000&it=product";
  const small = "https://dyn1.heritagestatic.com/ha?p=1-2-345&w=120&h=300&it=product";
  const img = new Element({ src: large, "data-src": small, loading: "lazy" });
  Object.assign(img, { currentSrc: large, complete: true, naturalWidth: 800, naturalHeight: 500 });
  const link = new Element({ href: "/itm/prints/portrait/a/8280-65001.s" });
  const card = { querySelector: (selector) => selector === "a.item-title[href]" ? link : img };
  const body = new Element();
  const document = {
    body,
    querySelector: () => ({ querySelectorAll: () => [card] }),
    getElementById: () => null,
    createElement: () => new Element(),
  };
  const script = readFileSync(path.join(__dirname, "heritage_prepare_images.js"), "utf8");
  vm.runInNewContext(script, {
    document, location: { href: "https://fineart.ha.com/c/search/results.zx?auction_name=8280" },
    URL, AbortController, console,
    Image: class { constructor() { throw new Error("Larger images must not be downloaded again"); } },
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(img.getAttribute("src"), large);
  assert.equal(img.getAttribute("data-src"), large);
  assert.equal(img.getAttribute("loading"), "eager");
  const banner = body.children[0];
  assert.match(banner.children[0].textContent, /1\/1 images ready; 0 failed/);
  assert.match(banner.children[0].textContent, /larger originals retained/);
  banner.children[1].listeners.get("click")();
  assert.equal(img.getAttribute("src"), large);
  assert.equal(img.getAttribute("data-src"), small);
  assert.equal(img.getAttribute("loading"), "lazy");
  assert.equal(banner.isConnected, false);
});
