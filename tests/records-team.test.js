import test from 'node:test';
import assert from 'node:assert/strict';
import { getBattingColumns, getPitchingColumns } from '../js/records.js';

const teams = [{ id: 20, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'sluggers.png' } }];
const row = { teamId: 20, team: 'Sluggers 2', acronym: 'BES2' };

test('batting records team column renders team mark, acronym and name', () => {
  const column = getBattingColumns('league-key', teams).find((item) => item.key === 'team');
  const html = column.render(row);
  assert.match(html, /sluggers\.png/);
  assert.match(html, /BES2/);
  assert.match(html, /Sluggers 2/);
});

test('pitching records team column renders team mark, acronym and name', () => {
  const column = getPitchingColumns('league-key', teams).find((item) => item.key === 'team');
  assert.match(column.render(row), /sluggers\.png/);
});
