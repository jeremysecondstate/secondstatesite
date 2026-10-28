/* Browser-sourced evidence entry. Prices are validated and calculated by the server. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LiveArtManualEntry = api;
})(typeof window === "undefined" ? globalThis : window, () => {
  "use strict";
  const categories = {prints_and_multiples: "Prints & Multiples", works_on_paper: "Drawings / Works on paper"};
  const definitions = [
    ["source_kind", "Evidence source", "select", true, 40],
    ["price_mode", "USD price basis", "select", true, 40],
    ["artist", "Artist", "text", true, 200],
    ["title", "Title", "text", true, 500],
    ["sale_date", "Sale date", "date", true, 10],
    ["auction_house", "Auction house", "text", true, 200],
    ["lot_number", "Lot number", "text", true, 80],
    ["hammer_usd", "USD hammer", "number", true, 30],
    ["provider_url", "LiveArt URL", "url", true, 2000],
    ["evidence_note", "Source evidence", "textarea", true, 3000],
    ["category", "Category", "select", true, 50],
    ["original_hammer", "Original hammer", "number", false, 30],
    ["original_currency", "Original currency", "text", false, 3],
    ["lot_url", "Original auction URL", "url", false, 2000],
    ["medium", "Medium", "text", false, 500],
    ["edition", "Edition", "text", false, 200],
    ["size", "Size", "text", false, 200],
    ["signature", "Signature", "text", false, 500],
    ["condition", "Condition", "text", false, 1000],
    ["fx_rate", "Historical exchange rate", "number", false, 30],
    ["fx_direction", "Exchange-rate direction", "select", false, 40],
    ["fx_date", "Exchange-rate date", "date", false, 10],
    ["fx_source_url", "Exchange-rate source URL", "url", false, 2000],
  ];
  const keys = new Map(definitions.flatMap(([key, label]) => [[key, key], [label.toLowerCase(), key]]));
  function parsePaste(text) {
    if (typeof text !== "string" || text.length > 12000) throw new Error("Paste one sale at a time (up to 12,000 characters).");
    const values = {};
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      const split = line.indexOf(":");
      const label = line.slice(0, split).trim().toLowerCase();
      const key = split >= 0 && keys.get(label);
      if (!key) throw new Error(`Use a template label followed by a colon: ${line.slice(0, 70)}`);
      if (Object.hasOwn(values, key)) throw new Error(`The ${label} field appears twice. Paste one sale at a time.`);
      let value = line.slice(split + 1).trim();
      const limit = definitions.find(([name]) => name === key)[4];
      if (value.length > limit) throw new Error(`${label} is too long (maximum ${limit} characters).`);
      if (["hammer_usd", "original_hammer"].includes(key) && value && !/^\d+(?:\.\d{1,2})?$/.test(value)) {
        throw new Error(`${label}: use a plain amount such as 3305.00, without a currency symbol or commas.`);
      }
      if (["sale_date", "fx_date"].includes(key) && value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Dates must use YYYY-MM-DD.");
      if (key === "category" && value) {
        const match = Object.entries(categories).find(([name, label]) => [name, label.toLowerCase()].includes(value.toLowerCase()));
        if (!match) throw new Error("Category must be Prints & Multiples or Drawings / Works on paper.");
        value = match[0];
      }
      values[key] = value;
    }
    if (!Object.keys(values).length) throw new Error("Paste the sale details first.");
    return values;
  }
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  function mount(parent, options) {
    const defaultValue = name => name === "artist" ? options.artist || "" : ({category: "prints_and_multiples", source_kind: "liveart_web", price_mode: "source_usd", fx_direction: "original_per_usd"}[name] || "");
    const details = el("details", null, "liveart-manual-entry");
    details.append(el("summary", "Add a sale from LiveArt web or an auction archive"));
    const body = el("div", null, "liveart-manual-body");
    body.append(el("p", "Use a completed sale with a documented hammer. Choose LiveArt web or the original auction archive. Archive currency conversions use your sourced historical rate and are calculated by the server. Add the sale, then select it below and save the evidence.", "liveart-group-note"));
    const paste = el("details", null, "liveart-manual-paste");
    paste.append(el("summary", "Quick paste · one sale"));
    const pasteLabel = el("label", "Paste labeled sale details");
    const textarea = el("textarea");
    textarea.id = `${options.idPrefix}manual-paste`;
    textarea.maxLength = 12000;
    textarea.rows = 9;
    textarea.spellcheck = false;
    const template = definitions.filter(([key, , , required]) => required && !["source_kind", "price_mode"].includes(key)).map(([key, label]) => `${label}: ${key === "category" ? categories.prints_and_multiples : defaultValue(key)}`).join("\n");
    textarea.placeholder = template;
    pasteLabel.htmlFor = textarea.id;
    const pasteActions = el("div", null, "artprice-analysis-actions");
    const templateButton = el("button", "Insert template");
    templateButton.type = "button";
    templateButton.addEventListener("click", () => { if (!textarea.value.trim()) textarea.value = template; textarea.focus(); });
    const fillButton = el("button", "Fill fields from paste");
    fillButton.type = "button";
    pasteActions.append(templateButton, fillButton);
    paste.append(pasteLabel, textarea, el("p", "Use YYYY-MM-DD for dates and plain numbers for prices. Keep source evidence on one line. Optional labels: Original hammer, Original currency, Original auction URL, Medium, Edition, Size, Signature, Condition.", "liveart-group-note"), pasteActions);
    body.append(paste);
    const grid = el("div", null, "liveart-manual-grid");
    const extra = el("details", null, "liveart-manual-extra");
    extra.append(el("summary", "Original price & artwork details (optional)"));
    const extraGrid = el("div", null, "liveart-manual-grid");
    const fields = {}, fieldGroups = {}, fieldLabels = {};
    definitions.forEach(([name, labelText, type, required, max]) => {
      const group = el("div", null, `artprice-analysis-field${type === "textarea" || type === "url" ? " is-wide" : ""}`);
      const label = el("label", labelText);
      const input = el(type === "textarea" ? "textarea" : type === "select" ? "select" : "input");
      if (!["textarea", "select"].includes(type)) input.type = type;
      else input.rows = 3;
      if (type === "select") {
        const choices = name === "category" ? Object.entries(categories) : name === "source_kind" ? [["liveart_web", "LiveArt web"], ["auction_archive", "Auction archive"]]
          : name === "price_mode" ? [["source_usd", "Source-reported USD hammer"], ["historical_fx", "Convert original hammer using historical FX"]]
          : [["original_per_usd", "Original currency units per 1 USD (divide)"], ["usd_per_original", "USD per 1 original currency unit (multiply)"]];
        choices.forEach(([value, text]) => {const option = el("option", text); option.value = value; input.append(option);});
        input.value = choices[0][0];
      }
      input.id = `${options.idPrefix}manual-${name}`;
      input.name = name;
      input.required = required;
      input.maxLength = max;
      if (type === "number") { input.min = "0.01"; input.max = "1000000000000"; input.step = "0.01"; input.inputMode = "decimal"; }
      if (name === "fx_rate") {input.min = "0.000000000001"; input.step = "any";}
      if (name === "original_currency") input.placeholder = "e.g. CHF";
      if (name === "provider_url") input.placeholder = "https://liveart.ai/…";
      input.value = defaultValue(name);
      if (name === "evidence_note") input.placeholder = "Paste the source text showing the sold result, USD hammer and print category; note any discrepancies.";
      label.htmlFor = input.id;
      fields[name] = input;
      fieldGroups[name] = group;
      fieldLabels[name] = label;
      group.append(label, input);
      if (name === "hammer_usd") group.append(el("small", "Enter a source-reported USD hammer. For archive conversion, leave this blank and supply the original hammer and historical rate below. Exclude premiums and estimates."));
      (required ? grid : extraGrid).append(group);
    });
    extra.append(extraGrid);
    body.append(grid, extra);
    const updateMode = () => {
      const archive = fields.source_kind.value === "auction_archive";
      if (!archive) fields.price_mode.value = "source_usd";
      fields.price_mode.disabled = !archive;
      const converted = archive && fields.price_mode.value === "historical_fx";
      fieldLabels.provider_url.textContent = archive ? "Auction archive URL" : "LiveArt URL";
      fields.provider_url.placeholder = archive ? "https://auction-house.example/lot/…" : "https://liveart.ai/…";
      fields.hammer_usd.required = !converted;
      fields.hammer_usd.disabled = converted;
      if (converted) { fields.hammer_usd.value = ""; extra.open = true; }
      for (const key of ["original_hammer", "original_currency"]) fields[key].required = converted;
      for (const key of ["fx_rate", "fx_direction", "fx_date", "fx_source_url"]) {
        fieldGroups[key].hidden = !converted;
        fields[key].required = converted;
        fields[key].disabled = !converted;
        if (!converted && key !== "fx_direction") fields[key].value = "";
      }
    };
    fields.source_kind.addEventListener("change", () => {updateMode(); saveDraft();});
    fields.price_mode.addEventListener("change", () => {updateMode(); saveDraft();});
    const confirmation = el("label", null, "liveart-manual-confirmation");
    const confirmed = el("input");
    confirmed.type = "checkbox";
    confirmed.required = true;
    confirmation.append(confirmed, el("span", "I checked the source: this is a completed sold work in the selected artwork category by the named artist, the documented price is hammer only, and any conversion uses the cited historical exchange rate."));
    const actions = el("div", null, "artprice-analysis-actions");
    const addButton = el("button", "Add sale for review", "is-primary");
    addButton.type = "button";
    actions.append(addButton);
    const status = el("p", "", "artprice-analysis-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    body.append(confirmation, actions, status);
    details.append(body);
    parent.append(details);
    const saveDraft = () => {
      try { sessionStorage.setItem(options.draftKey, JSON.stringify({fields: Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value])), paste: textarea.value})); } catch (_) {}
      confirmed.checked = false;
    };
    body.addEventListener("input", event => { if (event.target !== confirmed) saveDraft(); });
    fields.category.addEventListener("change", saveDraft);
    try {
      const draft = JSON.parse(sessionStorage.getItem(options.draftKey) || "null");
      if (draft?.fields) Object.entries(fields).forEach(([key, input]) => { if (typeof draft.fields[key] === "string") input.value = draft.fields[key]; });
      if (typeof draft?.paste === "string") textarea.value = draft.paste;
    } catch (_) {}
    updateMode();
    fillButton.addEventListener("click", () => {
      try {
        const values = parsePaste(textarea.value);
        Object.entries(fields).forEach(([key, input]) => { input.value = defaultValue(key); });
        Object.entries(values).forEach(([key, value]) => { fields[key].value = value; });
        if (!fields.source_kind.value) fields.source_kind.value = "liveart_web";
        if (!fields.price_mode.value) fields.price_mode.value = "source_usd";
        if (!fields.fx_direction.value) fields.fx_direction.value = "original_per_usd";
        updateMode();
        if (definitions.some(([name, , , required]) => !required && values[name])) extra.open = true;
        saveDraft();
        status.textContent = "Fields filled. Check the details and source confirmation, then add the sale for review.";
        status.className = "artprice-analysis-status";
        fields.title.focus();
      } catch (error) { status.textContent = error.message; status.className = "artprice-analysis-status is-error"; }
    });
    let adding = false;
    addButton.addEventListener("click", async () => {
      if (adding) return;
      const invalid = [...Object.values(fields), confirmed].find(input => !input.checkValidity());
      if (invalid) { if (extra.contains(invalid)) extra.open = true; invalid.reportValidity(); return; }
      adding = true;
      status.textContent = "Adding the sale for review…";
      try {
        const result = await options.onAdd(Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value.trim()])));
        Object.entries(fields).forEach(([key, input]) => { input.value = defaultValue(key); });
        fields.source_kind.value = "liveart_web"; fields.price_mode.value = "source_usd"; fields.fx_direction.value = "original_per_usd";
        updateMode();
        textarea.value = "";
        confirmed.checked = false;
        try { sessionStorage.removeItem(options.draftKey); } catch (_) {}
        status.textContent = `${result?.duplicate ? "This sale is already in the review list." : "Sale added to the review list."} Select “Use in resale bid” below, then save selected evidence.`;
        status.className = "artprice-analysis-status is-success";
      } catch (error) { status.textContent = error.message; status.className = "artprice-analysis-status is-error"; }
      finally { adding = false; }
    });
    return {element: details};
  }
  return {parsePaste, mount};
});
