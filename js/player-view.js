import { aggregateBattingRows, aggregatePitchingRows } from './career.js';

export function filterHistoryForSelection(history, selection = 'career') {
  if (selection === 'career') return history;
  const season = Number(selection);
  return history.filter((row) => Number(row.season) === season && row.rowType !== 'career-total');
}

export function selectedTotal(history, selection = 'career') {
  if (selection === 'career') {
    return history.find((row) => row.rowType === 'career-total') ?? null;
  }
  const season = Number(selection);
  return history.find((row) => row.rowType === 'season-total' && Number(row.season) === season) ?? null;
}

export function comparisonAverage(rows, kind) {
  if (!rows?.length) return null;
  return kind === 'pitching' ? aggregatePitchingRows(rows) : aggregateBattingRows(rows);
}

export function comparisonTotals(rows, kind, selection = 'career') {
  const season = selection === 'career' ? null : Number(selection);
  const filtered = season === null ? rows : rows.filter((row) => Number(row.season) === season);
  const aggregate = kind === 'pitching' ? aggregatePitchingRows : aggregateBattingRows;
  const byPlayer = new Map();

  for (const row of filtered) {
    const key = String(row.personId ?? '');
    if (!key) continue;
    if (!byPlayer.has(key)) byPlayer.set(key, []);
    byPlayer.get(key).push(row);
  }

  return [...byPlayer.entries()].map(([personId, playerRows]) => ({
    ...aggregate(playerRows),
    personId: playerRows[0]?.personId ?? personId,
    name: playerRows[0]?.name ?? 'Unbekannter Spieler',
    season: season ?? 'Karriere',
  }));
}
