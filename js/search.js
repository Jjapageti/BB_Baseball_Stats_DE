import { renderTeamMark, resolveTeam } from './team.js';
import { escapeHtml } from './ui.js';

function normalized(value) {
  return String(value ?? '').trim().toLocaleLowerCase('de-DE');
}

function personName(person = {}) {
  return [person.first_name, person.last_name].filter(Boolean).join(' ').trim()
    || person.full_name
    || person.name
    || 'Unbekannter Spieler';
}

export function buildGlobalSearchIndex(allLeagueData = []) {
  const teams = new Map();
  const players = new Map();

  for (const data of allLeagueData ?? []) {
    const season = Number(data?.selectedSeason ?? data?.league?.season);
    const leagueKey = String(data?.selectedLeagueKey ?? data?.league?.key ?? '');
    const leagueName = String(data?.league?.name ?? 'Liga');

    for (const team of data?.teams ?? []) {
      const teamId = Number(team?.id);
      if (!Number.isFinite(teamId) || !leagueKey) continue;
      const key = `team:${season}:${leagueKey}:${teamId}`;
      teams.set(key, {
        type: 'team', key, teamId, season, leagueKey, leagueName,
        name: String(team?.name ?? 'Mannschaft'),
        acronym: String(team?.acronym ?? '–'),
        team,
      });
    }

    for (const record of [...(data?.batting ?? []), ...(data?.pitching ?? [])]) {
      const personId = record?.person?.id;
      if (personId === undefined || personId === null) continue;
      const entry = record?.league_entry ?? {};
      const candidate = {
        type: 'player',
        key: `player:${personId}`,
        personId,
        name: personName(record.person),
        team: String(entry.name ?? '–'),
        acronym: String(entry.acronym ?? '–'),
        teamId: entry.id,
        season,
        leagueKey,
        leagueName,
        teamObject: resolveTeam({ teamId: entry.id, team: entry.name, acronym: entry.acronym }, data?.teams ?? []),
      };
      const current = players.get(candidate.key);
      if (!current || Number(candidate.season) > Number(current.season)) players.set(candidate.key, candidate);
    }
  }

  return [...players.values(), ...teams.values()];
}

function scoreResult(result, query) {
  const name = normalized(result.name);
  const acronym = normalized(result.acronym);
  const team = normalized(result.team);
  if (name === query) return 0;
  if (result.type === 'team' && acronym === query) return 0;
  if (name.startsWith(query)) return 1;
  if (result.type === 'team' && acronym.startsWith(query)) return 1;
  if (result.type === 'player' && team.startsWith(query)) return 2;
  if (name.includes(query)) return 3;
  if (result.type === 'team' && acronym.includes(query)) return 3;
  if (result.type === 'player' && (team.includes(query) || acronym.includes(query))) return 4;
  if (normalized(result.leagueName).includes(query)) return 5;
  return Number.POSITIVE_INFINITY;
}

export function filterGlobalSearch(index, query, limit = 10) {
  const normalizedQuery = normalized(query);
  if (!normalizedQuery) return [];
  return (index ?? [])
    .map((result) => ({ result, score: scoreResult(result, normalizedQuery) }))
    .filter(({ score }) => Number.isFinite(score))
    .sort((a, b) => a.score - b.score
      || (a.result.type === b.result.type ? 0 : a.result.type === 'player' ? -1 : 1)
      || a.result.name.localeCompare(b.result.name, 'de'))
    .slice(0, limit)
    .map(({ result }) => result);
}

export function globalSearchResultUrl(result) {
  if (result?.type === 'player') {
    return `player.html?${new URLSearchParams({ id: String(result.personId) }).toString()}`;
  }
  const params = new URLSearchParams({
    season: String(result?.season ?? ''),
    league: String(result?.leagueKey ?? ''),
    team: String(result?.teamId ?? ''),
  });
  return `dashboard.html?${params.toString()}`;
}

function resultMark(result) {
  if (result.type === 'team') return renderTeamMark(result.team, { size: 'sm' });
  return renderTeamMark(result.teamObject ?? { name: result.team }, { size: 'sm' });
}

function resultHtml(result, index) {
  const typeLabel = result.type === 'player' ? 'Spieler' : 'Mannschaft';
  const meta = result.type === 'player'
    ? `${result.team} · zuletzt ${result.season}`
    : `${result.acronym} · ${result.leagueName} ${result.season}`;
  return `<a class="global-search-result" role="option" id="global-search-option-${index}" href="${escapeHtml(globalSearchResultUrl(result))}">
    ${resultMark(result)}
    <span><strong>${escapeHtml(result.name)}</strong><small>${escapeHtml(typeLabel)} · ${escapeHtml(meta)}</small></span>
  </a>`;
}

export function initGlobalSearch(allLeagueData = []) {
  const root = typeof document !== 'undefined' ? document.getElementById('globalSearch') : null;
  if (!root) return;
  const input = root.querySelector('input');
  const panel = root.querySelector('[data-search-results]');
  const index = buildGlobalSearchIndex(allLeagueData);
  let activeIndex = -1;
  let current = [];

  const close = () => {
    panel.hidden = true;
    panel.innerHTML = '';
    activeIndex = -1;
    input.setAttribute('aria-expanded', 'false');
  };

  const draw = () => {
    current = filterGlobalSearch(index, input.value, 10);
    activeIndex = -1;
    if (!input.value.trim()) {
      close();
      return;
    }
    panel.innerHTML = current.length
      ? current.map(resultHtml).join('')
      : '<div class="global-search-empty">Keine Treffer gefunden.</div>';
    panel.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  const setActive = (nextIndex) => {
    const options = [...panel.querySelectorAll('.global-search-result')];
    if (!options.length) return;
    activeIndex = (nextIndex + options.length) % options.length;
    options.forEach((option, indexValue) => option.classList.toggle('active', indexValue === activeIndex));
    input.setAttribute('aria-activedescendant', options[activeIndex].id);
  };

  input.addEventListener('input', draw);
  input.addEventListener('focus', draw);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive(activeIndex + 1); }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive(activeIndex - 1); }
    if (event.key === 'Escape') close();
    if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      window.location.href = globalSearchResultUrl(current[activeIndex]);
    }
  });
  document.addEventListener('click', (event) => {
    if (!root.contains(event.target)) close();
  });
}
