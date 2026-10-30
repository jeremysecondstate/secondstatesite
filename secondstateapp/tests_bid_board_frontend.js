// Run with node --test. Exercise the public board views against the server contract.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.events = {};
    this.dataset = {};
    this.className = "";
    this.value = "";
    this.disabled = false;
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: (...names) => {this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" ");},
      remove: (...names) => {this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(" ");},
      toggle: (name, enabled) => enabled ? this.classList.add(name) : this.classList.remove(name),
    };
  }
  set textContent(value) {this.text = String(value); this.children = [];}
  get textContent() {return (this.text || "") + this.children.map(node => node.textContent).join(" ");}
  get childElementCount() {return this.children.length;}
  append(...nodes) {nodes.forEach(node => {node.parentElement = this; this.children.push(node);});}
  prepend(...nodes) {nodes.forEach(node => {node.parentElement = this;}); this.children.unshift(...nodes);}
  replaceChildren(...nodes) {this.children = []; this.text = ""; this.append(...nodes);}
  setAttribute(name, value) {this.attributes[name] = String(value);}
  removeAttribute(name) {delete this.attributes[name];}
  addEventListener(name, handler) {(this.events[name] ||= []).push(handler);}
  async dispatch(name, event = {}) {for (const handler of this.events[name] || []) await handler({target: this, ...event});}
  querySelectorAll(selector) {return descendants(this).filter(node => selector.startsWith(".") ? node.classList.contains(selector.slice(1)) : node.tagName === selector);}
  querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
  closest() {return null;}
  checkValidity() {return true;}
  focus() {}
  showModal() {this.open = true;}
}
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);

const detail = {
  bid: "300.00", case_key: "working", all_in_acquisition: "300.00", gross_resale_hammer: "1000.00",
  net_resale_proceeds: "1000.00", net_profit: "700.00", return_on_cost_pct: "233.33", profit_on_gross_pct: "70.00",
  buyer_premium: "0.00", purchase_tax: "0.00", purchase_tax_basis_amount: "300.00", selling_commission: "0.00", break_even_resale: "300.00",
  qualifies: true, profit_500: true, profit_1000: false,
  one_more_bid: {available: false, bid: null, additional_all_in_cost: null, profit_reduction: null, reason: "Bid rules above $300.00 are unknown."},
};
function board(overrides = {}) {
  return {
    assumptions: {starting_hammer: "100.00", starting_basis: "opening", increment_mode: "tiers", fixed_increment: "100.00", tiers: [{up_to: "300.00", increment: "100.00"}],
      minimum_profit: "100.00", minimum_return_pct: "10.00", buyer_premium_pct: "0.00", purchase_tax_pct: "0.00", purchase_tax_basis: "hammer_premium",
      acquisition_costs: "0.00", selling_commission_pct: "0.00", selling_costs: "0.00", downside_factor: "0.80", upside_factor: "1.20", resale_overrides: {working: "1000.00"}},
    cases: [{key: "working", resale_hammer: "1000.00", origin: "manual", basis: "Manual override"}],
    coverage_limit: "300.00", notices: ["Known bid tiers end at $300.00; higher bids are not evaluated."],
    shortlist: [{case_key: "working", label: "Working highest supported bid", bid: "300.00", coverage_limited: true, reason: "Higher bid rules are unknown.", detail}],
    selected_bid: "300.00", selected_case: "working", detail,
    rows: [{bid: "300.00", all_in_acquisition: "300.00", cells: [detail]}],
    pagination: {page: 0, page_count: 1, has_next: false},
    profit_targets: [{minimum_profit: "100.00", ceilings: {working: "300.00"}, coverage_limited: {working: true}}],
    ...overrides,
  };
}

function environment(payload) {
  const document = new Element("document");
  document.body = new Element("body"); document.append(document.body);
  document.createElement = tag => new Element(tag);
  const requests = [];
  const storage = new Map();
  const context = vm.createContext({
    document, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    window: {location: {href: "https://example.test/calendar/"}, history: {replaceState() {}}, addEventListener() {}, dispatchEvent() {}},
    CustomEvent: class {constructor(type, options) {this.type = type; Object.assign(this, options);}},
    fetch: async (url, options) => {requests.push({url, options}); return {ok: true, json: async () => payload};},
  });
  for (const file of ["archive_bid_board.js", "saved_bid_board.js"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "static/secondstateapp", file), "utf8"), context);
  const root = new Element(); document.body.append(root);
  return {context, root, requests};
}
async function mount(data) {
  const page = environment({ok: true, analysis: data});
  const view = page.context.window.ArchiveBidBoard.mount(page.root, {lot: {id: 1, bid_board_url: "/board/"}, getEvidence: async () => ({selected_ids: []})});
  await view.refresh();
  return page;
}

test("finite coverage labels the supported ceiling and stops next-bid arithmetic", async () => {
  const {root} = await mount(board());
  assert.match(root.textContent, /Known bid tiers end at \$300\.00/);
  assert.match(root.textContent, /Working highest supported bid/);
  assert.match(root.textContent, /Higher bid rules are unknown/);
  assert.match(root.textContent, /At known tier limit/);
  assert.match(root.textContent, /Bid rules above \$300\.00 are unknown/);
  assert.doesNotMatch(root.textContent, /Next bid Unavailable|Unavailable more acquisition/);
  assert.equal(root.querySelectorAll("button").find(node => node.textContent === "One more bid →").disabled, true);
  assert.equal(root.querySelectorAll("button").find(node => node.textContent === "Later bids →").disabled, true);
});

test("a finite ladder with no supported next bid keeps the save control available", async () => {
  const {root, requests} = await mount(board({rows: [], selected_bid: null, detail: null, shortlist: [], empty_reason: "The next bid is outside the known tier limits."}));
  assert.match(root.textContent, /The next bid is outside the known tier limits/);
  assert.match(root.textContent, /No supported bid is available from this starting hammer/);
  assert.doesNotMatch(root.textContent, /Opening hammer is available as the first bid/);
  assert.equal(root.querySelectorAll("button").find(node => node.textContent === "Save Bid Board").disabled, false);
  assert.equal(JSON.parse(requests[1].options.body).selected_bid, null);
  assert.equal(root.querySelectorAll("button").some(node => node.textContent === "One more bid →"), false);
});

test("open-ended schedules retain the next-bid comparison without a coverage cap", async () => {
  const {root} = await mount(board({coverage_limit: null, notices: [],
    shortlist: [{case_key: "working", label: "Working-case ceiling", bid: "300.00", detail}],
    profit_targets: [{minimum_profit: "100.00", ceilings: {working: "300.00"}}],
    detail: {...detail, one_more_bid: {available: true, bid: "400.00", additional_all_in_cost: "100.00", profit_reduction: "100.00"}},
  }));
  assert.match(root.textContent, /Next bid \$400\.00: \$100\.00 more acquisition cost \/ \$100\.00 less profit/);
  assert.doesNotMatch(root.textContent, /At known tier limit|Higher bid rules are unknown/);
  assert.equal(root.querySelectorAll("button").find(node => node.textContent === "One more bid →").disabled, false);
});

test("saved catalog summary identifies a coverage-capped qualifying bid", () => {
  const {root, context} = environment({});
  const summary = {qualifying_bid: "300.00", qualifying_coverage_limited: true, qualifies: true};
  context.window.SavedBidBoard.mountSummary(root, {lot: {id: 1, title: "Example", saved_bid_board: summary}});
  assert.match(root.textContent, /Qualifying Bid: \$300\.00/);
  assert.match(root.textContent, /At known tier limit; higher bids not evaluated/);
  root.updateSavedBoard({...summary, qualifying_coverage_limited: false});
  assert.doesNotMatch(root.textContent, /At known tier limit/);
});

test("saved viewer preserves finite coverage and supported-bid labels", async () => {
  const data = board();
  const summary = {qualifying_bid: "300.00", qualifying_coverage_limited: true, selected_case: "working", selected_bid: "300.00", qualifies: true, detail};
  const {context} = environment({ok: true, board: {analysis: data, assumptions: data.assumptions, summary}});
  await context.window.SavedBidBoard.open({id: 1, title: "Example", saved_bid_board_url: "/saved/"});
  const text = context.document.body.textContent;
  assert.match(text, /highest supported bid at the known tier limit; higher bids not evaluated/);
  assert.match(text, /Working highest supported bid/);
  assert.match(text, /Higher bid rules are unknown/);
  assert.doesNotMatch(text, /highest saved bid meeting both minimums/);
});

test("saved viewer explains an exhausted finite range without asking for existing inputs", async () => {
  const data = board({rows: [], shortlist: [], selected_bid: null, detail: null, empty_reason: "No available bid remains within the provided bid rules."});
  const {context} = environment({ok: true, board: {analysis: data, assumptions: data.assumptions, summary: {qualifying_bid: null, qualifies: null}}});
  await context.window.SavedBidBoard.open({id: 1, title: "Example", saved_bid_board_url: "/saved/"});
  assert.match(context.document.body.textContent, /No available bid remains within the provided bid rules/);
  assert.doesNotMatch(context.document.body.textContent, /Save a starting hammer and resale case/);
});

test("live and saved Boards count auction archive evidence separately from LiveArt", async () => {
  const data = board({source_summary: {artprice_included_count: 0, liveart_selected_count: 2, archive_selected_count: 1, combined_comp_count: 3}});
  const live = await mount(data);
  assert.match(live.root.textContent, /2 LiveArt \+ 1 auction archive · 3 unique sales used/);
  const {context} = environment({ok: true, board: {analysis: data, assumptions: data.assumptions, summary: {qualifying_bid: "300.00", qualifies: true, detail}}});
  await context.window.SavedBidBoard.open({id: 1, title: "Example", saved_bid_board_url: "/saved/"});
  assert.match(context.document.body.textContent, /2 LiveArt \+ 1 auction archive · 3 unique sales used/);
});

function fiveCaseBoard() {
  const cases = [
    {key: "conservative", label: "Conservative", resale_hammer: "1040.00", origin: "evidence"},
    {key: "working", label: "Working case", resale_hammer: "2200.00", origin: "evidence"},
    {key: "upside_one_third", label: "Upside ⅓", resale_hammer: "4766.67", origin: "interpolated", basis: "One-third between working and optimistic resale assumptions."},
    {key: "upside_two_thirds", label: "Upside ⅔", resale_hammer: "7333.33", origin: "interpolated", basis: "Two-thirds between working and optimistic resale assumptions."},
    {key: "optimistic", label: "Optimistic", resale_hammer: "9900.00", origin: "evidence"},
  ];
  const cells = cases.map(c => ({...detail, bid: "2600.00", case_key: c.key, gross_resale_hammer: c.resale_hammer, all_in_acquisition: "3450.00"}));
  return board({
    cases, rows: [{bid: "2600.00", all_in_acquisition: "3450.00", cells}],
    shortlist: cases.map((c, index) => ({case_key: c.key, label: `${c.label} ceiling`, bid: "2600.00", detail: cells[index]})),
    selected_bid: "2600.00", selected_case: "upside_one_third", detail: cells[2],
    profit_targets: [{minimum_profit: "100.00", ceilings: Object.fromEntries(cases.map(c => [c.key, "2600.00"]))}],
  });
}

test("five cases render in order and intermediate cells remain selectable without new override inputs", async () => {
  const data = fiveCaseBoard();
  const {root, requests} = await mount(data);
  const grid = root.querySelector(".ab-grid"), rows = grid.querySelectorAll("tr");
  assert.equal(rows[0].children.length, 7);
  assert.equal(rows[1].children.length, 7);
  assert.deepEqual(rows[0].children.slice(2).map((th, index) => th.textContent.startsWith(data.cases[index].label)), [true, true, true, true, true]);
  assert.match(rows[0].children[4].textContent, /Resale \$4,766\.67.*Interpolated assumption/);
  assert.match(rows[0].children[5].textContent, /Resale \$7,333\.33.*Interpolated assumption/);
  assert.equal(grid.classList.contains("ab-expanded-cases"), true);
  assert.equal(root.querySelector(".ab-targets").querySelector("tr").children.length, 6);
  assert.equal(root.querySelector(".ab-shortlist").children.length, 5);
  assert.equal(root.querySelector(".ab-resale-fields").querySelectorAll("input").length, 3);
  assert.match(root.querySelector(".ab-detail").textContent, /hammer · Upside ⅓/);
  const intermediate = root.querySelectorAll(".ab-cell").find(cell => cell.dataset.caseKey === "upside_two_thirds");
  assert.match(intermediate.attributes["aria-label"], /Upside ⅔/);
  await intermediate.dispatch("click");
  await new Promise(resolve => setImmediate(resolve));
  const request = JSON.parse(requests.at(-1).options.body);
  assert.equal(request.selected_case, "upside_two_thirds");
  assert.equal(request.selected_bid, "2600.00");
  assert.deepEqual(Object.keys(request.assumptions.resale_overrides), ["conservative", "working", "optimistic"]);
});

test("choosing an intermediate case preserves the grid's horizontal scroll after recalculation", async () => {
  const {root} = await mount(fiveCaseBoard());
  const previousWrap = root.querySelector(".ab-grid").parentElement;
  previousWrap.scrollLeft = 480;
  const intermediate = root.querySelectorAll(".ab-cell").find(cell => cell.dataset.caseKey === "upside_two_thirds");
  await intermediate.dispatch("click");
  await new Promise(resolve => setImmediate(resolve));
  const refreshedWrap = root.querySelector(".ab-grid").parentElement;
  assert.notEqual(refreshedWrap, previousWrap);
  assert.equal(refreshedWrap.scrollLeft, 480);
});

test("saved five-case snapshots show intermediate labels, values and the saved selected cell", async () => {
  const data = fiveCaseBoard();
  const summary = {qualifying_bid: "2600.00", selected_bid: "2600.00", selected_case: "upside_one_third", qualifies: true, detail: data.detail};
  const {context} = environment({ok: true, board: {analysis: data, assumptions: data.assumptions, summary}});
  await context.window.SavedBidBoard.open({id: 1, title: "Example", saved_bid_board_url: "/saved/"});
  const grid = context.document.body.querySelector(".ab-grid"), rows = grid.querySelectorAll("tr");
  assert.equal(rows[0].children.length, 7);
  assert.equal(rows[1].children.length, 7);
  assert.match(rows[0].children[4].textContent, /Upside ⅓.*Resale \$4,766\.67/);
  assert.match(rows[0].children[5].textContent, /Upside ⅔.*Resale \$7,333\.33/);
  assert.match(context.document.body.querySelector(".sb-saved-selection").textContent, /Upside ⅓/);
  assert.match(rows[1].children[4].textContent, /Selected/);
  assert.equal(rows[1].children[4].classList.contains("sb-selected-cell"), true);
  assert.doesNotMatch(context.document.body.textContent, /undefined/);
});

test("existing three-case saved snapshots keep their original three scenario columns", async () => {
  const source = fiveCaseBoard(), keys = ["conservative", "working", "optimistic"];
  const data = {...source, cases: source.cases.filter(c => keys.includes(c.key)),
    rows: source.rows.map(row => ({...row, cells: row.cells.filter(cell => keys.includes(cell.case_key))})),
    shortlist: source.shortlist.filter(pick => keys.includes(pick.case_key)), selected_case: "working"};
  const {context} = environment({ok: true, board: {analysis: data, assumptions: data.assumptions,
    summary: {qualifying_bid: "2600.00", selected_bid: "2600.00", selected_case: "working", qualifies: true}}});
  await context.window.SavedBidBoard.open({id: 1, title: "Existing board", saved_bid_board_url: "/saved/"});
  const grid = context.document.body.querySelector(".ab-grid"), rows = grid.querySelectorAll("tr");
  assert.equal(rows[0].children.length, 5);
  assert.equal(rows[1].children.length, 5);
  assert.equal(grid.classList.contains("ab-expanded-cases"), false);
  assert.doesNotMatch(grid.textContent, /Upside ⅓|Upside ⅔/);
});
