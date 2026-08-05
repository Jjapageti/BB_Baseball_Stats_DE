import { escapeHtml } from './ui.js';

function normalized(value) {
  return String(value ?? '').trim().toLocaleLowerCase('de-DE');
}

function normalizedAcronym(value) {
  return String(value ?? '').trim().toLocaleUpperCase('de-DE');
}

export function teamLogoUrl(team) {
  return team?.club?.logo_url
    ?? team?.clubs?.find((club) => club?.logo_url)?.logo_url
    ?? team?.team?.clubs?.find((club) => club?.logo_url)?.logo_url
    ?? team?.team?.club?.logo_url
    ?? team?.logo_url
    ?? '';
}

function richness(team) {
  return (teamLogoUrl(team) ? 100 : 0)
    + (team?.club ? 10 : 0)
    + (Array.isArray(team?.clubs) ? team.clubs.length : 0)
    + Object.keys(team ?? {}).length;
}

export function buildTeamCatalog(leaguePayloads = []) {
  const byId = new Map();
  const withoutId = new Map();

  for (const payload of leaguePayloads ?? []) {
    for (const team of payload?.teams ?? []) {
      if (!team || typeof team !== 'object') continue;
      const id = Number(team.id);
      if (Number.isFinite(id)) {
        const current = byId.get(id);
        if (!current || richness(team) > richness(current)) byId.set(id, team);
        continue;
      }
      const key = `${normalized(team.name)}:${normalizedAcronym(team.acronym)}`;
      const current = withoutId.get(key);
      if (!current || richness(team) > richness(current)) withoutId.set(key, team);
    }
  }

  return [...byId.values(), ...withoutId.values()];
}

export function resolveTeam(reference = {}, teams = []) {
  const idCandidates = [
    reference.teamId,
    reference.league_entry_id,
    reference.id,
  ].map(Number).filter(Number.isFinite);

  for (const id of idCandidates) {
    const byId = teams.find((team) => Number(team?.id) === id);
    if (byId) return byId;
  }

  const name = normalized(reference.team ?? reference.name ?? reference.team_name);
  if (name) {
    const byName = teams.find((team) => normalized(team?.name) === name);
    if (byName) return byName;
  }

  const acronym = normalizedAcronym(reference.acronym ?? reference.short_name ?? reference.team_acronym);
  if (acronym) {
    const byAcronym = teams.find((team) => normalizedAcronym(team?.acronym) === acronym);
    if (byAcronym) return byAcronym;
  }

  return null;
}

function displayName(reference = {}, team = null) {
  return String(reference.team ?? reference.name ?? reference.team_name ?? team?.name ?? '–');
}

function displayAcronym(reference = {}, team = null) {
  return String(reference.acronym ?? reference.short_name ?? reference.team_acronym ?? team?.acronym ?? '–');
}

export function renderTeamMark(team, { size = 'sm', className = '' } = {}) {
  const name = String(team?.name ?? team?.team?.name ?? 'Mannschaft');
  const logoUrl = teamLogoUrl(team);
  const letter = name.trim().charAt(0).toLocaleUpperCase('de-DE') || 'B';
  const classes = ['team-mark', `team-mark--${size}`, !logoUrl ? 'team-mark-fallback' : '', className].filter(Boolean).join(' ');
  const fallback = `<span class="team-mark-letter" aria-hidden="true">${escapeHtml(letter)}</span>`;
  const image = logoUrl
    ? `<img class="team-logo" src="${escapeHtml(logoUrl)}" alt="Logo ${escapeHtml(name)}" loading="lazy" decoding="async" onerror="this.remove()">`
    : '';
  return `<span class="${classes}" role="img" aria-label="Mannschaftslogo ${escapeHtml(name)}">${fallback}${image}</span>`;
}

export function renderTeamIdentity(reference = {}, teams = [], {
  size = 'sm',
  showAcronym = true,
  showName = true,
  strongName = false,
  align = 'left',
  className = '',
} = {}) {
  const team = resolveTeam(reference, teams) ?? reference;
  const name = displayName(reference, team);
  const acronym = displayAcronym(reference, team);
  const classes = ['team-identity', `team-identity--${align}`, className].filter(Boolean).join(' ');
  const nameHtml = strongName ? `<strong>${escapeHtml(name)}</strong>` : `<span class="team-name">${escapeHtml(name)}</span>`;
  return `<span class="${classes}">${showAcronym ? `<span class="team-chip">${escapeHtml(acronym)}</span>` : ''}${renderTeamMark({ ...team, name }, { size })}${showName ? nameHtml : ''}</span>`;
}

function nestedMatchTeam(match, side) {
  const entry = match?.[`${side}_league_entry`] ?? {};
  const nested = entry?.team ?? {};
  const clubs = nested?.clubs ?? (nested?.club ? [nested.club] : []);
  const club = clubs.find((item) => item?.logo_url) ?? clubs[0] ?? null;
  return {
    id: entry?.id,
    name: match?.[`${side}_team_name`] ?? nested?.name ?? '–',
    acronym: nested?.short_name ?? nested?.acronym ?? club?.acronym ?? '–',
    club,
    clubs,
  };
}

export function renderMatchTeamIdentity(match, side, teams = [], options = {}) {
  const nested = nestedMatchTeam(match, side);
  const resolved = resolveTeam({ teamId: nested.id, team: nested.name, acronym: nested.acronym }, teams);
  const team = resolved ?? nested;
  return renderTeamIdentity(
    { teamId: team?.id, team: nested.name, acronym: nested.acronym },
    [team],
    { size: 'xs', showAcronym: true, strongName: false, ...options },
  );
}
