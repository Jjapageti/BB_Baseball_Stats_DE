const SEASONS = Object.freeze([2026, 2025, 2024, 2023]);
const STORAGE_KEY = 'bbStats.selection.v2';

let seasonPayloadCache = null;
let catalogCache = null;
const leagueDataCache = new Map();

function asSeason(value) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? number : null;
}

function leagueAcronym(league) {
  const acronyms = (league?.source_groups ?? [])
    .map((group) => String(group?.acronym ?? '').trim())
    .filter(Boolean);
  return [...new Set(acronyms)].join('+') || String(league?.level ?? 'Liga').toUpperCase();
}

export function validateSeasonShape(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('Die Saisondatei ist kein JSON-Objekt.');
  if (asSeason(payload.season) === null) throw new Error('In der Saisondatei fehlt „season“.');
  if (!Array.isArray(payload.leagues) || !payload.leagues.length) {
    throw new Error('In der Saisondatei sind keine Ligen enthalten.');
  }
  for (const league of payload.leagues) validateLeagueShape(league);
  return true;
}

export function validateLeagueShape(league) {
  if (!league || typeof league !== 'object') throw new Error('Eine Liga ist kein Objekt.');
  if (!league.key) throw new Error('Eine Liga besitzt keinen key.');
  for (const key of ['teams', 'matches', 'standings', 'batting', 'pitching']) {
    if (!Array.isArray(league[key])) throw new Error(`In ${league.key} fehlt das Array „${key}“.`);
  }
  return true;
}

export function validateDataShape(data) {
  if (!data || typeof data !== 'object') throw new Error('Die oberste JSON-Ebene ist kein Objekt.');
  if (!data.league || typeof data.league !== 'object') throw new Error('Die Liga-Informationen fehlen.');
  for (const key of ['teams', 'matches', 'standings', 'batting', 'pitching']) {
    if (!Array.isArray(data[key])) throw new Error(`Das Array „${key}“ fehlt.`);
  }
  return true;
}

export function normalizeData(data) {
  validateDataShape(data);
  return {
    ...data,
    league: { ...data.league },
    teams: [...data.teams],
    matches: [...data.matches],
    standings: [...data.standings],
    batting: [...data.batting],
    pitching: [...data.pitching],
    counts: {
      teams: data.counts?.teams ?? data.teams.length,
      matches: data.counts?.matches ?? data.matches.length,
      played_matches: data.counts?.played_matches
        ?? data.matches.filter((match) => ['played', 'manually_valued'].includes(match.state)).length,
      batters: data.counts?.batters ?? data.batting.length,
      pitchers: data.counts?.pitchers ?? data.pitching.length,
    },
  };
}

export function normalizeLeagueData(seasonPayload, leaguePayload, catalog = null) {
  validateSeasonShape(seasonPayload);
  validateLeagueShape(leaguePayload);
  const season = asSeason(seasonPayload.season);
  const acronym = leagueAcronym(leaguePayload);
  const normalized = normalizeData({
    ...leaguePayload,
    generated_at: seasonPayload.generated_at,
    target_club: seasonPayload.target_club,
    season_counts: seasonPayload.counts,
    league: {
      key: leaguePayload.key,
      id: leaguePayload.source_groups?.[0]?.id ?? null,
      name: leaguePayload.name,
      acronym,
      season,
      level: leaguePayload.level,
      stage: leaguePayload.stage,
      merged: Boolean(leaguePayload.merged),
      source_groups: [...(leaguePayload.source_groups ?? [])],
    },
  });
  return {
    ...normalized,
    catalog,
    seasonPayload,
    selectedSeason: season,
    selectedLeagueKey: leaguePayload.key,
    leagueConfig: {
      key: leaguePayload.key,
      name: leaguePayload.name,
      acronym,
      season,
      level: leaguePayload.level,
      stage: leaguePayload.stage,
      description: `${leaguePayload.name} · Saison ${season}${leaguePayload.stage === 'postseason' ? ' · Postseason' : ''}`,
    },
  };
}

export function buildSeasonCatalog(payloads) {
  const seasons = payloads.map((payload) => {
    validateSeasonShape(payload);
    return {
      season: asSeason(payload.season),
      generatedAt: payload.generated_at ?? null,
      targetClub: payload.target_club ?? null,
      counts: payload.counts ?? {},
      leagues: payload.leagues.map((league) => ({
        key: league.key,
        name: league.name,
        acronym: leagueAcronym(league),
        season: asSeason(payload.season),
        level: league.level,
        stage: league.stage,
        merged: Boolean(league.merged),
        sourceGroups: [...(league.source_groups ?? [])],
      })),
      payload,
    };
  }).sort((a, b) => b.season - a.season);

  if (!seasons.length) throw new Error('Keine Saisondateien wurden geladen.');
  return {
    seasons,
    defaultSeason: seasons[0].season,
    defaultLeagueKey: seasons[0].leagues[0]?.key ?? null,
  };
}

function findSeason(catalog, season) {
  return catalog.seasons.find((row) => row.season === asSeason(season)) ?? null;
}

function firstLeagueKey(seasonRow) {
  return seasonRow?.leagues?.[0]?.key ?? null;
}

export function resolveSelection(catalog, search = '', storedSelection = null) {
  const params = new URLSearchParams(String(search).replace(/^\?/, ''));
  const querySeason = asSeason(params.get('season'));
  const storedSeason = asSeason(storedSelection?.season);
  const seasonRow = findSeason(catalog, querySeason)
    ?? findSeason(catalog, storedSeason)
    ?? findSeason(catalog, catalog.defaultSeason)
    ?? catalog.seasons[0];

  const queryLeague = params.get('league');
  const storedLeague = storedSelection?.leagueKey;
  const validKeys = new Set(seasonRow.leagues.map((league) => league.key));
  const leagueKey = validKeys.has(queryLeague)
    ? queryLeague
    : validKeys.has(storedLeague)
      ? storedLeague
      : firstLeagueKey(seasonRow);
  return { season: seasonRow.season, leagueKey };
}

export function buildSelectionUrl(currentUrl, selection) {
  const source = String(currentUrl || 'dashboard.html');
  const hashIndex = source.indexOf('#');
  const hash = hashIndex >= 0 ? source.slice(hashIndex) : '';
  const withoutHash = hashIndex >= 0 ? source.slice(0, hashIndex) : source;
  const queryIndex = withoutHash.indexOf('?');
  const path = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  const params = new URLSearchParams(queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : '');
  params.set('season', String(selection.season));
  params.set('league', String(selection.leagueKey));
  return `${path || 'dashboard.html'}?${params.toString()}${hash}`;
}

export function buildLeagueUrl(currentUrl, leagueKey, season = null) {
  const resolvedSeason = season ?? new URLSearchParams(
    String(currentUrl).includes('?') ? String(currentUrl).split('?')[1] : ''
  ).get('season') ?? SEASONS[0];
  return buildSelectionUrl(currentUrl, { season: resolvedSeason, leagueKey });
}

function runtimeSearch() {
  return typeof window !== 'undefined' ? window.location.search : '';
}

function runtimeStoredSelection() {
  if (typeof window === 'undefined' || !window.localStorage) return null;
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    return null;
  }
}

export function persistSelection(selection) {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
  } catch {
    // URL parameters remain authoritative when storage is unavailable.
  }
}

export function persistLeagueKey(_catalog, leagueKey) {
  const current = runtimeStoredSelection() ?? {};
  persistSelection({ season: current.season ?? SEASONS[0], leagueKey });
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export async function loadSeasonPayloads({ force = false } = {}) {
  if (seasonPayloadCache && !force) return seasonPayloadCache;
  const results = await Promise.all(SEASONS.map(async (season) => {
    const url = `./data/seasons/${season}.json`;
    const payload = await fetchJson(url);
    validateSeasonShape(payload);
    return payload;
  }));
  seasonPayloadCache = results;
  catalogCache = buildSeasonCatalog(results);
  if (force) leagueDataCache.clear();
  return seasonPayloadCache;
}

export async function loadSeasonCatalog({ force = false } = {}) {
  if (catalogCache && !force) return catalogCache;
  await loadSeasonPayloads({ force });
  return catalogCache;
}

export const loadLeagueCatalog = loadSeasonCatalog;

export async function loadData({ season = null, leagueKey = null, force = false } = {}) {
  const catalog = await loadSeasonCatalog({ force });
  const resolved = season !== null || leagueKey !== null
    ? resolveSelection(catalog, `?season=${season ?? ''}&league=${leagueKey ?? ''}`, runtimeStoredSelection())
    : resolveSelection(catalog, runtimeSearch(), runtimeStoredSelection());
  persistSelection(resolved);

  const cacheKey = `${resolved.season}:${resolved.leagueKey}`;
  if (leagueDataCache.has(cacheKey) && !force) return leagueDataCache.get(cacheKey);

  const seasonRow = findSeason(catalog, resolved.season);
  const league = seasonRow?.payload?.leagues?.find((row) => row.key === resolved.leagueKey);
  if (!seasonRow || !league) throw new Error('Die gewählte Saison oder Liga wurde nicht gefunden.');
  const result = normalizeLeagueData(seasonRow.payload, league, catalog);
  leagueDataCache.set(cacheKey, result);
  return result;
}

export async function loadAllData({ force = false } = {}) {
  const catalog = await loadSeasonCatalog({ force });
  return catalog.seasons.flatMap((seasonRow) => seasonRow.payload.leagues.map((league) => {
    const cacheKey = `${seasonRow.season}:${league.key}`;
    if (!leagueDataCache.has(cacheKey) || force) {
      leagueDataCache.set(cacheKey, normalizeLeagueData(seasonRow.payload, league, catalog));
    }
    return leagueDataCache.get(cacheKey);
  }));
}

export function resolveLeagueKey(catalog, search = '', storedKey = null) {
  const seasonCatalog = catalog.seasons ? catalog : {
    seasons: [{ season: SEASONS[0], leagues: catalog.leagues ?? [] }],
    defaultSeason: SEASONS[0],
    defaultLeagueKey: catalog.defaultLeague,
  };
  return resolveSelection(seasonCatalog, search, { season: SEASONS[0], leagueKey: storedKey }).leagueKey;
}

export function getLeagueConfig(catalog, leagueKey, season = null) {
  const seasonRow = findSeason(catalog, season ?? catalog.defaultSeason) ?? catalog.seasons[0];
  return seasonRow.leagues.find((league) => league.key === leagueKey) ?? seasonRow.leagues[0];
}

export { SEASONS as AVAILABLE_SEASONS };
