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
  replaceChildren(...children) { this.children = []; this.append(...children); }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
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
    + productionBlock("  const appendRetainedSavedWork =", "  const galleryCard =")
    + productionBlock("  const galleryCard =", "  const renderGalleryCards =");
  const render = new Function("document", "appendText", "galleryResearchUrl", "galleryImage",
    "updateGalleryEmailButton", "toggleGalleryEmail", "appendCurrencyPrice", "window", "galleryArtists", "csrfToken",
    source + "\nreturn {appendArtistLabel, galleryCard};")(
      document, appendText, lot => `https://secondstate.test/calendar/?lot=${lot.id}`,
      () => [new Element("img")], () => {},
      (lot, index) => emailCalls.push({id: lot.id, index}),
      (parent, lot, kind, className) => appendText(parent, "p", className, lot[kind]),
      {CalendarArtists: require("./static/secondstateapp/calendar_artists.js")}, {dataset: {timeZone: "America/Los_Angeles"}}, "test-csrf",
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

test("every catalog lot exposes an estimated arrival separately from the listed time without requiring a board", () => {
  for (const saved_bid_board of [null, {qualifying_bid: "300"}, {qualifying_bid: null}]) {
    const source = lot({event_at: "2026-11-04T13:00:00Z", time: "5:00 AM", lot_number: "39", saved_bid_board});
    const before = JSON.stringify(source), card = renderer().galleryCard(source, 0);
    assert.equal(withClass(card, "day-gallery-lot-arrival")[0].textContent, "Est. lot arrival: ≈ 5:39 AM");
    assert(withClass(card, "day-gallery-meta").some(node => node.textContent.includes("5:00 AM")), "listed source time remains visible");
    assert.equal(JSON.stringify(source), before);
  }
  const unknown = renderer().galleryCard(lot({event_at: null}), 0);
  assert.equal(withClass(unknown, "day-gallery-lot-arrival")[0].textContent, "Est. lot arrival: Unavailable");
});

test("published arrival blocks have an explicit source link and retain source time and saved controls", () => {
  const source = lot({event_at: "2026-11-06T08:00:00Z", time: "12:00 AM", lot_number: "3466", won_by_us: true,
    research_queue_selected: true, arrival_schedule: {
      kind: "published_timetable", at: "2026-11-06T13:30:00Z", session_start_at: "2026-11-06T13:00:00Z",
      first_lot: 3446, last_lot: 3467, source_url: "https://www.dobiaschofsky.com/g246.html",
    }});
  const before = JSON.stringify(source);
  const card = renderer().galleryCard(source, 0);
  assert.equal(withClass(card, "day-gallery-lot-arrival")[0].textContent, "House timetable: ≈ 5:30 AM · lots 3446–3467");
  const link = withClass(card, "day-gallery-auction-link").find(node => node.textContent === "House timetable ↗");
  assert.equal(link.href, "https://www.dobiaschofsky.com/g246.html");
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener noreferrer");
  assert(withClass(card, "day-gallery-meta").some(node => node.textContent.includes("Listed auction: 12:00 AM")));
  assert.equal(withClass(card, "lot-won-badge").length, 1);
  assert.equal(withClass(card, "lot-attribution-badge")[0].textContent, "After");
  assert.equal(JSON.stringify(source), before);
});

test("published lot closing cards show the exact time without approximation or added minutes", () => {
  const url = "https://www.sothebys.com/en/buy/auction/2026/modern-contemporary-discoveries-de2640/untitled?locale=en";
  const source = lot({event_at: "2026-11-12T13:36:00Z", time: "5:36 AM", lot_number: "37",
    lot_url: url, url, won_by_us: true, research_queue_selected: true,
    arrival_schedule: {kind: "published_closing", at: "2026-11-12T13:36:00Z", source_url: url}});
  const before = JSON.stringify(source), card = renderer().galleryCard(source, 0);
  assert.equal(withClass(card, "day-gallery-lot-arrival")[0].textContent, "Lot closes: 5:36 AM");
  assert(withClass(card, "day-gallery-auction-link").some(node => node.href === url));
  assert.equal(withClass(card, "lot-won-badge").length, 1);
  assert.equal(withClass(card, "lot-attribution-badge")[0].textContent, "After");
  assert.equal(JSON.stringify(source), before);
});

test("Heritage pace estimates link to their basis while preserving source times and saved controls", () => {
  const source = lot({event_at: "2026-11-11T16:50:00Z", time: "8:50 AM", lot_number: "79087", won_by_us: true,
    research_queue_selected: true, arrival_estimate: {session_start_at: "2026-11-11T17:00:00Z",
      first_lot: 79001, last_lot: 79230, lots_per_hour: 54,
      source_url: "https://fineart.ha.com/c/auction-home.zx?saleNo=8256"}});
  const before = JSON.stringify(source);
  const card = renderer().galleryCard(source, 0);
  assert.equal(withClass(card, "day-gallery-lot-arrival")[0].textContent, "Est. lot arrival: ≈ 10:35 AM");
  const link = withClass(card, "day-gallery-auction-link").find(node => node.textContent === "Estimate basis ↗");
  assert.equal(link.href, source.arrival_estimate.source_url);
  assert.equal(link.target, "_blank");
  assert.equal(link.rel, "noopener noreferrer");
  assert(withClass(card, "day-gallery-meta").some(node => node.textContent.includes("Listed auction: 8:50 AM")));
  assert.equal(withClass(card, "lot-won-badge").length, 1);
  assert.equal(withClass(card, "lot-attribution-badge")[0].textContent, "After");
  assert.equal(JSON.stringify(source), before);
});

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

test("a canonical card exposes each retained provider's saved work without adding another card or changing state", () => {
  const source = lot({retained_saved_work: [
    {id: 10, source: "Drouot", research_url: "/calendar/?view=research&day=2026-11-04&lot=10", saved_bid_board: true},
    {id: 11, source: "Invaluable", research_url: "/calendar/?view=research&day=2026-11-04&lot=11", saved_bid_board: true, email_tray_selected: true},
  ]});
  const before = JSON.stringify(source);
  const card = renderer().galleryCard(source, 0);
  const retained = descendants(card).filter(node => node.tagName === "a" && /Saved with/.test(node.textContent));
  assert.equal(card.dataset.galleryLotId, "123");
  assert.equal(retained.length, 2);
  assert.deepEqual(retained.map(link => link.href), source.retained_saved_work.map(work => work.research_url));
  assert.match(retained[0].textContent, /Saved with Drouot/);
  assert.match(retained[1].textContent, /Saved with Invaluable/);
  retained.forEach(link => { assert.equal(link.target, "_blank"); assert.equal(link.rel, "noopener noreferrer"); });
  assert.equal(JSON.stringify(source), before);
});
