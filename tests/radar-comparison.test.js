import test from 'node:test';
import assert from 'node:assert/strict';
import { renderRadar } from '../js/radar.js';
import { comparisonAverage } from '../js/player-view.js';

test('renderRadar draws a separate league-average polygon and German legend', () => {
  const container = { innerHTML: '' };
  const axes = [
    { label: 'Kontakt', value: 80 },
    { label: 'Schlagkraft', value: 70 },
    { label: 'Disziplin', value: 60 },
  ];
  const comparisonAxes = [
    { label: 'Kontakt', value: 50 },
    { label: 'Schlagkraft', value: 45 },
    { label: 'Disziplin', value: 55 },
  ];

  renderRadar(container, axes, { comparisonAxes });

  assert.match(container.innerHTML, /class="radar-comparison"/);
  assert.match(container.innerHTML, /Spieler/);
  assert.match(container.innerHTML, /Liga-Durchschnitt/);
});

test('comparisonAverage aggregates the selected batting comparison group', () => {
  const average = comparisonAverage([
    { ab: 10, hits: 4, doubles: 1, triples: 0, hr: 1, bb: 2, hbp: 0, sf: 0, pa: 12, so: 2, sb: 1, games: 3, wrcPlus: 120, war: 0.4 },
    { ab: 20, hits: 6, doubles: 2, triples: 0, hr: 0, bb: 4, hbp: 0, sf: 0, pa: 24, so: 6, sb: 2, games: 5, wrcPlus: 80, war: 0.2 },
  ], 'batting');

  assert.equal(average.ab, 30);
  assert.equal(average.hits, 10);
  assert.equal(average.pa, 36);
  assert.equal(average.so, 8);
  assert.ok(Math.abs(average.avg - (10 / 30)) < 1e-12);
});
