/* Artwork supplied with a sale record; never substitute an artist portrait. */
(function (root) {
  "use strict";
  const safeImageUrl = (value) => {
    if (typeof value !== "string" || value.length > 4096) return "";
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) return "";
      if (!url.hostname.includes(".") || /^[\d.]+$/.test(url.hostname) || url.hostname.includes(":")
        || /(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(url.hostname)) return "";
      return url.href;
    } catch (_error) { return ""; }
  };

  const create = (document, record) => {
    const figure = document.createElement("figure");
    figure.className = "research-sale-artwork";
    const url = safeImageUrl(record.image_url);
    const title = record.title || "Untitled artwork";
    const source = record.provider === "Artprice" || record.match_type === "artprice_html" ? "saved Artprice sale" : "LiveArt record";
    const unavailable = document.createElement("span");
    unavailable.className = "research-sale-image-unavailable";
    unavailable.textContent = "Image unavailable";
    figure.appendChild(unavailable);
    if (!url) return figure;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "research-sale-image-open";
    button.setAttribute("aria-label", `Enlarge image of ${title}`);
    button.title = `Image from ${source} — click to enlarge`;
    const image = document.createElement("img");
    image.alt = `${title} — ${source}`;
    image.loading = "lazy";
    image.decoding = "async";
    image.referrerPolicy = "no-referrer";
    const hint = document.createElement("span");
    hint.className = "research-sale-image-hint";
    hint.textContent = "Enlarge ↗";
    button.append(image, hint);
    unavailable.hidden = true;
    image.addEventListener("error", () => {
      button.hidden = true;
      unavailable.hidden = false;
    });
    image.src = url;

    let dialog = null;
    button.addEventListener("click", () => {
      if (!dialog) {
        dialog = document.createElement("dialog");
        dialog.className = "archive-image-dialog research-sale-image-dialog";
        dialog.setAttribute("aria-label", `Artwork image: ${title}`);
        const header = document.createElement("div");
        header.className = "archive-dialog-heading";
        const heading = document.createElement("h3");
        heading.textContent = title;
        const close = document.createElement("button");
        close.type = "button";
        close.textContent = "Close ×";
        close.addEventListener("click", () => dialog.close());
        header.append(heading, close);
        const expanded = document.createElement("img");
        expanded.alt = image.alt;
        expanded.referrerPolicy = "no-referrer";
        const caption = document.createElement("p");
        caption.className = "research-sale-image-caption";
        caption.textContent = [record.artist, record.auction_house, record.sale_date, `Image from ${source}`].filter(Boolean).join(" · ");
        expanded.addEventListener("error", () => {
          expanded.hidden = true;
          caption.textContent = "This image is currently unavailable. The sale record is still available below.";
        });
        expanded.src = url;
        dialog.append(header, expanded, caption);
        dialog.addEventListener("close", () => button.focus({preventScroll: true}));
        dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
        figure.appendChild(dialog);
      }
      dialog.showModal();
    });
    figure.appendChild(button);
    return figure;
  };
  root.CalendarResearchImages = {safeImageUrl, create};
  if (typeof module === "object" && module.exports) module.exports = root.CalendarResearchImages;
})(typeof window === "object" ? window : globalThis);
