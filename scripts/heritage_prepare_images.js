/* Paste this entire file into DevTools on a Heritage sale's results page.
 * It changes only that sale's primary catalog images, then offers Restore.
 * Wait for the banner to finish before Save As -> Webpage, Complete.
 */
(() => {
  "use strict";

  const WIDTH = 612;
  const HEIGHT = 600;
  const CONCURRENCY = 4;
  const TIMEOUT_MS = 20000;
  const BANNER_ID = "secondstate-heritage-image-preparation";

  function largerHeritageImageURL(value) {
    let source;
    try {
      source = new URL(value);
    } catch {
      return null;
    }
    if (source.protocol !== "https:" || source.username || source.password || source.port
        || !/^dyn\d+\.heritagestatic\.com$/i.test(source.hostname)
        || source.pathname !== "/ha" || source.searchParams.getAll("p").length !== 1) {
      return null;
    }
    const product = source.searchParams.get("p");
    if (!/^\d+(?:-\d+)+$/.test(product)) return null;
    // Carry only the public image identity, never arbitrary query parameters.
    const target = new URL(`${source.origin}/ha`);
    target.searchParams.set("p", product);
    target.searchParams.set("w", String(WIDTH));
    target.searchParams.set("h", String(HEIGHT));
    target.searchParams.set("it", "product");
    return target.href;
  }

  function isLargerWithoutDownsizing(next, previous) {
    return next.width >= previous.width && next.height >= previous.height
      && (next.width > previous.width || next.height > previous.height);
  }

  // Permit offline tests of the URL and resolution rules without a browser.
  if (typeof document === "undefined") {
    if (typeof module !== "undefined") {
      module.exports = { largerHeritageImageURL, isLargerWithoutDownsizing };
    }
    return;
  }

  const current = new URL(location.href);
  const isHeritage = (host) => /^(?:[a-z0-9-]+\.)*ha\.com$/i.test(host);
  if (current.protocol !== "https:" || !isHeritage(current.hostname)
      || !/^\/c\/search(?:\/results)?\.zx$/.test(current.pathname)) {
    throw new Error("Open the selected Heritage sale's live results page before running this helper.");
  }
  const sales = new Set([...current.searchParams]
    .filter(([key]) => /^(auction_name|saleno)$/i.test(key))
    .map(([, value]) => value));
  if (sales.size !== 1 || !/^\d+$/.test([...sales][0])) {
    throw new Error("Use a results URL identifying one Heritage sale with auction_name or saleNo.");
  }
  const sale = [...sales][0];
  const catalog = document.querySelector("#batchBids");
  if (!catalog) throw new Error("No Heritage results catalog was found. Wait for its lot cards to load.");
  if (document.getElementById(BANNER_ID)) {
    console.info("Image preparation is already open. Use its Restore button before running it again.");
    return;
  }

  const tasks = [];
  const seen = new Set();
  for (const card of catalog.querySelectorAll(".item-block")) {
    const link = card.querySelector("a.item-title[href]");
    if (!link) continue;
    let lotURL;
    try { lotURL = new URL(link.getAttribute("href"), current); } catch { continue; }
    const identity = /\/a\/(\d+)-(\d+)\.s(?:\/|$)/i.exec(lotURL.pathname);
    if (!isHeritage(lotURL.hostname) || !identity || identity[1] !== sale) continue;
    const img = card.querySelector("a.photo-holder img, img.thumbnail");
    if (img && seen.has(img)) continue;
    if (img) seen.add(img);
    tasks.push({ img, lotNumber: identity[2] });
  }
  if (!tasks.length) throw new Error("No lot cards matched the selected sale. Wait for the results to finish loading.");

  const banner = document.createElement("div");
  banner.id = BANNER_ID;
  banner.setAttribute("role", "status");
  banner.style.cssText = "position:fixed;left:12px;right:12px;bottom:12px;z-index:2147483647;"
    + "padding:14px 18px;background:#102534;color:white;border:2px solid #e2bd70;"
    + "border-radius:8px;font:15px/1.5 system-ui,sans-serif;box-shadow:0 4px 24px #0007;";
  const status = document.createElement("span");
  const restoreButton = document.createElement("button");
  restoreButton.type = "button";
  restoreButton.textContent = "Stop and restore originals";
  restoreButton.style.cssText = "margin-left:16px;padding:6px 12px;cursor:pointer;color:#102534;background:#fff;";
  banner.append(status, restoreButton);
  document.body.append(banner);

  const controller = new AbortController();
  const snapshots = new Map();
  const failures = [];
  let ready = 0;
  let kept = 0;
  let cursor = 0;
  let finished = false;
  const attributes = ["src", "data-src", "loading"];

  function restoreImage(img) {
    const original = snapshots.get(img);
    if (!original) return;
    for (const [name, value] of original) {
      if (value === null) img.removeAttribute(name);
      else img.setAttribute(name, value);
    }
  }

  function updateProgress() {
    status.textContent = `Heritage sale ${sale}: ${ready}/${tasks.length} images ready; `
      + `${failures.length} failed${kept ? `; ${kept} larger originals retained` : ""}. `
      + (finished
        ? ready
          ? "Save now with Ctrl+S → Webpage, Complete, then import the saved HTML in Artist Watchlist. "
            + (failures.length ? "Failed images were left at their original size; restore and rerun to retry." : "")
          : "No larger images were prepared. Restore and retry after the catalog thumbnails have loaded."
        : "Preparing up to four images at a time; wait before saving.");
    if (finished) restoreButton.textContent = "Restore originals";
    banner.title = failures.length ? `Lots needing another attempt: ${failures.join(", ")}` : "";
  }

  restoreButton.addEventListener("click", () => {
    controller.abort();
    for (const img of snapshots.keys()) restoreImage(img);
    banner.remove();
  });

  function loadImage(img, url) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const signal = controller.signal;
      const timer = setTimeout(() => finish(new Error("Image load timed out")), TIMEOUT_MS);
      const cleanup = () => {
        clearTimeout(timer);
        img.removeEventListener("load", loaded);
        img.removeEventListener("error", failed);
        signal.removeEventListener("abort", aborted);
      };
      const finish = (error) => {
        if (settled) return;
        settled = true;
        cleanup();
        if (error) {
          // End a timed-out detached preload before a worker starts another.
          if (!img.isConnected) img.removeAttribute("src");
          reject(error);
        }
        else resolve({ width: img.naturalWidth, height: img.naturalHeight });
      };
      const loaded = () => {
        Promise.resolve(typeof img.decode === "function" ? img.decode() : undefined)
          .then(() => finish(img.naturalWidth > 0 && img.naturalHeight > 0
            ? null : new Error("Image has no decoded pixels")), finish);
      };
      const failed = () => finish(new Error("Image did not load"));
      const aborted = () => finish(new Error("Preparation was stopped"));
      img.addEventListener("load", loaded);
      img.addEventListener("error", failed);
      signal.addEventListener("abort", aborted, { once: true });
      if (signal.aborted) return aborted();
      img.src = url;
      if (img.complete && img.naturalWidth) loaded();
    });
  }

  async function prepare({ img, lotNumber }) {
    try {
      if (!img || img.getAttribute("srcset") || img.closest("picture")?.querySelector("source[srcset]")) {
        throw new Error("No supported primary catalog image");
      }
      const source = [img.currentSrc, img.getAttribute("src"), img.getAttribute("data-src")]
        .find((value) => value && largerHeritageImageURL(value));
      const target = source && largerHeritageImageURL(source);
      if (!target) throw new Error("Image is not a recognized Heritage CDN product");
      snapshots.set(img, attributes.map((name) => [name, img.getAttribute(name)]));
      const previous = img.complete && img.naturalWidth && img.naturalHeight
        ? { width: img.naturalWidth, height: img.naturalHeight }
        : await loadImage(new Image(), source);
      if (controller.signal.aborted) return;
      if (previous.width >= WIDTH || previous.height >= HEIGHT) {
        // Heritage's lazy loader can otherwise replace a retained large src
        // with its older small data-src after scrolling or saving the page.
        img.setAttribute("loading", "eager");
        img.setAttribute("data-src", source);
        kept++;
        ready++;
        return;
      }
      const candidate = await loadImage(new Image(), target);
      if (!isLargerWithoutDownsizing(candidate, previous)) throw new Error("Source did not provide larger pixels");
      if (controller.signal.aborted) return;
      if (!img.isConnected) throw new Error("Catalog changed during preparation; rerun on the current page");
      img.setAttribute("loading", "eager");
      img.setAttribute("data-src", target);
      const displayed = await loadImage(img, target);
      if (controller.signal.aborted) return;
      if (!isLargerWithoutDownsizing(displayed, previous)) throw new Error("Larger image was not retained by the page");
      ready++;
    } catch {
      if (img) restoreImage(img);
      if (!controller.signal.aborted) failures.push(lotNumber);
    } finally {
      if (!controller.signal.aborted) updateProgress();
    }
  }

  async function worker() {
    while (!controller.signal.aborted && cursor < tasks.length) {
      await prepare(tasks[cursor++]);
    }
  }
  updateProgress();
  Promise.all(Array.from({ length: Math.min(CONCURRENCY, tasks.length) }, worker)).then(() => {
    if (controller.signal.aborted) return;
    finished = true;
    updateProgress();
  });
})();
