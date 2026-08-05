function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + number(row?.[key]), 0);
}

function weighted(rows, key, weightKey) {
  const denominator = sum(rows, weightKey);
  return denominator > 0
    ? rows.reduce((total, row) => total + number(row?.[key]) * number(row?.[weightKey]), 0) / denominator
    : 0;
}

function uniqueText(rows, key) {
  return [...new Set(rows.map((row) => String(row?.[key] ?? '').trim()).filter(Boolean))].join(' / ');
}

export function formatInnings(ip) {
  const outs = Math.max(0, Math.round(number(ip) * 3));
  return `${Math.floor(outs / 3)}.${outs % 3}`;
}

export function aggregateBattingRows(rows) {
  const ab = sum(rows, 'ab');
  const hits = sum(rows, 'hits');
  const doubles = sum(rows, 'doubles');
  const triples = sum(rows, 'triples');
  const hr = sum(rows, 'hr');
  const bb = sum(rows, 'bb');
  const hbp = sum(rows, 'hbp');
  const sf = sum(rows, 'sf');
  const pa = sum(rows, 'pa');
  const so = sum(rows, 'so');
  const totalBases = Math.max(0, hits - doubles - triples - hr) + 2 * doubles + 3 * triples + 4 * hr;
  const obpDenominator = ab + bb + hbp + sf;
  const avg = ab > 0 ? hits / ab : 0;
  const obp = obpDenominator > 0 ? (hits + bb + hbp) / obpDenominator : 0;
  const slg = ab > 0 ? totalBases / ab : 0;
  return {
    games: sum(rows, 'games'), pa, ab,
    runs: sum(rows, 'runs'), rbi: sum(rows, 'rbi'), hits,
    singles: Math.max(0, hits - doubles - triples - hr), doubles, triples, hr,
    bb, hbp, sf, so, sb: sum(rows, 'sb'), cs: sum(rows, 'cs'),
    avg, obp, slg, ops: obp + slg, iso: slg - avg,
    bbPct: pa > 0 ? bb / pa : 0,
    kPct: pa > 0 ? so / pa : 0,
    woba: weighted(rows, 'woba', 'pa'),
    opsPlus: weighted(rows, 'opsPlus', 'pa'),
    wrcPlus: weighted(rows, 'wrcPlus', 'pa'),
    war: sum(rows, 'war'),
    team: uniqueText(rows, 'team'), acronym: uniqueText(rows, 'acronym'),
  };
}

export function aggregatePitchingRows(rows) {
  const ip = sum(rows, 'ip');
  const er = sum(rows, 'er');
  const hits = sum(rows, 'hits');
  const bb = sum(rows, 'bb');
  const hr = sum(rows, 'hr');
  const so = sum(rows, 'so');
  return {
    games: sum(rows, 'games'), gamesStarted: sum(rows, 'gamesStarted'),
    completeGames: sum(rows, 'completeGames'), ip, ipDisplay: formatInnings(ip),
    battersFaced: sum(rows, 'battersFaced'), runs: sum(rows, 'runs'), er, hits, hr, bb,
    hbp: sum(rows, 'hbp'), so, wins: sum(rows, 'wins'), losses: sum(rows, 'losses'), saves: sum(rows, 'saves'),
    era: ip > 0 ? er * 9 / ip : 0,
    whip: ip > 0 ? (hits + bb) / ip : 0,
    fip: weighted(rows, 'fip', 'ip'),
    k9: ip > 0 ? so * 9 / ip : 0,
    bb9: ip > 0 ? bb * 9 / ip : 0,
    hr9: ip > 0 ? hr * 9 / ip : 0,
    kbb: bb > 0 ? so / bb : so,
    eraPlus: weighted(rows, 'eraPlus', 'ip'),
    fipMinus: weighted(rows, 'fipMinus', 'ip'),
    war: sum(rows, 'war'),
    team: uniqueText(rows, 'team'), acronym: uniqueText(rows, 'acronym'),
  };
}

function buildHistory(rows, aggregate) {
  if (!rows.length) return [];
  const bySeason = new Map();
  for (const row of rows) {
    const season = Number(row.season);
    if (!bySeason.has(season)) bySeason.set(season, []);
    bySeason.get(season).push(row);
  }
  const output = [];
  for (const season of [...bySeason.keys()].sort((a, b) => b - a)) {
    const seasonRows = bySeason.get(season).sort((a, b) => String(a.leagueName).localeCompare(String(b.leagueName), 'de'));
    output.push(...seasonRows.map((row) => ({ ...row, rowType: 'league' })));
    output.push({
      ...aggregate(seasonRows),
      season,
      leagueName: 'Gesamt',
      leagueKey: `season-total-${season}`,
      rowType: 'season-total',
    });
  }
  output.push({
    ...aggregate(rows),
    season: 'Karriere',
    leagueName: 'Gesamt',
    leagueKey: 'career-total',
    rowType: 'career-total',
  });
  return output;
}

export function buildBattingHistory(rows) {
  return buildHistory(rows, aggregateBattingRows);
}

export function buildPitchingHistory(rows) {
  return buildHistory(rows, aggregatePitchingRows);
}
