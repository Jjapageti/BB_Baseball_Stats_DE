import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildSelectionUrl,
  buildSeasonCatalog,
  normalizeLeagueData,
  resolveSelection,
  validateSeasonShape,
} from '../js/data.js';

const season2026 = {
  schema_version: 2,
  generated_at: '2026-08-05T09:00:00Z',
  season: 2026,
  target_club: { id: 492, name: 'Berlin Sluggers' },
  counts: { leagues: 2 },
  leagues: [
    {
      key: 'verbandsliga-regular-verbandsliga-baseball',
      name: 'Verbandsliga Baseball', level: 'verbandsliga', stage: 'regular', season: 2026,
      source_groups: [{ id: 6205, acronym: 'VLBB' }],
      counts: { teams: 1, matches: 0, played_matches: 0, batters: 0, pitchers: 0 },
      teams: [], matches: [], standings: [], batting: [], pitching: [],
    },
    {
      key: 'landesliga-regular-landesliga-baseball',
      name: 'Landesliga Baseball', level: 'landesliga', stage: 'regular', season: 2026,
      source_groups: [{ id: 6208, acronym: 'LLBBDivA' }, { id: 6209, acronym: 'LLBBDivB' }],
      counts: { teams: 2, matches: 0, played_matches: 0, batters: 0, pitchers: 0 },
      teams: [], matches: [], standings: [], batting: [], pitching: [],
    },
  ],
};

const season2025 = {
  ...season2026,
  season: 2025,
  leagues: [{ ...season2026.leagues[0], season: 2025, key: '2-bundesliga-regular' }],
};

test('validateSeasonShape accepts schema version 2 season files', () => {
  assert.equal(validateSeasonShape(season2026), true);
});

test('validateSeasonShape rejects a season without leagues', () => {
  assert.throws(() => validateSeasonShape({ season: 2026, leagues: [] }), /Ligen/);
});

test('buildSeasonCatalog sorts seasons descending and keeps league metadata', () => {
  const catalog = buildSeasonCatalog([season2025, season2026]);
  assert.deepEqual(catalog.seasons.map((row) => row.season), [2026, 2025]);
  assert.equal(catalog.seasons[0].leagues[1].acronym, 'LLBBDivA+LLBBDivB');
});

test('resolveSelection prefers valid URL season and league', () => {
  const catalog = buildSeasonCatalog([season2025, season2026]);
  assert.deepEqual(
    resolveSelection(catalog, '?season=2025&league=2-bundesliga-regular', null),
    { season: 2025, leagueKey: '2-bundesliga-regular' },
  );
});

test('resolveSelection falls back to first league when stored league belongs to another season', () => {
  const catalog = buildSeasonCatalog([season2025, season2026]);
  assert.deepEqual(
    resolveSelection(catalog, '?season=2026', { season: 2026, leagueKey: '2-bundesliga-regular' }),
    { season: 2026, leagueKey: 'verbandsliga-regular-verbandsliga-baseball' },
  );
});

test('buildSelectionUrl preserves player id and changes season/league', () => {
  assert.equal(
    buildSelectionUrl('player.html?id=77&season=2026&league=old', { season: 2024, leagueKey: 'new' }),
    'player.html?id=77&season=2024&league=new',
  );
});

test('normalizeLeagueData exposes the legacy league shape used by pages', () => {
  const result = normalizeLeagueData(season2026, season2026.leagues[1]);
  assert.equal(result.league.season, 2026);
  assert.equal(result.league.acronym, 'LLBBDivA+LLBBDivB');
  assert.equal(result.counts.teams, 2);
});
