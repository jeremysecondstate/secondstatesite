/* Browser-sourced evidence entry. Prices are validated and calculated by the server. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LiveArtManualEntry = api;
})(typeof window === "undefined" ? globalThis : window, () => {
  "use strict";
  const categories = {
    prints_and_multiples: "Prints & Multiples",
    works_on_paper: "Drawings / Works on paper",
  };
  const definitions = [
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
      if (key === "sale_date" && value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Sale date must use YYYY-MM-DD.");
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
    const defaultValue = name => name === "artist" ? options.artist || "" : name === "category" ? "prints_and_multiples" : "";
    const details = el("details", null, "liveart-manual-entry");
    details.append(el("summary", "Add a sale from LiveArt web"));
    const body = el("div", null, "liveart-manual-body");
    body.append(el("p", "Use a sale you checked on LiveArt’s website. No API search or API units are needed. Add it here, then select it below and save the evidence.", "liveart-group-note"));
    const paste = el("details", null, "liveart-manual-paste");
    paste.append(el("summary", "Quick paste · one sale"));
    const pasteLabel = el("label", "Paste labeled sale details");
    const textarea = el("textarea");
    textarea.id = `${options.idPrefix}manual-paste`;
    textarea.maxLength = 12000;
    textarea.rows = 9;
    textarea.spellcheck = false;
    const template = definitions.filter(([, , , required]) => required).map(([key, label]) => `${label}: ${key === "category" ? categories.prints_and_multiples : defaultValue(key)}`).join("\n");
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
    const fields = {};
    definitions.forEach(([name, labelText, type, required, max]) => {
      const group = el("div", null, `artprice-analysis-field${type === "textarea" || type === "url" ? " is-wide" : ""}`);
      const label = el("label", labelText);
      const input = el(["textarea", "select"].includes(type) ? type : "input");
      if (type === "select") Object.entries(categories).forEach(([value, label]) => {
        const option = el("option", label);
        option.value = value;
        input.append(option);
      });
      else if (type === "textarea") input.rows = 3;
      else input.type = type;
      input.id = `${options.idPrefix}manual-${name}`;
      input.name = name;
      input.required = required;
      input.maxLength = max;
      if (type === "number") { input.min = "0.01"; input.max = "1000000000000"; input.step = "0.01"; input.inputMode = "decimal"; }
      if (name === "original_currency") input.placeholder = "e.g. CHF";
      if (name === "provider_url") input.placeholder = "https://liveart.ai/…";
      input.value = defaultValue(name);
      if (name === "evidence_note") input.placeholder = "Paste the source text showing the sold result, USD hammer and selected artwork category; note any discrepancies.";
      label.htmlFor = input.id;
      fields[name] = input;
      group.append(label, input);
      if (name === "hammer_usd") group.append(el("small", "The USD hammer shown by the source. Exclude buyer’s premium; do not enter an estimate or convert another currency yourself."));
      (required ? grid : extraGrid).append(group);
    });
    extra.append(extraGrid);
    body.append(grid, extra);
    const confirmation = el("label", null, "liveart-manual-confirmation");
    const confirmed = el("input");
    confirmed.type = "checkbox";
    confirmed.required = true;
    confirmation.append(confirmed, el("span", "I checked the source: this is a sold work in the selected artwork category by the named artist, and the USD price is hammer only (excluding buyer’s premium)."));
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
    fillButton.addEventListener("click", () => {
      try {
        const values = parsePaste(textarea.value);
        Object.entries(fields).forEach(([key, input]) => { input.value = defaultValue(key); });
        Object.entries(values).forEach(([key, value]) => { fields[key].value = value; });
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
