import test from 'node:test';
import assert from 'node:assert/strict';
import {
  comparisonTotals,
  filterHistoryForSelection,
  selectedTotal,
} from '../js/player-view.js';

const history = [
  { season: 2025, leagueName: 'Landesliga', rowType: 'league', pa: 20 },
  { season: 2025, leagueName: 'Verbandsliga', rowType: 'league', pa: 10 },
  { season: 2025, leagueName: 'Gesamt', rowType: 'season-total', pa: 30 },
  { season: 2024, leagueName: 'Verbandsliga', rowType: 'league', pa: 40 },
  { season: 2024, leagueName: 'Gesamt', rowType: 'season-total', pa: 40 },
  { season: 'Karriere', leagueName: 'Gesamt', rowType: 'career-total', pa: 70 },
];

test('filterHistoryForSelection keeps the complete table for career view', () => {
  assert.deepEqual(filterHistoryForSelection(history, 'career'), history);
});

test('filterHistoryForSelection keeps league rows and season total for one year', () => {
  const rows = filterHistoryForSelection(history, 2025);
  assert.deepEqual(rows.map((row) => row.rowType), ['league', 'league', 'season-total']);
  assert.ok(rows.every((row) => Number(row.season) === 2025));
});

test('selectedTotal returns career or season aggregate', () => {
  assert.equal(selectedTotal(history, 'career').pa, 70);
  assert.equal(selectedTotal(history, 2024).pa, 40);
  assert.equal(selectedTotal(history, 2023), null);
});

test('comparisonTotals aggregates each player for a selected season', () => {
  const rows = [
    { personId: 1, season: 2025, team: 'A', acronym: 'A', pa: 10, ab: 8, hits: 3, doubles: 1, triples: 0, hr: 0, bb: 2, hbp: 0, sf: 0, so: 1, runs: 2, rbi: 1, sb: 1, cs: 0, war: .2 },
    { personId: 1, season: 2025, team: 'B', acronym: 'B', pa: 20, ab: 18, hits: 7, doubles: 1, triples: 0, hr: 1, bb: 2, hbp: 0, sf: 0, so: 3, runs: 4, rbi: 3, sb: 0, cs: 0, war: .4 },
    { personId: 1, season: 2024, team: 'A', acronym: 'A', pa: 5, ab: 5, hits: 1, doubles: 0, triples: 0, hr: 0, bb: 0, hbp: 0, sf: 0, so: 2, runs: 0, rbi: 0, sb: 0, cs: 0, war: 0 },
    { personId: 2, season: 2025, team: 'C', acronym: 'C', pa: 12, ab: 10, hits: 4, doubles: 0, triples: 0, hr: 0, bb: 2, hbp: 0, sf: 0, so: 2, runs: 1, rbi: 2, sb: 0, cs: 0, war: .1 },
  ];
  const totals = comparisonTotals(rows, 'batting', 2025);
  assert.equal(totals.length, 2);
  assert.equal(totals.find((row) => row.personId === 1).pa, 30);
  assert.equal(totals.find((row) => row.personId === 2).pa, 12);
});

test('comparisonTotals builds one career aggregate per player', () => {
  const rows = [
    { personId: 1, season: 2025, team: 'A', acronym: 'A', pa: 10, ab: 8, hits: 3, doubles: 1, triples: 0, hr: 0, bb: 2, hbp: 0, sf: 0, so: 1, runs: 2, rbi: 1, sb: 1, cs: 0, war: .2 },
    { personId: 1, season: 2024, team: 'A', acronym: 'A', pa: 5, ab: 5, hits: 1, doubles: 0, triples: 0, hr: 0, bb: 0, hbp: 0, sf: 0, so: 2, runs: 0, rbi: 0, sb: 0, cs: 0, war: 0 },
    { personId: 2, season: 2025, team: 'C', acronym: 'C', pa: 12, ab: 10, hits: 4, doubles: 0, triples: 0, hr: 0, bb: 2, hbp: 0, sf: 0, so: 2, runs: 1, rbi: 2, sb: 0, cs: 0, war: .1 },
  ];
  const totals = comparisonTotals(rows, 'batting', 'career');
  assert.equal(totals.length, 2);
  assert.equal(totals.find((row) => row.personId === 1).pa, 15);
});
