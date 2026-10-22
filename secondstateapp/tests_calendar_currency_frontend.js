// Run with node --test. Exchange-rate fixtures are deterministic; no browser or network is used.
const assert = require("node:assert/strict");
const {test} = require("node:test");
const currency = require("./static/secondstateapp/calendar_currency.js");

function quote(sourceCurrency, sourceAmount, usdAmount, rate = "1.10") {
  return {source_currency: sourceCurrency, source_amount: String(sourceAmount), usd_amount: String(usdAmount),
    rate, rate_date: "2026-10-21", provider: "Frankfurter"};
}

test("USD comparison crosses nominal JPY/EUR prices and never sorts using bids or sold results", () => {
  const lots = [
    {id: "eur", currency: "EUR", estimate_low: "100.00", current_bid: "1.00", sold_price: "2.00",
      usd_prices: {estimate_low: quote("EUR", "100.00", "110.00")}},
    {id: "usd", currency: "USD", estimate_low: "105.00", estimate_high: "900.00"},
    {id: "jpy", currency: "JPY", estimate_low: "10000.00",
      usd_prices: {estimate_low: quote("JPY", "10000.00", "65.00", "0.0065")}},
  ];
  assert.deepEqual(lots.toSorted((a, b) => currency.sortPrice(a) - currency.sortPrice(b)).map(lot => lot.id),
    ["jpy", "usd", "eur"]);
  assert.deepEqual(lots.toSorted((a, b) => currency.sortPrice(b) - currency.sortPrice(a)).map(lot => lot.id),
    ["eur", "usd", "jpy"]);
});

test("high estimate fallback is allowed only when the original low estimate is not positive", () => {
  for (const low of [null, undefined, "", "0", -1, "bogus", "NaN", Infinity, true]) {
    const lot = {currency: "EUR", estimate_low: low, estimate_high: "200.00",
      usd_prices: {estimate_high: quote("EUR", "200.00", "220.00")}};
    assert.equal(currency.sortPrice(lot), 220);
  }
  assert.equal(currency.sortPrice({currency: "EUR", estimate_low: "100.00", estimate_high: "200.00",
    usd_prices: {estimate_high: quote("EUR", "200.00", "220.00")}}), null);
  assert.equal(currency.sortPrice({currency: "EUR", current_bid: "10", sold_price: "20"}), null);
});

test("missing, invalid, and stale-source conversion values are unavailable, not native USD", () => {
  const lot = {currency: "JPY", estimate_low: "10000.00"};
  assert.equal(currency.usdAmount(lot, "estimate_low"), null);
  assert.equal(currency.hasForeignPrices(lot), true);
  assert.equal(currency.hasUnavailablePrices(lot), true);
  for (const bad of [null, "", "bogus", "0", "-1", "NaN", "Infinity", true]) {
    lot.usd_prices = {estimate_low: quote("JPY", "10000.00", bad)};
    assert.equal(currency.usdAmount(lot, "estimate_low"), null);
  }
  for (const stale of [quote("EUR", "10000.00", "65.00"), quote("JPY", "9000.00", "65.00")]) {
    lot.usd_prices = {estimate_low: stale};
    assert.equal(currency.usdAmount(lot, "estimate_low"), null);
  }
  lot.currency = "";
  lot.usd_prices = {estimate_low: quote("", "10000.00", "65.00")};
  assert.equal(currency.usdAmount(lot, "estimate_low"), null);
});

test("USD originals stay unchanged, while foreign estimates show an approximate range and provenance", () => {
  const usd = {currency: " usd ", estimate_low: "100.25", estimate_high: "200.50", estimate: "$100.25–200.50 estimate"};
  assert.equal(currency.usdAmount(usd, "estimate_low"), 100.25);
  assert.deepEqual(currency.display(usd, "estimate"), {text: usd.estimate, title: ""});
  assert.equal(currency.hasForeignPrices(usd), false);
  const euro = {currency: "EUR", estimate_low: "100.00", estimate_high: "200.00", estimate: "€100–200 estimate",
    usd_prices: {estimate_low: quote("EUR", "100.00", "110.25", "1.1025"), estimate_high: quote("EUR", "200.00", "220.50", "1.1025")}};
  const original = JSON.stringify(euro);
  assert.deepEqual(currency.display(euro, "estimate"), {
    text: "≈ $110.25–220.50 USD estimate · Original: €100–200 estimate",
    title: "Frankfurter · 2026-10-21 · 1 EUR = 1.1025 USD",
  });
  assert.equal(currency.hasUnavailablePrices(euro), false);
  assert.equal(JSON.stringify(euro), original);
});

test("incomplete conversions retain the original estimate with accurate pending or unavailable state", () => {
  const lot = {currency: "GBP", estimate_low: "200", estimate_high: "300", estimate: "£200–300 estimate",
    usd_prices: {estimate_low: quote("GBP", "200", "260", "1.30")}};
  assert.equal(currency.display(lot, "estimate").text, "£200–300 estimate · Converting to USD…");
  lot.usd_status = "unavailable";
  assert.equal(currency.display(lot, "estimate").text, "£200–300 estimate · USD conversion unavailable");
  assert.equal(currency.hasUnavailablePrices(lot), true);
});

test("sold prices use their own currency, while no-bid and ended labels never infer a current bid", () => {
  const sold = {currency: "EUR", sold_currency: "HKD", sold_price: "1000", ended: true,
    bid: "Sold: HK$1,000 HKD", current_bid: "90", usd_prices: {sold_price: quote("HKD", "1000", "128", "0.128")}};
  assert.equal(currency.display(sold, "bid").text, "Sold: ≈ $128 USD · Original: Sold: HK$1,000 HKD");
  assert.equal(currency.usdAmount(sold, "sold_price"), 128);
  assert.equal(currency.hasUnavailablePrices(sold), false);
  sold.sold_currency = "USD";
  assert.equal(currency.display(sold, "bid").text, sold.bid);
  assert.equal(currency.usdAmount(sold, "sold_price"), 1000);
  for (const lot of [
    {currency: "EUR", current_bid: "100", bid_count: 0, bid: "Current bid: No bids"},
    {currency: "EUR", current_bid: "100", ended: true, bid: "Sale ended · Sold price unavailable"},
    {currency: "EUR", current_bid: null, bid: "Current bid: N/A"},
  ]) {
    assert.equal(currency.display(lot, "bid").text, lot.bid);
    assert.equal(currency.hasForeignPrices(lot), false);
    assert.equal(currency.hasUnavailablePrices(lot), false);
  }
  const bid = {currency: "EUR", current_bid: "100", bid_count: 2, bid: "Current bid: €100 · 2 bids",
    usd_prices: {current_bid: quote("EUR", "100", "110")}};
  assert.equal(currency.display(bid, "bid").text, "Current bid: ≈ $110 USD · Original: Current bid: €100 · 2 bids");
});
