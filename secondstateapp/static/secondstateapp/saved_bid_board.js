/* Saved snapshots only: this viewer never requests a live Bid Board preview. */
(() => {
  "use strict";
  const caseKeys = ["conservative", "working", "optimistic"];
  const labels = {conservative: "Conservative", working: "Working case", optimistic: "Optimistic"};
  const labelForCase = (key, list = []) => labels[key] || list.find(c => (c.key || c.case_key) === key)?.label || key;
  const parts = value => value == null || value === "" ? null : /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(String(value));
  const grouped = digits => new Intl.NumberFormat("en-US").format(BigInt(digits));
  const money = value => {const match = parts(value); return match ? `${match[1]}$${grouped(match[2])}.${(match[3] || "").padEnd(2, "0")}` : "Unavailable";};
  const pct = value => {const match = parts(value); return match ? `${match[1]}${grouped(match[2])}${match[3]?.replace(/0+$/, "") ? `.${match[3].replace(/0+$/, "")}` : ""}%` : "Unavailable";};
  const el = (tag, text, className) => {const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node;};
  const qualification = summary => summary.qualifies === true ? "Meets both minimums" : summary.qualifies === false ? "Below saved minimums" : "Qualification unavailable";
  const pending = new Map();
  const revisions = new Map();
  let activeDialog = null;

  function publish(lot, summary) {
    lot.saved_bid_board = summary;
    window.dispatchEvent(new CustomEvent("archive-bid-board-saved", {detail: {lotId: lot.id, savedBoard: summary}}));
  }

  function emailControl(lot, csrfToken) {
    const wrap = el("div", null, "sb-email-control"), label = el("label", null, "sb-email-label");
    const checkbox = el("input"); checkbox.type = "checkbox";
    checkbox.dataset.bidBoardEmailLotId = String(lot.id);
    checkbox.checked = pending.get(String(lot.id)) ?? Boolean(lot.saved_bid_board?.include_in_email);
    checkbox.disabled = pending.has(String(lot.id));
    label.append(checkbox, el("span", "Include Bid Board & qualifying bid in this lot’s email"));
    const status = el("p", "", "sb-email-status"); status.setAttribute("role", "status");
    wrap.append(label, status);
    checkbox.addEventListener("change", async () => {
      const lotId = String(lot.id), requested = checkbox.checked;
      const restoreFocus = document.activeElement === checkbox;
      pending.set(lotId, requested);
      document.querySelectorAll("[data-bid-board-email-lot-id]").forEach(input => {if (input.dataset.bidBoardEmailLotId === lotId) input.disabled = true;});
      status.textContent = "Saving email preference…";
      status.classList.remove("is-error");
      try {
        if (!lot.bid_board_email_url) throw new Error("Reload the page to update this email preference.");
        const response = await fetch(lot.bid_board_email_url, {
          method: "POST", credentials: "same-origin",
          headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-CSRFToken": csrfToken, "X-Requested-With": "XMLHttpRequest"},
          body: new URLSearchParams({include_in_email: String(requested)}),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok || !payload.saved_board) throw new Error(payload.error || "The email preference could not be saved. Please try again.");
        publish(lot, payload.saved_board);
        status.textContent = requested ? "Included when this lot is emailed." : "Bid Board excluded from this lot’s email.";
      } catch (error) {
        checkbox.checked = Boolean(lot.saved_bid_board?.include_in_email);
        status.textContent = error.message || "The email preference could not be saved.";
        status.classList.add("is-error");
      } finally {
        pending.delete(lotId);
        document.querySelectorAll("[data-bid-board-email-lot-id]").forEach(input => {
          if (input.dataset.bidBoardEmailLotId === lotId) {
            input.disabled = false;
            input.checked = Boolean(lot.saved_bid_board?.include_in_email);
          }
        });
        const focus = document.activeElement;
        if (restoreFocus && checkbox.isConnected && (!focus || focus === document.body || focus === document.documentElement || focus === activeDialog)) checkbox.focus({preventScroll: true});
      }
    });
    return wrap;
  }

  function mountSummary(root, options) {
    const {lot, csrfToken} = options;
    root.className = "sb-catalog-summary";
    root.dataset.savedBidBoardLotId = String(lot.id);
    const copy = el("div", null, "sb-catalog-copy"), actions = el("div", null, "sb-catalog-actions");
    const button = el("button", "See Bid Board", "sb-view-button"); button.type = "button";
    button.dataset.savedBoardOpenLotId = String(lot.id);
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-label", `See saved Bid Board for ${lot.title}`);
    button.addEventListener("click", () => open(lot, {csrfToken}));
    actions.append(button);
    root.append(copy, actions, emailControl(lot, csrfToken));
    root.updateSavedBoard = summary => {
      lot.saved_bid_board = summary;
      root.hidden = !summary;
      if (!summary) return;
      copy.replaceChildren(el("strong", summary.qualifying_bid == null ? (summary.qualifies == null ? "Qualifying Bid: Unavailable" : "Qualifying Bid: No qualifying bid") : `Qualifying Bid: ${money(summary.qualifying_bid)}`, "sb-qualifying-bid"));
      if (summary.qualifying_coverage_limited) copy.append(el("small", "At known tier limit; higher bids not evaluated.", "ab-muted"));
      root.querySelector("input").checked = pending.get(String(lot.id)) ?? Boolean(summary.include_in_email);
    };
    root.updateSavedBoard(lot.saved_bid_board);
  }

  function metrics(entries) {
    const list = el("dl", null, "ab-metrics");
    entries.forEach(([label, value]) => {const item = el("div"); item.append(el("dt", label), el("dd", value)); list.append(item);});
    return list;
  }

  function renderSnapshot(root, lot, board, csrfToken) {
    const data = board.analysis || {}, summary = board.summary || lot.saved_bid_board || {};
    const assumptions = board.assumptions || data.assumptions || {};
    const detail = summary.detail || data.detail;
    const caseList = Array.isArray(data.cases) ? data.cases : caseKeys.map(key => ({key, ...data.cases?.[key]}));
    const displayKeys = caseList.map(c => c.key || c.case_key);
    const caseLabel = summary.selected_case_label || labelForCase(summary.selected_case || data.selected_case, caseList) || "Saved case";
    const selected = el("section", null, "sb-saved-selection");
    selected.append(el("span", "SAVED BID · USD HAMMER", "ab-overline"));
    selected.append(el("h3", summary.qualifying_bid == null ? (summary.qualifies == null ? "Qualifying Bid: Unavailable" : "No qualifying bid") : `Qualifying Bid: ${money(summary.qualifying_bid)}`));
    selected.append(el("p", `${caseLabel} · ${summary.qualifying_bid == null ? (data.empty_reason || (summary.qualifies == null ? "Save a starting hammer and resale case to calculate a qualifying bid." : "no available bid meets both saved minimums")) : summary.qualifying_coverage_limited ? "highest supported bid at the known tier limit; higher bids not evaluated" : "highest saved bid meeting both minimums"}`, "ab-muted"));
    if (summary.selected_bid != null) selected.append(el("p", `Selected bid: ${money(summary.selected_bid)} · ${qualification(summary)}`, "sb-saved-selected"));
    else selected.append(el("p", "No bid selected in this saved board.", "ab-muted"));
    if (detail) selected.append(metrics([
      ["Selected bid · all-in acquisition", money(detail.all_in_acquisition)], ["Gross resale hammer", money(detail.gross_resale_hammer)],
      ["Net resale proceeds", money(detail.net_resale_proceeds)], ["Selected bid · net profit / loss", money(detail.net_profit)],
      ["Return on cost", pct(detail.return_on_cost_pct)], ["Profit / gross resale", pct(detail.profit_on_gross_pct)],
    ]));
    selected.append(emailControl(lot, csrfToken));
    root.append(selected);
    const notices = [...(data.notices || []), data.evidence_notice, data.message].filter(Boolean);
    notices.forEach(message => root.append(el("p", message, "ab-notice")));
    const source = board.evidence_snapshot?.source_summary || data.source_summary || {};
    root.append(el("p", `${source.artprice_included_count || 0} Artprice + ${source.liveart_selected_count || 0} LiveArt${source.archive_selected_count ? ` + ${source.archive_selected_count} auction archive` : ""} · ${source.combined_comp_count || 0} unique sales used`, "ab-muted"));

    const picks = el("section", null, "ab-shortlist sb-saved-shortlist");
    picks.classList.toggle("ab-expanded-cases", (data.shortlist || []).length > 3);
    (data.shortlist || []).forEach(pick => {
      const item = el("div", null, "ab-pick");
      item.append(el("span", pick.label || labelForCase(pick.case_key || pick.key, caseList)), el("strong", pick.bid == null ? (pick.reason === "Resale assumption unavailable" ? "Unavailable" : "No qualifying bid") : money(pick.bid)));
      if (pick.detail) item.append(el("small", `${money(pick.detail.net_profit)} profit · ${pct(pick.detail.return_on_cost_pct)} return`));
      if (pick.coverage_limited) item.append(el("small", pick.reason || "Limited by known bid tiers; higher bids have not been evaluated."));
      else if (pick.bid == null) item.append(el("small", pick.reason || "No bid meets both minimums."));
      picks.append(item);
    });
    root.append(picks);
    if (data.rows?.length) {
      root.append(el("h3", "Saved bid × resale grid"));
      root.append(el("p", `Saved page ${(data.pagination?.page || 0) + 1} of ${data.pagination?.page_count || 1} · ${data.rows.length} bid levels captured. Each cell shows profit and return on cost; ✓ meets both saved minimums.`, "ab-muted"));
      const wrap = el("div", null, "ab-table-wrap"); wrap.tabIndex = 0; wrap.setAttribute("role", "region"); wrap.setAttribute("aria-label", "Saved bid and resale scenarios; scroll horizontally on small screens");
      const table = el("table", null, "ab-grid"), head = el("thead"), header = el("tr"), body = el("tbody");
      table.classList.toggle("ab-expanded-cases", displayKeys.length > 3);
      ["Purchase hammer", "All-in cost", ...displayKeys.map(key => labelForCase(key, caseList))].forEach((label, index) => {
        const th = el("th", label); th.scope = "col";
        if (index > 1) th.append(el("small", `Resale ${money(caseList.find(c => (c.key || c.case_key) === displayKeys[index - 2])?.resale_hammer)}`));
        header.append(th);
      });
      head.append(header);
      data.rows.forEach(row => {
        const tr = el("tr"); tr.classList.toggle("ab-active-row", row.bid === summary.selected_bid);
        const th = el("th", money(row.bid)); th.scope = "row"; if (row.label) th.append(el("small", row.label));
        tr.append(th, el("td", money(row.all_in_acquisition)));
        displayKeys.forEach(key => {
          const cell = row.cells?.find(value => (value.case_key || value.key) === key), td = el("td");
          if (cell?.net_profit == null) td.append(el("span", "No resale evidence", "ab-muted"));
          else {
            td.append(el("strong", money(cell.net_profit), String(cell.net_profit).startsWith("-") ? "ab-loss" : ""), el("small", `${pct(cell.return_on_cost_pct)} return ${cell.qualifies ? "✓" : "×"}`));
            if (row.bid === summary.selected_bid && key === summary.selected_case) {td.classList.add("sb-selected-cell"); td.append(el("small", "Selected"));}
          }
          tr.append(td);
        });
        body.append(tr);
      });
      table.append(head, body); wrap.append(table); root.append(wrap);
    } else root.append(el("p", data.empty_reason || "No bid grid was available when this board was saved.", "ab-muted"));
    if (data.calculation_basis) root.append(el("p", data.calculation_basis, "ab-muted"));

    const costs = el("details", null, "ab-disclosure"); costs.append(el("summary", "Saved costs, resale cases & bid rules"));
    const taxBasis = {hammer: "Hammer", hammer_premium: "Hammer + buyer premium", acquisition: "Hammer + premium + acquisition costs"}[assumptions.purchase_tax_basis] || "Unavailable";
    costs.append(metrics([
      [assumptions.starting_basis === "opening" ? "Opening hammer" : "Current hammer reference", money(assumptions.starting_hammer)],
      ["Minimum net profit", money(assumptions.minimum_profit)], ["Minimum return on cost", pct(assumptions.minimum_return_pct)],
      ["Buyer premium", pct(assumptions.buyer_premium_pct)], ["Purchase tax", pct(assumptions.purchase_tax_pct)], ["Purchase tax applies to", taxBasis],
      ["Other acquisition costs", money(assumptions.acquisition_costs)], ["Selling commission", pct(assumptions.selling_commission_pct)], ["Other selling costs", money(assumptions.selling_costs)],
      ["Bid increments", assumptions.increment_mode === "tiers" ? "Configured auction tiers" : money(assumptions.fixed_increment)],
      ["Conservative evidence factor", assumptions.downside_factor == null ? "Unavailable" : `${assumptions.downside_factor}×`],
      ["Optimistic evidence factor", assumptions.upside_factor == null ? "Unavailable" : `${assumptions.upside_factor}×`],
    ]));
    if (detail) costs.append(metrics([["Selected bid · buyer premium", money(detail.buyer_premium)], ["Selected bid · purchase tax", money(detail.purchase_tax)], ["Selected bid · break-even resale", money(detail.break_even_resale)]]));
    if (assumptions.increment_mode === "tiers") (assumptions.tiers || []).forEach(tier => costs.append(el("p", `${tier.up_to == null ? "No upper limit" : `Up to ${money(tier.up_to)}`}: ${money(tier.increment)} increment`, "ab-muted")));
    if (data.increment_notice) costs.append(el("p", data.increment_notice, "ab-muted"));
    caseList.forEach(c => costs.append(el("p", `${labelForCase(c.key || c.case_key, caseList)}: ${money(c.resale_hammer)} · ${c.basis || "No resale evidence"}`, "ab-muted")));
    root.append(costs);

    const evidence = el("details", null, "ab-disclosure"), records = board.evidence_snapshot?.selected_records || [];
    evidence.append(el("summary", `Saved comparable sales (${records.length})`));
    if (!records.length) evidence.append(el("p", "No comparable sale records were captured. Review the saved manual resale assumptions.", "ab-muted"));
    else {
      const list = el("ul", null, "sb-evidence-list");
      records.forEach(record => {
        const item = el("li");
        item.append(el("strong", [record.artist, record.title].filter(Boolean).join(" · ") || "Comparable sale"));
        item.append(el("p", [record.provider, record.auction_house, record.sale_date, `${money(record.hammer_usd)} USD hammer`].filter(Boolean).join(" · "), "ab-muted"));
        list.append(item);
      });
      evidence.append(list);
    }
    root.append(evidence);
  }

  async function open(lot, {csrfToken} = {}) {
    if (activeDialog) activeDialog.close();
    const opener = document.activeElement, controller = new AbortController();
    const dialog = el("dialog", null, "sb-dialog"); activeDialog = dialog;
    dialog.setAttribute("aria-labelledby", "saved-bid-board-title");
    const inner = el("div", null, "archive-board sb-dialog-inner"), header = el("header", null, "sb-dialog-header");
    const heading = el("div");
    heading.append(el("span", "SAVED BID BOARD", "ab-overline"));
    const title = el("h2", lot.title); title.id = "saved-bid-board-title"; heading.append(title);
    heading.append(el("p", [lot.artist, lot.auction_house, lot.lot_number ? `Lot ${lot.lot_number}` : ""].filter(Boolean).join(" · "), "ab-muted"));
    const close = el("button", "Close ×", "sb-dialog-close"); close.type = "button"; close.autofocus = true; close.setAttribute("aria-label", "Close saved Bid Board");
    close.addEventListener("click", () => dialog.close());
    header.append(heading, close);
    const status = el("p", "Loading saved Bid Board…", "ab-status"); status.setAttribute("role", "status");
    const content = el("div", null, "sb-dialog-content");
    inner.append(header, status, content); dialog.append(inner); document.body.append(dialog);
    let backdropPressed = false;
    dialog.addEventListener("pointerdown", event => {backdropPressed = event.target === dialog;});
    dialog.addEventListener("click", event => {if (event.target === dialog && backdropPressed) dialog.close();});
    dialog.addEventListener("close", () => {
      controller.abort(); dialog.remove(); if (activeDialog === dialog) activeDialog = null;
      const url = new URL(window.location.href);
      if (url.searchParams.get("saved_bid_board") === String(lot.id)) {url.searchParams.delete("saved_bid_board"); window.history.replaceState(window.history.state, "", url);}
      const fallback = Array.from(document.querySelectorAll("[data-saved-board-open-lot-id]")).find(button => button.dataset.savedBoardOpenLotId === String(lot.id));
      (opener?.isConnected && opener !== document.body ? opener : fallback || document.getElementById("day-gallery-title"))?.focus({preventScroll: true});
    });
    dialog.showModal();
    const url = new URL(window.location.href); url.searchParams.set("saved_bid_board", String(lot.id)); window.history.replaceState(window.history.state, "", url);
    try {
      if (!lot.saved_bid_board_url) throw new Error("The saved Bid Board is unavailable. Reload this page to try again.");
      let payload;
      // A Save or email preference may already be in flight when the viewer
      // opens. Retry its snapshot once rather than publishing an older reply.
      for (let attempt = 0; attempt < 2; attempt++) {
        const revision = revisions.get(String(lot.id)) || 0;
        const response = await fetch(lot.saved_bid_board_url, {credentials: "same-origin", headers: {"X-Requested-With": "XMLHttpRequest"}, signal: controller.signal});
        payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok || !payload.board) throw new Error(payload.error || "This saved Bid Board could not be loaded. Close and try again.");
        if (revision === (revisions.get(String(lot.id)) || 0)) break;
        if (attempt) throw new Error("The saved Bid Board changed while loading. Close and reopen to see the latest saved board.");
      }
      if (controller.signal.aborted) return;
      if (payload.board.summary) publish(lot, payload.board.summary);
      const updated = payload.board.updated_at || payload.board.summary?.updated_at;
      const date = updated ? new Date(updated) : null;
      status.textContent = `Saved snapshot${date && !Number.isNaN(date.valueOf()) ? ` · ${date.toLocaleString()}` : ""}. Displays the bids, assumptions, and evidence saved with this lot.`;
      renderSnapshot(content, lot, payload.board, csrfToken);
    } catch (error) {
      if (error.name === "AbortError") return;
      status.textContent = error.message || "The saved Bid Board could not be loaded."; status.classList.add("is-error");
    }
  }

  window.addEventListener("archive-bid-board-saved", event => {
    const {lotId, savedBoard} = event.detail;
    revisions.set(String(lotId), (revisions.get(String(lotId)) || 0) + 1);
    document.querySelectorAll("[data-saved-bid-board-lot-id]").forEach(root => {if (root.dataset.savedBidBoardLotId === String(lotId)) root.updateSavedBoard?.(savedBoard);});
    document.querySelectorAll("[data-bid-board-email-lot-id]").forEach(input => {if (input.dataset.bidBoardEmailLotId === String(lotId)) input.checked = pending.get(String(lotId)) ?? Boolean(savedBoard?.include_in_email);});
  });
  window.SavedBidBoard = {mountSummary, open};
})();
