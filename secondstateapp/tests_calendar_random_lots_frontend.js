const assert = require("node:assert/strict");
const {setImmediate: completeRequests} = require("node:timers/promises");
const {test} = require("node:test");
const {createRandomLotsGallery} = require("./static/secondstateapp/calendar_random_lots.js");

function gallery(search, fetchPage) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const node = new EventTarget();
      Object.assign(node, {
        hidden: true,
        dataset: {},
        classList: {toggle() {}},
        setAttribute(name, value) { this[name] = value; },
        replaceChildren(...children) { this.children = children; },
        focus() { this.focused = true; },
      });
      elements.set(id, node);
    }
    return elements.get(id);
  }
  element("random-lots-panel").dataset.url = "/calendar/random-lots/";
  const location = new URL("/calendar/?" + search, "https://secondstate.art");
  const navigate = (_state, _title, url) => { location.href = url; };
  const window = {location, history: {pushState: navigate, replaceState: navigate}, fetch: fetchPage};
  const controller = createRandomLotsGallery({getElementById: element}, window, lot => lot.id);
  return {
    element, location, controller,
    click: id => element(id).dispatchEvent(new Event("click")),
  };
}

function response(page) {
  return {ok: true, json: async () => ({
    page, total: 25, pages: 2, lots: [{id: page === 1 ? 31796 : 31342}],
  })};
}

test("opening and paging the saved collection preserves the selected catalog day and house", async () => {
  const search = "view=catalog&day=2026-11-24&house=AZ+Auction&hide_attributed=1";
  const requests = [];
  const g = gallery(search, async url => {
    requests.push(url.search);
    return response(Number(url.searchParams.get("page")));
  });
  g.controller.syncView("catalog");
  assert.equal(g.element("random-lots-open").hidden, false);
  assert.equal(g.element("random-lots-panel").hidden, true);
  assert.equal(requests.length, 0);

  g.click("random-lots-open");
  await completeRequests();
  assert.equal(g.element("random-lots-panel").hidden, false);
  assert.deepEqual(g.element("random-lots-grid").children, [31796]);
  assert.equal(g.element("random-lots-previous").disabled, true);
  assert.equal(g.location.searchParams.get("collection"), "random");

  g.click("random-lots-next");
  await completeRequests();
  assert.deepEqual(requests, ["?page=1", "?page=2"]);
  assert.deepEqual(g.element("random-lots-grid").children, [31342]);
  assert.equal(g.element("random-lots-next").disabled, true);
  assert.equal(g.location.searchParams.get("collection_page"), "2");
  g.click("random-lots-back");
  assert.equal(g.element("random-lots-panel").hidden, true);
  assert.equal(g.location.searchParams.toString(), search);
});

test("a direct page link supports retry and safely discards a response after leaving the gallery", async () => {
  let attempts = 0;
  let resolveRetry;
  const g = gallery("view=catalog&collection=random&collection_page=2", async url => {
    assert.equal(url.searchParams.get("page"), "2");
    if (++attempts === 1) return {ok: false};
    return new Promise(resolve => { resolveRetry = resolve; });
  });
  g.controller.syncView("catalog");
  await completeRequests();
  assert.equal(g.element("random-lots-retry").hidden, false);
  g.click("random-lots-retry");
  assert.equal(attempts, 2);
  g.click("random-lots-back");
  resolveRetry(response(2));
  await completeRequests();
  assert.equal(g.element("random-lots-panel").hidden, true);
  assert.deepEqual(g.element("random-lots-grid").children, []);
});
