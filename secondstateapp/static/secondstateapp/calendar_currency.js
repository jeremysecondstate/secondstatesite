/* Calendar display and sorting use server-normalized USD amounts; source prices stay intact. */
((root, factory) => {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CalendarCurrency = api;
})(typeof window === "undefined" ? null : window, () => {
  "use strict";
  const wholeFormat = new Intl.NumberFormat("en-US", {maximumFractionDigits: 0});
  const centsFormat = new Intl.NumberFormat("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const moneyAmount = amount => (Number.isInteger(amount) ? wholeFormat : centsFormat).format(amount);
  const positive = value => {
    if (typeof value !== "number" && typeof value !== "string") return null;
    if (typeof value === "string" && !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  };
  const currency = (lot, field) => {
    const value = field === "sold_price" ? lot.sold_currency || lot.currency : lot.currency;
    return typeof value === "string" ? value.trim().toUpperCase() : "";
  };
  const conversion = (lot, field) => {
    const item = lot.usd_prices?.[field];
    const code = currency(lot, field);
    if (!item || !/^[A-Z]{3}$/.test(code) || item.source_currency !== code
      || positive(item.source_amount) !== positive(lot[field]) || positive(lot[field]) === null
      || positive(item.usd_amount) === null) return null;
    return item;
  };
  const usdAmount = (lot, field) => currency(lot, field) === "USD"
    ? positive(lot[field]) : positive(conversion(lot, field)?.usd_amount);
  const sortPrice = lot => positive(lot.estimate_low) !== null
    ? usdAmount(lot, "estimate_low") : usdAmount(lot, "estimate_high");
  const bidField = lot => {
    if (positive(lot.sold_price) !== null) return "sold_price";
    if (!lot.ended && lot.bid_count !== 0 && positive(lot.current_bid) !== null) return "current_bid";
    return null;
  };
  const fieldsFor = (lot, kind) => (kind === "estimate"
    ? ["estimate_low", "estimate_high"] : [bidField(lot)])
    .filter(field => field && positive(lot[field]) !== null);
  const foreignFields = lot => [...fieldsFor(lot, "estimate"), ...fieldsFor(lot, "bid")]
    .filter(field => currency(lot, field) !== "USD");
  const hasForeignPrices = lot => foreignFields(lot).length > 0;
  const hasUnavailablePrices = lot => foreignFields(lot).some(field => usdAmount(lot, field) === null);
  const provenance = (lot, fields) => Array.from(new Set(fields.map(field => {
    const item = conversion(lot, field);
    return item ? [item.provider, item.rate_date,
      positive(item.rate) !== null ? `1 ${item.source_currency} = ${item.rate} USD` : ""]
      .filter(Boolean).join(" · ") : "";
  }).filter(Boolean))).join("; ");
  const display = (lot, kind) => {
    const original = (kind === "estimate" ? lot.estimate : lot.bid) || "";
    const fields = fieldsFor(lot, kind);
    if (!fields.length || fields.every(field => currency(lot, field) === "USD")) {
      return {text: original, title: ""};
    }
    const amounts = fields.map(field => usdAmount(lot, field));
    if (amounts.some(amount => amount === null)) {
      const status = lot.usd_status === "unavailable" ? "USD conversion unavailable" : "Converting to USD…";
      return {text: [original, status].filter(Boolean).join(" · "), title: ""};
    }
    const money = `≈ $${amounts.map(moneyAmount).join("–")} USD`;
    const converted = kind === "estimate" ? `${money} estimate`
      : `${fields[0] === "sold_price" ? "Sold" : "Current bid"}: ${money}`;
    return {
      text: original ? `${converted} · Original: ${original}` : converted,
      title: provenance(lot, fields),
    };
  };
  return {usdAmount, sortPrice, display, hasForeignPrices, hasUnavailablePrices};
});
