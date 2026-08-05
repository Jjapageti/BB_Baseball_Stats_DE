import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseInnings,
  buildLeagueContext,
  buildBattingRows,
  buildPitchingRows,
  getPlayerKey,
} from '../js/stats.js';

const sample = {
  league: { season: 2026, name: 'Landesliga Baseball' },
  standings: [{ games: 10 }, { games: 8 }],
  batting: [
    {
      person: { id: 1, first_name: 'Max', last_name: 'Mustermann' },
      league_entry: { id: 11, name: 'A Team', acronym: 'AAA' },
      values: {
        games: 10, plate_appearances: 40, at_bats: 32, runs: 12,
        runs_batted_in: 10, hits: 16, doubles: 4, triples: 1, homeruns: 2,
        strikeouts: 4, base_on_balls: 6, hit_by_pitches: 1, sacrifice_flys: 1,
        stolen_bases: 3, caught_stealings: 1,
        batting_average: '.500', on_base_percentage: '.575',
        slugging_percentage: '.875', on_base_plus_slugging: '1.450'
      }
    },
    {
      person: { id: 2, first_name: 'Erika', last_name: 'Musterfrau' },
      league_entry: { id: 12, name: 'B Team', acronym: 'BBB' },
      values: {
        games: 8, plate_appearances: 30, at_bats: 25, runs: 5,
        runs_batted_in: 4, hits: 5, doubles: 1, triples: 0, homeruns: 0,
        strikeouts: 10, base_on_balls: 4, hit_by_pitches: 1, sacrifice_flys: 0,
        stolen_bases: 1, caught_stealings: 0,
        batting_average: '.200', on_base_percentage: '.333',
        slugging_percentage: '.240', on_base_plus_slugging: '.573'
      }
    }
  ],
  pitching: [
    {
      person: { id: 1, first_name: 'Max', last_name: 'Mustermann' },
      league_entry: { id: 11, name: 'A Team', acronym: 'AAA' },
      values: {
        games: 4, games_started: 3, innings_pitched: '12.2', batters_faced: 55,
        runs: 8, earned_runs: 5, hits: 12, homeruns: 1, strikeouts: 15,
        base_on_balls_allowed: 4, hit_by_pitches: 1, wins: 2, losses: 1, saves: 0,
        earned_runs_average: '3.55', walks_and_hits_per_innings_pitched: '1.26'
      }
    }
  ]
};

test('parseInnings converts baseball decimal notation', () => {
  assert.equal(parseInnings('12.0'), 12);
  assert.equal(parseInnings('12.1'), 12 + 1 / 3);
  assert.equal(parseInnings('12.2'), 12 + 2 / 3);
  assert.equal(parseInnings('bad'), 0);
});

test('getPlayerKey includes team entry to avoid collisions', () => {
  assert.equal(getPlayerKey({ person: { id: 9 }, league_entry: { id: 22 } }), '22:9');
});

test('buildBattingRows derives advanced statistics and identity', () => {
  const context = buildLeagueContext(sample);
  const rows = buildBattingRows(sample.batting, context);
  assert.equal(rows[0].name, 'Max Mustermann');
  assert.equal(rows[0].team, 'A Team');
  assert.equal(rows[0].pa, 40);
  assert.equal(rows[0].singles, 9);
  assert.ok(rows[0].woba > rows[1].woba);
  assert.ok(rows[0].opsPlus > 100);
  assert.ok(Number.isFinite(rows[0].war));
});

test('buildPitchingRows interprets IP and derives rates', () => {
  const context = buildLeagueContext(sample);
  const rows = buildPitchingRows(sample.pitching, context);
  assert.equal(rows[0].ipDisplay, '12.2');
  assert.ok(Math.abs(rows[0].ip - (12 + 2 / 3)) < 1e-9);
  assert.ok(rows[0].k9 > rows[0].bb9);
  assert.ok(Number.isFinite(rows[0].fip));
  assert.ok(Number.isFinite(rows[0].eraPlus));
});
