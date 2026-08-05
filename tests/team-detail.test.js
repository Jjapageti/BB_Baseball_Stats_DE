import test from 'node:test';
import assert from 'node:assert/strict';
import { filterTeamRows, teamDetailHeading } from '../js/team-detail.js';
import { renderStandingTeamButton } from '../js/dashboard.js';

test('filterTeamRows keeps only players from the clicked league entry', () => {
  const rows = [
    { teamId: 10, name: 'A' },
    { teamId: 20, name: 'B' },
    { teamId: 10, name: 'C' },
  ];
  assert.deepEqual(filterTeamRows(rows, 10).map((row) => row.name), ['A', 'C']);
});

test('standing team is rendered as an accessible detail button', () => {
  const html = renderStandingTeamButton(
    { league_entry_id: 10, team: 'Sluggers', acronym: 'BES' },
    [{ id: 10, name: 'Sluggers', acronym: 'BES', club: { logo_url: 'sluggers.png' } }],
  );
  assert.match(html, /<button/);
  assert.match(html, /data-team-id="10"/);
  assert.match(html, /Sluggers/);
  assert.match(html, /Teamstatistik öffnen/);
});

test('team detail heading is fully German', () => {
  const heading = teamDetailHeading({ name: 'Sluggers', acronym: 'BES' }, { name: 'Verbandsliga Baseball', season: 2026 });
  assert.equal(heading.title, 'Sluggers');
  assert.equal(heading.subtitle, 'BES · Verbandsliga Baseball 2026');
});
