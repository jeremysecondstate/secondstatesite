/* Read-only artist summaries for the selected day's complete catalog. */
((root, factory) => {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CalendarArtists = api;
})(typeof window === "undefined" ? null : window, () => {
  "use strict";

  const lotNumber = (value) => {
    const text = String(value ?? "").trim();
    if (!/^\d+$/.test(text)) return null;
    const number = Number(text);
    return Number.isSafeInteger(number) && number > 0 ? number : null;
  };

  const artistName = (lot) => String(lot.artist || "").normalize("NFC").trim().replace(/\s+/g, " ") || "Artist unknown";
  const artistKey = (lot) => artistName(lot).toLocaleLowerCase("en");

  const summarize = (lots) => {
    const groups = new Map();
    lots.forEach((lot) => {
      const name = artistName(lot);
      // Group display labels only. Surname sort keys omit attribution ("After",
      // etc.) and must not be used to combine distinct artist labels.
      const key = artistKey(lot);
      if (!groups.has(key)) groups.set(key, {
        key, name, sortKey: String(lot.artist_sort_key || name), count: 0,
        earliestTime: null, timeLabel: "Time TBA",
        arrivalTime: null, arrivalLotNumber: null, arrivalHouse: "",
      });
      const group = groups.get(key);
      group.count += 1;
      const time = typeof lot.event_at === "string" && lot.event_at.trim()
        ? Date.parse(lot.event_at) : NaN;
      if (Number.isFinite(time) && (group.earliestTime === null || time < group.earliestTime)) {
        group.earliestTime = time;
        // The server formats this in the Calendar timezone, not the browser's.
        group.timeLabel = lot.time || "Time unavailable";
        group.arrivalTime = null;
        group.arrivalLotNumber = null;
        group.arrivalHouse = "";
      }
      // The planning estimate uses the first numbered lot in the earliest
      // known auction, not a later sale with a smaller number.
      const number = lotNumber(lot.lot_number);
      if (Number.isFinite(time) && time === group.earliestTime && number !== null
        && (group.arrivalLotNumber === null || number < group.arrivalLotNumber)) {
        const arrival = time + number * 60000;
        if (Number.isFinite(new Date(arrival).getTime())) {
          group.arrivalTime = arrival;
          group.arrivalLotNumber = number;
          group.arrivalHouse = lot.auction_house || "";
        }
      }
    });
    return Array.from(groups.values());
  };

  const compareNames = (a, b) => a.sortKey.localeCompare(b.sortKey, "en", {sensitivity: "base"})
    || a.name.localeCompare(b.name, "en", {sensitivity: "base"});

  const sorted = (artists, order) => [...artists].sort((a, b) => {
    if (order === "count_desc") return b.count - a.count || compareNames(a, b);
    if (order === "count_asc") return a.count - b.count || compareNames(a, b);
    if (order === "artist_desc") return compareNames(b, a);
    if (order === "time_asc" || order === "arrival_asc") {
      const key = order === "arrival_asc" ? "arrivalTime" : "earliestTime";
      if (a[key] == null) return b[key] == null ? compareNames(a, b) : 1;
      if (b[key] == null) return -1;
      return a[key] - b[key] || compareNames(a, b);
    }
    return compareNames(a, b);
  });

  const formatArrival = (artist, timeZone) => {
    if (artist.arrivalTime == null || !Number.isFinite(artist.arrivalTime)) return "Unavailable";
    const dateFormat = new Intl.DateTimeFormat("en-US", {timeZone, year: "numeric", month: "2-digit", day: "2-digit"});
    const crossesDay = dateFormat.format(artist.earliestTime) !== dateFormat.format(artist.arrivalTime);
    return new Intl.DateTimeFormat("en-US", {
      timeZone, hour: "numeric", minute: "2-digit", hour12: true,
      ...(crossesDay ? {month: "short", day: "numeric"} : {}),
    }).format(artist.arrivalTime);
  };

  // Planning estimate only: listed auction time + lot number at one minute
  // per lot. Letter suffixes (191A) use the numeric part (191); source labels
  // and artist-level summaries are left intact. No session offset is inferred.
  const estimateLotArrival = (lot) => {
    if (!lot || lot.is_all_day || typeof lot.event_at !== "string") return null;
    const event = lot.event_at.trim();
    // A date or a timezone-less time must not become the browser's midnight.
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/i.test(event)) return null;
    // Date.parse otherwise silently normalizes dates such as February 30.
    const calendarDate = new Date(event.slice(0, 10) + "T00:00:00Z");
    if (!Number.isFinite(calendarDate.getTime()) || calendarDate.toISOString().slice(0, 10) !== event.slice(0, 10)) return null;
    const time = Date.parse(event);
    const match = /^(\d+)[a-z]*$/i.exec(String(lot.lot_number ?? "").trim());
    const number = match ? Number(match[1]) : null;
    if (!Number.isFinite(time) || !Number.isSafeInteger(number) || number <= 0) return null;
    const arrival = time + number * 60000;
    return Number.isFinite(new Date(arrival).getTime()) ? arrival : null;
  };

  const formatLotArrival = (lot, timeZone) => {
    const arrivalTime = estimateLotArrival(lot);
    if (arrivalTime === null) return "Unavailable";
    return formatArrival({earliestTime: Date.parse(lot.event_at), arrivalTime}, timeZone);
  };

  return {artistKey, summarize, sorted, formatArrival, estimateLotArrival, formatLotArrival};
});
