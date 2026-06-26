(async () => {
  const HOUSE = "rago";
  const AUCTION_URL = location.href;
  const CONCURRENCY = 3;
  const DETAIL_DELAY_MS = 250;

  const clean = (v) =>
    String(v ?? "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t\r\f\v]+/g, " ")
      .replace(/\n\s+/g, "\n")
      .trim();

  const absoluteUrl = (url, base = location.href) => {
    if (!url) return "";
    try {
      return new URL(url, base).href;
    } catch {
      return "";
    }
  };

  const escapeHtml = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));

  const nl2br = (v) => escapeHtml(v).replace(/\n/g, "<br>");

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const splitLines = (text) =>
    clean(text)
      .split(/\n| {2,}|\t|(?=\b(?:Estimate|Starting Bid|Starting price|Current Bid|Condition|Condition Report|Provenance|Literature|Description|Lot Description)\b\s*:)/i)
      .map(clean)
      .filter(Boolean);

  const uniqBy = (arr, fn) => {
    const seen = new Set();
    return arr.filter((item) => {
      const key = fn(item);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  const csvEscape = (v) => {
    const s = String(v ?? "");
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };

  const downloadTextFile = (filename, text, mime = "text/plain;charset=utf-8") => {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 1000);
  };

  const fetchDoc = async (url) => {
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    const html = await res.text();
    return new DOMParser().parseFromString(html, "text/html");
  };

  const mapWithConcurrency = async (items, limit, mapper) => {
    const results = new Array(items.length);
    let i = 0;
    const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (i < items.length) {
        const idx = i++;
        results[idx] = await mapper(items[idx], idx);
      }
    });
    await Promise.all(workers);
    return results;
  };

  const textOf = (root, selectors) => {
    for (const sel of selectors) {
      const el = root.querySelector(sel);
      const txt = clean(el?.innerText || el?.textContent || "");
      if (txt) return txt;
    }
    return "";
  };

  const attrOf = (root, selectors, attr) => {
    for (const sel of selectors) {
      const el = root.querySelector(sel);
      const val = el?.getAttribute(attr);
      if (val) return val;
    }
    return "";
  };

  const getImgUrl = (root) => {
    const img = root.querySelector("img");
    if (!img) return "";
    const srcset =
      img.getAttribute("data-srcset") ||
      img.getAttribute("srcset") ||
      img.getAttribute("data-lazy-srcset") ||
      "";
    if (srcset) {
      const best = srcset
        .split(",")
        .map((part) => {
          const [url, size] = part.trim().split(/\s+/);
          const n = parseInt(size, 10) || 0;
          return { url, n };
        })
        .filter((x) => x.url)
        .sort((a, b) => b.n - a.n)[0];
      if (best?.url) return absoluteUrl(best.url);
    }
    return absoluteUrl(
      img.getAttribute("data-src") ||
        img.getAttribute("data-lazy-src") ||
        img.getAttribute("data-original") ||
        img.getAttribute("src")
    );
  };

  const normalizeMoney = (s) => clean(s).replace(/\s+/g, " ");

  const extractByLabel = (text, labels) => {
    const labelGroup = labels.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    const stop =
      "Estimate|Starting Bid|Starting price|Current Bid|Bid Count|Bids|Condition Report|Condition|Provenance|Literature|Description|Lot Description|Medium|Dimensions|Measurements|Signed|Exhibited|Notes";
    const re = new RegExp(
      `(?:^|\\n|\\b)(${labelGroup})\\s*:?\\s*([\\s\\S]{0,2500}?)(?=\\n\\s*(?:${stop})\\s*:?|$)`,
      "i"
    );
    const m = text.match(re);
    return clean(m?.[2] || "");
  };

  const extractSection = (doc, labels) => {
    const wanted = labels.map((s) => s.toLowerCase());
    const candidates = Array.from(doc.querySelectorAll("h1,h2,h3,h4,h5,dt,strong,b,.label,[class*='label'],[class*='title']"));
    for (const el of candidates) {
      const label = clean(el.textContent).replace(/:$/, "").toLowerCase();
      if (!wanted.some((w) => label === w || label.includes(w))) continue;

      const parts = [];
      let n = el.nextElementSibling;
      for (let guard = 0; n && guard < 8; guard++, n = n.nextElementSibling) {
        const tag = n.tagName?.toLowerCase();
        const nt = clean(n.innerText || n.textContent || "");
        if (!nt) continue;
        if (/^(h1|h2|h3|h4|h5|dt)$/.test(tag)) break;
        if (/^(estimate|starting bid|current bid|condition|condition report|provenance|literature|description|lot description|medium|dimensions|measurements)$/i.test(nt.replace(/:$/, ""))) break;
        parts.push(nt);
        if (nt.length > 1200) break;
      }
      const joined = clean(parts.join("\n"));
      if (joined) return joined;
    }
    return "";
  };

  const parseLotFromUrl = (url) => {
    const m = String(url || "").match(/\/(\d+)(?:[/?#]|$)/);
    return m ? m[1] : "";
  };

  const parseCard = (card) => {
    const link =
      card.matches("a[href]") ? card : card.querySelector('a[href*="/auction-lot/"], a[href*="/auctions/"]');
    const url = absoluteUrl(link?.getAttribute("href") || "");
    const rawText = clean(card.innerText || card.textContent || "");
    const dataLot = card.getAttribute("data-lot") || card.getAttribute("data-lot-ref") || card.dataset?.lot || "";
    const lotFromText = rawText.match(/^\s*(\d+[A-Z]?)\b/i)?.[1] || "";
    const lot = clean(dataLot || lotFromText || parseLotFromUrl(url));

    const artist =
      textOf(card, [".artist", "[class*='artist']", "[data-field='artist']"]) ||
      clean(rawText.match(/^\s*\d+[A-Z]?\s+([^\n]+?)(?=\n| {2,}|$)/i)?.[1] || "");

    const title =
      textOf(card, [".title", "[class*='title']", "[data-field='title']"]) ||
      clean(rawText.split(/\n/).map(clean).filter(Boolean).find((line) => line && !line.match(/^\d+[A-Z]?\b/) && line !== artist && !/\$\d/.test(line)) || "");

    const estimate =
      textOf(card, [".estimate", "[class*='estimate']", "[data-field='estimate']"]) ||
      normalizeMoney(rawText.match(/\$[\d,]+(?:\s*[–-]\s*\$?[\d,]+)?/)?.[0] || "");

    const startingPrice =
      normalizeMoney(rawText.match(/starting\s*bid\s*:?\s*(\$[\d,]+)/i)?.[1] || "");

    const currentBid =
      normalizeMoney(rawText.match(/current\s*bid\s*:?\s*(\$[\d,]+)/i)?.[1] || "");

    const bidCount =
      clean(
        rawText.match(/(?:current\s*bid\s*:?\s*\$[\d,]+\s*)?(\d+)\s*bids?\b/i)?.[1] ||
          rawText.match(/\bbids?\s*:?\s*(\d+)\b/i)?.[1] ||
          ""
      );

    return {
      lot,
      artist,
      birth: "",
      title,
      estimate,
      startingPrice,
      currentBid,
      bidCount,
      provenance: "",
      literature: "",
      image: getImgUrl(card),
      url,
      error: "",
      _cardText: rawText,
    };
  };

  const parseDetail = (doc, baseLot) => {
    const bodyText = clean(doc.body?.innerText || "");
    const titleText = textOf(doc, ["h1", ".lot-title", "[class*='lot'][class*='title']", ".title", "[class*='title']"]);
    const artistText = textOf(doc, [".artist", "[class*='artist']", "[data-field='artist']"]);
    const estimateText =
      textOf(doc, [".estimate", "[class*='estimate']", "[data-field='estimate']"]) ||
      normalizeMoney(bodyText.match(/Estimate\s*:?\s*(\$[\d,]+(?:\s*[–-]\s*\$?[\d,]+)?)/i)?.[1] || "");

    const startingPrice =
      normalizeMoney(bodyText.match(/(?:Starting Bid|Starting price)\s*:?\s*(\$[\d,]+)/i)?.[1] || "");

    const currentBid =
      normalizeMoney(bodyText.match(/Current Bid\s*:?\s*(\$[\d,]+)/i)?.[1] || "");

    const bidCount =
      clean(
        bodyText.match(/(\d+)\s*bids?\b/i)?.[1] ||
          bodyText.match(/Bid Count\s*:?\s*(\d+)/i)?.[1] ||
          ""
      );

    const birth =
      clean(
        bodyText.match(/\b(?:born|b\.)\s*(\d{4})\b/i)?.[0] ||
          bodyText.match(/\((?:[A-Z][a-z]+\s*)?(?:b\.?\s*)?\d{4}(?:\s*[-–]\s*(?:\d{4})?)?\)/)?.[0] ||
          ""
      );

    let provenance =
      extractSection(doc, ["Provenance"]) ||
      extractByLabel(bodyText, ["Provenance"]);

    let literature =
      extractSection(doc, ["Literature"]) ||
      extractByLabel(bodyText, ["Literature"]);

    return {
      artist: artistText || baseLot.artist,
      birth: birth || baseLot.birth,
      title: titleText && !/^\d+$/.test(titleText) ? titleText : baseLot.title,
      estimate: estimateText || baseLot.estimate,
      startingPrice: startingPrice || baseLot.startingPrice,
      currentBid: currentBid || baseLot.currentBid,
      bidCount: bidCount || baseLot.bidCount,
      provenance: provenance || baseLot.provenance,
      literature: literature || baseLot.literature,
      image: getImgUrl(doc) || baseLot.image,
    };
  };

  const autoScrollAndLoad = async () => {
    console.log(`[${HOUSE}] Scrolling page to trigger lazy loading...`);
    let lastHeight = 0;
    let stable = 0;

    for (let pass = 0; pass < 20 && stable < 4; pass++) {
      const loadMore =
        Array.from(document.querySelectorAll("button,a"))
          .find((el) => /load more|show more|more lots|view more/i.test(clean(el.innerText || el.textContent || "")) && !el.disabled);

      if (loadMore) {
        console.log(`[${HOUSE}] Clicking load-more button...`);
        loadMore.click();
        await sleep(1200);
      }

      window.scrollTo(0, document.body.scrollHeight);
      await sleep(900);

      const h = document.body.scrollHeight;
      if (h === lastHeight) stable++;
      else stable = 0;
      lastHeight = h;
    }

    window.scrollTo(0, 0);
    await sleep(300);
  };

  await autoScrollAndLoad();

  const cardSelectors = [
    '[data-type="item"][data-lot]',
    '[data-type="item"][data-lot-ref]',
    ".mosaic.item",
    ".mosaic-item",
    '[class*="mosaic"][class*="item"]',
    '[class*="lot"][class*="card"]',
    '[class*="item"][class*="grid"]',
  ];

  let cards = [];
  for (const sel of cardSelectors) {
    cards = Array.from(document.querySelectorAll(sel));
    if (cards.length) {
      console.log(`[${HOUSE}] Found ${cards.length} lot cards with selector: ${sel}`);
      break;
    }
  }

  if (!cards.length) {
    const links = Array.from(document.querySelectorAll('a[href*="/auction-lot/"], a[href*="/auctions/"]'))
      .filter((a) => /\/\d+\/?$|\/auction-lot\//i.test(a.href));
    cards = links.map((a) => a.closest("[data-type='item'], article, li, .item, .card, div") || a);
    console.log(`[${HOUSE}] Fallback found ${cards.length} candidate lot cards from lot links.`);
  }

  cards = uniqBy(cards, (card) => {
    const a = card.matches("a[href]") ? card : card.querySelector("a[href]");
    return absoluteUrl(a?.getAttribute("href") || "") || clean(card.getAttribute("data-lot") || card.textContent).slice(0, 120);
  });

  if (!cards.length) {
    console.warn(`[${HOUSE}] No lot cards found. Try running this from the auction grid/listing page after lots have loaded.`);
    window.__auctionLots = [];
    window.__ragoLots = [];
    return [];
  }

  let lots = cards.map(parseCard).filter((lot) => lot.url || lot.lot || lot.artist || lot.title);
  lots = uniqBy(lots, (lot) => lot.url || `${lot.lot}-${lot.artist}-${lot.title}`);

  console.log(`[${HOUSE}] Parsed ${lots.length} lots from grid. Fetching detail pages...`);

  lots = await mapWithConcurrency(lots, CONCURRENCY, async (lot, idx) => {
    if (!lot.url) {
      lot.error = "No lot URL found";
      return lot;
    }

    try {
      await sleep(DETAIL_DELAY_MS);
      console.log(`[${HOUSE}] ${idx + 1}/${lots.length}: fetching lot ${lot.lot || ""} ${lot.url}`);
      const doc = await fetchDoc(lot.url);
      const detail = parseDetail(doc, lot);
      return { ...lot, ...detail, error: "" };
    } catch (err) {
      console.warn(`[${HOUSE}] Error fetching detail for lot ${lot.lot || lot.url}:`, err);
      return { ...lot, error: err?.message || String(err) };
    }
  });

  lots = lots.map(({ _cardText, ...lot }) => lot);

  const headers = [
    "lot",
    "artist",
    "birth",
    "title",
    "estimate",
    "startingPrice",
    "currentBid",
    "bidCount",
    "provenance",
    "literature",
    "image",
    "url",
    "error",
  ];

  const csv = [
    headers.join(","),
    ...lots.map((lot) => headers.map((h) => csvEscape(lot[h])).join(",")),
  ].join("\n");

  const html = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Rago Auction Catalog Export</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #101214;
    --card: #181b1f;
    --text: #f1f1f1;
    --muted: #b8bec7;
    --line: #31363d;
    --accent: #d8c28a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 28px;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    line-height: 1.45;
  }
  header {
    margin: 0 0 26px;
    border-bottom: 1px solid var(--line);
    padding-bottom: 18px;
  }
  h1 { margin: 0 0 8px; font-size: 28px; }
  .meta { color: var(--muted); font-size: 14px; }
  .catalog {
    display: grid;
    gap: 18px;
  }
  .lot-card {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 20px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 16px;
    page-break-inside: avoid;
  }
  .image-wrap {
    background: #0b0c0e;
    border: 1px solid var(--line);
    border-radius: 8px;
    min-height: 180px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  img {
    display: block;
    max-width: 100%;
    max-height: 320px;
    object-fit: contain;
  }
  .no-img { color: var(--muted); font-size: 13px; }
  .lot-heading {
    display: flex;
    gap: 10px;
    align-items: baseline;
    flex-wrap: wrap;
    margin-bottom: 4px;
  }
  .lot-number {
    color: var(--accent);
    font-weight: 700;
    letter-spacing: .04em;
  }
  h2 {
    font-size: 20px;
    margin: 0;
  }
  .title {
    font-style: italic;
    color: var(--text);
    margin: 3px 0 10px;
  }
  .facts {
    display: grid;
    grid-template-columns: 145px minmax(0, 1fr);
    gap: 4px 12px;
    font-size: 14px;
    margin: 12px 0;
  }
  .label { color: var(--muted); }
  .value { color: var(--text); }
  section {
    margin-top: 12px;
    border-top: 1px solid var(--line);
    padding-top: 10px;
  }
  section h3 {
    margin: 0 0 5px;
    font-size: 13px;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: .08em;
  }
  section p {
    margin: 0;
    color: var(--text);
    font-size: 14px;
  }
  a { color: var(--accent); }
  .error { color: #ffb4a8; }
  @media (max-width: 760px) {
    body { padding: 14px; }
    .lot-card { grid-template-columns: 1fr; }
  }
  @media print {
    body { background: #fff; color: #000; padding: 12px; }
    .lot-card { background: #fff; color: #000; border-color: #ccc; grid-template-columns: 190px 1fr; }
    .meta, .label, section h3, .lot-number, a { color: #333; }
    img { max-height: 240px; }
  }
</style>
</head>
<body>
<header>
  <h1>Rago Auction Catalog Export</h1>
  <div class="meta">
    Source: <a href="${escapeHtml(AUCTION_URL)}">${escapeHtml(AUCTION_URL)}</a><br>
    Exported: ${escapeHtml(new Date().toLocaleString())}<br>
    Lots: ${lots.length}
  </div>
</header>
<main class="catalog">
${lots.map((lot) => `
  <article class="lot-card">
    <div class="image-wrap">
      ${lot.image ? `<a href="${escapeHtml(lot.url || lot.image)}" target="_blank" rel="noopener"><img src="${escapeHtml(lot.image)}" alt="${escapeHtml([lot.lot, lot.artist, lot.title].filter(Boolean).join(" "))}"></a>` : `<span class="no-img">No image</span>`}
    </div>
    <div>
      <div class="lot-heading">
        <span class="lot-number">Lot ${escapeHtml(lot.lot)}</span>
        <h2>${escapeHtml(lot.artist || "Unknown artist")}</h2>
      </div>
      ${lot.birth ? `<div class="meta">${escapeHtml(lot.birth)}</div>` : ""}
      ${lot.title ? `<div class="title">${escapeHtml(lot.title)}</div>` : ""}

      <div class="facts">
        ${lot.estimate ? `<div class="label">Estimate</div><div class="value">${escapeHtml(lot.estimate)}</div>` : ""}
        ${lot.startingPrice ? `<div class="label">Starting bid</div><div class="value">${escapeHtml(lot.startingPrice)}</div>` : ""}
        ${lot.currentBid ? `<div class="label">Current bid</div><div class="value">${escapeHtml(lot.currentBid)}</div>` : ""}
        ${lot.bidCount ? `<div class="label">Bid count</div><div class="value">${escapeHtml(lot.bidCount)}</div>` : ""}
        ${lot.url ? `<div class="label">Original lot</div><div class="value"><a href="${escapeHtml(lot.url)}" target="_blank" rel="noopener">Open lot page</a></div>` : ""}
      </div>

      ${lot.provenance ? `<section><h3>Provenance</h3><p>${nl2br(lot.provenance)}</p></section>` : ""}
      ${lot.literature ? `<section><h3>Literature</h3><p>${nl2br(lot.literature)}</p></section>` : ""}
      ${lot.error ? `<section><h3>Error</h3><p class="error">${escapeHtml(lot.error)}</p></section>` : ""}
    </div>
  </article>
`).join("\n")}
</main>
</body>
</html>`;

  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const baseName = `rago-prints-multiples-${stamp}`;

  window.__auctionLots = lots;
  window.__ragoLots = lots;

  downloadTextFile(`${baseName}.csv`, csv, "text/csv;charset=utf-8");
  downloadTextFile(`${baseName}.html`, html, "text/html;charset=utf-8");

  const htmlBlob = new Blob([html], { type: "text/html;charset=utf-8" });
  const htmlUrl = URL.createObjectURL(htmlBlob);
  const opened = window.open(htmlUrl, "_blank");
  if (!opened) {
    console.warn(`[${HOUSE}] Popup blocked. The HTML and CSV downloads should still have started.`);
  }

  console.log(`[${HOUSE}] Done. Extracted ${lots.length} lots.`);
  console.log(`[${HOUSE}] Data stored on window.__auctionLots and window.__ragoLots`);
  console.table(lots.map(({ lot, artist, title, estimate, currentBid, bidCount, url, error }) => ({
    lot, artist, title, estimate, currentBid, bidCount, url, error
  })));

  return lots;
})();