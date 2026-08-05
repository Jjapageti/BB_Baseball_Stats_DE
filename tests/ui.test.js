import test from 'node:test';
import assert from 'node:assert/strict';
import { playerUrl } from '../js/ui.js';

test('playerUrl opens the career overview by default', () => {
  assert.equal(playerUrl({ personId: 42, season: 2025, leagueKey: 'vl-2025' }), 'player.html?id=42');
});
