// Run with node --test. Exercise the shipped lot actions without network access.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function productionBlock(startMarker, endMarker) {
  const start = template.indexOf(startMarker);
  const end = template.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `Missing production block: ${startMarker}`);
  return template.slice(start, end);
}

class Element {
  constructor(tagName) {
    Object.assign(this, {tagName, children: [], attributes: {}, dataset: {}, events: {}});
    this._text = "";
    this.classList = {toggle() {}, remove() {}};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  append(...children) {
    for (const child of children) { child.parent = this; this.children.push(child); }
  }
  appendChild(child) { this.append(child); return child; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}

function descendants(element) {
  return element.children.flatMap(child => [child, ...descendants(child)]);
}
function withClass(element, name) {
  return descendants(element).filter(child => (child.className || "").split(/\s+/).includes(name));
}

function renderer(lot) {
  const document = {createElement: tag => new Element(tag)};
  const source = productionBlock("  const appendText =", "  const applyCurrencyPrice =")
    + productionBlock("  const externalLink =", "  const formatAnalysisMoney =")
    + productionBlock("  const appendArtpriceEditor =", "  const appendLiveArtResearch =")
    + productionBlock("  const appendRetainedSavedWork =", "  const renderGalleryCards =")
    + productionBlock("  const renderResearchWorkspace =", "  const openResearchWorkspace =");
  const context = {
    document, window: {CalendarArtists: require("./static/secondstateapp/calendar_artists.js")},
    galleryArtists: {dataset: {timeZone: "America/Los_Angeles"}}, csrfToken: "test-csrf", readDraft: () => undefined,
    registerLotInstance() {}, artpriceEditorInstances: new Map(),
    galleryResearchUrl: () => "https://secondstate.test/calendar/?view=research&lot=123",
    galleryImage: () => [new Element("img")], updateGalleryEmailButton() {}, toggleGalleryEmail() {},
    appendCurrencyPrice() {}, dayLots: () => [lot], selectedDay: "2026-11-01",
    formatCalendarDay: () => "Sunday, November 1, 2026", renderResearchRail() {},
    researchTitle: new Element("h2"), researchSubtitle: new Element("p"),
    researchPrevious: new Element("button"), researchNext: new Element("button"),
    researchCount: new Element("span"), researchDaySelect: new Element("select"),
    researchDaySelection: new Map(), researchLotCard: new Element("article"),
    researchLotCache: new Map(), appendArchiveGallery: () => new Element("figure"),
    appendArtpriceAnalysis() {}, activateArchiveStage() {},
  };
  return new Function(...Object.keys(context),
    `let researchIndex = 0; let researchRenderedKey = "";\n${source}\n`
    + "return {galleryCard, appendArtpriceEditor, research() { renderResearchWorkspace(); return researchLotCard; }};",
  )(...Object.values(context));
}

const liveartUrl = "https://www.liveart.ai/artists/aMCprL/pablo-picasso";
function lot(overrides = {}) {
  return {
    id: 123, artist: "Picasso, Pablo", title: "Nestor's Tales", lot_number: "127",
    artist_liveart_url: liveartUrl, artist_artprice_url: "https://www.artprice.com/artist/22796/pablo-picasso",
    artist_invaluable_url: "https://www.invaluable.com/search?artistName=Pablo%2520Picasso",
    artprice_search_url: "https://www.artprice.com/search?s=pablo-picasso", artprice_search_scope: "artist",
    url: "https://example.test/auction/127", artprice_url: "https://www.artprice.com/lot/123",
    ...overrides,
  };
}

function assertLiveartLink(parent, artist) {
  const links = withClass(parent, "lot-artist-liveart-link");
  assert.equal(links.length, 1, "the artist action is rendered once");
  assert.equal(links[0].href, liveartUrl);
  assert.equal(links[0].textContent, "LiveArt ↗");
  assert.equal(links[0].target, "_blank");
  assert.equal(links[0].rel, "noopener noreferrer");
  assert.equal(links[0].attributes["aria-label"], `Open ${artist} on LiveArt (opens in a new tab)`);
}

test("Archive Research dossier adds LiveArt beside the existing source links without changing lot state", () => {
  const source = lot({artist: "After Picasso, Pablo", attribution_label: "After", email_tray_selected: true});
  const original = JSON.stringify(source);
  const card = renderer(source).research();
  assertLiveartLink(card, source.artist);
  const actions = withClass(card, "lot-browser-action-links")[0];
  assert.deepEqual(actions.children.map(link => link.textContent),
    ["Open auction lot ↗", "Open Artprice ↗", "View on Artprice ↗", "Invaluable prints ↗", "Search Artprice comps ↗", "LiveArt ↗"]);
  assert.equal(withClass(card, "lot-attribution-badge")[0].textContent, "After");
  assert.equal(withClass(card, "lot-artist-link")[0].href, source.artist_artprice_url);
  assert.equal(JSON.stringify(source), original);
});

test("Gallery Catalog and Oliver's shared lot cards include the saved LiveArt artist action", () => {
  const source = lot();
  const card = renderer(source).galleryCard(source, 0);
  assertLiveartLink(card, source.artist);
  assert.deepEqual(withClass(card, "day-gallery-auction-link").map(link => link.href),
    [source.url, source.artist_invaluable_url, liveartUrl]);
});

test("Zwaan shared lot card shows the session-based ETA and explains its estimated pace", () => {
  const sourceUrl = "https://veilinggebouw.dezwaan.nl/wp-content/uploads/Orde-der-veiling-V117-2.pdf";
  const source = lot({artist: "Zúñiga, Francisco", title: "FRANCISCO ZUNIGA (1912 - 1998)",
    lot_number: "6816", event_at: "2026-11-12T09:00:00Z", time: "1:00 AM",
    auction_house: "Veilinggebouw de Zwaan", email_tray_selected: true,
    arrival_estimate: {kind: "session_estimate", session_start_at: "2026-11-12T18:00:00Z",
      first_lot: 6800, last_lot: 7015, lots_per_hour: 60, source_url: sourceUrl}});
  const before = JSON.stringify(source);
  const card = renderer(source).galleryCard(source, 0);
  const [arrival] = withClass(card, "day-gallery-lot-arrival");
  assert.equal(arrival.textContent, "Est. lot arrival: ≈ 10:16 AM");
  assert.match(arrival.title, /Published session start, plus one minute per lot from lot 6800/);
  assert.match(arrival.title, /Actual pace varies/);
  const basis = withClass(card, "day-gallery-auction-link").filter(link => link.textContent === "Estimate basis ↗");
  assert.equal(basis.length, 1);
  assert.equal(basis[0].href, sourceUrl);
  assert.equal(basis[0].target, "_blank");
  assert.equal(basis[0].rel, "noopener noreferrer");
  assert.equal(withClass(card, "day-gallery-auction-link").some(link => link.href === source.url), true);
  assert.equal(JSON.stringify(source), before);
});

test("missing LiveArt bookmarks leave source actions and the Artprice editor usable", () => {
  for (const artist_liveart_url of [undefined, ""]) {
    const source = lot({artist_liveart_url});
    const render = renderer(source);
    const card = render.research();
    assert.equal(withClass(card, "lot-artist-liveart-link").length, 0);
    assert.equal(withClass(card, "artprice-form").length, 1);
    assert.equal(withClass(card, "lot-artprice-search")[0].href, source.artprice_search_url);
    assert.equal(withClass(render.galleryCard(source, 0), "lot-artist-liveart-link").length, 0);
  }
});
