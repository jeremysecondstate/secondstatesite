/* Saved lots page separately from the selected day's tracked lots. */
function createRandomLotsGallery(document, window, renderCard, updatePrices) {
  const element = (id) => document.getElementById(id);
  const catalog = element("day-gallery-catalog");
  const panel = element("random-lots-panel");
  const open = element("random-lots-open");
  const heading = element("random-lots-title");
  const status = element("random-lots-status");
  const grid = element("random-lots-grid");
  const pagination = element("random-lots-pagination");
  const previous = element("random-lots-previous");
  const next = element("random-lots-next");
  const retry = element("random-lots-retry");
  const countBadge = element("random-lots-count");
  const orderSelect = element("random-lots-sort");
  const sortNote = element("random-lots-sort-note");
  const orders = new Set(["catalog", "artist", "house", "estimate-desc", "estimate-asc"]);
  let saleDay = "";
  let loadedDay = "";
  let loadedOrder = "catalog";
  let lots = [];
  let page = 0;
  let pending = null;

  function writeLocation(number, method, order = loadedOrder) {
    const url = new URL(window.location.href);
    if (number) url.searchParams.set("collection", "random");
    else url.searchParams.delete("collection");
    if (number > 1) url.searchParams.set("collection_page", number);
    else url.searchParams.delete("collection_page");
    if (number && order !== "catalog") url.searchParams.set("collection_sort", order);
    else url.searchParams.delete("collection_sort");
    window.history[method](window.history.state, "", url);
  }

  async function loadPrices(url, request) {
    if (!lots.some(window.CalendarCurrency.hasForeignPrices)) return;
    const priceUrl = new URL(url);
    priceUrl.searchParams.set("prices", "usd");
    let quotes = [];
    try {
      const response = await window.fetch(priceUrl, {
        credentials: "same-origin", headers: {Accept: "application/json"}, signal: request.signal,
      });
      if (response.ok) {
        const payload = await response.json();
        if (payload.day === loadedDay && payload.page === page &&
            (payload.sort == null || payload.sort === loadedOrder) && Array.isArray(payload.lots)) quotes = payload.lots;
      }
    } catch {
      // The original prices stay visible when an exchange-rate source is unavailable.
    }
    if (request === pending) updatePrices(grid, lots, quotes);
  }

  async function loadPage(number, order = loadedOrder) {
    pending?.abort();
    const request = new AbortController();
    pending = request;
    const day = saleDay;
    loadedDay = day;
    loadedOrder = order;
    page = number;
    lots = [];
    grid.replaceChildren();
    grid.setAttribute("aria-busy", "true");
    pagination.hidden = true;
    retry.hidden = true;
    status.textContent = "Loading saved lots…";
    const url = new URL(panel.dataset.url, window.location.origin);
    url.searchParams.set("day", day);
    url.searchParams.set("page", number);
    url.searchParams.set("sort", order);
    try {
      const response = await window.fetch(url, {
        credentials: "same-origin", headers: {Accept: "application/json"}, signal: request.signal,
      });
      if (request !== pending) return;
      if (number > 1 && response.status === 404) {
        writeLocation(1, "replaceState");
        return loadPage(1);
      }
      if (!response.ok) throw new Error("Random Lots unavailable");
      const data = await response.json();
      if (request !== pending) return;
      if (data.day !== day) throw new Error("Unexpected sale date");
      if (data.sort != null && data.sort !== order) throw new Error("Unexpected sort order");
      lots = data.lots;
      grid.replaceChildren(...lots.map(renderCard));
      grid.setAttribute("aria-busy", "false");
      page = data.page;
      if (number !== page) writeLocation(page, "replaceState");
      countBadge.textContent = String(data.total);
      status.textContent = data.total
        ? `${data.total} saved lot${data.total === 1 ? "" : "s"} for this date`
        : "No saved lots for this date.";
      element("random-lots-page").textContent = `Page ${page} of ${data.pages}`;
      previous.disabled = page <= 1;
      next.disabled = page >= data.pages;
      pagination.hidden = data.pages <= 1;
      await loadPrices(url, request);
    } catch {
      if (request !== pending) return;
      status.textContent = "The saved lots couldn’t load.";
      retry.hidden = false;
    } finally {
      if (request === pending) {
        pending = null;
        grid.setAttribute("aria-busy", "false");
      }
    }
  }

  function syncPanel() {
    const params = new URL(window.location.href).searchParams;
    const visible = !open.hidden && params.get("collection") === "random";
    const wasVisible = !panel.hidden;
    panel.hidden = !visible;
    catalog.classList.toggle("is-random-lots-open", visible);
    catalog.setAttribute("aria-labelledby", visible ? "random-lots-title" : "day-gallery-title");
    if (visible) {
      const requested = Number(params.get("collection_page"));
      const number = Number.isSafeInteger(requested) && requested > 0 ? requested : 1;
      const requestedOrder = params.get("collection_sort");
      const order = orders.has(requestedOrder) ? requestedOrder : "catalog";
      orderSelect.value = order;
      sortNote.hidden = !order.startsWith("estimate-");
      if (loadedDay !== saleDay || number !== page || order !== loadedOrder) loadPage(number, order);
      if (!wasVisible) heading.focus();
    } else if (wasVisible) {
      pending?.abort();
      pending = null;
      page = 0;
      lots = [];
      grid.replaceChildren();
      if (!open.hidden) {
        element("day-gallery-houses").open = true;
        open.focus();
      }
    }
  }

  function syncView(view, day, count, dayLabel = day) {
    if (day !== saleDay) countBadge.textContent = String(count || 0);
    saleDay = day;
    open.hidden = view !== "catalog" || !day;
    element("random-lots-date").textContent = day ? `Jeremy’s Catalog / ${dayLabel}` : "";
    syncPanel();
  }

  open.addEventListener("click", () => {
    writeLocation(1, "pushState", "catalog");
    syncPanel();
  });
  element("random-lots-back").addEventListener("click", () => {
    writeLocation(0, "replaceState");
    syncPanel();
  });
  orderSelect.addEventListener("change", () => {
    writeLocation(1, "replaceState", orderSelect.value);
    syncPanel();
  });
  function goToPage(number) {
    writeLocation(number, "replaceState");
    loadPage(number);
    heading.focus();
  }
  previous.addEventListener("click", () => goToPage(page - 1));
  next.addEventListener("click", () => goToPage(page + 1));
  retry.addEventListener("click", () => loadPage(page));
  return {syncView, get lots() { return lots; }};
}

if (typeof module !== "undefined" && module.exports) module.exports = {createRandomLotsGallery};
