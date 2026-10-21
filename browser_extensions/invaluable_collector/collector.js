"use strict";
const rules = globalThis.SecondStateCollector;
const byId = (id) => document.getElementById(id);
let selectedURLs = [];
let currentRun = null;
let busy = false;
let pollBusy = false;
let formRunId = null;
function dateText(date) { return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(date); }
byId("start-date").value = dateText(new Date());
byId("end-date").value = dateText(new Date(Date.now() + 7 * 86400000));
function showError(error) { byId("message").textContent = error.message || String(error); byId("message").classList.add("error"); }
function render(run) {
  currentRun = run;
  byId("run-status").textContent = run?.status || "No run";
  byId("message").textContent = run?.note || "Import your bookmarks to begin.";
  byId("message").classList.remove("error");
  byId("counts").textContent = run ? `${run.progress.filter((row) => row.status === "captured").length} of ${run.watches.length} artists captured · ${run.snapshot_count} pages · ${run.lot_count} lot records · ${(run.bytes / 1048576).toFixed(2)} of 7 MB` : "";
  byId("progress").replaceChildren();
  for (const row of run?.progress || []) {
    const tr = document.createElement("tr"); tr.dataset.status = row.status;
    for (const value of [row.artist, row.status, `${row.captured_pages.length} / ${row.reported_pages ?? "?"}`, row.captured_lots, row.note]) {
      const td = document.createElement("td"); td.textContent = String(value); tr.append(td);
    }
    byId("progress").append(tr);
  }
  const running = run?.status === "running";
  byId("prepare").disabled = busy || running || !!run?.snapshot_count || !selectedURLs.length;
  byId("start").disabled = busy || run?.status !== "ready";
  byId("pause").disabled = busy || !running;
  byId("resume").disabled = busy || run?.status !== "paused";
  byId("skip").disabled = busy || !run || run.current_index >= run.watches.length || run.status === "complete";
  byId("download").disabled = busy || !run;
  byId("reset").disabled = busy || !run || running;
  for (const id of ["bookmarks", "start-date", "end-date", "time-zone"]) byId(id).disabled = running;
}
async function command(type, extra = {}) {
  const response = await chrome.runtime.sendMessage({ type, ...extra });
  if (!response?.ok) throw new Error(response?.error || "The collector did not respond. Reload this extension page.");
  return response;
}
async function action(type, extra = {}) {
  busy = true; render(currentRun);
  try { const response = await command(type, extra); if (Object.hasOwn(response, "run")) render(response.run); return response; }
  finally { busy = false; render(currentRun); }
}
byId("bookmarks").addEventListener("change", async () => {
  try {
    const file = byId("bookmarks").files[0];
    if (!file) return;
    if (file.size > 16 * 1024 * 1024) throw new Error("The bookmark export exceeds 16 MB.");
    // Extract only anchor href attributes. Never parse the supplied document's
    // resource tags, execute its markup, or insert it into the visible page.
    const html = await file.text();
    const hrefs = [];
    const decoder = document.createElement("textarea");
    for (const match of html.matchAll(/<a\b(?:[^>"']|"[^"]*"|'[^']*')*?\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
      decoder.innerHTML = match[1] ?? match[2];
      hrefs.push(decoder.value);
    }
    selectedURLs = rules.normalizeWatches(hrefs).map((entry) => entry.url);
    byId("bookmark-note").textContent = `${selectedURLs.length} supported Invaluable artist searches selected. Sorted by ending soon. Saved source date filters are removed; Studio applies your chosen import window.`;
    render(currentRun);
  } catch (error) { selectedURLs = []; render(currentRun); showError(error); }
});
byId("prepare").addEventListener("click", () => action("configure", { urls: selectedURLs, window: {
  start_date: byId("start-date").value, end_date: byId("end-date").value, time_zone: byId("time-zone").value.trim(),
} }).catch(showError));
for (const type of ["start", "pause", "resume", "skip"]) byId(type).addEventListener("click", () => action(type).catch(showError));
byId("reset").addEventListener("click", () => {
  if (confirm("Reset this local capture run? Download its bundle first if you want to keep the captured pages.")) action("reset").catch(showError);
});
byId("download").addEventListener("click", async () => {
  try {
    const { bundle } = await command("export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url;
    link.download = `secondstate-invaluable-${bundle.window.start_date}-through-${bundle.window.end_date}.json`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (error) { showError(error); }
});
async function refresh() {
  if (busy || pollBusy) return;
  pollBusy = true;
  try {
    const response = await command("status"); render(response.run);
    if (response.run && formRunId !== response.run.id) {
      byId("start-date").value = response.run.window.start_date;
      byId("end-date").value = response.run.window.end_date;
      byId("time-zone").value = response.run.window.time_zone;
      formRunId = response.run.id;
    }
  } catch (error) { showError(error); }
  finally { pollBusy = false; }
}
render(null); refresh(); setInterval(refresh, 2000);
