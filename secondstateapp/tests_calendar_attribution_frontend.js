// Run with node --test. Render the production Calendar functions without a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function productionBlock(startText, endText) {
  const start = template.indexOf(startText);
  const end = template.indexOf(endText, start);
  assert.ok(start >= 0 && end > start, `production block ${startText} must be present`);
  return template.slice(start, end);
}

class Element {
  constructor(tagName) {
    Object.assign(this, {tagName, children: [], attributes: {}, dataset: {}, events: {}});
    this._text = "";
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  append(...children) {
    for (const child of children) { child.parent = this; this.children.push(child); }
  }
  appendChild(child) { this.append(child); return child; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { this.events[name] = listener; }
}

function descendants(element) {
  return element.children.flatMap(child => [child, ...descendants(child)]);
}
function withClass(element, className) {
  return descendants(element).filter(child => (child.className || "").split(/\s+/).includes(className));
}

const document = {createElement: tag => new Element(tag)};
function renderer() {
  const emailCalls = [];
  const appendText = (parent, tag, className, text) => {
    const child = Object.assign(new Element(tag), {className, textContent: text});
    return parent.appendChild(child);
  };
  const source = productionBlock("  const externalLink =", "  const formatAnalysisMoney =")
    + productionBlock("  const galleryCard =", "  const renderGalleryCards =");
  const render = new Function("document", "appendText", "galleryResearchUrl", "galleryImage",
    "updateGalleryEmailButton", "toggleGalleryEmail", "appendCurrencyPrice", "window", "csrfToken",
    source + "\nreturn {appendArtistLabel, galleryCard};")(
      document, appendText, lot => `https://secondstate.test/calendar/?lot=${lot.id}`,
      () => [new Element("img")], () => {},
      (lot, index) => emailCalls.push({id: lot.id, index}),
      (parent, lot, kind, className) => appendText(parent, "p", className, lot[kind]),
      {}, "test-csrf",
    );
  return {...render, emailCalls};
}

const artistUrl = "https://www.artprice.com/artist/22796/pablo-picasso/lots/pasts?idcategory=2&p=1&sort=datesale_desc";
function lot(overrides = {}) {
  return {
    id: 123, artist: "After Picasso, Pablo", artist_artprice_url: artistUrl,
    attribution_label: "After", title: "Bouquet de Fleurs", lot_number: "40111",
    auction_house: "Heritage Auctions", sale_title: "Prints & Multiples",
    medium: "Lithograph", time: "Time TBA", estimate: "$1,000–1,500 estimate", bid: "No bids",
    url: "https://example.test/auction/40111", artist_invaluable_url: "https://www.invaluable.com/search?artistName=Picasso",
    ...overrides,
  };
}

for (const attribution of ["After", "Attributed to"]) {
  test(`${attribution} is readable without changing the artist name or Artprice link`, () => {
    const parent = new Element("div");
    const source = lot({attribution_label: attribution});
    const original = JSON.stringify(source);
    renderer().appendArtistLabel(parent, source);
    const name = withClass(parent, "lot-artist")[0];
    const link = withClass(parent, "lot-artist-link")[0];
    const badge = withClass(parent, "lot-attribution-badge")[0];
    assert.equal(name.textContent, source.artist, "audit text must contain only the supplied artist name");
    assert.equal(link.href, artistUrl);
    assert.equal(link.target, "_blank");
    assert.equal(link.rel, "noopener noreferrer");
    assert.equal(link.attributes["aria-label"], `View ${source.artist} on Artprice (opens in a new tab)`);
    assert.equal(badge.textContent, attribution);
    assert.equal(badge.parent, parent, "badge must be a sibling, outside the artist-name paragraph");
    assert.ok(!descendants(name).includes(badge));
    assert.equal(JSON.stringify(source), original, "rendering must not rewrite source data");
  });
}

test("unqualified payloads remain unflagged even when a work title contains After", () => {
  for (const attribution_label of [undefined, ""]) {
    const render = renderer();
    const card = render.galleryCard(lot({artist: "Warhol, Andy", title: "After the Party", attribution_label}), 0);
    assert.equal(withClass(card, "lot-attribution-badge").length, 0);
    assert.ok(!card.className.split(/\s+/).includes("has-attribution"));
    assert.equal(withClass(card, "lot-artist")[0].textContent, "Warhol, Andy");
  }
});

test("a qualified artist without a saved Artprice URL retains its plain name and badge", () => {
  const parent = new Element("div");
  renderer().appendArtistLabel(parent, lot({artist_artprice_url: ""}));
  assert.equal(withClass(parent, "lot-artist-link").length, 0);
  assert.equal(withClass(parent, "lot-artist")[0].textContent, "After Picasso, Pablo");
  assert.equal(withClass(parent, "lot-attribution-badge")[0].textContent, "After");
});

test("flagged gallery cards remain visible with their auction and research actions", () => {
  const render = renderer();
  const card = render.galleryCard(lot(), 7);
  assert.ok(card.className.split(/\s+/).includes("has-attribution"));
  assert.equal(card.hidden, undefined);
  assert.equal(card.dataset.galleryLotId, "123");
  assert.equal(withClass(card, "lot-attribution-badge")[0].textContent, "After");
  assert.equal(withClass(card, "day-gallery-title")[0].textContent, "Bouquet de Fleurs");
  assert.equal(withClass(card, "day-gallery-quick-look")[0].href, "https://secondstate.test/calendar/?lot=123");
  assert.deepEqual(withClass(card, "day-gallery-auction-link").map(link => link.href),
    ["https://example.test/auction/40111", "https://www.invaluable.com/search?artistName=Picasso"]);
  withClass(card, "day-gallery-email")[0].events.click();
  assert.deepEqual(render.emailCalls, [{id: 123, index: 7}]);
});

test("attribution does not remove confirmed-purchase or ended state", () => {
  const card = renderer().galleryCard(lot({won_by_us: true, ended: true, attribution_label: "Attributed to"}), 0);
  const classes = card.className.split(/\s+/);
  for (const state of ["day-gallery-work", "has-attribution", "is-won", "is-ended"]) assert.ok(classes.includes(state));
  assert.equal(withClass(card, "lot-won-badge")[0].textContent, "✓ Won by SECONDSTATE");
  assert.equal(withClass(card, "lot-attribution-badge")[0].textContent, "Attributed to");
  assert.equal(withClass(card, "lot-artist-link")[0].href, artistUrl);
});
