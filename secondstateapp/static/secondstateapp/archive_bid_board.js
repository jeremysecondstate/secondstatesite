/* Archive bid board: financial arithmetic belongs to the Decimal server engine. */
(() => {
  "use strict";
  const cases = ["conservative", "working", "optimistic"];
  const labels = {conservative: "Conservative", working: "Working case", optimistic: "Optimistic"};
  const ceilings = {conservative: "Conservative ceiling", working: "Working-case ceiling", optimistic: "Optimistic stretch"};
  // Keep the server's rounded decimal strings exact even for a very large
  // theoretical break-even amount; Number can lose cents beyond 2^53.
  const decimalParts = value => value == null || value === "" ? null : /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(String(value));
  const grouped = digits => new Intl.NumberFormat("en-US").format(BigInt(digits));
  const money = value => {const match = decimalParts(value); return match ? `${match[1]}$${grouped(match[2])}.${(match[3] || "").padEnd(2, "0")}` : "Unavailable";};
  const pct = value => {const match = decimalParts(value); if (!match) return "Unavailable"; const fraction = (match[3] || "").replace(/0+$/, ""); return `${match[1]}${grouped(match[2])}${fraction ? `.${fraction}` : ""}%`;};
  const el = (tag, text, cls) => {const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node;};
  function mount(root, options) {
    root.classList.add("archive-board");
    const url = options.lot.bid_board_url;
    const storageKey = options.draftKey || `archive-board-v2:${options.userId ?? "session"}:${options.lot.id}`;
    let analysis = null, loaded = false, dirty = false, revision = 0, page = 0, selectedBid = null, selectedCase = "working", timer = null;
    let controller = null, loadingPromise = null, saving = false, stale = false, focusRequested = false;
    const fields = {}, resaleFields = {};
    let draft = null;
    try {draft = JSON.parse(sessionStorage.getItem(storageKey) || "null");} catch (_) {}
    const heading = el("div", null, "ab-heading");
    const headingCopy = el("div");
    headingCopy.append(el("span", "03 / SCENARIO ANALYSIS", "ab-overline"), el("h2", "Find the room in each bid."));
    const sources = el("p", "Loading saved evidence…", "ab-muted");
    heading.append(headingCopy, sources);
    const form = el("form", null, "ab-form");
    const controls = el("div", null, "ab-controls");
    function input(parent, name, label, config = {}) {
      const wrap = el("label", label), field = el(config.choices ? "select" : "input");
      field.name = name;
      field.id = `archive-board-${options.lot.id}-${name}`;
      if (config.choices) config.choices.forEach(([value, title]) => {const o = el("option", title); o.value = value; field.append(o);});
      else {field.type = "number"; field.inputMode = "decimal"; field.step = "0.01"; field.min = "0"; field.max = config.max || "1000000000000"; field.required = !config.optional;}
      wrap.append(field); parent.append(wrap); fields[name] = field; return field;
    }
    input(controls, "starting_hammer", "Current / opening hammer (USD)", {optional: true});
    input(controls, "increment_mode", "Bid increments", {choices: [["fixed", "Fixed increment"], ["tiers", "Configurable auction tiers"]]});
    input(controls, "minimum_profit", "Minimum net profit (USD)");
    input(controls, "minimum_return_pct", "Minimum return on cost (%)");
    const notice = el("p", "", "ab-notice");
    const costSummary = el("p", "", "ab-cost-overview");
    const status = el("p", "", "ab-status"); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const result = el("div", null, "ab-results");
    const assumptions = el("details", null, "ab-disclosure");
    assumptions.append(el("summary", "Costs, resale cases & bid rules"));
    const costs = el("div", null, "ab-assumption-fields");
    input(costs, "starting_basis", "Starting amount represents", {choices: [["current", "Current hammer — next bid required"], ["opening", "Opening hammer — available to bid"]]});
    input(costs, "fixed_increment", "Fixed bid increment (USD)");
    input(costs, "buyer_premium_pct", "Buyer premium (%)", {max: "100"});
    input(costs, "purchase_tax_pct", "Purchase tax (%)", {max: "100"});
    input(costs, "purchase_tax_basis", "Purchase tax applies to", {choices: [["hammer_premium", "Hammer + buyer premium"], ["hammer", "Hammer only"], ["acquisition", "Hammer + premium + acquisition costs"]]});
    input(costs, "acquisition_costs", "Other acquisition costs (USD)");
    input(costs, "selling_commission_pct", "Selling commission (%)", {max: "100"});
    input(costs, "selling_costs", "Other selling costs (USD)");
    input(costs, "downside_factor", "Conservative factor × lowest sale", {max: "1"});
    input(costs, "upside_factor", "Optimistic factor × highest sale", {max: "2"});
    const tiersLabel = el("label", "Auction tiers: upper limit, increment (USD); one tier per line. Bids stop at the final limit; use * only for a known open-ended tier.", "ab-tier-label");
    const tiers = el("textarea"); tiers.rows = 4; tiers.spellcheck = false; tiers.setAttribute("aria-label", "Auction bid tiers"); tiersLabel.append(tiers);
    const resaleHeading = el("h3", "Resale cases");
    const resaleGrid = el("div", null, "ab-resale-fields");
    const basisTexts = {};
    cases.forEach(key => {
      const wrap = el("label", `${labels[key]} override (USD)`), field = el("input");
      field.type = "number"; field.min = "0"; field.step = "0.01"; field.max = "1000000000000"; field.placeholder = "Use selected evidence";
      field.inputMode = "decimal"; resaleFields[key] = field; basisTexts[key] = el("small", "No evidence available");
      wrap.append(field, basisTexts[key]); resaleGrid.append(wrap);
    });
    assumptions.append(costs, tiersLabel, resaleHeading, el("p", "Leave overrides blank to use selected sold evidence. Overrides are manual assumptions. These cases are conditional estimates, not probabilities.", "ab-muted"), resaleGrid);
    const actions = el("div", null, "ab-actions");
    const preview = el("button", "Update grid"), save = el("button", "Save Bid Board", "ab-primary");
    preview.type = "submit"; save.type = "button";
    actions.append(preview, save);
    form.append(controls, notice, costSummary, status, result, assumptions, actions);
    root.replaceChildren(heading, form);
    function readAssumptions() {
      const values = Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, key === "starting_hammer" && !field.value.trim() ? null : field.value]));
      values.resale_overrides = Object.fromEntries(cases.map(key => [key, resaleFields[key].value.trim() || null]));
      if (values.increment_mode === "tiers") {
        values.tiers = tiers.value.split(/\n/).filter(line => line.trim()).map(line => {
          const parts = line.split(",").map(x => x.trim());
          if (parts.length !== 2 || !parts[0] || !parts[1]) throw new Error("Each tier needs an upper limit and increment separated by a comma.");
          return {up_to: parts[0] === "*" ? null : parts[0], increment: parts[1]};
        });
      } else values.tiers = analysis?.assumptions?.tiers || [];
      return values;
    }
    function setFields(values) {
      Object.entries(fields).forEach(([key, field]) => {if (key in values) field.value = values[key] ?? "";});
      cases.forEach(key => {resaleFields[key].value = values.resale_overrides?.[key] ?? "";});
      tiers.value = (values.tiers || []).map(t => `${t.up_to ?? "*"}, ${t.increment}`).join("\n");
      tiersLabel.hidden = fields.increment_mode.value !== "tiers";
      fields.fixed_increment.parentElement.hidden = fields.increment_mode.value !== "fixed";
    }
    function persistDraft(markDirty = true) {
      if (!loaded) return;
      if (markDirty) dirty = true;
      if (!dirty) return;
      // Preserve incomplete tier edits too; validation belongs to Update/Save.
      const values = Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, key === "starting_hammer" && !field.value.trim() ? null : field.value]));
      values.resale_overrides = Object.fromEntries(cases.map(key => [key, resaleFields[key].value.trim() || null]));
      values.tiers = analysis?.assumptions?.tiers || [];
      try {sessionStorage.setItem(storageKey, JSON.stringify({assumptions: values, tier_text: tiers.value, page, selected_bid: selectedBid, selected_case: selectedCase, base_updated_at: analysis?.updated_at || null, usd_normalization_version: 1}));} catch (_) {}
    }
    const stateText = message => {status.textContent = message; status.classList.remove("is-error");};
    function invalidate() {
      clearTimeout(timer);
      revision++;
      controller?.abort();
      controller = null;
      save.disabled = !loaded || saving;
    }
    function markStale(message = "Previous calculation — update the grid before using these bids.") {
      stale = true;
      result.classList.add("ab-stale"); result.setAttribute("aria-label", message);
      result.inert = true;
      result.querySelectorAll("button").forEach(button => {button.disabled = true;});
      if (result.childElementCount && !result.querySelector(".ab-stale-notice")) result.prepend(el("p", message, "ab-notice ab-stale-notice"));
    }
    function lockAssumptions(value) {
      Object.values(fields).concat(Object.values(resaleFields), tiers).forEach(field => {field.disabled = value;});
      preview.disabled = value;
    }
    function render(data) {
      analysis = data; page = data.pagination?.page || 0;
      selectedBid = data.detail?.bid ?? data.detail?.hammer ?? data.selected_bid ?? null;
      selectedCase = data.selected_case || data.detail?.case_key || selectedCase;
      const summary = data.source_summary || {};
      sources.textContent = `${summary.artprice_included_count || 0} Artprice + ${summary.liveart_selected_count || 0} LiveArt${summary.archive_selected_count ? ` + ${summary.archive_selected_count} auction archive` : ""} · ${summary.combined_comp_count || 0} unique sales used`;
      notice.textContent = data.increment_notice || "Bid increments are user assumptions. Confirm this sale’s actual house rules.";
      const costsUsed = data.assumptions;
      const taxBasis = {hammer: "hammer", hammer_premium: "hammer + premium", acquisition: "hammer + premium + acquisition costs"}[costsUsed.purchase_tax_basis];
      costSummary.textContent = `Costs assumed: ${pct(costsUsed.buyer_premium_pct)} buyer premium · ${pct(costsUsed.purchase_tax_pct)} tax on ${taxBasis} · ${pct(costsUsed.selling_commission_pct)} selling commission · ${money(costsUsed.acquisition_costs)} other acquisition + ${money(costsUsed.selling_costs)} other selling costs.`;
      const caseList = Array.isArray(data.cases) ? data.cases : cases.map(key => ({key, ...(data.cases?.[key] || {})}));
      caseList.forEach(c => {const key = c.key || c.case_key; if (basisTexts[key]) basisTexts[key].textContent = `${money(c.resale_hammer)} · ${c.basis || "No evidence available"}${c.origin === "manual" && !c.basis?.includes("Manual") ? " · Manual override" : ""}`;});
      result.replaceChildren(); result.classList.remove("ab-stale"); result.removeAttribute("aria-label"); result.inert = saving; stale = false;
      fields.starting_hammer.removeAttribute("aria-describedby");
      notice.textContent += ` ${data.coverage_limit != null && data.empty_reason ? "No supported bid is available from this starting hammer." : data.assumptions.starting_basis === "current" ? "Current hammer is a reference; the grid starts at the next available bid." : "Opening hammer is available as the first bid."}`;
      (data.notices || []).forEach(message => result.append(el("p", message, "ab-notice")));
      if (data.evidence_changed_since_save) result.append(el("p", "Selected evidence has changed since the saved analysis. Review and save the refreshed Bid Board.", "ab-notice"));
      if (data.evidence_notice) result.append(el("p", data.evidence_notice, "ab-notice"));
      if (data.message) result.append(el("p", data.message, "ab-notice"));
      if (data.assumptions.starting_hammer == null || data.assumptions.starting_hammer === "") {
        const scenarioTitle = el("div", null, "ab-section-title");
        scenarioTitle.append(el("h3", "Resale scenarios"), el("small", "USD resale assumptions used to compare each bid"));
        const scenarioCards = el("div", null, "ab-scenarios");
        caseList.forEach(c => {
          const key = c.key || c.case_key, card = el("div", null, "ab-scenario-card");
          card.append(el("span", labels[key] || c.label), el("strong", money(c.resale_hammer)));
          card.append(el("small", c.origin === "manual" ? "Manual resale assumption" : c.resale_hammer != null ? "From selected sold evidence" : "Add eligible evidence or a manual resale assumption"));
          if (c.basis && c.resale_hammer != null) card.append(el("p", c.basis));
          scenarioCards.append(card);
        });
        const setup = el("div", null, "ab-start-required");
        const setupCopy = el("div"), setupMessage = el("p");
        setupMessage.id = `archive-board-${options.lot.id}-start-help`;
        const availableCases = caseList.filter(c => c.resale_hammer != null).length;
        const currency = String(data.lot_currency || "").trim().toUpperCase();
        const ready = availableCases ? `${availableCases === 1 ? "Your resale scenario is" : "Your resale scenarios are"} ready. ` : "Add eligible sold evidence or enter a manual resale assumption under Costs, resale cases & bid rules. ";
        const currencyHelp = currency && currency !== "USD"
          ? data.source_hammer_conversion
            ? `This lot is listed in ${currency}. The converted source hammer is ${money(data.source_current_hammer)} USD. Enter it or another USD starting amount to calculate bids, costs, and profit.`
            : `This lot is listed in ${currency}. A converted starting hammer is not available. Enter a current or opening hammer in USD to calculate bids, costs, and profit.`
          : currency === "USD"
            ? "Enter the current or opening hammer in USD to calculate available bids, costs, and profit."
            : "The lot's source currency is unavailable. Verify it and enter a current or opening hammer in USD.";
        setupMessage.textContent = ready + currencyHelp;
        setupCopy.append(el("h3", "Add a starting hammer to build the bid grid"), setupMessage);
        const enterHammer = el("button", "Enter starting hammer", "ab-primary"); enterHammer.type = "button";
        enterHammer.addEventListener("click", () => {fields.starting_hammer.focus(); fields.starting_hammer.scrollIntoView({block: "center", behavior: "smooth"});});
        setup.append(setupCopy, enterHammer);
        fields.starting_hammer.setAttribute("aria-describedby", setupMessage.id);
        result.append(scenarioTitle, scenarioCards, setup);
        return;
      }
      const pickTitle = el("div", null, "ab-section-title"); pickTitle.append(el("span", "BIDS TO REVIEW", "ab-overline"), el("small", data.coverage_limit == null ? "Highest available bid meeting both minimums in each case" : "Highest supported bid meeting both minimums within the known tier limits"));
      const picks = el("div", null, "ab-shortlist");
      (data.shortlist || []).forEach(pick => {
        const key = pick.case_key || pick.key, button = el("button", null, "ab-pick"); button.type = "button";
        button.append(el("span", pick.label || ceilings[key] || labels[key]), el("strong", pick.bid == null ? "No qualifying bid" : money(pick.bid)));
        button.disabled = pick.bid == null;
        button.setAttribute("aria-pressed", String(pick.bid === selectedBid && key === selectedCase));
        if (pick.detail) button.append(el("small", `${money(pick.detail.net_profit)} profit · ${pct(pick.detail.return_on_cost_pct)} return`));
        if (key !== "conservative" && pick.conservative_downside) button.append(el("small", `Conservative result: ${money(pick.conservative_downside.net_profit)}`, Number(pick.conservative_downside.net_profit) < 0 ? "ab-loss" : ""));
        if (pick.coverage_limited) button.append(el("small", pick.reason || "Limited by known bid tiers; higher bids have not been evaluated."));
        else if (pick.bid == null) button.append(el("small", pick.reason || "No available bid meets both minimums."));
        button.addEventListener("click", () => choose(pick.bid, key)); picks.append(button);
      });
      if (picks.childElementCount) result.append(pickTitle, picks);
      if (!data.rows?.length) {result.append(el("p", data.empty_reason || "Enter a starting hammer and add eligible evidence or manual resale cases to build the grid.", "ab-empty")); return;}
      const tableTitle = el("div", null, "ab-section-title");
      tableTitle.append(el("h3", "The bid × resale grid"), el("small", "Each cell: net profit / return on cost. ✓ meets both minimums."));
      const wrap = el("div", null, "ab-table-wrap"); wrap.tabIndex = 0; wrap.setAttribute("role", "region"); wrap.setAttribute("aria-label", "Bid by resale scenarios, scroll horizontally on small screens");
      const table = el("table", null, "ab-grid"), head = el("thead"), headRow = el("tr"), body = el("tbody");
      ["Purchase hammer", "All-in cost", ...cases.map(key => labels[key])].forEach((label, i) => {
        const th = el("th", label); th.scope = "col";
        if (i > 1) {
          const c = caseList.find(c => (c.key || c.case_key) === cases[i-2]);
          th.append(el("small", `Resale ${money(c?.resale_hammer)}`), el("small", c?.origin === "manual" ? "Manual override" : c?.origin === "evidence" ? "Selected evidence" : "No resale evidence"));
          if (c?.basis) th.title = c.basis;
        }
        headRow.append(th);
      });
      head.append(headRow);
      data.rows.forEach(row => {
        const tr = el("tr"); tr.classList.toggle("ab-active-row", row.bid === selectedBid);
        const th = el("th"); th.scope = "row"; th.append(el("strong", money(row.bid)), el("small", row.label || (row.is_reference ? "Current · reference" : "Available bid")));
        tr.append(th, el("td", money(row.all_in_acquisition ?? row.cells?.[0]?.all_in_acquisition)));
        (row.cells || []).forEach(cell => {
          const key = cell.case_key || cell.key, td = el("td");
          if (cell.net_profit == null) {td.append(el("span", "No resale evidence", "ab-muted")); tr.append(td); return;}
          const button = el("button", null, "ab-cell"); button.type = "button";
          button.dataset.bid = row.bid; button.dataset.caseKey = key;
          button.setAttribute("aria-pressed", String(row.bid === selectedBid && key === selectedCase));
          button.setAttribute("aria-label", `${money(row.bid)} hammer, ${labels[key]}, net ${money(cell.net_profit)}, return ${pct(cell.return_on_cost_pct)}, ${cell.qualifies ? "meets both minimums" : "below minimums"}${row.is_reference ? ", current reference only" : ""}`);
          button.append(el("strong", money(cell.net_profit), Number(cell.net_profit) < 0 ? "ab-loss" : ""), el("small", `${pct(cell.return_on_cost_pct)} return ${cell.qualifies ? "✓" : "×"}`));
          button.addEventListener("click", () => choose(row.bid, key)); td.append(button); tr.append(td);
        }); body.append(tr);
      });
      table.append(head, body); wrap.append(table);
      const pagination = el("div", null, "ab-pagination"), previous = el("button", "← Earlier bids"), next = el("button", "Later bids →");
      previous.type = next.type = "button";
      previous.disabled = page === 0; next.disabled = data.pagination?.has_next === false;
      previous.addEventListener("click", () => {page = Math.max(0, page-1); persistDraft(false); update();}); next.addEventListener("click", () => {page++; persistDraft(false); update();});
      pagination.append(el("span", `Page ${page+1} of ${data.pagination?.page_count || 1} · ${data.rows.length} bid levels shown`), previous, next);
      result.append(tableTitle, wrap, pagination, el("p", data.calculation_basis, "ab-muted"));
      if (data.detail) renderDetail(data.detail, data);
      const targets = el("details", null, "ab-disclosure"); targets.append(el("summary", "Compare more profit targets"));
      const targetWrap = el("div", null, "ab-table-wrap"), targetTable = el("table", null, "ab-targets"), targetHead = el("tr");
      ["Minimum profit", ...cases.map(key => labels[key])].forEach(label => targetHead.append(el("th", label))); targetTable.append(targetHead);
      (data.profit_targets || []).forEach(target => {const tr = el("tr"); tr.append(el("th", money(target.target_profit ?? target.minimum_profit))); cases.forEach(key => {const bid = target.ceilings?.[key]?.bid ?? target.ceilings?.[key], cell = el("td", bid == null || typeof bid === "object" ? "No available bid" : money(bid)); if (target.coverage_limited?.[key]) cell.append(el("small", "At known tier limit")); tr.append(cell);}); targetTable.append(tr);});
      targetWrap.append(targetTable); targets.append(el("p", data.coverage_limit == null ? "Maximum available hammer with the return floor applied." : "Highest supported hammer with the return floor applied. Higher bids require additional verified tier rules.", "ab-muted"), targetWrap); result.append(targets);
    }
    function renderDetail(detail, data) {
      const panel = el("section", null, "ab-detail");
      const title = el("div", null, "ab-section-title"); title.append(el("h3", `${money(detail.bid ?? detail.hammer)} hammer · ${labels[detail.case_key] || labels[selectedCase]}`));
      const next = detail.one_more_bid;
      const nextAvailable = next?.bid != null && next.available !== false;
      const more = el("button", "One more bid →"); more.type = "button"; more.disabled = !nextAvailable;
      more.addEventListener("click", () => {if (nextAvailable) choose(next.bid, selectedCase);}); title.append(more);
      const metrics = el("dl", null, "ab-metrics");
      [["All-in acquisition", money(detail.all_in_acquisition)], ["Gross resale hammer", money(detail.gross_resale_hammer)], ["Net resale proceeds", money(detail.net_resale_proceeds)], ["Net profit / loss", money(detail.net_profit)], ["Return on cost", pct(detail.return_on_cost_pct)], ["Profit / gross resale", pct(detail.profit_on_gross_pct)]].forEach(([name, value]) => {const group = el("div"); group.append(el("dt", name), el("dd", value)); metrics.append(group);});
      const flags = el("p", `${detail.profit_500 ? "✓" : "×"} $500 profit · ${detail.profit_1000 ? "✓" : "×"} $1,000 profit · ${detail.qualifies ? "Meets both minimums" : "Below minimums"}`, "ab-target-flags");
      panel.append(title, metrics, flags);
      if (nextAvailable) panel.append(el("p", `Next bid ${money(next.bid)}: ${money(next.additional_all_in_cost)} more acquisition cost / ${money(next.profit_reduction)} less profit.`, "ab-muted"));
      else if (next || data.coverage_limit != null) panel.append(el("p", next?.reason || (data.coverage_limit != null ? "The next bid is unavailable beyond the known tier limits. Add verified higher-tier rules to continue." : "The next bid is outside the supported range."), "ab-muted"));
      const breakdown = el("details", null, "ab-disclosure"); breakdown.append(el("summary", "Cost breakdown & break-even resale"));
      const list = el("dl", null, "ab-metrics");
      [["Purchase hammer", detail.bid ?? detail.hammer], ["Buyer premium", detail.buyer_premium], ["Purchase tax basis", detail.purchase_tax_basis_amount], ["Purchase tax", detail.purchase_tax], ["Other acquisition", analysis.assumptions.acquisition_costs], ["Selling commission", detail.selling_commission], ["Other selling costs", analysis.assumptions.selling_costs], ["Break-even resale hammer", detail.break_even_resale]].forEach(([name, value]) => {const group = el("div"); group.append(el("dt", name), el("dd", money(value))); list.append(group);});
      breakdown.append(list); panel.append(breakdown); result.append(panel);
    }
    async function request(body, signal) {
      if (!url) throw new Error("Bid Board endpoint is unavailable. Reload the page.");
      const response = await fetch(url, {method: body ? "POST" : "GET", credentials: "same-origin", signal, headers: {"X-CSRFToken": options.csrfToken, "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}, ...(body ? {body: JSON.stringify(body)} : {})});
      let payload;
      try {payload = await response.json();} catch (_) {throw new Error("The server did not return a Bid Board response. Your session may have expired; reload and sign in.");}
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Bid Board could not be calculated.");
      if (body?.action === "save" && payload.saved_board) {
        options.lot.saved_bid_board = payload.saved_board;
        window.dispatchEvent(new CustomEvent("archive-bid-board-saved", {detail: {lotId: options.lot.id, savedBoard: payload.saved_board}}));
      }
      return payload.analysis;
    }
    async function update(action = "preview", _markDirty = false) {
      clearTimeout(timer);
      if (!loaded || saving) return;
      if (!form.checkValidity()) {assumptions.open = true; markStale(); form.reportValidity(); return;}
      invalidate();
      const current = revision;
      const restoreFocus = focusRequested; focusRequested = false;
      controller = new AbortController();
      const signal = controller.signal;
      saving = action === "save";
      if (saving) lockAssumptions(true);
      markStale("Previous calculation — recalculation is in progress.");
      stateText(action === "save" ? "Saving analysis…" : "Calculating…");
      save.disabled = true;
      try {
        const assumptions = readAssumptions();
        const evidence = await options.getEvidence();
        if (current !== revision) return;
        const payload = {action, assumptions, page, selected_bid: selectedBid, selected_case: selectedCase, focus_selected: action === "focus"};
        if (action === "focus") payload.action = "preview";
        if (Array.isArray(evidence?.selected_ids)) payload.selected_ids = evidence.selected_ids;
        if (evidence?.research_id) payload.research_id = evidence.research_id;
        const data = await request(payload, signal);
        if (current !== revision) return;
        render(data);
        if (restoreFocus && !root.closest("[hidden]")) {
          const selectedCell = Array.from(result.querySelectorAll(".ab-cell")).find(button => button.dataset.bid === selectedBid && button.dataset.caseKey === selectedCase);
          selectedCell?.focus({preventScroll: true});
        }
        if (action === "save") {
          dirty = false;
          try {sessionStorage.removeItem(storageKey);} catch (_) {}
          try {
            const synced = await options.onSaved?.(data, evidence);
            stateText(synced?.preservedDraft ? "Bid Board saved. Your newer Workbench evidence edits remain unsaved." : "Bid Board saved for this lot.");
          } catch (error) {stateText(`Bid Board saved. ${error.message || "Refresh Workbench to load its saved evidence."}`);}
        } else if (dirty || evidence?.has_unsaved_changes || data.evidence_changed_since_save) {persistDraft(); stateText("Preview updated. Save to keep this analysis with the lot.");}
        else stateText(data.saved ? "Saved Bid Board loaded; calculations reflect the current selected evidence." : "Review costs and house bid rules before saving.");
      } catch (error) {
        if (current !== revision || error.name === "AbortError") return;
        status.textContent = error.message; status.classList.add("is-error");
        markStale("Previous calculation — correct the error and update before using these bids.");
      } finally {
        if (current === revision) {saving = false; lockAssumptions(false); save.disabled = false; result.inert = stale; controller = null;}
      }
    }
    function choose(bid, key) {if (stale || saving) return; selectedBid = bid; selectedCase = key; focusRequested = true; persistDraft(); update("focus");}
    form.addEventListener("submit", event => {event.preventDefault(); update();});
    save.addEventListener("click", () => update("save"));
    const edited = event => {
      if (!loaded || saving) return;
      invalidate(); markStale();
      if (event.target === fields.starting_hammer || event.target === fields.starting_basis || event.target === fields.increment_mode || event.target === fields.fixed_increment || event.target === tiers) {page = 0; selectedBid = null;}
      tiersLabel.hidden = fields.increment_mode.value !== "tiers";
      fields.fixed_increment.parentElement.hidden = fields.increment_mode.value !== "fixed";
      persistDraft(); stateText("Unsaved assumptions. Update the grid to recalculate.");
    };
    form.addEventListener("input", edited);
    form.addEventListener("change", event => {edited(event); if (loaded && !saving) timer = setTimeout(() => update(), 200);});
    async function refresh() {
      if (saving) return;
      if (loaded) return update("preview", false);
      if (loadingPromise) return loadingPromise;
      loadingPromise = (async () => {
        invalidate(); const current = revision;
        controller = new AbortController(); lockAssumptions(true); save.disabled = true;
        try {
          const data = await request(null, controller.signal); if (current !== revision) return;
          render(data); setFields(data.assumptions || {}); loaded = true;
          if (draft?.assumptions) {
            const draftAssumptions = {...draft.assumptions};
            // Drafts from before USD normalization stored the unavailable start
            // as blank. Keep the new converted default while restoring costs.
            // Versioned drafts preserve intentional clears as well as amounts.
            if (!draft.usd_normalization_version && (draftAssumptions.starting_hammer == null || draftAssumptions.starting_hammer === "") && data.source_hammer_conversion && data.assumptions.starting_hammer != null) {
              delete draftAssumptions.starting_hammer;
              delete draftAssumptions.starting_basis;
            }
            setFields(draftAssumptions); if (typeof draft.tier_text === "string") tiers.value = draft.tier_text;
            page = draft.page || 0; selectedBid = draft.selected_bid || null; selectedCase = draft.selected_case || "working"; dirty = true;
            stateText("Restored this browser’s unsaved Bid Board draft."); markStale();
          } else stateText(data.saved ? "Saved Bid Board loaded." : "Review costs and house bid rules before saving.");
          lockAssumptions(false); save.disabled = false;
          await update(draft ? "preview" : "focus", false);
        } catch (error) {if (error.name !== "AbortError") {status.textContent = error.message; status.classList.add("is-error");}}
        finally {loadingPromise = null;}
      })();
      return loadingPromise;
    }
    lockAssumptions(true); save.disabled = true;
    return {refresh, get dirty() {return dirty;}};
  }
  window.ArchiveBidBoard = {mount};
})();
