import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aggregateBattingRows,
  aggregatePitchingRows,
  buildBattingHistory,
  buildPitchingHistory,
  formatInnings,
} from '../js/career.js';

const batting = [
  { season: 2024, leagueName: 'Verbandsliga', leagueKey: 'vl-2024', team: 'Sluggers', acronym: 'BES', games: 10, pa: 40, ab: 32, runs: 10, rbi: 8, hits: 12, doubles: 2, triples: 1, hr: 2, bb: 6, hbp: 1, sf: 1, so: 5, sb: 3, cs: 1, war: 0.8, woba: .400, opsPlus: 120, wrcPlus: 125 },
  { season: 2024, leagueName: 'Playoffs', leagueKey: 'po-2024', team: 'Sluggers', acronym: 'BES', games: 2, pa: 8, ab: 7, runs: 2, rbi: 2, hits: 3, doubles: 1, triples: 0, hr: 0, bb: 1, hbp: 0, sf: 0, so: 1, sb: 0, cs: 0, war: 0.2, woba: .390, opsPlus: 115, wrcPlus: 118 },
  { season: 2023, leagueName: '2. Bundesliga', leagueKey: '2bl-2023', team: 'Berlin Sluggers', acronym: 'BES', games: 5, pa: 20, ab: 18, runs: 3, rbi: 4, hits: 6, doubles: 1, triples: 0, hr: 1, bb: 2, hbp: 0, sf: 0, so: 4, sb: 1, cs: 0, war: 0.3, woba: .350, opsPlus: 105, wrcPlus: 108 },
];

const pitching = [
  { season: 2024, leagueName: 'Verbandsliga', leagueKey: 'vl-2024', team: 'Sluggers', acronym: 'BES', games: 4, gamesStarted: 3, completeGames: 0, ip: 12 + 2 / 3, battersFaced: 55, runs: 8, er: 5, hits: 12, hr: 1, bb: 4, hbp: 1, so: 15, wins: 2, losses: 1, saves: 0, fip: 3.2, eraPlus: 130, fipMinus: 85, war: 0.6 },
  { season: 2023, leagueName: '2. Bundesliga', leagueKey: '2bl-2023', team: 'Berlin Sluggers', acronym: 'BES', games: 2, gamesStarted: 1, completeGames: 0, ip: 3 + 1 / 3, battersFaced: 17, runs: 4, er: 3, hits: 4, hr: 0, bb: 2, hbp: 0, so: 5, wins: 0, losses: 1, saves: 0, fip: 2.8, eraPlus: 90, fipMinus: 80, war: 0.1 },
];

test('aggregateBattingRows sums counting stats and recomputes rate stats', () => {
  const total = aggregateBattingRows(batting.slice(0, 2));
  assert.equal(total.games, 12);
  assert.equal(total.pa, 48);
  assert.equal(total.hits, 15);
  assert.equal(total.war, 1);
  assert.ok(Math.abs(total.avg - 15 / 39) < 1e-12);
});

test('buildBattingHistory adds each season total and one career total', () => {
  const rows = buildBattingHistory(batting);
  assert.equal(rows.filter((row) => row.rowType === 'season-total').length, 2);
  assert.equal(rows.at(-1).rowType, 'career-total');
  assert.equal(rows.at(-1).pa, 68);
});

test('aggregatePitchingRows recomputes ERA and formats baseball innings', () => {
  const total = aggregatePitchingRows(pitching);
  assert.ok(Math.abs(total.ip - 16) < 1e-12);
  assert.equal(formatInnings(total.ip), '16.0');
  assert.equal(total.era, 4.5);
});

test('buildPitchingHistory adds season and career totals', () => {
  const rows = buildPitchingHistory(pitching);
  assert.equal(rows.filter((row) => row.rowType === 'season-total').length, 2);
  assert.equal(rows.at(-1).rowType, 'career-total');
  assert.equal(rows.at(-1).wins, 2);
});
