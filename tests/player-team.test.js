import test from 'node:test';
import assert from 'node:assert/strict';
import {
  renderHistoryTeamIdentity,
  renderPlayerHeroMark,
  renderPlayerTeamList,
} from '../js/player.js';

const teams = [
  { id: 200, name: 'Sluggers 2', acronym: 'BES2', club: { logo_url: 'sluggers.png' } },
  { id: 300, name: 'Berlin Sluggers', acronym: 'BES', club: { logo_url: 'berlin.png' } },
];

test('renderPlayerHeroMark uses the player latest team logo instead of an initial', () => {
  const html = renderPlayerHeroMark({ teamId: 200, team: 'Sluggers 2', acronym: 'BES2', name: 'Tim Junker' }, teams);
  assert.match(html, /player-avatar/);
  assert.match(html, /sluggers\.png/);
  assert.doesNotMatch(html, />T<\/span>/);
});

test('renderPlayerTeamList displays each career team with mark and name once', () => {
  const html = renderPlayerTeamList([
    { teamId: 200, team: 'Sluggers 2', acronym: 'BES2' },
    { teamId: 201, team: 'Sluggers 2', acronym: 'BES2' },
    { teamId: 300, team: 'Berlin Sluggers', acronym: 'BES' },
  ], teams);
  assert.equal((html.match(/sluggers\.png/g) ?? []).length, 1);
  assert.equal((html.match(/berlin\.png/g) ?? []).length, 1);
});

test('renderHistoryTeamIdentity includes mark, acronym and team name for league rows', () => {
  const html = renderHistoryTeamIdentity({ teamId: 200, team: 'Sluggers 2', acronym: 'BES2', rowType: 'league' }, teams);
  assert.match(html, /sluggers\.png/);
  assert.match(html, /BES2/);
  assert.match(html, /Sluggers 2/);
});
