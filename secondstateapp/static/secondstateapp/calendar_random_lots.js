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
  const artistSearch = element("random-lots-artist-search");
  const facetControls = {
    house: {details: element("random-lots-houses"), list: element("random-lots-house-filters"),
      summary: element("random-lots-houses-summary"), all: "All houses"},
    artist: {details: element("random-lots-artists"), list: element("random-lots-artist-filters"),
      summary: element("random-lots-artists-summary"), all: "All artists"},
  };
  const orders = new Set(["catalog", "artist", "house", "estimate-desc", "estimate-asc"]);
  let saleDay = "";
  let loadedDay = "";
  let loadedOrder = "catalog";
  let filters = {house: "", artist: ""};
  let choices = {houses: [], artists: []};
  let lots = [];
  let page = 0;
  let pending = null;

  function writeLocation(number, method, order = loadedOrder, selection = filters) {
    const url = new URL(window.location.href);
    if (number) url.searchParams.set("collection", "random");
    else url.searchParams.delete("collection");
    if (number > 1) url.searchParams.set("collection_page", number);
    else url.searchParams.delete("collection_page");
    if (number && order !== "catalog") url.searchParams.set("collection_sort", order);
    else url.searchParams.delete("collection_sort");
    for (const name of Object.keys(facetControls)) {
      if (number && selection[name]) url.searchParams.set("collection_" + name, selection[name]);
      else url.searchParams.delete("collection_" + name);
    }
    window.history[method](window.history.state, "", url);
  }

  const searchText = text => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();

  function sameOptions(left, right) {
    return left === right || (left.length === right.length && left.every((option, index) => {
      const other = right[index];
      return option.key === other.key && option.label === other.label && option.count === other.count;
    }));
  }

  function renderChoices(name) {
    const control = facetControls[name];
    const {details, list, summary, all} = control;
    const options = name === "artist" ? choices.artists : choices.houses;
    const selected = filters[name];
    const current = options.find(option => option.key === selected);
    const available = options.filter(option => option.count > 0).length;
    const selectionLabel = selected ? (current?.label ?? `Selected ${name} unavailable`) : all;
    summary.textContent = `${available} ${name}${available === 1 ? "" : "s"} · ${selectionLabel}`;
    if (!details.open) return;
    const query = name === "artist" ? searchText(artistSearch.value) : "";
    const last = control.rendered;
    if (last && selected === last.selected && query === last.query && sameOptions(options, last.options)) return;
    control.rendered = {options, selected, query};
    const count = options.reduce((total, option) => total + option.count, 0);
    const focusedKey = list.contains(document.activeElement) ? document.activeElement.dataset.key : undefined;
    let focusTarget;
    const buttons = [];
    for (const {key, label, count: optionCount} of [{key: "", label: all, count}, ...options]) {
      if (key && query && !searchText(label).includes(query)) continue;
      const button = document.createElement("button");
      button.className = "day-gallery-filter";
      button.type = "button";
      button.dataset.key = key;
      button.setAttribute("aria-pressed", String(key === selected));
      const title = document.createElement("span");
      title.className = "day-gallery-filter-name";
      title.textContent = label;
      const badge = document.createElement("span");
      badge.className = "day-gallery-filter-count";
      badge.textContent = String(optionCount);
      button.append(title, badge);
      button.addEventListener("click", () => {
        if (filters[name] === key) return;
        writeLocation(1, "pushState", loadedOrder, {...filters, [name]: key});
        syncPanel();
      });
      buttons.push(button);
      if (key === focusedKey) focusTarget = button;
    }
    if (query && buttons.length === 1) {
      const empty = document.createElement("p");
      empty.className = "day-gallery-sort-note";
      empty.textContent = "No artists match your search.";
      buttons.push(empty);
    }
    list.replaceChildren(...buttons);
    if (focusedKey !== undefined) (focusTarget || buttons[0]).focus({preventScroll: true});
  }

  async function loadPrices(url, request) {
    if (!lots.some(window.CalendarCurrency.hasForeignPrices)) return;
    const priceUrl = new URL(url);
    priceUrl.searchParams.delete("facets");
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

  async function loadPage(number, order = loadedOrder, selection = filters) {
    pending?.abort();
    const request = new AbortController();
    pending = request;
    const day = saleDay;
    const changedDay = day !== loadedDay;
    const changedFilters = selection.house !== filters.house || selection.artist !== filters.artist;
    loadedDay = day;
    loadedOrder = order;
    filters = selection;
    if (changedDay || changedFilters) {
      if (changedDay) {
        choices = {houses: [], artists: []};
        artistSearch.value = "";
      }
      renderChoices("house");
      renderChoices("artist");
    }
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
    url.searchParams.set("facets", "1");
    for (const name of Object.keys(facetControls)) {
      if (selection[name]) url.searchParams.set("collection_" + name, selection[name]);
    }
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
      if (data.facets) {
        choices = data.facets;
        renderChoices("house");
        renderChoices("artist");
      }
      lots = data.lots;
      grid.replaceChildren(...lots.map(renderCard));
      grid.setAttribute("aria-busy", "false");
      page = data.page;
      if (number !== page) writeLocation(page, "replaceState");
      const filtered = Boolean(selection.house || selection.artist);
      if (data.day_total != null || !filtered) countBadge.textContent = String(data.day_total ?? data.total);
      if (filtered && data.day_total !== 0) {
        status.textContent = data.total
          ? `${data.total} matching saved lot${data.total === 1 ? "" : "s"} for this date`
          : "No saved lots match these filters.";
      } else {
        status.textContent = data.total
          ? `${data.total} saved lot${data.total === 1 ? "" : "s"} for this date`
          : "No saved lots for this date.";
      }
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
      const selection = {house: params.get("collection_house") || "", artist: params.get("collection_artist") || ""};
      orderSelect.value = order;
      sortNote.hidden = !order.startsWith("estimate-");
      if (loadedDay !== saleDay || number !== page || order !== loadedOrder ||
          filters.house !== selection.house || filters.artist !== selection.artist) loadPage(number, order, selection);
      if (!wasVisible) heading.focus();
    } else if (wasVisible) {
      pending?.abort();
      pending = null;
      page = 0;
      lots = [];
      artistSearch.value = "";
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
    writeLocation(1, "pushState", "catalog", {});
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
  artistSearch.addEventListener("input", () => renderChoices("artist"));
  for (const [name, control] of Object.entries(facetControls)) {
    control.details.addEventListener("toggle", () => {
      if (control.details.open) renderChoices(name);
    });
  }
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
