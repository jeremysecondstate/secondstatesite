// Run with node --test. Exercise the production scoped gallery and research functions.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const CalendarCurrency = require("./static/secondstateapp/calendar_currency.js");
const CalendarArtists = require("./static/secondstateapp/calendar_artists.js");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
const oliverHouseNames = JSON.parse(fs.readFileSync(
  path.join(__dirname, "data/oliver_auction_houses.json"), "utf8"
)).houses.map(house => house.name);

function declaration(name) {
  const marker = `  const ${name} =`;
  const start = template.indexOf(marker);
  assert.notEqual(start, -1, `Missing production function: ${name}`);
  // Read one top-level statement, so adjacent event listeners are not executed.
  let depth = 0;
  let quote = "";
  let escaped = false;
  let comment = "";
  for (let i = start; i < template.length; i += 1) {
    const character = template[i];
    if (comment === "line") { if (character === "\n") comment = ""; continue; }
    if (comment === "block") {
      if (character === "*" && template[i + 1] === "/") { comment = ""; i += 1; }
      continue;
    }
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
      continue;
    }
    if (character === "/" && template[i + 1] === "/") { comment = "line"; i += 1; continue; }
    if (character === "/" && template[i + 1] === "*") { comment = "block"; i += 1; continue; }
    if (["\"", "'", "`"].includes(character)) { quote = character; continue; }
    if ("({[".includes(character)) depth += 1;
    if (")}]".includes(character)) depth -= 1;
    if (character === ";" && depth === 0) return template.slice(start, i + 1);
  }
  throw new Error(`Unterminated production function: ${name}`);
}

function between(start, end) {
  const first = template.indexOf(start);
  const last = template.indexOf(end, first + start.length);
  assert(first >= 0 && last > first, `Missing production snippet: ${start}`);
  return template.slice(first, last);
}

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.textContent = "";
    this.value = "";
    this.classList = {toggle() {}};
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, callback) { this[name] = callback; }
  focus(options) { this.focused = true; this.focusOptions = options; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  scrollIntoView(options) { this.scrollOptions = options; }
}

const dayA = "2026-10-24";
const dayB = "2026-10-25";
const dayC = "2026-10-26";
const dayD = "2026-10-27";
const lot = (id, house, eligible, overrides = {}) => ({
  id, auction_house: house, oliver_house: eligible, currency: "USD",
  title: `Artwork ${id}`, artist: `Artist ${id}`, artist_sort_key: `artist ${id}`,
  event_at: `${dayA}T15:00:00Z`, time: "8:00 AM", lot_number: String(id), ...overrides,
});

function page(data, view = "oliver") {
  const elements = new Map();
  const document = {
    createElement: tag => new Element(tag),
    getElementById: id => {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
    querySelectorAll: () => [],
  };
  const context = vm.createContext({
    data, document, oliverHouseNames, selectedDay: Object.keys(data)[0], activeView: view, researchScope: "",
    researchLook: "dossier", researchIndex: 0, galleryFilter: "all", galleryVisibleCount: 24,
    galleryArtistsDay: "", galleryArtistsExpanded: false, URL, URLSearchParams,
    window: {
      CalendarCurrency, CalendarArtists,
      location: {href: "https://secondstate.art/calendar/", pathname: "/calendar/", origin: "https://secondstate.art"},
      history: {state: {}, replaceState(state, _title, url) { this.state = state; this.url = String(url); }},
      matchMedia: () => ({matches: false}),
    },
    gallerySort: Object.assign(new Element("select"), {value: "catalog"}),
    galleryArtistSort: Object.assign(new Element("select"), {value: "count_desc"}),
    galleryGrid: new Element(), galleryMore: new Element(), gallerySortNote: new Element(),
    galleryDescription: new Element(), galleryResults: new Element(), galleryCatalog: new Element(),
    galleryFilters: new Element(), galleryHouseFilters: new Element(), galleryHousesSummary: new Element(),
    gallerySendLaunch: new Element("button"), galleryArtists: Object.assign(new Element(), {dataset: {timeZone: "America/Los_Angeles"}}),
    galleryArtistSummary: new Element(), galleryArtistList: new Element(), galleryArtistsMore: new Element(),
    galleryArtistClear: new Element("button"),
    researchSearch: new Element("input"), researchLotCard: new Element(),
    renderResearchWorkspace() { context.lastResearchLot = context.data[context.selectedDay]?.find(l => l.id === context.lastResearchLot?.id); },
    updateCalendarLocation() {}, loadCurrencyPrices() {}, refreshCurrencyPrices() {}, restoringHistory: false,
    galleryCard: (item, index) => ({id: item.id, index}),
    appendText(parent, tag, className, text) {
      const node = Object.assign(new Element(tag), {className, textContent: text});
      parent.appendChild(node);
      return node;
    },
  });
  const functions = ["isGalleryView", "inOliverScope", "dayLots"];
  vm.runInContext(functions.map(declaration).join("\n"), context);
  vm.runInContext(between("  const galleryPrice =", "  const renderGalleryFilters ="), context);
  vm.runInContext(declaration("renderGalleryFilters"), context);
  vm.runInContext(declaration("renderGalleryCards"), context);
  vm.runInContext(declaration("renderGalleryArtists"), context);
  vm.runInContext(declaration("chooseGalleryArtist"), context);
  vm.runInContext(between('  galleryArtistClear.addEventListener("click"',
    '  galleryArtistsMore.addEventListener("click"'), context);
  context.run = expression => vm.runInContext(expression, context);
  context.ids = expression => Array.from(context.run(expression), item => item.id);
  return context;
}

test("Oliver scopes by explicit eligibility while all views share the original lot objects", () => {
  const outsider = lot(1, "Other house", false);
  const partner = lot(2, "Phillips", true);
  const unverified = lot(3, "Unknown", "true");
  const data = {[dayA]: [outsider, partner, unverified]};
  const before = JSON.stringify(data);
  const context = page(data);
  assert.deepEqual(context.ids("dayLots()"), [2]);
  assert.equal(context.run("dayLots()[0]"), partner);
  context.run("dayLots()[0].email_tray_selected = true");
  assert.equal(partner.email_tray_selected, true, "selection is shared with the ordinary Calendar");
  delete partner.email_tray_selected;
  context.activeView = "catalog";
  assert.equal(context.run("dayLots()"), data[dayA]);
  context.activeView = "research";
  context.researchScope = "oliver";
  assert.deepEqual(context.ids("dayLots()"), [2]);
  context.researchScope = "";
  assert.deepEqual(context.ids("dayLots()"), [1, 2, 3]);
  assert.equal(JSON.stringify(data), before, "view changes must not rewrite or reorder source lots");
});

test("Oliver retains all catalog sort modes and cannot reveal a filtered-out house", () => {
  const data = {[dayA]: [
    lot(1, "Other", false, {estimate_low: "1", artist_sort_key: "a", event_at: `${dayA}T00:00:00Z`}),
    lot(2, "Phillips", true, {estimate_low: "900", artist_sort_key: "z", event_at: `${dayA}T18:00:00Z`}),
    lot(3, "Bradford's", true, {estimate_low: "90", artist_sort_key: "a", event_at: `${dayA}T15:00:00Z`}),
    lot(4, "Phillips", true, {estimate_low: null, artist_sort_key: "m", event_at: null}),
  ]};
  const context = page(data);
  const expected = {
    catalog: [2, 3, 4], artist: [3, 4, 2], house: [3, 2, 4],
    price_asc: [3, 2, 4], price_desc: [2, 3, 4],
    time_asc: [3, 2, 4], time_desc: [2, 3, 4],
  };
  for (const [sort, ids] of Object.entries(expected)) {
    context.gallerySort.value = sort;
    const entries = Array.from(context.run("visibleGalleryLots()"));
    assert.deepEqual(entries.map(entry => entry.lot.id), ids, sort);
    for (const entry of entries) assert.equal(context.run("dayLots()")[entry.index], entry.lot);
  }
  context.galleryFilter = "house:Other";
  assert.equal(context.run("visibleGalleryLots().length"), 0);
  context.activeView = "catalog";
  assert.deepEqual(context.ids("visibleGalleryLots().map(entry => entry.lot)"), [1]);
});

test("lot number sorting is numeric, handles suffixes and ties, and keeps missing numbers last in both galleries", () => {
  const lots = [
    lot(1, "Phillips", true, {lot_number: "100"}),
    lot(2, "Bradford's", true, {lot_number: "2"}),
    lot(3, "Phillips", true, {lot_number: "10A"}),
    lot(4, "Phillips", true, {lot_number: "10"}),
    lot(5, "Other", false, {lot_number: "1"}),
    lot(6, "Phillips", true, {lot_number: "10a"}),
    lot(7, "Phillips", true, {lot_number: ""}),
    lot(8, "Phillips", true, {lot_number: null}),
  ];
  const context = page({[dayA]: lots});
  const before = JSON.stringify(lots);
  context.gallerySort.value = "lot_asc";
  assert.deepEqual(context.ids("visibleGalleryLots().map(entry => entry.lot)"), [2, 4, 3, 6, 1, 7, 8]);
  context.gallerySort.value = "lot_desc";
  assert.deepEqual(context.ids("visibleGalleryLots().map(entry => entry.lot)"), [1, 3, 6, 4, 2, 7, 8]);
  context.activeView = "catalog";
  context.gallerySort.value = "lot_asc";
  assert.deepEqual(context.ids("visibleGalleryLots().map(entry => entry.lot)"), [5, 2, 4, 3, 6, 1, 7, 8]);
  assert.equal(JSON.stringify(lots), before);
});

test("Oliver house, artist and Email Tray counts use its complete scoped day before pagination", () => {
  const lots = Array.from({length: 60}, (_, index) => lot(index + 1,
    index % 2 ? "Phillips" : "Other", index % 2 === 1, {
      artist: index % 2 ? "Marc Chagall" : "Unrelated Artist",
      estimate_low: String(60 - index), email_tray_selected: index % 3 === 0,
    }));
  const context = page({[dayA]: lots});
  context.gallerySort.value = "price_asc";
  context.run("renderGalleryFilters(); renderGalleryArtists(); renderGalleryCards()");
  assert.equal(context.galleryHouseFilters.children.length, 17);
  const phillips = context.galleryHouseFilters.children.find(button => button.dataset.galleryFilter === "house:Phillips");
  assert.equal(phillips.children[1].textContent, "30");
  assert.equal(context.galleryFilters.children[1].children[1].textContent, "10");
  assert.match(context.galleryArtistSummary.textContent, /1 artist.*30 watched lots/);
  assert.equal(context.galleryArtistList.children.length, 1);
  assert.equal(context.galleryGrid.children.length, 24);
  assert.equal(context.galleryGrid.children[0].id, 60);
  assert.equal(context.galleryMore.hidden, false);
  context.galleryVisibleCount += 24;
  context.run("renderGalleryCards()");
  assert.equal(context.galleryGrid.children.length, 30);
  assert.equal(context.galleryMore.hidden, true);
  context.galleryFilter = "tray";
  context.run("renderGalleryCards()");
  assert.equal(context.galleryGrid.children.length, 10);
  assert(context.galleryGrid.children.every(card => lots[card.id - 1].oliver_house));
});

test("Oliver always shows all 17 workbook houses in stable order, including zero counts and empty days", () => {
  const context = page({
    [dayA]: [lot(1, "Phillips", true), lot(2, "Other", false)],
    [dayB]: [lot(3, "Other", false)],
  });
  assert.equal(oliverHouseNames.length, 17);
  context.run("renderGalleryFilters()");
  const labels = () => context.galleryHouseFilters.children.map(button => button.children[0].textContent);
  const counts = () => context.galleryHouseFilters.children.map(button => button.children[1].textContent);
  assert.deepEqual(labels(), oliverHouseNames);
  assert.deepEqual(counts(), oliverHouseNames.map(name => name === "Phillips" ? "1" : "0"));
  assert.equal(context.galleryFilters.children[0].children[1].textContent, "17");
  assert.match(context.galleryHousesSummary.textContent, /^17 houses · 1 with lots/);
  context.selectedDay = dayB;
  context.run("renderGalleryFilters()");
  assert.deepEqual(labels(), oliverHouseNames, "house order must survive day changes");
  assert.deepEqual(counts(), Array(17).fill("0"));
  assert.equal(context.galleryFilters.children[0].children[1].textContent, "17");
  assert.match(context.galleryHousesSummary.textContent, /^17 houses · 0 with lots/);
});

test("Oliver combines verified aliases under one canonical house while regular Gallery keeps actual source names", () => {
  const lots = [
    lot(1, "Rago Arts and Auction Center", true, {oliver_house_name: "Rago Auctions"}),
    lot(2, "Rago Auctions", true, {oliver_house_name: "Rago Auctions"}),
    lot(3, "Other", false),
  ];
  const before = JSON.stringify(lots);
  const context = page({[dayA]: lots});
  context.run("renderGalleryFilters()");
  const rago = context.galleryHouseFilters.children.find(button => button.dataset.galleryFilter === "house:Rago Auctions");
  assert.equal(context.galleryHouseFilters.children.length, 17);
  assert.equal(rago.children[1].textContent, "2");
  assert.equal(context.galleryHouseFilters.children.some(button => button.children[0].textContent === "Rago Arts and Auction Center"), false);
  rago.click();
  assert.deepEqual(context.ids("visibleGalleryLots().map(entry => entry.lot)"), [1, 2]);
  context.activeView = "catalog";
  context.galleryFilter = "all";
  context.run("renderGalleryFilters()");
  assert.deepEqual(context.galleryHouseFilters.children.map(button => button.children[0].textContent),
    ["Rago Arts and Auction Center", "Rago Auctions", "Other"]);
  assert.deepEqual(context.galleryHouseFilters.children.map(button => button.children[1].textContent), ["1", "1", "1"]);
  assert.equal(context.galleryFilters.children[0].children[1].textContent, "3");
  assert.equal(JSON.stringify(lots), before, "canonical labels must not rewrite source names or lot records");
});

test("a zero-count Oliver house stays selected with no lot cards and All houses restores eligible lots", () => {
  const context = page({[dayA]: [lot(1, "Phillips", true), lot(2, "Other", false)]});
  for (const name of ["galleryDate", "gallerySummary", "galleryPrevious", "galleryNext", "galleryBrowserLaunch"]) {
    context[name] = new Element();
  }
  context.document.getElementById("day-gallery-title").firstChild = new Element();
  context.formatCalendarDay = day => day;
  context.previousGalleryDay = () => undefined;
  context.nextGalleryDay = () => undefined;
  vm.runInContext(declaration("renderGalleryCatalog"), context);
  context.run("renderGalleryCatalog()");
  assert.match(context.gallerySummary.textContent, /1 of 17 auction houses with lots/);
  const zeroHouse = oliverHouseNames.find(name => name !== "Phillips");
  context.galleryHouseFilters.children.find(button => button.dataset.galleryFilter === `house:${zeroHouse}`).click();
  context.run("renderGalleryCatalog()");
  assert.equal(context.galleryFilter, `house:${zeroHouse}`, "a full catalog refresh must preserve a valid zero-count house filter");
  assert.equal(context.run("visibleGalleryLots().length"), 0);
  assert.equal(context.galleryGrid.children.filter(card => card.id !== undefined).length, 0);
  assert.equal(context.galleryResults.textContent, "0 watched lots");
  const selected = context.galleryHouseFilters.children.find(button => button.dataset.galleryFilter === `house:${zeroHouse}`);
  assert.equal(selected.getAttribute("aria-pressed"), "true");
  assert.equal(selected.children[1].textContent, "0");
  assert(context.galleryGrid.children[0].textContent.includes(zeroHouse));
  context.galleryFilters.children.find(button => button.dataset.galleryFilter === "all").click();
  assert.equal(context.galleryFilter, "all");
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [1]);
  assert.equal(context.galleryFilters.children[0].getAttribute("aria-pressed"), "true");
});

test("Oliver previous and next days skip dates containing only unrelated houses", () => {
  const context = page({
    [dayA]: [lot(1, "Phillips", true)],
    [dayB]: [lot(2, "Other", false)],
    [dayC]: [lot(3, "Bradford's", true)],
    [dayD]: [lot(4, "Other", false)],
  });
  vm.runInContext(between("  const galleryDays =", "  const updateGalleryEmailButton ="), context);
  assert.equal(context.run("nextGalleryDay()"), dayC);
  context.selectedDay = dayC;
  assert.equal(context.run("previousGalleryDay()"), dayA);
  assert.equal(context.run("nextGalleryDay()"), undefined);
  context.activeView = "catalog";
  assert.equal(context.run("previousGalleryDay()"), dayB);
  assert.equal(context.run("nextGalleryDay()"), dayD);
});

test("Oliver artwork links keep the exact lot ID and existing research stage with scope", () => {
  const context = page({[dayA]: [lot(87, "Phillips", true)]});
  vm.runInContext(declaration("galleryResearchUrl"), context);
  context.researchLook = "bidboard";
  let url = new URL(context.run("galleryResearchUrl(dayLots()[0])"));
  assert.equal(url.pathname, "/calendar/");
  assert.equal(url.searchParams.get("lot"), "87");
  assert.equal(url.searchParams.get("look"), "bidboard");
  assert.equal(url.searchParams.get("scope"), "oliver");
  context.activeView = "catalog";
  url = new URL(context.run("galleryResearchUrl(dayLots()[0])"));
  assert.equal(url.searchParams.has("scope"), false);
  assert.equal(url.searchParams.get("lot"), "87");
});

test("Oliver and scoped research URLs retain their view across month links and clear scope on exit", () => {
  const context = page({[dayA]: [
    lot(1, "Other", false), lot(2, "Phillips", true), lot(4, "Bradford's", true),
  ]});
  const links = [{href: "https://secondstate.art/calendar/?month=2026-11&day=2026-10-24&lot=1"}];
  context.document.querySelectorAll = selector => selector === ".month-nav a" ? links : [];
  vm.runInContext(declaration("updateCalendarLocation"), context);
  context.galleryFilter = "tray";
  context.run("updateCalendarLocation()");
  let current = new URL(context.window.history.url);
  assert.equal(current.searchParams.get("view"), "oliver");
  assert.equal(current.searchParams.get("filter"), "tray");
  assert.equal(new URL(links[0].href).searchParams.get("view"), "oliver");
  assert.equal(new URL(links[0].href).searchParams.has("lot"), false);
  const artistKey = CalendarArtists.artistKey({artist: "Miró, Joan"});
  context.galleryFilter = `artist:${artistKey}`;
  context.run("updateCalendarLocation()");
  current = new URL(context.window.history.url);
  assert.equal(current.searchParams.get("artist"), artistKey);
  assert.equal(current.searchParams.has("filter"), false, "artist navigation replaces the Email Tray filter");
  assert.equal(new URL(links[0].href).searchParams.has("artist"), false, "month navigation starts with all artists");
  context.activeView = "research";
  context.researchScope = "oliver";
  context.researchLook = "workbench";
  context.researchIndex = 1;
  context.run("updateCalendarLocation()");
  current = new URL(context.window.history.url);
  assert.equal(current.searchParams.get("lot"), "4");
  assert.equal(current.searchParams.get("scope"), "oliver");
  assert.equal(current.searchParams.get("look"), "workbench");
  assert.equal(current.searchParams.has("artist"), false);
  const month = new URL(links[0].href);
  assert.equal(month.searchParams.get("scope"), "oliver");
  assert.equal(month.searchParams.get("view"), "research");
  assert.equal(month.searchParams.get("look"), "workbench");
  assert.equal(month.searchParams.has("day"), false);
  context.activeView = "catalog";
  context.run("updateCalendarLocation()");
  current = new URL(context.window.history.url);
  assert.equal(current.searchParams.get("view"), "catalog");
  for (const key of ["scope", "lot", "look"]) assert.equal(current.searchParams.has(key), false);
  assert.equal(new URL(links[0].href).searchParams.has("scope"), false);
});

test("browser Back from Oliver research restores the artist selection and Oliver month links after popstate", () => {
  const context = page({[dayA]: [lot(1, "Other", false), lot(2, "Phillips", true)]});
  for (const name of ["calendarLayout", "researchWorkspace", "researchTitle", "auctionCalendar",
    "calendarPageShell", "calendarViewToggle", "catalogViewToggle", "oliverViewToggle",
    "researchViewToggle"]) context[name] = new Element();
  context.dayButtons = [];
  context.researchLookButtons = [];
  context.renderResearchDays = () => {};
  context.renderGalleryCatalog = () => {};
  context.renderResearchWorkspace = () => {};
  const monthLinks = [{href: "https://secondstate.art/calendar/?month=2026-11"}];
  context.document.querySelectorAll = selector => selector === ".month-nav a" ? monthLinks : [];
  const listeners = new Map();
  context.window.addEventListener = (name, callback) => listeners.set(name, callback);
  let pushes = 0;
  const setLocation = url => {
    const next = new URL(String(url));
    context.window.location.href = next.href;
    context.window.location.search = next.search;
  };
  context.window.history.replaceState = function(state, _title, url) {
    this.state = state;
    this.url = String(url);
    setLocation(url);
  };
  context.window.history.pushState = function(state, _title, url) {
    pushes += 1;
    this.replaceState(state, _title, url);
  };
  vm.runInContext(["updateCalendarLocation", "setCalendarView", "openResearchWorkspace"].map(declaration).join("\n"), context);
  vm.runInContext(between('  window.addEventListener("popstate"',
    '  researchPrevious.addEventListener("click"'), context);
  context.galleryFilter = `artist:${CalendarArtists.artistKey({artist: "Artist 2"})}`;
  context.run('setCalendarView("oliver")');
  const oliverUrl = context.window.location.href;
  assert.equal(new URL(oliverUrl).searchParams.get("artist"), "artist 2");
  context.run("openResearchWorkspace()");
  assert.equal(new URL(monthLinks[0].href).searchParams.get("view"), "research");
  assert.equal(new URL(monthLinks[0].href).searchParams.get("scope"), "oliver");
  setLocation(oliverUrl);
  context.window.history.state = {};
  listeners.get("popstate")();
  const restoredMonth = new URL(monthLinks[0].href);
  assert.equal(context.activeView, "oliver");
  assert.equal(context.galleryFilter, "artist:artist 2");
  assert.deepEqual(context.ids("visibleGalleryLots().map(entry => entry.lot)"), [2]);
  assert.equal(context.restoringHistory, false);
  assert.equal(restoredMonth.searchParams.get("view"), "oliver");
  for (const key of ["scope", "look", "lot"]) assert.equal(restoredMonth.searchParams.has(key), false);
  assert.equal(new URL(context.window.location.href).searchParams.get("view"), "oliver");
  assert.equal(context.document.getElementById("day-gallery-title").focused, true);
  assert.equal(pushes, 1, "restoring history must not add another navigation entry");
});

test("switching Oliver, research and regular Calendar reuses the same gallery and correct lot set", () => {
  const context = page({[dayA]: [lot(1, "Other", false), lot(2, "Phillips", true)]}, "catalog");
  for (const name of ["calendarLayout", "researchWorkspace", "researchTitle", "researchDaySelect",
    "auctionCalendar", "calendarPageShell", "calendarViewToggle", "catalogViewToggle",
    "oliverViewToggle", "researchViewToggle"]) context[name] = new Element();
  context.sidebarRenderedDay = "";
  context.renderGalleryCatalog = () => { context.galleryLotIds = context.ids("dayLots()"); };
  context.renderResearchWorkspace = () => { context.researchLotIds = context.ids("dayLots()"); };
  context.renderSidebarLots = lots => { context.sidebarLotIds = lots.map(item => item.id); };
  context.formatCalendarDay = day => day;
  context.window.history.pushState = function(state, _title, url) { this.state = state; this.url = String(url); };
  vm.runInContext(between("  const galleryDays =", "  const updateGalleryEmailButton ="), context);
  vm.runInContext(["updateCalendarLocation", "setCalendarView", "openResearchWorkspace"].map(declaration).join("\n"), context);
  context.galleryFilter = "artist:artist 1";
  context.galleryVisibleCount = 72;
  context.run('setCalendarView("oliver")');
  assert.equal(context.galleryFilter, "all", "changing house scope clears an artist from the prior scope");
  assert.equal(context.galleryVisibleCount, 24);
  assert.equal(context.activeView, "oliver");
  assert.equal(context.oliverViewToggle.getAttribute("aria-pressed"), "true");
  assert.equal(context.galleryCatalog.hidden, false);
  assert.deepEqual(context.galleryLotIds, [2]);
  context.run("openResearchWorkspace()");
  assert.equal(context.activeView, "research");
  assert.equal(context.researchScope, "oliver");
  assert.deepEqual(context.researchLotIds, [2]);
  assert.equal(new URL(context.window.history.url).searchParams.get("lot"), "2");
  context.run('setCalendarView("calendar")');
  assert.equal(context.researchScope, "");
  assert.equal(context.calendarLayout.hidden, false);
  assert.equal(context.galleryCatalog.hidden, true);
  assert.deepEqual(context.sidebarLotIds, [1, 2]);
  context.run('setCalendarView("catalog")');
  assert.deepEqual(context.galleryLotIds, [1, 2]);
});

test("an empty Oliver day preserves the regular Calendar's Research and Browse launch controls", () => {
  const context = page({
    [dayA]: [lot(1, "Phillips", true)],
    [dayB]: [lot(2, "Unrelated house", false)],
  });
  for (const name of ["title", "list", "lotBrowserLaunch", "researchLaunch", "calendarLayout",
    "researchWorkspace", "auctionCalendar", "calendarPageShell", "calendarViewToggle",
    "catalogViewToggle", "oliverViewToggle", "researchViewToggle"]) context[name] = new Element();
  context.dayButtons = [];
  context.researchDaySelection = new Map();
  context.sidebarRenderedDay = "";
  context.researchRenderedKey = "";
  context.formatCalendarDay = day => day;
  context.renderDaySales = () => {};
  context.renderResearchDays = () => {};
  context.renderGalleryCatalog = () => { context.galleryLotIds = context.ids("dayLots()"); };
  context.renderSidebarLots = lots => { context.sidebarLotIds = lots.map(item => item.id); };
  vm.runInContext(["showDay", "setCalendarView"].map(declaration).join("\n"), context);
  context.galleryFilter = "artist:artist 1";
  context.galleryVisibleCount = 72;
  context.run(`showDay("${dayB}")`);
  assert.equal(context.galleryFilter, "all", "changing dates clears the previous day's artist selection");
  assert.equal(context.galleryVisibleCount, 24);
  assert.deepEqual(context.galleryLotIds, [], "the selected day has no Oliver lots");
  assert.equal(context.researchLaunch.hidden, false);
  assert.equal(context.researchLaunch.textContent, "Research this lot");
  assert.equal(context.lotBrowserLaunch.hidden, false);
  assert.equal(context.lotBrowserLaunch.textContent, "Browse this lot");
  context.run('setCalendarView("calendar")');
  assert.deepEqual(context.sidebarLotIds, [2]);
  assert.equal(context.researchLaunch.hidden, false, "switching back does not call showDay again");
  assert.equal(context.lotBrowserLaunch.hidden, false);
});

test("research next and previous stay within Oliver houses without changing lot identity", () => {
  const context = page({[dayA]: [
    lot(1, "Other", false), lot(2, "Phillips", true),
    lot(3, "Other", false), lot(4, "Bradford's", true),
  ]}, "research");
  context.researchScope = "oliver";
  vm.runInContext(declaration("matchesResearchSearch") + "\n" + declaration("moveResearchLot"), context);
  context.run("moveResearchLot(1)");
  assert.equal(context.researchIndex, 1);
  assert.equal(context.run("dayLots()[researchIndex].id"), 4);
  context.run("moveResearchLot(1)");
  assert.equal(context.researchIndex, 1, "last eligible lot is the research boundary");
  context.run("moveResearchLot(-1)");
  assert.equal(context.run("dayLots()[researchIndex].id"), 2);
});

test("Oliver email dialog includes only selected relationship lots and declares its server scope", () => {
  const context = page({[dayA]: [
    lot(1, "Other", false, {email_tray_selected: true}),
    lot(2, "Phillips", true, {email_tray_selected: true}),
    lot(3, "Bradford's", true, {email_tray_selected: false}),
  ]});
  const fields = new Map();
  context.catalogEmailForm = {elements: {namedItem(name) {
    if (!fields.has(name)) fields.set(name, {value: ""});
    return fields.get(name);
  }}};
  context.catalogEmailDialog = {showModal() { this.open = true; }};
  context.formatCalendarDay = day => day;
  vm.runInContext(between('  gallerySendLaunch.addEventListener("click"',
    '  document.getElementById("catalog-email-close")'), context);
  context.gallerySendLaunch.click();
  assert.equal(fields.get("scope_houses").value, "oliver");
  assert.equal(fields.get("return_view").value, "oliver");
  assert.equal(fields.get("scope_day").value, dayA);
  assert.deepEqual(context.document.getElementById("catalog-email-lot-ids").children.map(x => x.value), ["2"]);
  assert.equal(context.catalogEmailDialog.open, true);
  context.activeView = "catalog";
  context.gallerySendLaunch.click();
  assert.equal(fields.get("scope_houses").value, "");
  assert.equal(fields.get("return_view").value, "catalog");
  assert.deepEqual(context.document.getElementById("catalog-email-lot-ids").children.map(x => x.value), ["1", "2"]);
});

function artistButton(context, name) {
  const text = node => [node.textContent || "", ...node.children.map(text)].join(" ");
  const row = context.galleryArtistList.children.find(node => text(node).includes(name));
  assert(row, `Artist summary is rendered for ${name}`);
  const descendants = node => [node, ...node.children.flatMap(descendants)];
  const button = descendants(row).find(node => node.tag === "button");
  assert(button, `The ${name} card contains a native button`);
  return button;
}

test("an artist card reveals its full-day lots before pagination and preserves sort and research identities", () => {
  const lots = Array.from({length: 60}, (_, index) => lot(index + 1,
    index % 2 ? "Phillips" : "Swann", true, {
      artist: index % 3 ? "Max, Peter" : "Other artist",
      estimate_low: String(1000 - index), email_tray_selected: index % 5 === 0,
    }));
  const before = JSON.stringify(lots);
  const context = page({[dayA]: lots}, "catalog");
  context.galleryFilter = "house:Phillips";
  context.gallerySort.value = "price_asc";
  context.galleryVisibleCount = 72;
  context.run("renderGalleryArtists()");
  const button = artistButton(context, "Max, Peter");
  assert.equal(button.type, "button");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(button.getAttribute("aria-controls"), "day-gallery-grid");
  assert.equal(button.getAttribute("aria-label"), "Show 40 lots by Max, Peter");
  button.click();
  const matching = lots.filter(item => item.artist === "Max, Peter").reverse();
  assert.equal(context.galleryFilter, `artist:${CalendarArtists.artistKey({artist: "Max, Peter"})}`);
  assert.equal(context.gallerySort.value, "price_asc");
  assert.equal(context.galleryVisibleCount, 24);
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), matching.slice(0, 24).map(item => item.id));
  assert.equal(context.galleryMore.hidden, false);
  assert.match(context.galleryResults.textContent, /24 of 40/);
  assert.equal(artistButton(context, "Max, Peter").getAttribute("aria-pressed"), "true");
  assert.equal(context.galleryDescription.focused, true);
  assert.equal(context.galleryDescription.scrollOptions.block, "start");
  assert.equal(context.galleryArtistClear.hidden, false);
  context.galleryVisibleCount += 24;
  context.run("renderGalleryCards()");
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), matching.map(item => item.id));
  for (const card of context.galleryGrid.children) assert.equal(lots[card.index].id, card.id);
  assert.equal(context.galleryMore.hidden, true);
  assert.equal(JSON.stringify(lots), before, "artist navigation cannot rewrite lots or Email Tray membership");
});

test("artist navigation uses the summary's normalized label without merging attribution or accents", () => {
  const context = page({[dayA]: [
    lot(1, "Phillips", true, {artist: "  Miró,\tJoan  ", artist_sort_key: "miro, joan"}),
    lot(2, "Phillips", true, {artist: "MIRÓ, JOAN", artist_sort_key: "miro, joan"}),
    lot(3, "Swann", true, {artist: "Miro\u0301, Joan", artist_sort_key: "miro, joan"}),
    lot(4, "Swann", true, {artist: "Miro, Joan", artist_sort_key: "miro, joan"}),
    lot(5, "Phillips", true, {artist: "After Miró, Joan", artist_sort_key: "miro, joan"}),
    lot(6, "Phillips", true, {artist: "", artist_sort_key: ""}),
    lot(7, "Phillips", true, {artist: null, artist_sort_key: ""}),
  ]}, "catalog");
  context.galleryFilter = "tray";
  context.run("renderGalleryArtists()");
  artistButton(context, "Miró, Joan").click();
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [1, 2, 3]);
  context.run(`chooseGalleryArtist(${JSON.stringify(CalendarArtists.artistKey({artist: "After Miró, Joan"}))})`);
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [5]);
  context.run(`chooseGalleryArtist(${JSON.stringify(CalendarArtists.artistKey({artist: ""}))})`);
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [6, 7]);
  assert(context.galleryGrid.children.every(card => context.run("dayLots()")[card.index].id === card.id));
});

test("clearing the artist restores all lots and respects reduced motion when moving focus", () => {
  const context = page({[dayA]: [
    lot(1, "Phillips", true, {artist: "Max, Peter", estimate_low: "400"}),
    lot(2, "Swann", true, {artist: "Other artist", estimate_low: "900"}),
  ]}, "catalog");
  context.window.matchMedia = () => ({matches: true});
  context.gallerySort.value = "price_desc";
  context.run(`chooseGalleryArtist(${JSON.stringify(CalendarArtists.artistKey({artist: "Max, Peter"}))})`);
  assert.equal(context.galleryDescription.scrollOptions.behavior, "auto");
  context.galleryArtistClear.click();
  assert.equal(context.galleryFilter, "all");
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [2, 1]);
  assert.equal(context.galleryArtistClear.hidden, true);
  assert.equal(artistButton(context, "Max, Peter").getAttribute("aria-pressed"), "false");
  assert.equal(context.galleryDescription.focused, true);
});

test("an artist card in Oliver's Calendar never reveals the same artist at unrelated houses", () => {
  const context = page({[dayA]: [
    lot(1, "Other", false, {artist: "Max, Peter"}),
    lot(2, "Phillips", true, {artist: "Max, Peter"}),
    lot(3, "Swann", true, {artist: "Another artist"}),
  ]}, "oliver");
  context.run("renderGalleryArtists()");
  artistButton(context, "Max, Peter").click();
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [2]);
  assert.match(context.galleryArtistSummary.textContent, /2 artists.*2 watched lots/);
  assert.equal(context.run("dayLots()[0].id"), 2);
  context.run('chooseGalleryArtist("")');
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [2, 3]);
});

test("a full catalog refresh preserves the selected artist while another house or tray selection clears it", () => {
  const context = page({[dayA]: [
    lot(1, "Phillips", true, {artist: "Max, Peter"}),
    lot(2, "Swann", true, {artist: "Max, Peter"}),
    lot(3, "Phillips", true, {artist: "Another artist", email_tray_selected: true}),
  ]}, "catalog");
  for (const name of ["galleryDate", "gallerySummary", "galleryPrevious", "galleryNext", "galleryBrowserLaunch"]) {
    context[name] = new Element();
  }
  context.document.getElementById("day-gallery-title").firstChild = new Element();
  context.formatCalendarDay = day => day;
  context.previousGalleryDay = () => undefined;
  context.nextGalleryDay = () => undefined;
  vm.runInContext(declaration("renderGalleryCatalog"), context);
  context.run('chooseGalleryArtist("max, peter"); renderGalleryCatalog()');
  assert.equal(context.galleryFilter, "artist:max, peter");
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [1, 2]);
  context.galleryHouseFilters.children.find(button => button.dataset.galleryFilter === "house:Phillips").click();
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [1, 3]);
  assert.equal(artistButton(context, "Max, Peter").getAttribute("aria-pressed"), "false");
  assert.equal(context.galleryArtistClear.hidden, true);
  context.run('chooseGalleryArtist("max, peter")');
  context.galleryFilters.children.find(button => button.dataset.galleryFilter === "tray").click();
  assert.deepEqual(context.galleryGrid.children.map(card => card.id), [3]);
  assert.equal(artistButton(context, "Max, Peter").getAttribute("aria-pressed"), "false");
  assert.equal(context.galleryArtistClear.hidden, true);
});
