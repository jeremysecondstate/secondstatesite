// Run with node --test. Artist summaries use the full selected day's saved lots.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const CalendarArtists = require("./static/secondstateapp/calendar_artists.js");

const names = (artists) => artists.map((artist) => artist.name);

test("an empty day has no artists and every sort returns a separate empty array", () => {
  const artists = CalendarArtists.summarize([]);
  assert.deepEqual(artists, []);
  for (const order of ["artist_asc", "artist_desc", "count_desc", "count_asc", "time_asc"]) {
    const result = CalendarArtists.sorted(artists, order);
    assert.deepEqual(result, []);
    assert.notEqual(result, artists);
  }
});

test("counts include the full day across houses, tray selections, ended lots, and pagination", () => {
  const lots = Array.from({length: 69}, (_, index) => ({
    id: index,
    artist: index < 35 ? "Albers, Josef" : index < 58 ? "Banksy" : "Miró, Joan",
    auction_house: index % 2 ? "House B" : "House A",
    email_tray_selected: index % 3 === 0,
    ended: index % 4 === 0,
  }));
  const artists = CalendarArtists.summarize(lots);
  assert.deepEqual(Object.fromEntries(artists.map(({name, count}) => [name, count])), {
    "Albers, Josef": 35,
    Banksy: 23,
    "Miró, Joan": 11,
  });
  assert.equal(artists.reduce((total, artist) => total + artist.count, 0), lots.length);
});

test("display names group case, whitespace and Unicode composition without losing accents or punctuation", () => {
  const artists = CalendarArtists.summarize([
    {artist: "  Miró,\tJoan  ", artist_sort_key: "miro, joan"},
    {artist: "MIRÓ, JOAN", artist_sort_key: "miro, joan"},
    {artist: "Miro\u0301, Joan", artist_sort_key: "miro, joan"},
    {artist: "Miro, Joan", artist_sort_key: "miro, joan"},
    {artist: "Miró Joan", artist_sort_key: "miro, joan"},
  ]);
  assert.equal(artists.length, 3);
  assert.deepEqual(artists.map(({name, count}) => ({name, count})), [
    {name: "Miró, Joan", count: 3},
    {name: "Miro, Joan", count: 1},
    {name: "Miró Joan", count: 1},
  ]);
  assert.equal(artists[0].sortKey, "miro, joan");
});

test("attribution remains distinct even when artist surname sort keys match", () => {
  const artists = CalendarArtists.summarize([
    {artist: "Picasso, Pablo", artist_sort_key: "picasso, pablo"},
    {artist: "After Picasso, Pablo", artist_sort_key: "picasso, pablo"},
    {artist: "Picasso, Pablo (attributed to)", artist_sort_key: "picasso, pablo"},
    {artist: "after picasso, pablo", artist_sort_key: "picasso, pablo"},
  ]);
  assert.deepEqual(artists.map(({name, count}) => ({name, count})), [
    {name: "Picasso, Pablo", count: 1},
    {name: "After Picasso, Pablo", count: 2},
    {name: "Picasso, Pablo (attributed to)", count: 1},
  ]);
});

test("missing names have a readable fallback and do not merge with named artists", () => {
  const artists = CalendarArtists.summarize([
    {}, {artist: null}, {artist: ""}, {artist: " \t "}, {artist: "Banksy"},
  ]);
  assert.deepEqual(artists.map(({name, count}) => ({name, count})), [
    {name: "Artist unknown", count: 4}, {name: "Banksy", count: 1},
  ]);
});

test("the earliest known instant compares timezone offsets and uses its saved local time label", () => {
  const artists = CalendarArtists.summarize([
    {artist: "Banksy", event_at: "2026-10-22T12:00:00-07:00", time: "12:00 PM"},
    {artist: "Banksy", event_at: null, time: "Time TBA"},
    {artist: "Banksy", event_at: "2026-10-22T14:00:00+02:00", time: "5:00 AM"},
    {artist: "Banksy", event_at: "2026-10-22T12:00:00Z", time: "5:00 AM"},
  ]);
  assert.equal(artists[0].count, 4);
  assert.equal(artists[0].earliestTime, Date.parse("2026-10-22T12:00:00Z"));
  assert.equal(artists[0].timeLabel, "5:00 AM");
});

test("real midnight and ended lots retain known times while missing or invalid times remain TBA", () => {
  const artists = CalendarArtists.summarize([
    {artist: "No time", event_at: null, time: "Time TBA"},
    {artist: "No time", event_at: "invalid", time: "Time TBA"},
    {artist: "No time", event_at: "", time: "Time TBA"},
    {artist: "No time"},
    {artist: "Midnight", event_at: "2026-10-22T00:00:00-07:00", time: "12:00 AM", ended: true},
    {artist: "Midnight", event_at: "2026-10-22T12:00:00-07:00", time: "12:00 PM"},
  ]);
  const unknown = artists.find(({name}) => name === "No time");
  const midnight = artists.find(({name}) => name === "Midnight");
  assert.equal(unknown.earliestTime, null);
  assert.equal(unknown.timeLabel, "Time TBA");
  assert.equal(midnight.earliestTime, Date.parse("2026-10-22T07:00:00Z"));
  assert.equal(midnight.timeLabel, "12:00 AM");
  assert.deepEqual(names(CalendarArtists.sorted(artists, "time_asc")), ["Midnight", "No time"]);
});

test("all artist sorts use surname keys, numeric counts, chronological times, and surname tie breaks", () => {
  const artists = [
    {name: "Joan Miró", sortKey: "miro, joan", count: 2, earliestTime: null, timeLabel: "Time TBA"},
    {name: "Albrecht Dürer", sortKey: "durer, albrecht", count: 4, earliestTime: 300, timeLabel: "Later"},
    {name: "Banksy", sortKey: "banksy", count: 4, earliestTime: 100, timeLabel: "Earlier"},
    {name: "Josef Albers", sortKey: "albers, josef", count: 12, earliestTime: 100, timeLabel: "Earlier"},
  ];
  assert.deepEqual(names(CalendarArtists.sorted(artists, "artist_asc")),
    ["Josef Albers", "Banksy", "Albrecht Dürer", "Joan Miró"]);
  assert.deepEqual(names(CalendarArtists.sorted(artists, "artist_desc")),
    ["Joan Miró", "Albrecht Dürer", "Banksy", "Josef Albers"]);
  assert.deepEqual(names(CalendarArtists.sorted(artists, "count_desc")),
    ["Josef Albers", "Banksy", "Albrecht Dürer", "Joan Miró"]);
  assert.deepEqual(names(CalendarArtists.sorted(artists, "count_asc")),
    ["Joan Miró", "Banksy", "Albrecht Dürer", "Josef Albers"]);
  assert.deepEqual(names(CalendarArtists.sorted(artists, "time_asc")),
    ["Josef Albers", "Banksy", "Albrecht Dürer", "Joan Miró"]);
});

test("sorting respects accent-insensitive surnames and mononyms without rewriting displayed names", () => {
  const artists = CalendarArtists.summarize([
    {artist: "Éluard, Paul", artist_sort_key: "eluard, paul"},
    {artist: "Banksy", artist_sort_key: "banksy"},
    {artist: "Dürer, Albrecht", artist_sort_key: "durer, albrecht"},
    {artist: "Albers, Josef", artist_sort_key: "albers, josef"},
  ]);
  assert.deepEqual(names(CalendarArtists.sorted(artists, "artist_asc")),
    ["Albers, Josef", "Banksy", "Dürer, Albrecht", "Éluard, Paul"]);
});

test("summarizing and sorting preserve source lot data, ordering, and research identities", () => {
  const lots = Object.freeze([
    Object.freeze({id: 8, artist: "Banksy", event_at: null, time: "Time TBA", lot_url: "https://example.test/8"}),
    Object.freeze({id: 2, artist: "Albers, Josef", artist_sort_key: "albers, josef", event_at: "2026-10-22T12:00:00Z", time: "5:00 AM"}),
    Object.freeze({id: 7, artist: "Banksy", artist_source: "BANKSY", email_tray_selected: true, ended: true}),
  ]);
  const originalLots = JSON.stringify(lots);
  const artists = CalendarArtists.summarize(lots);
  const originalArtists = JSON.stringify(artists);
  artists.forEach(Object.freeze);
  Object.freeze(artists);
  for (const order of ["artist_asc", "artist_desc", "count_desc", "count_asc", "time_asc"]) {
    const sorted = CalendarArtists.sorted(artists, order);
    assert.notEqual(sorted, artists);
    assert.equal(JSON.stringify(artists), originalArtists);
  }
  assert.equal(JSON.stringify(lots), originalLots);
  assert.deepEqual(lots.map(({id}) => id), [8, 2, 7]);
});

test("the browser build exposes the same summary API without CommonJS", () => {
  const source = fs.readFileSync(path.join(__dirname, "static/secondstateapp/calendar_artists.js"), "utf8");
  const context = vm.createContext({window: {}});
  vm.runInContext(source, context);
  assert.equal(typeof context.window.CalendarArtists.summarize, "function");
  assert.equal(typeof context.window.CalendarArtists.sorted, "function");
  assert.equal(typeof context.window.CalendarArtists.estimateLotArrival, "function");
  assert.equal(typeof context.window.CalendarArtists.formatLotArrival, "function");
  const result = context.window.CalendarArtists.summarize([{artist: "Banksy"}]);
  assert.equal(result[0].name, "Banksy");
  assert.equal(result[0].count, 1);
});

test("lot 100 arrives an estimated 100 minutes after the artist's first auction", () => {
  const [artist] = CalendarArtists.summarize([
    {artist: "Chagall, Marc", event_at: "2026-10-24T08:00:00-04:00", time: "8:00 AM",
      lot_number: "100", auction_house: "First House"},
  ]);
  assert.equal(artist.arrivalTime, Date.parse("2026-10-24T09:40:00-04:00"));
  assert.equal(artist.arrivalLotNumber, 100);
  assert.equal(artist.arrivalHouse, "First House");
  assert.equal(CalendarArtists.formatArrival(artist, "America/New_York"), "9:40 AM");
});

test("arrival uses the first auction even when a later auction's lot would arrive sooner", () => {
  const [artist] = CalendarArtists.summarize([
    {artist: "Chagall, Marc", event_at: "2026-10-24T08:00:00-04:00", lot_number: "300", auction_house: "First House"},
    {artist: "Chagall, Marc", event_at: "2026-10-24T09:00:00-04:00", lot_number: "1", auction_house: "Later House"},
  ]);
  assert.equal(artist.earliestTime, Date.parse("2026-10-24T08:00:00-04:00"));
  assert.equal(artist.arrivalTime, Date.parse("2026-10-24T13:00:00-04:00"));
  assert.equal(artist.arrivalLotNumber, 300);
  assert.equal(artist.arrivalHouse, "First House");
});

test("an earlier auction discovered later resets the previously selected lot", () => {
  const [artist] = CalendarArtists.summarize([
    {artist: "Chagall, Marc", event_at: "2026-10-24T09:00:00-04:00", lot_number: "1", auction_house: "Later House"},
    {artist: "Chagall, Marc", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100", auction_house: "First House"},
    {artist: "Chagall, Marc", event_at: "2026-10-24T08:00:00-04:00", lot_number: "200", auction_house: "First House"},
  ]);
  assert.equal(artist.arrivalTime, Date.parse("2026-10-24T09:40:00-04:00"));
  assert.equal(artist.arrivalLotNumber, 100);
  assert.equal(artist.arrivalHouse, "First House");
});

test("simultaneous auction times choose the lowest lot numerically and retain its house", () => {
  const [artist] = CalendarArtists.summarize([
    {artist: "Banksy", event_at: "2026-10-24T12:00:00Z", lot_number: "100", auction_house: "Hundred House"},
    {artist: "Banksy", event_at: "2026-10-24T08:00:00-04:00", lot_number: " 009 ", auction_house: "Nine House"},
    {artist: "Banksy", event_at: "2026-10-24T14:00:00+02:00", lot_number: "20", auction_house: "Twenty House"},
  ]);
  assert.equal(artist.arrivalTime, Date.parse("2026-10-24T12:09:00Z"));
  assert.equal(artist.arrivalLotNumber, 9);
  assert.equal(artist.arrivalHouse, "Nine House");
});

test("an unusable earliest-sale lot number never falls forward to a later auction", () => {
  for (const earliestFirst of [true, false]) {
    const lots = [
      {artist: "Banksy", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100/1", auction_house: "First House"},
      {artist: "Banksy", event_at: "2026-10-24T09:00:00-04:00", lot_number: "10", auction_house: "Later House"},
    ];
    if (!earliestFirst) lots.reverse();
    const [artist] = CalendarArtists.summarize(lots);
    assert.equal(artist.earliestTime, Date.parse("2026-10-24T08:00:00-04:00"));
    assert.equal(artist.arrivalTime, null);
    assert.equal(artist.arrivalLotNumber, null);
    assert.equal(CalendarArtists.formatArrival(artist, "America/New_York"), "Unavailable");
  }
});

test("missing and ambiguous lot numbers cannot produce arrival estimates", () => {
  const invalidNumbers = [undefined, null, "", " ", "0", "000", "-1", "+1", "1.5", "100/1",
    "100-101", "Lot 100", "1,000", "1e2", "Infinity", "9007199254740992", "144000000000"];
  for (const lotNumber of invalidNumbers) {
    const [artist] = CalendarArtists.summarize([
      {artist: "Banksy", event_at: "2026-10-24T08:00:00-04:00", lot_number: lotNumber},
    ]);
    assert.equal(artist.arrivalTime, null, `Unexpected estimate for ${String(lotNumber)}`);
    assert.equal(artist.arrivalLotNumber, null, `Unexpected selected number for ${String(lotNumber)}`);
  }
});

test("unknown times do not block the first known auction or create estimates themselves", () => {
  const artists = CalendarArtists.summarize([
    {artist: "Banksy", event_at: null, time: "Time TBA", lot_number: "1"},
    {artist: "Banksy", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100"},
    {artist: "Banksy", event_at: "invalid", time: "Time TBA", lot_number: "2"},
    {artist: "Unknown time", event_at: null, time: "Time TBA", lot_number: "10"},
  ]);
  assert.equal(artists[0].count, 3);
  assert.equal(artists[0].arrivalTime, Date.parse("2026-10-24T09:40:00-04:00"));
  assert.equal(artists[1].earliestTime, null);
  assert.equal(artists[1].arrivalTime, null);
  assert.equal(CalendarArtists.formatArrival(artists[1], "America/New_York"), "Unavailable");
});

test("arrival sorting is chronological with unavailable estimates last and surname ties", () => {
  const artists = CalendarArtists.summarize([
    {artist: "Miró, Joan", artist_sort_key: "miro, joan", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100/1"},
    {artist: "Dürer, Albrecht", artist_sort_key: "durer, albrecht", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100"},
    {artist: "Banksy", artist_sort_key: "banksy", event_at: "2026-10-24T09:00:00-04:00", lot_number: "20"},
    {artist: "Albers, Josef", artist_sort_key: "albers, josef", event_at: "2026-10-24T08:00:00-04:00", lot_number: "80"},
    {artist: "Unknown time", artist_sort_key: "unknown time", event_at: null, lot_number: "1"},
  ]);
  assert.deepEqual(names(CalendarArtists.sorted(artists, "arrival_asc")), [
    "Albers, Josef", "Banksy", "Dürer, Albrecht", "Miró, Joan", "Unknown time",
  ]);
  assert.deepEqual(CalendarArtists.sorted([], "arrival_asc"), []);
});

test("arrival formatting uses the Calendar timezone and detects its own midnight boundary", () => {
  const [sameLocalDate] = CalendarArtists.summarize([
    {artist: "Banksy", event_at: "2026-10-24T23:30:00Z", lot_number: "100"},
  ]);
  // UTC passes midnight, but Los Angeles stays on October 24.
  assert.equal(CalendarArtists.formatArrival(sameLocalDate, "America/Los_Angeles"), "6:10 PM");
  const [nextLocalDate] = CalendarArtists.summarize([
    {artist: "Banksy", event_at: "2026-10-25T06:30:00Z", lot_number: "70"},
  ]);
  // UTC stays on October 25, but Los Angeles passes midnight.
  assert.equal(CalendarArtists.formatArrival(nextLocalDate, "America/Los_Angeles"), "Oct 25, 12:40 AM");
  assert.equal(CalendarArtists.formatArrival(nextLocalDate, "America/New_York"), "3:40 AM");
});

test("arrival calculations add elapsed minutes correctly through both daylight-saving transitions", () => {
  const [spring] = CalendarArtists.summarize([
    {artist: "Banksy", event_at: "2026-03-08T01:30:00-05:00", lot_number: "60"},
  ]);
  assert.equal(spring.arrivalTime, Date.parse("2026-03-08T07:30:00Z"));
  assert.equal(CalendarArtists.formatArrival(spring, "America/New_York"), "3:30 AM");
  const [fall] = CalendarArtists.summarize([
    {artist: "Banksy", event_at: "2026-11-01T01:30:00-04:00", lot_number: "60"},
  ]);
  assert.equal(fall.arrivalTime, Date.parse("2026-11-01T06:30:00Z"));
  assert.equal(CalendarArtists.formatArrival(fall, "America/New_York"), "1:30 AM");
});

test("arrival summaries and formatting preserve source records and artist summary order", () => {
  const lots = Object.freeze([
    Object.freeze({id: 80, artist: "Banksy", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100",
      auction_house: "First House", lot_url: "https://example.test/80", artprice_url: "https://example.test/research/80"}),
    Object.freeze({id: 90, artist: "Albers, Josef", event_at: "2026-10-24T09:00:00-04:00", lot_number: "10",
      auction_house: "Later House", email_tray_selected: true}),
  ]);
  const originalLots = JSON.stringify(lots);
  const artists = CalendarArtists.summarize(lots);
  artists.forEach(Object.freeze);
  Object.freeze(artists);
  const originalArtists = JSON.stringify(artists);
  const sorted = CalendarArtists.sorted(artists, "arrival_asc");
  sorted.forEach((artist) => CalendarArtists.formatArrival(artist, "America/New_York"));
  assert.notEqual(sorted, artists);
  assert.deepEqual(names(sorted), ["Albers, Josef", "Banksy"]);
  assert.equal(JSON.stringify(lots), originalLots);
  assert.equal(JSON.stringify(artists), originalArtists);
});

test("per-lot arrival uses each lot's own listed time and numeric or suffixed lot number", () => {
  const base = {event_at: "2026-11-04T13:00:00Z"};
  assert.equal(CalendarArtists.estimateLotArrival({...base, lot_number: "39"}), Date.parse("2026-11-04T13:39:00Z"));
  assert.equal(CalendarArtists.formatLotArrival({...base, lot_number: "39"}, "America/Los_Angeles"), "5:39 AM");
  for (const lot_number of ["191A", "191a", "00191B", " 191AB ", 191]) {
    assert.equal(CalendarArtists.estimateLotArrival({...base, lot_number}), Date.parse("2026-11-04T16:11:00Z"));
  }
  assert.equal(CalendarArtists.estimateLotArrival({event_at: "2026-11-04T17:00:00+02:00", lot_number: "39"}), Date.parse("2026-11-04T15:39:00Z"));
});

test("per-lot arrival requires a known explicit-zone time and never invents all-day timing", () => {
  for (const event_at of [undefined, null, "", " ", "invalid", "2026-11-04", "2026-11-04T13:00:00", "2026-11-04 13:00:00Z", "2026-11-04T25:00:00Z", "2026-02-30T13:00:00Z", "2026-02-29T13:00:00Z"]) {
    const lot = {event_at, lot_number: "39"};
    assert.equal(CalendarArtists.estimateLotArrival(lot), null, String(event_at));
    assert.equal(CalendarArtists.formatLotArrival(lot, "America/Los_Angeles"), "Unavailable");
  }
  assert.equal(CalendarArtists.estimateLotArrival({event_at: "2026-11-04T00:00:00Z", is_all_day: true, lot_number: "39"}), null);
  assert.equal(CalendarArtists.estimateLotArrival(null), null);
  assert.equal(CalendarArtists.formatLotArrival(undefined, "America/Los_Angeles"), "Unavailable");
  assert.equal(CalendarArtists.estimateLotArrival({event_at: "2026-11-04T00:00:00Z", lot_number: "1"}), Date.parse("2026-11-04T00:01:00Z"));
});

test("per-lot arrival rejects ambiguous numbers and out-of-range dates", () => {
  for (const lot_number of [undefined, null, "", "0", "-1", "+1", "1.5", "100-101", "100/1", "Lot 100", "1,000", "1e2", "Infinity", "9007199254740992", "144000000000"]) {
    assert.equal(CalendarArtists.estimateLotArrival({event_at: "2026-11-04T13:00:00Z", lot_number}), null, String(lot_number));
  }
});

test("per-lot arrival shows its local rollover date, including large lot numbers", () => {
  const lot = {event_at: "2026-11-05T07:30:00Z", lot_number: "70"};
  assert.equal(CalendarArtists.formatLotArrival(lot, "America/Los_Angeles"), "Nov 5, 12:40 AM");
  assert.equal(CalendarArtists.formatLotArrival(lot, "America/New_York"), "3:40 AM");
  const large = {event_at: "2026-11-04T08:00:00Z", lot_number: "8063"};
  assert.equal(CalendarArtists.estimateLotArrival(large), Date.parse("2026-11-09T22:23:00Z"));
  assert.equal(CalendarArtists.formatLotArrival(large, "America/Los_Angeles"), "Nov 9, 2:23 PM");
});

test("per-lot arrival preserves source data and calculates elapsed minutes through DST", () => {
  const lot = Object.freeze({id: 19, event_at: "2026-11-01T01:30:00-04:00", lot_number: "60A", is_all_day: false,
    saved_bid_board: Object.freeze({qualifying_bid: "30"}), email_tray_selected: true, won_by_us: true});
  const before = JSON.stringify(lot);
  assert.equal(CalendarArtists.estimateLotArrival(lot), Date.parse("2026-11-01T06:30:00Z"));
  assert.equal(CalendarArtists.formatLotArrival(lot, "America/New_York"), "1:30 AM");
  assert.equal(JSON.stringify(lot), before);
});

test("explicit numbering baselines subtract the sale offset without guessing from watched lots", () => {
  const lot = Object.freeze({artist: "Example", event_at: "2026-11-06T08:00:00Z", lot_number: "3325", numbering_baseline: 3000});
  const expected = Date.parse("2026-11-06T13:25:00Z");
  assert.equal(CalendarArtists.estimateLotArrival(lot), expected);
  const [artist] = CalendarArtists.summarize([lot]);
  assert.equal(artist.arrivalTime, expected);
  assert.equal(artist.arrivalMinutes, 325);
  assert.equal(CalendarArtists.estimateLotArrival({...lot, lot_number: "3325A"}), expected);
  assert.equal(CalendarArtists.estimateLotArrival({...lot, lot_number: "3000"}), Date.parse(lot.event_at));
  for (const numbering_baseline of [-1, 3326, 1.5, "3000", Infinity]) {
    assert.equal(CalendarArtists.estimateLotArrival({...lot, numbering_baseline}), null);
  }
  const withoutBaseline = {...lot};
  delete withoutBaseline.numbering_baseline;
  assert.equal(CalendarArtists.estimateLotArrival(withoutBaseline), Date.parse(lot.event_at) + 3325 * 60000);
  assert.equal(CalendarArtists.summarize([{...lot, lot_number: "3340"}])[0].arrivalMinutes, 340);
});

const houseTimetable = (at = "2026-11-06T13:30:00Z", first = 3446, last = 3467) => ({
  kind: "published_timetable", at, session_start_at: "2026-11-06T13:00:00Z",
  first_lot: first, last_lot: last, source_url: "https://www.dobiaschofsky.com/g246.html",
});

test("artist summaries share per-lot suffix handling for timetable and fallback arrivals", () => {
  for (const lot of [
    {artist: "Miró", event_at: "2026-11-06T08:00:00Z", lot_number: "3466A", arrival_schedule: houseTimetable()},
    {artist: "Example", event_at: "2026-11-06T08:00:00Z", lot_number: "3325A", numbering_baseline: 3000},
    {artist: "Example", event_at: "2026-11-06T08:00:00Z", lot_number: "100A"},
  ]) {
    const before = JSON.stringify(lot);
    const [artist] = CalendarArtists.summarize([lot]);
    assert.equal(artist.arrivalTime, CalendarArtists.estimateLotArrival(lot));
    assert.equal(CalendarArtists.formatArrival(artist, "America/Los_Angeles"), CalendarArtists.formatLotArrival(lot, "America/Los_Angeles"));
    assert.equal(artist.arrivalLotNumber, Number.parseInt(lot.lot_number, 10));
    assert.equal(JSON.stringify(lot), before);
  }
});

test("published timetable overrides provider day-start differences without changing records", () => {
  const schedule = Object.freeze(houseTimetable());
  for (const event_at of ["2026-11-06T08:00:00Z", "2026-11-06T13:00:00Z"]) {
    const lot = Object.freeze({event_at, lot_number: "3466", arrival_schedule: schedule, won_by_us: true, email_tray_selected: true});
    const before = JSON.stringify(lot);
    assert.equal(CalendarArtists.estimateLotArrival(lot), Date.parse("2026-11-06T13:30:00Z"));
    assert.equal(CalendarArtists.formatLotArrival(lot, "America/Los_Angeles"), "5:30 AM");
    assert.equal(CalendarArtists.formatLotArrival(lot, "America/New_York"), "8:30 AM");
    assert.equal(CalendarArtists.lotArrivalDetails(lot).kind, "published_timetable");
    assert.equal(JSON.stringify(lot), before);
  }
});

test("artist summaries compare the same verified session and select the earliest block", () => {
  const lots = [
    {artist: "Miró", event_at: "2026-11-06T08:00:00Z", time: "12:00 AM", lot_number: "3468", arrival_schedule: houseTimetable("2026-11-06T13:45:00Z", 3468, 3490)},
    {artist: "Miró", event_at: "2026-11-06T13:00:00Z", time: "5:00 AM", lot_number: "3466", arrival_schedule: houseTimetable()},
    {artist: "Miró", event_at: "2026-11-06T08:00:00Z", time: "12:00 AM", lot_number: "3463", arrival_schedule: houseTimetable()},
  ];
  for (const input of [lots, [...lots].reverse()]) {
    const [artist] = CalendarArtists.summarize(input);
    assert.equal(artist.earliestTime, Date.parse("2026-11-06T08:00:00Z"));
    assert.equal(artist.timeLabel, "12:00 AM");
    assert.equal(artist.arrivalStartTime, Date.parse("2026-11-06T13:00:00Z"));
    assert.equal(artist.arrivalTime, Date.parse("2026-11-06T13:30:00Z"));
    assert.equal(artist.arrivalLotNumber, 3463);
    assert.equal(artist.arrivalKind, "published_timetable");
    assert.equal(artist.arrivalSourceUrl, "https://www.dobiaschofsky.com/g246.html");
  }
});

test("unknown dates and invalid timetable ranges never invent a house time", () => {
  const lot = {event_at: "2026-11-06T08:00:00Z", lot_number: "3466", arrival_schedule: houseTimetable()};
  for (const changes of [{event_at: null}, {is_all_day: true}, {lot_number: "3499"}, {lot_number: "3466/1"}]) {
    assert.equal(CalendarArtists.estimateLotArrival({...lot, ...changes}), null);
  }
  for (const changes of [{at: "2026-11-06"}, {session_start_at: "2026-11-06T15:00:00Z"}, {source_url: "https://example.test"}, {first_lot: "3446"}]) {
    assert.equal(CalendarArtists.estimateLotArrival({...lot, arrival_schedule: {...lot.arrival_schedule, ...changes}}), null);
  }
  assert.equal(CalendarArtists.estimateLotArrival({...lot, lot_number: "3466A"}), Date.parse("2026-11-06T13:30:00Z"));
});
