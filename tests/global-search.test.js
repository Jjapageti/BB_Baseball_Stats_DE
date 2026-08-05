import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildGlobalSearchIndex,
  filterGlobalSearch,
  globalSearchResultUrl,
} from '../js/search.js';

const leagueData = [{
  selectedSeason: 2026,
  selectedLeagueKey: 'vlbb-2026',
  league: { season: 2026, name: 'Verbandsliga Baseball' },
  teams: [
    { id: 10, name: 'Sluggers', acronym: 'BES', club: { logo_url: 'sluggers.png' } },
    { id: 20, name: 'Wizards', acronym: 'BEW' },
  ],
  batting: [{
    person: { id: 100, first_name: 'Tim', last_name: 'Junker' },
    league_entry: { id: 10, name: 'Sluggers', acronym: 'BES' },
  }],
  pitching: [],
}];

test('global search index contains player and team entries', () => {
  const index = buildGlobalSearchIndex(leagueData);
  assert.equal(index.filter((row) => row.type === 'team').length, 2);
  assert.equal(index.filter((row) => row.type === 'player').length, 1);
});

test('global search finds a team by acronym and player by name', () => {
  const index = buildGlobalSearchIndex(leagueData);
  assert.equal(filterGlobalSearch(index, 'BES')[0].name, 'Sluggers');
  assert.equal(filterGlobalSearch(index, 'Junker')[0].name, 'Tim Junker');
});

test('team search result URL selects the league and opens the team detail', () => {
  const index = buildGlobalSearchIndex(leagueData);
  const team = index.find((row) => row.type === 'team' && row.teamId === 10);
  const url = globalSearchResultUrl(team);
  assert.match(url, /^dashboard\.html\?/);
  assert.match(url, /season=2026/);
  assert.match(url, /league=vlbb-2026/);
  assert.match(url, /team=10/);
});
