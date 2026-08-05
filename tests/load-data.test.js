import test from 'node:test';
import assert from 'node:assert/strict';

const makeSeason = (season) => ({
  schema_version: 2,
  generated_at: `${season}-08-05T09:00:00Z`,
  season,
  target_club: { id: 492, name: 'Berlin Sluggers' },
  counts: { leagues: 1 },
  leagues: [{
    key: `league-${season}`,
    name: `League ${season}`,
    level: 'landesliga',
    stage: 'regular',
    season,
    source_groups: [{ id: season, acronym: `L${season}` }],
    counts: { teams: 1, matches: 0, played_matches: 0, batters: 0, pitchers: 0 },
    teams: [{ id: 1, name: 'Sluggers' }], matches: [], standings: [], batting: [], pitching: [],
  }],
});

const fixtures = new Map([2023, 2024, 2025, 2026].map((season) => [
  `./data/seasons/${season}.json`, makeSeason(season),
]));

test('loadData and loadAllData consume data/seasons files', async () => {
  global.fetch = async (url) => ({
    ok: fixtures.has(url),
    status: fixtures.has(url) ? 200 : 404,
    statusText: fixtures.has(url) ? 'OK' : 'Not Found',
    async json() { return structuredClone(fixtures.get(url)); },
  });
  const { loadAllData, loadData } = await import(`../js/data.js?test=${Date.now()}`);
  const selected = await loadData({ season: 2024, leagueKey: 'league-2024' });
  assert.equal(selected.league.season, 2024);
  assert.equal(selected.league.key, 'league-2024');
  const all = await loadAllData();
  assert.equal(all.length, 4);
  assert.deepEqual(all.map((row) => row.league.season), [2026, 2025, 2024, 2023]);
});
