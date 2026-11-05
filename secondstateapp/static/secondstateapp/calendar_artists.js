/* Read-only artist summaries for the selected day's complete catalog. */
((root, factory) => {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CalendarArtists = api;
})(typeof window === "undefined" ? null : window, () => {
  "use strict";

  const artistName = (lot) => String(lot.artist || "").normalize("NFC").trim().replace(/\s+/g, " ") || "Artist unknown";
  const artistKey = (lot) => artistName(lot).toLocaleLowerCase("en");

  const knownInstant = (value) => {
    if (typeof value !== "string") return null;
    const event = value.trim();
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/i.test(event)) return null;
    const calendarDate = new Date(event.slice(0, 10) + "T00:00:00Z");
    if (!Number.isFinite(calendarDate.getTime()) || calendarDate.toISOString().slice(0, 10) !== event.slice(0, 10)) return null;
    const time = Date.parse(event);
    return Number.isFinite(time) ? time : null;
  };

  // Published block times take precedence. Otherwise an explicitly supplied
  // numbering baseline offsets the one-minute estimate; never infer one from
  // the watched subset, number length, or another sale.
  const lotArrivalDetails = (lot) => {
    if (!lot || lot.is_all_day) return null;
    const time = knownInstant(lot.event_at);
    const match = /^(\d+)[a-z]*$/i.exec(String(lot.lot_number ?? "").trim());
    const number = match ? Number(match[1]) : null;
    if (time === null || !Number.isSafeInteger(number) || number <= 0) return null;
    if (lot.arrival_schedule != null) {
      const schedule = lot.arrival_schedule;
      const at = knownInstant(schedule.at);
      const start = knownInstant(schedule.session_start_at);
      if (schedule.kind !== "published_timetable" || at === null || start === null || at < start
        || !Number.isSafeInteger(schedule.first_lot) || !Number.isSafeInteger(schedule.last_lot)
        || number < schedule.first_lot || number > schedule.last_lot
        || schedule.source_url !== "https://www.dobiaschofsky.com/g246.html") return null;
      return {number, time: at, startTime: start, kind: schedule.kind, sourceUrl: schedule.source_url,
        firstLot: schedule.first_lot, lastLot: schedule.last_lot, minutes: null};
    }
    const baseline = lot.numbering_baseline ?? 0;
    if (!Number.isSafeInteger(baseline) || baseline < 0 || baseline > number) return null;
    const minutes = number - baseline;
    const at = time + minutes * 60000;
    return Number.isFinite(new Date(at).getTime())
      ? {number, time: at, startTime: time, kind: "estimate", sourceUrl: "", minutes, baseline} : null;
  };

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
        arrivalTime: null, arrivalLotNumber: null, arrivalHouse: "", arrivalStartTime: null,
        arrivalKind: "", arrivalSourceUrl: "", arrivalMinutes: null,
      });
      const group = groups.get(key);
      group.count += 1;
      const time = typeof lot.event_at === "string" && lot.event_at.trim()
        ? Date.parse(lot.event_at) : NaN;
      if (Number.isFinite(time) && (group.earliestTime === null || time < group.earliestTime)) {
        group.earliestTime = time;
        // The server formats this in the Calendar timezone, not the browser's.
        group.timeLabel = lot.time || "Time unavailable";
      }
      // Keep the listed time intact, but compare verified sessions when a
      // provider lists the whole day and another lists only the afternoon.
      const details = lotArrivalDetails(lot);
      const start = details ? details.startTime : time;
      if (Number.isFinite(start) && (group.arrivalStartTime === null || start < group.arrivalStartTime)) {
        group.arrivalStartTime = start;
        group.arrivalTime = null;
        group.arrivalLotNumber = null;
        group.arrivalHouse = "";
        group.arrivalKind = "";
        group.arrivalSourceUrl = "";
        group.arrivalMinutes = null;
      }
      const number = details?.number ?? null;
      if (details && start === group.arrivalStartTime && number !== null
        && (group.arrivalTime === null || details.time < group.arrivalTime
          || (details.time === group.arrivalTime && number < group.arrivalLotNumber))) {
        group.arrivalTime = details.time;
        group.arrivalLotNumber = number;
        group.arrivalHouse = lot.auction_house || "";
        group.arrivalKind = details.kind;
        group.arrivalSourceUrl = details.sourceUrl;
        group.arrivalMinutes = details.minutes;
        group.arrivalFirstLot = details.firstLot;
        group.arrivalLastLot = details.lastLot;
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

  const estimateLotArrival = (lot) => lotArrivalDetails(lot)?.time ?? null;

  const formatLotArrival = (lot, timeZone) => {
    const details = lotArrivalDetails(lot);
    if (details === null) return "Unavailable";
    return formatArrival({earliestTime: details.startTime, arrivalTime: details.time}, timeZone);
  };

  return {artistKey, summarize, sorted, formatArrival, estimateLotArrival, formatLotArrival, lotArrivalDetails};
});
