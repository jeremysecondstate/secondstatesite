// Run with node --test. Exercise the actual month-scope and navigation functions.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const template = fs.readFileSync(path.join(__dirname, "../templates/calendar/calendar.html"), "utf8");
function declaration(name) {
  const start = template.indexOf(`  const ${name} =`);
  assert(start >= 0, `Missing production function: ${name}`);
  let depth = 0, quote = "", escaped = false, comment = "";
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
    this.events = {};
    this.hidden = false;
    this.value = "";
    this._text = "";
    this.classes = new Set();
    this.classList = {
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
      contains: name => this.classes.has(name),
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent || "").join(""); }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  addEventListener(name, callback) { this.events[name] = callback; }
  focus(options) { this.focused = true; this.focusOptions = options; }
  scrollIntoView(options) { this.scrollOptions = options; }
  closest() { return this.cell || null; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
}

const dayA = "2026-11-04";
const dayB = "2026-11-05";
const lot = (id, eligible, changes = {}) => ({
  id, title: `Work ${id}`, artist: `Artist ${id}`, auction_house: eligible === true ? "Phillips" : "Other house",
  oliver_house: eligible, event_at: `${dayA}T15:00:00Z`, time: "8:00 AM", lot_number: String(id),
  attribution_label: "", email_tray_selected: false, research_queue_selected: false,
  saved_bid_board: null, won_by_us: false, ...changes,
});
const sale = (house, count, changes = {}) => ({auction_house: house, lot_count: count,
  sale_title: "", time_label: "8:00 AM", sale_url: "", ...changes});

function page(data, view = "calendar") {
  const elements = new Map();
  const listeners = new Map();
  const grid = Object.assign(new Element(), {dataset: {monthLabel: "November 2026"}});
  const upcoming = ["all", "oliver"].map(scope => Object.assign(new Element(), {dataset: {calendarUpcomingScope: scope}}));
  const monthLinks = [{href: "https://secondstate.art/calendar/?month=2026-12"}];
  const dayButtons = Object.entries(data).map(([day, lots]) => {
    const button = new Element("button");
    Object.assign(button.dataset, {calendarDay: day, dateLabel: `Date ${day}`, lotCount: String(lots.length),
      saleCount: "2", oliverLotCount: String(lots.filter(item => item.oliver_house === true).length), oliverSaleCount: "1"});
    const cell = new Element();
    const scopes = ["all", "oliver"].map(scope => Object.assign(new Element(), {dataset: {calendarScope: scope}}));
    const link = Object.assign(new Element("a"), {href: `https://secondstate.art/calendar/?month=2026-11&day=${day}&view=catalog`});
    cell.querySelectorAll = selector => selector === "[data-calendar-scope]" ? scopes : [];
    cell.querySelector = selector => selector === ".day-catalog-link" ? link : null;
    Object.assign(cell, {scopes, link});
    button.cell = cell;
    return button;
  });
  const catalogLinks = dayButtons.map(button => button.cell.link);
  const document = {
    createElement: tag => new Element(tag),
    getElementById: id => {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    },
    querySelector: selector => selector === ".calendar-grid" ? grid : null,
    querySelectorAll: selector => selector === ".month-nav a" ? monthLinks
      : selector === ".day-catalog-link" ? catalogLinks
      : selector === "[data-calendar-upcoming-scope]" ? upcoming : [],
  };
  const previousEntries = [];
  const location = {origin: "https://secondstate.art", pathname: "/calendar/"};
  const setLocation = value => {
    const url = new URL(String(value));
    Object.assign(location, {href: url.href, search: url.search});
  };
  setLocation(`https://secondstate.art/calendar/?month=2026-11&day=${Object.keys(data)[0]}&view=${view}`);
  const history = {
    state: {}, pushes: 0,
    replaceState(state, _title, url) { this.state = state; setLocation(url); },
    pushState(state, _title, url) {
      previousEntries.push({state: this.state, url: location.href});
      this.pushes += 1;
      this.replaceState(state, _title, url);
    },
    back() {
      const previous = previousEntries.pop();
      assert(previous, "history Back must have a previous entry");
      this.state = previous.state;
      setLocation(previous.url);
      listeners.get("popstate")();
    },
  };
  const context = vm.createContext({
    data, document, URL, URLSearchParams, dayButtons, selectedDay: Object.keys(data)[0], activeView: view,
    salesData: Object.fromEntries(Object.keys(data).map(day => [day, [sale("Other house", 1), sale("Phillips", 1)]])),
    oliverSalesData: Object.fromEntries(Object.keys(data).map(day => [day, data[day].some(item => item.oliver_house === true) ? [sale("Phillips", 1)] : []])),
    researchScope: "", researchIndex: 0, researchLook: "dossier", researchRenderedKey: "",
    researchDaySelection: new Map(), researchLookButtons: [], restoringHistory: false,
    gallerySort: {value: "catalog"}, galleryFilter: "all", galleryHideAttributed: false, galleryVisibleCount: 24, galleryArtistsDay: "",
    sidebarRenderedDay: "", sidebarRenderedScope: "", csrfToken: "test-token",
    window: {location, history, addEventListener: (name, callback) => listeners.set(name, callback), matchMedia: () => ({matches: false})},
    formatCalendarDay: day => `Date ${day}`,
    renderResearchDays() {}, loadCurrencyPrices() {}, refreshCurrencyPrices() {},
    renderGalleryCatalog() { context.galleryIds = Array.from(context.run("dayLots()"), item => item.id); },
    renderResearchWorkspace() { context.researchIds = Array.from(context.run("dayLots()"), item => item.id); },
    appendText(parent, tag, className, text) {
      return parent.appendChild(Object.assign(new Element(tag), {className, textContent: text}));
    },
    externalLink(url, className, text) { return Object.assign(new Element("a"), {href: url, className, textContent: text}); },
    appendArtistLabel(parent, source) { parent.lotId = source.id; },
    appendCurrencyPrice() {}, appendLotControls() {}, appendArtpriceEditor() {}, appendArtpriceAnalysis() {},
  });
  for (const name of ["calendarLayout", "calendarViewToggle", "catalogViewToggle", "oliverViewToggle", "oliverCalendarViewToggle",
    "researchViewToggle", "auctionCalendar", "calendarPageShell", "galleryCatalog", "researchWorkspace", "researchTitle",
    "researchBack", "researchPrevious", "researchSearch", "title", "list", "salesSection", "salesCount", "salesList",
    "lotBrowserLaunch", "researchLaunch"]) context[name] = new Element();
  const functions = ["galleryOrganization", "gallerySortOrders", "restoreGalleryOrganization", "writeGalleryOrganization", "isGalleryView", "inOliverScope", "dayLots", "renderCalendarScope", "renderDaySales", "renderSidebarLots",
    "updateSidebarLaunches", "showDay", "setCalendarView", "updateCalendarLocation", "openResearchWorkspace"];
  vm.runInContext(functions.map(declaration).join("\n"), context);
  vm.runInContext(between('  researchBack.addEventListener("click"', '  researchPrevious.addEventListener("click"'), context);
  context.run = expression => vm.runInContext(expression, context);
  context.ids = () => Array.from(context.run("dayLots()"), item => item.id);
  context.sidebarIds = () => context.list.children.filter(node => node.lotId).map(node => node.lotId);
  Object.assign(context, {grid, upcoming, monthLinks, catalogLinks, listeners, setLocation});
  return context;
}

test("Oliver month uses strict eligibility and original lot objects without modifying saved or attribution state", () => {
  const outsider = lot(1, false, {email_tray_selected: true});
  const partner = lot(2, true, {attribution_label: "After", won_by_us: true, research_queue_selected: true, saved_bid_board: {qualifying_bid: "0"}});
  const unverified = lot(3, "true");
  const data = {[dayA]: [outsider, partner, unverified]};
  const before = JSON.stringify(data);
  const p = page(data, "oliver-calendar");
  assert.deepEqual(p.ids(), [2]);
  assert.equal(p.run("dayLots()[0]"), partner);
  p.galleryHideAttributed = true;
  p.run("showDay(selectedDay)");
  assert.deepEqual(p.sidebarIds(), [2], "month view retains qualified lots even while the catalog browsing preference is remembered");
  assert.equal(p.run("dayLots()[0].saved_bid_board"), partner.saved_bid_board);
  assert.equal(JSON.stringify(data), before);
  p.run('setCalendarView("calendar")');
  assert.deepEqual(p.ids(), [1, 2, 3]);
  assert.equal(p.run("dayLots()"), data[dayA]);
  assert.equal(JSON.stringify(data), before);
});

test("month scope swaps pre-grouped chips, meaningful counts, accessible labels, catalog links and upcoming sales", () => {
  const p = page({[dayA]: [lot(1, false), lot(2, true)], [dayB]: [lot(3, false)]});
  p.run('setCalendarView("oliver-calendar")');
  const [mixed, empty] = p.dayButtons;
  assert.equal(mixed.cell.scopes[0].hidden, true);
  assert.equal(mixed.cell.scopes[1].hidden, false);
  assert.equal(mixed.cell.classes.has("has-events"), true);
  assert.match(mixed.getAttribute("aria-label"), /1 watched lot in 1 auction/);
  assert.equal(mixed.cell.link.hidden, false);
  assert.equal(mixed.cell.link.textContent, "Oliver’s Catalog →");
  assert.match(mixed.cell.link.getAttribute("aria-label"), /Oliver’s Catalog for Date 2026-11-04/);
  assert.equal(new URL(mixed.cell.link.href).searchParams.get("view"), "oliver");
  assert.equal(empty.cell.classes.has("has-events"), false);
  assert.equal(empty.cell.link.hidden, true, "a nonpartner-only date must not advertise an Oliver catalog");
  assert.doesNotMatch(empty.getAttribute("aria-label"), /watched lot/);
  assert.deepEqual(p.upcoming.map(node => node.hidden), [true, false]);
  assert.equal(p.grid.getAttribute("aria-label"), "November 2026 Oliver’s auction calendar");
  p.run('setCalendarView("calendar")');
  assert.equal(mixed.cell.scopes[0].hidden, false);
  assert.equal(mixed.cell.scopes[1].hidden, true);
  assert.match(mixed.getAttribute("aria-label"), /2 watched lots in 2 auctions/);
  assert.equal(empty.cell.link.hidden, false);
  assert.equal(empty.cell.link.textContent, "Jeremy’s Catalog →");
  assert.equal(new URL(empty.cell.link.href).searchParams.get("view"), "catalog");
  assert.deepEqual(p.upcoming.map(node => node.hidden), [false, true]);
});

test("same-day month changes replace sidebar sales, suggestions and browse/research totals", () => {
  const p = page({[dayA]: [lot(1, false), lot(2, true)]});
  p.run("showDay(selectedDay)");
  assert.deepEqual(p.sidebarIds(), [1, 2]);
  p.run('setCalendarView("oliver-calendar")');
  assert.deepEqual(p.sidebarIds(), [2]);
  assert.equal(p.salesCount.textContent, "1");
  assert.equal(p.salesList.children.length, 1);
  assert.doesNotMatch(p.salesList.textContent, /Other house/);
  assert.equal(p.researchLaunch.textContent, "Research this lot");
  assert.equal(p.lotBrowserLaunch.textContent, "Browse this lot");
  assert.equal(p.oliverCalendarViewToggle.getAttribute("aria-pressed"), "true");
  assert.equal(p.calendarViewToggle.getAttribute("aria-pressed"), "false");
  assert.equal(p.calendarLayout.hidden, false);
  assert.equal(p.galleryCatalog.hidden, true);
  p.run('setCalendarView("calendar")');
  assert.deepEqual(p.sidebarIds(), [1, 2]);
  assert.equal(p.salesCount.textContent, "2");
  assert.equal(p.researchLaunch.textContent, "Research 2 lots in full view");
  assert.equal(p.lotBrowserLaunch.textContent, "Browse all 2 lots");
});

test("entering the Oliver month through a hidden catalog invalidates an all-house sidebar cache", () => {
  const p = page({[dayA]: [lot(1, false), lot(2, true)]});
  p.run("showDay(selectedDay)");
  p.run('setCalendarView("oliver")');
  assert.deepEqual(p.galleryIds, [2]);
  p.run('setCalendarView("oliver-calendar")');
  assert.deepEqual(p.sidebarIds(), [2], "same-date sidebar must follow its rendered scope, not the previous active view");
});

test("nonpartner-only dates remain selectable and show scoped empty guidance with no launch controls", () => {
  const p = page({[dayA]: [lot(1, true)], [dayB]: [lot(2, false)]}, "oliver-calendar");
  p.run(`showDay("${dayB}")`);
  assert.equal(p.selectedDay, dayB);
  assert.deepEqual(p.sidebarIds(), []);
  assert.match(p.list.textContent, /No lots from Oliver’s auction houses on this date/);
  assert.equal(p.salesCount.textContent, "0");
  assert.match(p.salesList.textContent, /No auctions from Oliver’s auction houses on this date/);
  assert.equal(p.researchLaunch.hidden, true);
  assert.equal(p.lotBrowserLaunch.hidden, true);
  assert.deepEqual(p.dayButtons.map(button => button.getAttribute("aria-pressed")), ["false", "true"]);
  assert.deepEqual(p.dayButtons.map(button => button.cell.getAttribute("aria-selected")), [null, null]);
  p.run('setCalendarView("calendar")');
  assert.deepEqual(p.sidebarIds(), [2]);
  assert.equal(p.researchLaunch.hidden, false);
  p.run(`showDay("${dayA}")`);
  assert.deepEqual(p.dayButtons.map(button => button.getAttribute("aria-pressed")), ["true", "false"]);
  assert.deepEqual(p.dayButtons.map(button => button.cell.getAttribute("aria-selected")), [null, null]);
});

test("month URLs, scoped catalog links and history restoration retain view/date and attribution preference", () => {
  const p = page({[dayA]: [lot(1, false), lot(2, true)], [dayB]: []});
  p.galleryHideAttributed = true;
  p.run('setCalendarView("oliver-calendar")');
  const current = new URL(p.window.location.href);
  assert.equal(current.searchParams.get("view"), "oliver-calendar");
  assert.equal(current.searchParams.get("day"), dayA);
  assert.equal(current.searchParams.get("hide_attributed"), "1");
  const month = new URL(p.monthLinks[0].href);
  assert.equal(month.searchParams.get("view"), "oliver-calendar");
  assert.equal(month.searchParams.get("hide_attributed"), "1");
  assert.equal(month.searchParams.has("day"), false);
  const catalog = new URL(p.catalogLinks[0].href);
  assert.equal(catalog.searchParams.get("view"), "oliver");
  assert.equal(catalog.searchParams.get("hide_attributed"), "1");
  assert.equal(catalog.searchParams.get("day"), dayA);
  p.run('setCalendarView("calendar")');
  p.setLocation(current.href);
  p.listeners.get("popstate")();
  assert.equal(p.activeView, "oliver-calendar");
  assert.equal(p.galleryHideAttributed, true);
  assert.equal(p.calendarLayout.hidden, false);
  assert.equal(p.oliverCalendarViewToggle.getAttribute("aria-pressed"), "true");
  assert.deepEqual(p.sidebarIds(), [2], "popstate must invalidate a same-day all-house sidebar even after it restores activeView early");
  assert.equal(p.restoringHistory, false);
  assert.equal(p.window.history.pushes, 0);
  assert.equal(new URL(p.monthLinks[0].href).searchParams.get("view"), "oliver-calendar");
});

test("research from the Oliver month stays scoped and browser Back returns to the month and original saved objects", () => {
  const partner = lot(2, true, {email_tray_selected: true, saved_bid_board: {qualifying_bid: "123.45"}});
  const data = {[dayA]: [lot(1, false), partner, lot(3, true)]};
  const before = JSON.stringify(data);
  const p = page(data);
  p.galleryHideAttributed = true;
  p.run('setCalendarView("oliver-calendar")');
  const monthUrl = p.window.location.href;
  p.run("openResearchWorkspace(1)");
  assert.equal(p.researchScope, "oliver");
  assert.deepEqual(p.researchIds, [2, 3]);
  const research = new URL(p.window.location.href);
  assert.equal(research.searchParams.get("view"), "research");
  assert.equal(research.searchParams.get("scope"), "oliver");
  assert.equal(research.searchParams.get("lot"), "3");
  assert.equal(research.searchParams.get("hide_attributed"), "1");
  assert.equal(p.run("dayLots()[0]"), partner);
  assert.equal(p.window.history.pushes, 1);
  p.researchBack.events.click();
  assert.equal(p.window.location.href, monthUrl);
  assert.equal(p.activeView, "oliver-calendar");
  assert.equal(p.oliverCalendarViewToggle.focused, true, "Back should focus the restored Oliver month control");
  assert.equal(p.calendarLayout.hidden, false);
  assert.equal(p.researchWorkspace.hidden, true);
  assert.deepEqual(p.sidebarIds(), [2, 3]);
  assert.equal(p.run("dayLots()[0]"), partner);
  assert.equal(JSON.stringify(data), before);
});
