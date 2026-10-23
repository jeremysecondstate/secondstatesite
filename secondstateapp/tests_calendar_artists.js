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
      {artist: "Banksy", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100A", auction_house: "First House"},
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
  const invalidNumbers = [undefined, null, "", " ", "0", "000", "-1", "+1", "1.5", "100A",
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
    {artist: "Miró, Joan", artist_sort_key: "miro, joan", event_at: "2026-10-24T08:00:00-04:00", lot_number: "100A"},
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
