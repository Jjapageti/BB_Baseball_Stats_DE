import test from 'node:test';
import assert from 'node:assert/strict';
import {
  resolveStandingTeam,
  renderStandingTeamIdentity,
} from '../js/dashboard.js';

test('resolveStandingTeam matches the league entry id before name or acronym', () => {
  const teams = [
    { id: 100, name: 'Other Sluggers', acronym: 'BES', club: { logo_url: 'other.png' } },
    { id: 200, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'sluggers.png' } },
  ];

  const team = resolveStandingTeam(
    { league_entry_id: 200, team: 'Sluggers 2', acronym: 'BES2' },
    teams,
  );

  assert.equal(team.id, 200);
});

test('renderStandingTeamIdentity shows acronym, team mark and team name', () => {
  const html = renderStandingTeamIdentity(
    { league_entry_id: 200, team: 'Sluggers 2', acronym: 'BES2' },
    [{ id: 200, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'https://example.test/sluggers.png?a=1&b=2' } }],
  );

  assert.match(html, /team-chip[^>]*>BES2</);
  assert.match(html, /class="team-logo"/);
  assert.match(html, /src="https:\/\/example\.test\/sluggers\.png\?a=1&amp;b=2"/);
  assert.match(html, /<strong>Sluggers 2<\/strong>/);
});

test('renderStandingTeamIdentity uses a visible fallback when no team mark exists', () => {
  const html = renderStandingTeamIdentity(
    { league_entry_id: 300, team: 'Porcupines 2', acronym: 'POT2' },
    [{ id: 300, name: 'Porcupines 2', acronym: 'POT2', club: {} }],
  );

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /team-mark-fallback/);
  assert.match(html, />P</);
});

import {
  leaderBox,
  renderMatchList,
  renderWarTeamIdentity,
} from '../js/dashboard.js';

test('WAR team identity includes the team mark, acronym and name', () => {
  const html = renderWarTeamIdentity(
    { teamId: 200, team: 'Sluggers 2', acronym: 'BES2' },
    [{ id: 200, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'sluggers.png' } }],
  );
  assert.match(html, /sluggers\.png/);
  assert.match(html, /BES2/);
  assert.match(html, /Sluggers 2/);
});

test('leaderBox includes a compact team mark beside each player', () => {
  const html = leaderBox(
    'OPS',
    [{ personId: 1, name: 'Max Mustermann', teamId: 200, team: 'Sluggers 2', acronym: 'BES2', ops: 1.2 }],
    (row) => String(row.ops),
    'league-key',
    [{ id: 200, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'sluggers.png' } }],
  );
  assert.match(html, /leader-team-mark/);
  assert.match(html, /sluggers\.png/);
});

test('renderMatchList includes both home and away team marks', () => {
  const html = renderMatchList([{
    time: '2026-08-16 13:00:00 +0200',
    state: 'planned',
    home_team_name: 'Wizards 2',
    away_team_name: 'Sluggers',
    home_league_entry: { id: 10, team: { name: 'Wizards 2', short_name: 'BEW2', clubs: [{ logo_url: 'wizards.png' }] } },
    away_league_entry: { id: 20, team: { name: 'Sluggers', short_name: 'BES', clubs: [{ logo_url: 'sluggers.png' }] } },
  }], false, []);

  assert.match(html, /wizards\.png/);
  assert.match(html, /sluggers\.png/);
  assert.match(html, /match-team--home/);
  assert.match(html, /match-team--away/);
});
