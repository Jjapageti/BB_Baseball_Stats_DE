import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildTeamCatalog,
  renderMatchTeamIdentity,
  renderTeamIdentity,
  renderTeamMark,
  resolveTeam,
} from '../js/team.js';

test('buildTeamCatalog combines teams from all league payloads and prefers a logo-bearing record', () => {
  const catalog = buildTeamCatalog([
    { teams: [{ id: 20, name: 'Sluggers 2', acronym: 'BES2', club: {} }] },
    { teams: [{ id: 20, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'sluggers.png' } }] },
  ]);

  assert.equal(catalog.length, 1);
  assert.equal(catalog[0].club.logo_url, 'sluggers.png');
});

test('resolveTeam uses team id before name and acronym', () => {
  const teams = [
    { id: 10, name: 'Sluggers', acronym: 'BES' },
    { id: 20, name: 'Sluggers 2', acronym: 'BES2' },
  ];

  assert.equal(resolveTeam({ teamId: 20, team: 'Sluggers', acronym: 'BES' }, teams).id, 20);
});

test('renderTeamIdentity shows acronym, club mark and team name', () => {
  const html = renderTeamIdentity(
    { teamId: 20, team: 'Sluggers 2', acronym: 'BES2' },
    [{ id: 20, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'https://example.test/logo.png?a=1&b=2' } }],
  );

  assert.match(html, /team-chip[^>]*>BES2</);
  assert.match(html, /class="team-logo"/);
  assert.match(html, /src="https:\/\/example\.test\/logo\.png\?a=1&amp;b=2"/);
  assert.match(html, /Sluggers 2/);
});

test('renderMatchTeamIdentity reads the nested league entry team and logo', () => {
  const match = {
    home_team_name: 'Wizards 2',
    home_league_entry: {
      id: 88,
      team: {
        name: 'Wizards 2',
        short_name: 'BEW2',
        clubs: [{ logo_url: 'wizards.png' }],
      },
    },
  };

  const html = renderMatchTeamIdentity(match, 'home', []);
  assert.match(html, /wizards\.png/);
  assert.match(html, /Wizards 2/);
  assert.match(html, /BEW2/);
});

test('renderTeamMark keeps a visible letter fallback when a logo is missing', () => {
  const html = renderTeamMark({ name: 'Porcupines 2', club: {} }, { size: 'lg' });

  assert.match(html, /team-mark--lg/);
  assert.match(html, /team-mark-letter/);
  assert.match(html, />P</);
  assert.doesNotMatch(html, /<img/);
});
