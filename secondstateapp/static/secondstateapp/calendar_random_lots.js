/* The saved collection has its own pages and never replaces the selected day's data. */
function createRandomLotsGallery(document, window, renderCard) {
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
  let page = 0;
  let pending = null;

  function writeLocation(number, method) {
    const url = new URL(window.location.href);
    if (number) url.searchParams.set("collection", "random");
    else url.searchParams.delete("collection");
    if (number > 1) url.searchParams.set("collection_page", number);
    else url.searchParams.delete("collection_page");
    window.history[method](window.history.state, "", url);
  }

  async function loadPage(number) {
    pending?.abort();
    const request = new AbortController();
    pending = request;
    page = number;
    grid.replaceChildren();
    grid.setAttribute("aria-busy", "true");
    pagination.hidden = true;
    retry.hidden = true;
    status.textContent = "Loading saved lots…";
    const url = new URL(panel.dataset.url, window.location.origin);
    url.searchParams.set("page", number);
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
      const cards = data.lots.map(renderCard);
      grid.replaceChildren(...cards);
      page = data.page;
      if (number !== page) writeLocation(page, "replaceState");
      status.textContent = data.total ? `${data.total} saved lots across all sale dates` : "No saved lots in this collection.";
      element("random-lots-page").textContent = `Page ${page} of ${data.pages}`;
      previous.disabled = page <= 1;
      next.disabled = page >= data.pages;
      pagination.hidden = data.pages <= 1;
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

  function syncView(view) {
    open.hidden = view !== "catalog";
    const params = new URL(window.location.href).searchParams;
    const visible = !open.hidden && params.get("collection") === "random";
    const wasVisible = !panel.hidden;
    panel.hidden = !visible;
    catalog.classList.toggle("is-random-lots-open", visible);
    catalog.setAttribute("aria-labelledby", visible ? "random-lots-title" : "day-gallery-title");
    if (visible) {
      const requested = Number(params.get("collection_page"));
      const number = Number.isSafeInteger(requested) && requested > 0 ? requested : 1;
      if (number !== page) loadPage(number);
      if (!wasVisible) heading.focus();
    } else if (wasVisible) {
      pending?.abort();
      pending = null;
      page = 0;
      grid.replaceChildren();
      if (!open.hidden) {
        element("day-gallery-houses").open = true;
        open.focus();
      }
    }
  }

  open.addEventListener("click", () => {
    writeLocation(1, "pushState");
    syncView("catalog");
  });
  element("random-lots-back").addEventListener("click", () => {
    writeLocation(0, "replaceState");
    syncView("catalog");
  });
  function goToPage(number) {
    writeLocation(number, "replaceState");
    loadPage(number);
    heading.focus();
  }
  previous.addEventListener("click", () => goToPage(page - 1));
  next.addEventListener("click", () => goToPage(page + 1));
  retry.addEventListener("click", () => loadPage(page));
  return {syncView};
}

if (typeof module !== "undefined" && module.exports) module.exports = {createRandomLotsGallery};
