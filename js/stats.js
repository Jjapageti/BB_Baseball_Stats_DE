const W = Object.freeze({
  BB: 0.69,
  HBP: 0.72,
  SINGLE: 0.89,
  DOUBLE: 1.27,
  TRIPLE: 1.62,
  HR: 2.10,
});

export function toNumber(value, fallback = 0) {
  if (value === null || value === undefined || value === '') return fallback;
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : fallback;
}

export function clamp(value, min = 0, max = 100) {
  return Math.min(max, Math.max(min, value));
}

export function parseInnings(value) {
  const match = String(value ?? '').trim().match(/^(\d+)(?:\.(\d))?$/);
  if (!match) return 0;
  const whole = Number(match[1]);
  const outs = Number(match[2] ?? 0);
  if (outs === 1) return whole + 1 / 3;
  if (outs === 2) return whole + 2 / 3;
  return whole;
}

export function playerName(person = {}) {
  return [person.name_prefix, person.first_name, person.last_name, person.name_suffix]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim() || 'Unbekannter Spieler';
}

export function getPlayerKey(record) {
  return `${record?.league_entry?.id ?? 'no-team'}:${record?.person?.id ?? 'no-person'}`;
}

function batterParts(record) {
  const v = record?.values ?? {};
  const ab = toNumber(v.at_bats);
  const hits = toNumber(v.hits);
  const doubles = toNumber(v.doubles);
  const triples = toNumber(v.triples);
  const hr = toNumber(v.homeruns);
  const bb = toNumber(v.base_on_balls);
  const hbp = toNumber(v.hit_by_pitches);
  const sf = toNumber(v.sacrifice_flys);
  const pa = toNumber(v.plate_appearances, ab + bb + hbp + sf);
  const singles = Math.max(0, hits - doubles - triples - hr);
  const wobaNumerator = W.BB * bb + W.HBP * hbp + W.SINGLE * singles
    + W.DOUBLE * doubles + W.TRIPLE * triples + W.HR * hr;
  const wobaDenominator = ab + bb + hbp + sf;
  return { v, ab, hits, doubles, triples, hr, bb, hbp, sf, pa, singles, wobaNumerator, wobaDenominator };
}

export function buildLeagueContext(data) {
  const batting = data?.batting ?? [];
  const pitching = data?.pitching ?? [];
  let totalPA = 0;
  let totalRuns = 0;
  let opsWeighted = 0;
  let opsWeight = 0;
  let wobaNumerator = 0;
  let wobaDenominator = 0;

  for (const record of batting) {
    const p = batterParts(record);
    const ops = toNumber(p.v.on_base_plus_slugging, NaN);
    totalPA += p.pa;
    totalRuns += toNumber(p.v.runs);
    wobaNumerator += p.wobaNumerator;
    wobaDenominator += p.wobaDenominator;
    if (Number.isFinite(ops) && p.pa > 0) {
      opsWeighted += ops * p.pa;
      opsWeight += p.pa;
    }
  }

  let totalIP = 0;
  let totalER = 0;
  let totalR = 0;
  let totalHR = 0;
  let totalBB = 0;
  let totalHBP = 0;
  let totalSO = 0;
  for (const record of pitching) {
    const v = record?.values ?? {};
    totalIP += parseInnings(v.innings_pitched);
    totalER += toNumber(v.earned_runs);
    totalR += toNumber(v.runs);
    totalHR += toNumber(v.homeruns);
    totalBB += toNumber(v.base_on_balls_allowed);
    totalHBP += toNumber(v.hit_by_pitches);
    totalSO += toNumber(v.strikeouts);
  }

  const lgERA = totalIP > 0 ? (totalER * 9) / totalIP : 0;
  const rawFIP = totalIP > 0
    ? (13 * totalHR + 3 * (totalBB + totalHBP) - 2 * totalSO) / totalIP
    : 0;
  const fipConstant = lgERA - rawFIP;
  const lgFIP = rawFIP + fipConstant;
  const avgTeamGames = data?.standings?.length
    ? data.standings.reduce((sum, row) => sum + toNumber(row.games), 0) / data.standings.length
    : 0;

  return {
    season: data?.league?.season ?? '',
    leagueName: data?.league?.name ?? '',
    leagueKey: data?.league?.key ?? '',
    lgOPS: opsWeight > 0 ? opsWeighted / opsWeight : 0,
    lgWoba: wobaDenominator > 0 ? wobaNumerator / wobaDenominator : 0,
    lgRunsPerPA: totalPA > 0 ? totalRuns / totalPA : 0,
    lgERA,
    lgR9: totalIP > 0 ? (totalR * 9) / totalIP : 0,
    fipConstant,
    lgFIP,
    replacementFIP: lgFIP + 1.0,
    avgTeamGames,
    minPA: Math.max(10, Math.floor(avgTeamGames * 2.7)),
    minIP: Math.max(3, Math.floor(avgTeamGames)),
  };
}

export function buildBattingRows(records, context) {
  return (records ?? []).map((record) => {
    const p = batterParts(record);
    const v = p.v;
    const avg = toNumber(v.batting_average, p.ab > 0 ? p.hits / p.ab : 0);
    const obp = toNumber(v.on_base_percentage);
    const slg = toNumber(v.slugging_percentage);
    const ops = toNumber(v.on_base_plus_slugging, obp + slg);
    const woba = p.wobaDenominator > 0 ? p.wobaNumerator / p.wobaDenominator : 0;
    const opsPlus = context.lgOPS > 0 ? (ops / context.lgOPS) * 100 : 0;
    const wrcPlus = context.lgWoba > 0 ? (woba / context.lgWoba) * 100 : 0;
    const battingRuns = context.lgRunsPerPA > 0
      ? ((wrcPlus - 100) / 100) * context.lgRunsPerPA * p.pa
      : 0;
    const replacementRuns = 20 * (p.pa / 600);
    const war = (battingRuns + replacementRuns) / 10;
    const entry = record?.league_entry ?? {};
    const person = record?.person ?? {};

    return {
      key: getPlayerKey(record),
      personId: person.id,
      season: context.season,
      leagueName: context.leagueName,
      leagueKey: context.leagueKey,
      teamId: entry.id,
      name: playerName(person),
      team: entry.name ?? '-',
      acronym: entry.acronym ?? '-',
      games: toNumber(v.games),
      pa: p.pa,
      ab: p.ab,
      runs: toNumber(v.runs),
      rbi: toNumber(v.runs_batted_in),
      hits: p.hits,
      singles: p.singles,
      doubles: p.doubles,
      triples: p.triples,
      hr: p.hr,
      bb: p.bb,
      hbp: p.hbp,
      sf: p.sf,
      so: toNumber(v.strikeouts),
      sb: toNumber(v.stolen_bases),
      cs: toNumber(v.caught_stealings),
      avg,
      obp,
      slg,
      ops,
      iso: slg - avg,
      bbPct: p.pa > 0 ? p.bb / p.pa : 0,
      kPct: p.pa > 0 ? toNumber(v.strikeouts) / p.pa : 0,
      woba,
      opsPlus,
      wrcPlus,
      war,
      qualified: p.pa >= context.minPA,
      raw: record,
    };
  });
}

export function buildPitchingRows(records, context) {
  return (records ?? []).map((record) => {
    const v = record?.values ?? {};
    const ip = parseInnings(v.innings_pitched);
    const er = toNumber(v.earned_runs);
    const hits = toNumber(v.hits);
    const hr = toNumber(v.homeruns);
    const bb = toNumber(v.base_on_balls_allowed);
    const hbp = toNumber(v.hit_by_pitches);
    const so = toNumber(v.strikeouts);
    const era = toNumber(v.earned_runs_average, ip > 0 ? (er * 9) / ip : 0);
    const whip = toNumber(v.walks_and_hits_per_innings_pitched, ip > 0 ? (hits + bb) / ip : 0);
    const fip = ip > 0
      ? (13 * hr + 3 * (bb + hbp) - 2 * so) / ip + context.fipConstant
      : 0;
    const eraPlus = ip > 0 && era === 0
      ? 999
      : era > 0 && context.lgERA > 0 ? (context.lgERA / era) * 100 : 0;
    const fipMinus = context.lgFIP > 0 ? (fip / context.lgFIP) * 100 : 0;
    const war = ip > 0 ? ((context.replacementFIP - fip) * ip / 9) / 10 : 0;
    const entry = record?.league_entry ?? {};
    const person = record?.person ?? {};

    return {
      key: getPlayerKey(record),
      personId: person.id,
      season: context.season,
      leagueName: context.leagueName,
      leagueKey: context.leagueKey,
      teamId: entry.id,
      name: playerName(person),
      team: entry.name ?? '-',
      acronym: entry.acronym ?? '-',
      games: toNumber(v.games),
      gamesStarted: toNumber(v.games_started),
      completeGames: toNumber(v.complete_games),
      ipDisplay: String(v.innings_pitched ?? '0.0'),
      ip,
      battersFaced: toNumber(v.batters_faced),
      runs: toNumber(v.runs),
      er,
      hits,
      hr,
      bb,
      hbp,
      so,
      wins: toNumber(v.wins),
      losses: toNumber(v.losses),
      saves: toNumber(v.saves),
      era,
      whip,
      fip,
      k9: ip > 0 ? (so * 9) / ip : 0,
      bb9: ip > 0 ? (bb * 9) / ip : 0,
      hr9: ip > 0 ? (hr * 9) / ip : 0,
      kbb: bb > 0 ? so / bb : so,
      eraPlus,
      fipMinus,
      war,
      qualified: ip >= context.minIP,
      raw: record,
    };
  });
}

export function buildCombinedWar(battingRows, pitchingRows) {
  const map = new Map();
  const add = (row, kind) => {
    const existing = map.get(row.key) ?? {
      key: row.key,
      personId: row.personId,
      teamId: row.teamId,
      name: row.name,
      team: row.team,
      acronym: row.acronym,
      battingWar: 0,
      pitchingWar: 0,
    };
    existing[kind] += row.war;
    map.set(row.key, existing);
  };
  battingRows.forEach((row) => add(row, 'battingWar'));
  pitchingRows.forEach((row) => add(row, 'pitchingWar'));
  return [...map.values()]
    .map((row) => ({ ...row, war: row.battingWar + row.pitchingWar }))
    .sort((a, b) => b.war - a.war);
}

export function percentile(value, rows, getter, higherIsBetter = true) {
  const valid = rows.map(getter).filter(Number.isFinite).sort((a, b) => a - b);
  if (!valid.length || !Number.isFinite(value)) return null;
  const below = valid.filter((item) => item < value).length;
  const equal = valid.filter((item) => item === value).length;
  const raw = ((below + equal * 0.5) / valid.length) * 100;
  return clamp(higherIsBetter ? raw : 100 - raw, 1, 99);
}

export function getPlayerRecords(data, personId, teamId) {
  const match = (record) => String(record?.person?.id) === String(personId)
    && (teamId === undefined || teamId === null || String(record?.league_entry?.id) === String(teamId));
  return {
    batting: (data?.batting ?? []).find(match) ?? null,
    pitching: (data?.pitching ?? []).find(match) ?? null,
  };
}
