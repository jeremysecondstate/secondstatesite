(() => {
  "use strict";
  const form = document.getElementById("placement-form");
  if (!form) return;
  const report = JSON.parse(document.getElementById("placement-data").textContent);
  const initialIds = report.proposals.map((entry) => entry.id);
  const statusMessage = document.getElementById("save-result");
  const venues = document.getElementById("venue-editors");
  const proposals = document.getElementById("proposal-editors");
  const menu = [...document.querySelectorAll(".venue-index a")];
  const pages = [...document.querySelectorAll(".venue-page")];
  const editor = document.getElementById("edit-report");
  function showVenue() {
    if (location.hash === "#edit-report") editor.open = true;
    const active = pages.find((section) => "#" + section.id === location.hash) || pages[0];
    pages.forEach((section) => { section.hidden = section !== active; });
    menu.forEach((link) => {
      if (active && link.hash === "#" + active.id) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    });
  }
  showVenue();
  window.addEventListener("hashchange", showVenue);
  document.querySelector('a[href="#edit-report"]')?.addEventListener("click", () => { editor.open = true; });
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function button(label, action) {
    const element = node("button", label);
    element.type = "button";
    element.addEventListener("click", action);
    return element;
  }
  function group(parent, heading) {
    const element = node("fieldset");
    const inputs = node("div", "", "placement-fields");
    element.append(node("legend", heading), inputs);
    parent.appendChild(element);
    return {element, inputs};
  }
  function field(inputs, row, key, label, options = {}) {
    const wrap = node("label", label, options.long ? "wide" : "");
    const control = node(options.long ? "textarea" : options.choices ? "select" : "input");
    if (options.long) control.rows = 3;
    else if (options.choices) {
      for (const [value, name] of options.choices) {
        const option = node("option", name);
        option.value = value;
        control.appendChild(option);
      }
    } else {
      control.type = options.type || "text";
      if (control.type === "number") {
        control.min = options.min ?? "0.01";
        control.step = options.step || ".01";
      }
    }
    control.value = row[key] ?? "";
    control.required = !!options.required;
    control.disabled = !!options.locked;
    if (options.placeholder) control.placeholder = options.placeholder;
    if (options.list) control.setAttribute("list", options.list);
    control.addEventListener("input", () => { row[key] = control.value; });
    wrap.appendChild(control);
    inputs.appendChild(wrap);
    return control;
  }
  function removeItem(collection, row, element) {
    collection.splice(collection.indexOf(row), 1);
    element.remove();
    updateVenueControl();
  }
  function sourceEditor(parent, venue, row) {
    const {element, inputs} = group(parent, "Supporting record");
    field(inputs, row, "label", "Sale, lot or source title", {required:true});
    field(inputs, row, "url", "Source link", {type:"url",required:true});
    field(inputs, row, "note", "Date, work, price basis and relevance", {long:true,required:true});
    element.append(button("Remove record", () => removeItem(venue.sources, row, element)));
  }
  const houseNames = node("datalist");
  houseNames.id = "resale-house-options";
  form.appendChild(houseNames);
  function updateVenueControl() {
    document.getElementById("add-venue").disabled = report.venues.length >= 5;
    houseNames.replaceChildren();
    report.venues.forEach((venue) => {
      if (!venue.house) return;
      const opt = node("option");
      opt.value = venue.house;
      houseNames.appendChild(opt);
    });
  }
  function priceControl(inputs, row, key, label, historicalDraft = false) {
    const control = field(inputs, row, key, label, {type:"number"});
    control.dataset.requireWhenReady = String(!historicalDraft);
    control.required = !historicalDraft && form.elements.status.value === "ready";
    return control;
  }
  form.elements.status.addEventListener("change", () => {
    form.querySelectorAll('[data-require-when-ready="true"]').forEach((control) => {
      control.required = form.elements.status.value === "ready";
    });
  });
  function venueEditor(row) {
    const {element, inputs} = group(venues, row.house || "Resale house");
    const name = field(inputs, row, "house", "Auction house", {required:true});
    name.addEventListener("input", updateVenueControl);
    field(inputs, row, "department", "Department or target sale", {required:true});
    priceControl(inputs, row, "low_usd", "Low hammer estimate · USD");
    priceControl(inputs, row, "high_usd", "High hammer estimate · USD");
    field(inputs, row, "fit", "Why this house", {long:true,required:true});
    field(inputs, row, "basis", "How the evidence supports the range", {long:true,required:true});
    const sourceList = node("div");
    element.appendChild(sourceList);
    row.sources.forEach((source) => sourceEditor(sourceList, row, source));
    element.append(button("Add supporting record", () => {
      const source = {};
      row.sources.push(source);
      sourceEditor(sourceList, row, source);
      sourceList.lastElementChild.querySelector("input").focus();
    }), button("Remove house", () => removeItem(report.venues, row, element)));
  }
  function photoInput(inputs, row) {
    const wrap = node("label", "Or upload an artwork image (JPEG, PNG or WebP, up to 512 KiB)", "wide");
    const input = node("input");
    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp";
    input.addEventListener("change", () => {
      delete row.image_base64;
      delete row.upload;
      const file = input.files[0];
      input.setCustomValidity(file && file.size > 512 * 1024 ? "Choose an image up to 512 KiB." : "");
      if (!file || !input.validity.valid) { input.reportValidity(); return; }
      row.upload = file;
    });
    wrap.appendChild(input);
    inputs.appendChild(wrap);
  }
  function proposalEditor(row) {
    const {element, inputs} = group(proposals, row.id ? row.house + " · " + row.title : "New proposal entry");
    const keyOptions = {required:true, locked:!!row.id};
    const houseInput = field(inputs, row, "house", "Recipient auction house", {...keyOptions,list:houseNames.id});
    field(inputs, row, "season", "Sale season", {...keyOptions,choices:[["spring","Spring"],["fall","Fall"]]});
    field(inputs, row, "year", "Sale year", {...keyOptions,type:"number",min:"1900",step:"1"});
    const workInput = field(inputs, row, "work_key", "Resale unit ID", {...keyOptions,placeholder:"lot for an intact lot, or a component such as A"});
    const controls = {};
    for (const [key,label] of [["artist","Artist or attribution"],["title","Work title"],["year_text","Date of work"],["medium","Medium"],["dimensions","Dimensions"],["edition","Edition"]]) {
      controls[key] = field(inputs, row, key, label, {required:key === "artist" || key === "title"});
    }
    const historicalDraft = row.id && row.estimate_low == null;
    controls.estimate_low = priceControl(inputs, row, "estimate_low", "Proposal estimate low · USD", historicalDraft);
    controls.estimate_high = priceControl(inputs, row, "estimate_high", "Proposal estimate high · USD", historicalDraft);
    field(inputs, row, "object_notes", "Object notes and signature", {long:true});
    field(inputs, row, "description", "Catalog paragraph for this house", {long:true,required:true});
    for (const [key,label] of [["condition","Condition"],["provenance","Provenance"],["literature","Literature"]]) {
      field(inputs, row, key, label);
    }
    field(inputs, row, "sort_order", "Page order", {type:"number",min:"0",step:"1"});
    controls.image_url = field(inputs, row, "image_url", "Image URL or saved Calendar image");
    photoInput(inputs, row);
    function setValue(key, value) {
      row[key] = value ?? "";
      controls[key].value = row[key];
    }
    let referenceHouse = row.house;
    let referenceWork = row.work_key;
    function applyVenuePrices() {
      const old = report.venues.find((v) => v.house === referenceHouse);
      const current = row.work_key === "lot" && report.venues.find((v) => v.house === row.house);
      for (const [key, bound] of [["estimate_low","low_usd"], ["estimate_high","high_usd"]]) {
        if (!row[key] || String(row[key]) === String(old?.[bound])) setValue(key, current?.[bound]);
      }
      referenceHouse = row.house;
    }
    houseInput.addEventListener("change", applyVenuePrices);
    workInput.addEventListener("change", () => {
      if (referenceWork === "lot" && row.work_key !== "lot") {
        for (const [key, original] of [["title",form.dataset.title],["medium",form.dataset.medium],["image_url",form.dataset.image]]) {
          if (row[key] === original) setValue(key, "");
        }
        applyVenuePrices();
      }
      referenceWork = row.work_key;
    });
    element.append(button("Copy to another proposal", () => {
      const copy = {...row};
      delete copy.id;
      const destination = report.venues.find((v) => !report.proposals.some((p) =>
        p.house === v.house && p.season === row.season && String(p.year) === String(row.year) && p.work_key === row.work_key));
      copy.house = destination?.house || "";
      copy.description = "";
      copy.estimate_low = row.work_key === "lot" ? destination?.low_usd : "";
      copy.estimate_high = row.work_key === "lot" ? destination?.high_usd : "";
      report.proposals.push(copy);
      proposalEditor(copy);
      proposals.lastElementChild.querySelector("input").focus();
    }), button("Remove from this proposal", () => removeItem(report.proposals, row, element)));
  }
  report.venues.forEach(venueEditor);
  report.proposals.forEach(proposalEditor);
  updateVenueControl();
  document.getElementById("add-venue").addEventListener("click", () => {
    const venue = {sources:[{}]};
    report.venues.push(venue);
    venueEditor(venue);
    updateVenueControl();
    venues.lastElementChild.querySelector("input").focus();
  });
  document.getElementById("add-proposal").addEventListener("click", () => {
    const date = new Date();
    const spring = date.getMonth() < 4 || date.getMonth() >= 9;
    const venue = report.venues.find((v) => !report.proposals.some((p) => p.house === v.house)) || report.venues[0];
    const entry = {house:venue?.house || "", year:date.getFullYear() + Number(date.getMonth() >= 9), season:spring ? "spring" : "fall",
      work_key:"lot", artist:form.dataset.artist, title:form.dataset.title, medium:form.dataset.medium,
      image_url:form.dataset.image, estimate_low:venue?.low_usd, estimate_high:venue?.high_usd, sort_order:0};
    report.proposals.push(entry);
    proposalEditor(entry);
    proposals.lastElementChild.querySelector("input").focus();
  });
  function encodeFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("The selected image could not be read."));
      reader.readAsDataURL(file);
    });
  }
  async function post(url, payload) {
    const response = await fetch(url, {method:"POST", headers:{
      "Content-Type":"application/json", "X-CSRFToken":form.elements.csrfmiddlewaretoken.value,
    }, body:JSON.stringify(payload)});
    if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("The save did not complete. Check your sign-in and retry.");
    const result = await response.json();
    if (!result.ok) throw new Error(result.error || "Unable to save.");
    return result;
  }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = form.querySelector('button[type="submit"]');
    save.disabled = true;
    statusMessage.textContent = "Saving…";
    try {
      const rows = [];
      for (const {upload, ...row} of report.proposals) {
        if (upload) {
          const photo = await post(location.pathname + "?upload=image", {image_base64:await encodeFile(upload)});
          row.image_url = photo.image_url;
        }
        rows.push(row);
      }
      const result = await post(location.pathname, {version:report.version, status:form.elements.status.value,
        resale_unit:form.elements.resale_unit.value, summary:form.elements.summary.value, venues:report.venues, proposals:rows,
        remove_proposal_ids:initialIds.filter((id) => !rows.some((entry) => entry.id === id))});
      const url = new URL(result.report_url, location.href);
      if (new URLSearchParams(location.search).get("scope") === "oliver") url.searchParams.set("scope","oliver");
      if (report.venues.length) url.hash = "venue-1";
      history.replaceState(null, "", url);
      location.reload();
    } catch (err) {
      statusMessage.textContent = err.message;
      statusMessage.setAttribute("role", "alert");
      save.disabled = false;
    }
  });
})();
