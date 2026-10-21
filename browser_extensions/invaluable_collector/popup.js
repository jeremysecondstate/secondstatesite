"use strict";
document.getElementById("open").addEventListener("click", async () => {
  await chrome.tabs.create({ url: chrome.runtime.getURL("collector.html") });
  window.close();
});
