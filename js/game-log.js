function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function asNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function timeSortValue(value) {
  const match = String(value ?? '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}):(\d{2}))?/);
  if (!match) return 0;
  const [, y, m, d, hh = '00', mm = '00', ss = '00'] = match;
  return Number(`${y}${m}${d}${hh}${mm}${ss}`);
}

function roleRows(kind, logs) {
  return (logs ?? []).filter((row) => kind === 'batting' ? Boolean(row?.batting) : Boolean(row?.pitching));
}

function normalizedSeason(value) {
  const season = Number(value);
  return Number.isInteger(season) && season >= 1900 && season <= 2200 ? season : null;
}

function seasonFromTime(value) {
  const match = String(value ?? '').match(/^(\d{4})-/);
  return match ? Number(match[1]) : null;
}

export function gameLogUrl(season) {
  const year = normalizedSeason(season);
  if (!year) throw new TypeError(`Ungültige Spielzeit: ${season}`);
  return new URL(`../data/game_logs/${year}.json`, import.meta.url);
}

// Backward-compatible helper: the tab is now part of the permanent player UI.
export function shouldShowGameLog() {
  return true;
}

export function recordTabsHtml({
  hasBatting,
  hasPitching,
  selection,
  activeTab,
}) {
  const tabs = [];

  if (hasBatting) {
    tabs.push(
      `<button type="button" data-tab="batting" class="${activeTab === 'batting' ? 'active' : ''}">Schlagstatistik</button>`,
    );
  }

  if (hasPitching) {
    tabs.push(
      `<button type="button" data-tab="pitching" class="${activeTab === 'pitching' ? 'active' : ''}">Wurfstatistik</button>`,
    );
  }

  tabs.push(
    `<button type="button" data-tab="gamelog" class="${activeTab === 'gamelog' ? 'active' : ''}">Spielprotokoll</button>`,
  );

  return tabs.join('');
}

export function selectPlayerGameLogs(data, personId) {
  const id = String(personId ?? '');
  if (!id) return [];

  return (data?.game_logs ?? [])
    .filter((row) => String(row?.person_id ?? '') === id)
    .sort((a, b) => {
      const timeDiff = timeSortValue(b?.time) - timeSortValue(a?.time);
      if (timeDiff) return timeDiff;
      return asNumber(b?.match_id) - asNumber(a?.match_id);
    });
}

async function loadSeasonGameLogs(season, personId, fetchImpl) {
  const response = await fetchImpl(gameLogUrl(season));

  if (response.status === 404) {
    return { season, available: false, logs: [] };
  }
  if (!response.ok) {
    throw new Error(`Spielprotokolle ${season} konnten nicht geladen werden (${response.status}).`);
  }

  const data = await response.json();
  return {
    season,
    available: true,
    logs: selectPlayerGameLogs(data, personId),
  };
}

export async function loadPlayerGameLogsForSelection(
  selection,
  personId,
  seasons,
  fetchImpl = fetch,
) {
  const requestedSeasons = selection === 'career'
    ? [...new Set((seasons ?? []).map(normalizedSeason).filter(Boolean))].sort((a, b) => a - b)
    : [normalizedSeason(selection)].filter(Boolean);

  const loaded = await Promise.all(
    requestedSeasons.map((season) => loadSeasonGameLogs(season, personId, fetchImpl)),
  );

  const availableSeasons = loaded.filter((item) => item.available).map((item) => item.season);
  const missingSeasons = loaded.filter((item) => !item.available).map((item) => item.season);
  const logs = loaded
    .flatMap((item) => item.logs)
    .sort((a, b) => {
      const timeDiff = timeSortValue(b?.time) - timeSortValue(a?.time);
      if (timeDiff) return timeDiff;
      return asNumber(b?.match_id) - asNumber(a?.match_id);
    });

  return {
    selection,
    logs,
    availableSeasons,
    missingSeasons,
  };
}

export function formatGameDate(value) {
  const match = String(value ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return '–';
  const [, year, month, day] = match;
  return `${day}.${month}.${year}`;
}

export function opponentName(row) {
  const team = String(row?.boxscore_team ?? '').trim();
  const home = String(row?.home_team ?? '').trim();
  const away = String(row?.away_team ?? '').trim();

  if (team && home && team === home) return away || '–';
  if (team && away && team === away) return home || '–';

  if (home && away) return `${home} / ${away}`;
  return away || home || '–';
}

export function positionText(row) {
  const positions = Array.isArray(row?.position_sequence) ? row.position_sequence : [];
  return positions.length ? positions.join(' → ') : '–';
}

export function decisionText(pitching) {
  const decision = String(pitching?.decision ?? '').trim();
  const record = String(pitching?.cumulative_record ?? '').trim();
  if (!decision) return '–';
  return record ? `${decision} ${record}` : decision;
}

function leagueText(row) {
  const acronyms = Array.isArray(row?.league_acronyms) ? row.league_acronyms.filter(Boolean) : [];
  return acronyms.length ? acronyms.join(' / ') : '–';
}

function countLabel(count) {
  return `${count} ${count === 1 ? 'Spiel' : 'Spiele'}`;
}

function tableShell(head, body) {
  return `<div class="table-scroll game-log-scroll"><table class="stats-table game-log-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function battingTable(logs) {
  const rows = roleRows('batting', logs);
  if (!rows.length) {
    return '<div class="empty-state game-log-empty">Keine Schlag-Spielprotokolle für diese Spielzeit vorhanden.</div>';
  }

  const head = [
    '<th>Datum</th>',
    '<th class="left">Gegner</th>',
    '<th class="left">Liga</th>',
    '<th class="left">Pos.</th>',
    '<th>AB</th>',
    '<th>R</th>',
    '<th>H</th>',
    '<th>RBI</th>',
    '<th>BB</th>',
    '<th>SO</th>',
  ].join('');

  const body = rows.map((row) => {
    const stats = row.batting ?? {};
    return `<tr>
      <td>${escapeHtml(formatGameDate(row.time))}</td>
      <td class="left game-log-opponent">${escapeHtml(opponentName(row))}</td>
      <td class="left">${escapeHtml(leagueText(row))}</td>
      <td class="left game-log-position">${escapeHtml(positionText(row))}</td>
      <td>${asNumber(stats.AB)}</td>
      <td>${asNumber(stats.R)}</td>
      <td>${asNumber(stats.H)}</td>
      <td>${asNumber(stats.RBI)}</td>
      <td>${asNumber(stats.BB)}</td>
      <td>${asNumber(stats.K)}</td>
    </tr>`;
  }).join('');

  return tableShell(head, body);
}

function pitchingTable(logs) {
  const rows = roleRows('pitching', logs);
  if (!rows.length) {
    return '<div class="empty-state game-log-empty">Keine Wurf-Spielprotokolle für diese Spielzeit vorhanden.</div>';
  }

  const head = [
    '<th>Datum</th>',
    '<th class="left">Gegner</th>',
    '<th class="left">Liga</th>',
    '<th>IP</th>',
    '<th>H</th>',
    '<th>R</th>',
    '<th>ER</th>',
    '<th>BB</th>',
    '<th>SO</th>',
    '<th>Entscheidung</th>',
  ].join('');

  const body = rows.map((row) => {
    const stats = row.pitching ?? {};
    return `<tr>
      <td>${escapeHtml(formatGameDate(row.time))}</td>
      <td class="left game-log-opponent">${escapeHtml(opponentName(row))}</td>
      <td class="left">${escapeHtml(leagueText(row))}</td>
      <td>${escapeHtml(stats.IP ?? '0.0')}</td>
      <td>${asNumber(stats.H)}</td>
      <td>${asNumber(stats.R)}</td>
      <td>${asNumber(stats.ER)}</td>
      <td>${asNumber(stats.BB)}</td>
      <td>${asNumber(stats.K)}</td>
      <td class="game-log-decision">${escapeHtml(decisionText(stats))}</td>
    </tr>`;
  }).join('');

  return tableShell(head, body);
}




function normalizeLeagueToken(value) {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '');
}

function canonicalLeagueKey(acronym) {
  const raw = String(acronym ?? '').trim();
  if (!raw) return '';

  const upper = raw.toUpperCase();
  if (upper.startsWith('LLBB')) return 'LLBB';
  if (upper.startsWith('VLBB')) return 'VLBB';
  if (upper === 'JUGBB') return 'JugBB';
  if (upper === 'JUNBB') return 'JunBB';
  if (upper === 'SCHBB') return 'SchBB';

  return raw;
}

function leagueLabel(key) {
  const labels = {
    VLBB: 'Verbandsliga',
    LLBB: 'Landesliga',
    JugBB: 'Jugendliga',
    JunBB: 'Juniorenliga',
    SchBB: 'Schülerliga',
    JUG_GR_A: 'DM Jugend Gruppe A',
    JUG_GR_B: 'DM Jugend Gruppe B',
    JUG_GR_C: 'DM Jugend Gruppe C',
    JUG_PO: 'DM Jugend Play-offs',
    JUN_GR_A: 'DM Junioren Gruppe A',
    JUN_GR_B: 'DM Junioren Gruppe B',
    JUN_PO: 'DM Junioren Play-offs',
    SCH_GR_A: 'DM Schüler Gruppe A',
    SCH_GR_B: 'DM Schüler Gruppe B',
    SCH_PO: 'DM Schüler Play-offs',
    JUNSB_GR_A: 'DM Juniorinnen Gruppe A',
    JUNSB_GR_B: 'DM Juniorinnen Gruppe B',
    JUNSB_PO: 'DM Juniorinnen Play-offs',
    JUGSB_GR_A: 'DM Jugend Softball Gruppe A',
    JUGSB_GR_B: 'DM Jugend Softball Gruppe B',
    JUGSB_GR_C: 'DM Jugend Softball Gruppe C',
    JUGSB_PO: 'DM Jugend Softball Play-offs',
    VLSB: 'Verbandsliga Softball',
  };
  return labels[key] ?? key;
}

function logLeagueKeys(row) {
  const acronyms = Array.isArray(row?.league_acronyms) ? row.league_acronyms : [];
  return [...new Set(acronyms.map(canonicalLeagueKey).filter(Boolean))];
}

export function leagueFilterOptions(logs) {
  const counts = new Map();

  for (const row of logs ?? []) {
    for (const key of logLeagueKeys(row)) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }

  const options = [...counts.entries()]
    .map(([key, count]) => ({ key, label: leagueLabel(key), count }))
    .sort((a, b) => a.label.localeCompare(b.label, 'de'));

  return [
    { key: 'all', label: 'Alle Ligen', count: (logs ?? []).length },
    ...options,
  ];
}

function leagueKeyFromName(value) {
  const token = normalizeLeagueToken(value);
  if (!token) return '';

  if (token.includes('verbandsligabaseball')) return 'VLBB';
  if (token.includes('landesligabaseball')) return 'LLBB';
  if (token.includes('jugendligabaseball')) return 'JugBB';
  if (token.includes('juniorenligabaseball')) return 'JunBB';
  if (token.includes('schulerligabaseball')) return 'SchBB';

  const group = token.match(/dmjugend(?:bb|baseball)?gruppe([abc])/);
  if (group) return `JUG_GR_${group[1].toUpperCase()}`;
  if (token.includes('dmjugendbbplayoffs') || token.includes('dmjugendplayoffs')) return 'JUG_PO';

  const junior = token.match(/dmjunioren(?:bb|baseball)?gruppe([ab])/);
  if (junior) return `JUN_GR_${junior[1].toUpperCase()}`;
  if (token.includes('dmjuniorenplayoffs')) return 'JUN_PO';

  const juniorinnen = token.match(/dmjuniorinnengruppe([ab])/);
  if (juniorinnen) return `JUNSB_GR_${juniorinnen[1].toUpperCase()}`;
  if (token.includes('dmjuniorinnenplayoffs')) return 'JUNSB_PO';

  if (token.includes('verbandsligasoftball')) return 'VLSB';

  return '';
}

export function historyLeagueHint(row) {
  return {
    leagueName: row?.leagueName ?? '',
    leagueKey: row?.leagueKey ?? '',
    leagueId: row?.leagueId ?? row?.groupId ?? null,
    groupId: row?.groupId ?? null,
    acronym: row?.leagueAcronym ?? row?.acronym ?? '',
  };
}

export function resolveLeagueFilterKey(logs, hint = {}) {
  const options = leagueFilterOptions(logs);
  const validKeys = new Set(options.map((item) => item.key));

  const numericIds = new Set();
  for (const value of [hint.leagueId, hint.groupId]) {
    const number = Number(value);
    if (Number.isInteger(number)) numericIds.add(number);
  }
  for (const match of String(hint.leagueKey ?? '').matchAll(/\d{4,}/g)) {
    numericIds.add(Number(match[0]));
  }

  if (numericIds.size) {
    for (const row of logs ?? []) {
      const ids = Array.isArray(row?.league_ids) ? row.league_ids.map(Number) : [];
      if (ids.some((id) => numericIds.has(id))) {
        const key = logLeagueKeys(row)[0];
        if (key && validKeys.has(key)) return key;
      }
    }
  }

  const acronymKey = canonicalLeagueKey(hint.acronym);
  if (acronymKey && validKeys.has(acronymKey)) return acronymKey;

  const nameKey = leagueKeyFromName(hint.leagueName);
  if (nameKey && validKeys.has(nameKey)) return nameKey;

  const keyToken = normalizeLeagueToken(hint.leagueKey);
  if (keyToken) {
    for (const option of options) {
      if (option.key === 'all') continue;
      const optionToken = normalizeLeagueToken(option.key);
      if (optionToken && keyToken.includes(optionToken)) return option.key;
    }
  }

  return 'all';
}

export function filterGameLogs(logs, {
  leagueKey = 'all',
  role = 'batting',
} = {}) {
  return (logs ?? []).filter((row) => {
    const leagueMatch = leagueKey === 'all' || logLeagueKeys(row).includes(leagueKey);
    if (!leagueMatch) return false;
    return role === 'pitching' ? Boolean(row?.pitching) : Boolean(row?.batting);
  });
}

function leagueFilterHtml(logs, activeKey) {
  return leagueFilterOptions(logs).map((option) => `
    <button type="button"
      data-game-league="${escapeHtml(option.key)}"
      class="${option.key === activeKey ? 'active' : ''}">
      ${escapeHtml(option.label)}
      <span>${option.count}</span>
    </button>`).join('');
}

function roleFilterHtml(activeRole) {
  return `
    <button type="button" data-game-role="batting" class="${activeRole === 'batting' ? 'active' : ''}">Schlag</button>
    <button type="button" data-game-role="pitching" class="${activeRole === 'pitching' ? 'active' : ''}">Wurf</button>`;
}

function gameEventValue(row, section, key) {
  const target = section === 'batting' ? row?.batting : row?.[section];
  if (!target || !Object.prototype.hasOwnProperty.call(target, key)) return '–';
  return asNumber(target[key]);
}

function latestCumulativeSnapshot(stats, key) {
  const snapshots = Array.isArray(stats?.displayed_cumulative_snapshots)
    ? stats.displayed_cumulative_snapshots
    : [];

  for (let index = snapshots.length - 1; index >= 0; index -= 1) {
    const raw = String(snapshots[index]?.[key] ?? '').trim();
    if (raw && raw !== '–' && raw !== '-') return raw;
  }
  return '–';
}

function roleGameTable(logs, role, isCareer) {
  if (!logs.length) {
    return `<div class="empty-state game-log-empty">Keine ${role === 'pitching' ? 'Wurf' : 'Schlag'}-Spielprotokolle für diese Auswahl vorhanden.</div>`;
  }

  const seasonHead = isCareer ? '<th>Saison</th>' : '';
  const seasonCell = (row) => isCareer ? `<td>${escapeHtml(seasonFromTime(row.time) ?? '–')}</td>` : '';

  if (role === 'pitching') {
    const cumulativePitching = cumulativePitchingState(logs);

    const head = [
      seasonHead,
      '<th>Datum</th>',
      '<th class="left">Gegner</th>',
      '<th class="left">Liga</th>',
      '<th>IP</th>',
      '<th>BF</th>',
      '<th>H</th>',
      '<th>R</th>',
      '<th>ER</th>',
      '<th>BB</th>',
      '<th>SO</th>',
      '<th>Entsch.</th>',
      '<th>ERA kum.</th>',
      '<th>WHIP kum.</th>',
    ].join('');

    const body = logs.map((row) => {
      const stats = row.pitching ?? {};
      return `<tr>
        ${seasonCell(row)}
        <td>${escapeHtml(formatGameDate(row.time))}</td>
        <td class="left game-log-opponent">${escapeHtml(opponentName(row))}</td>
        <td class="left">${escapeHtml(leagueText(row))}</td>
        <td>${escapeHtml(stats.IP ?? '0.0')}</td>
        <td>${asNumber(stats.BF)}</td>
        <td>${asNumber(stats.H)}</td>
        <td>${asNumber(stats.R)}</td>
        <td>${asNumber(stats.ER)}</td>
        <td>${asNumber(stats.BB)}</td>
        <td>${asNumber(stats.K)}</td>
        <td class="game-log-decision">${escapeHtml(decisionText(stats))}</td>
        <td class="game-log-cumulative">${escapeHtml(latestCumulativeSnapshot(stats, 'ERA'))}</td>
        <td class="game-log-cumulative">${escapeHtml(formatPitchRate(cumulativePitching.get(row)?.whip))}</td>
      </tr>`;
    }).join('');
    return tableShell(head, body);
  }

  const head = [
    seasonHead,
    '<th>Datum</th>',
    '<th class="left">Gegner</th>',
    '<th class="left">Liga</th>',
    '<th class="left">Pos.</th>',
    '<th>AB</th>',
    '<th>R</th>',
    '<th>H</th>',
    '<th>2B</th>',
    '<th>3B</th>',
    '<th>HR</th>',
    '<th>RBI</th>',
    '<th>BB</th>',
    '<th>SO</th>',
    '<th>SH</th>',
    '<th>SF</th>',
    '<th>SB</th>',
    '<th>CS</th>',
    '<th>AVG kum.</th>',
    '<th>OPS kum.</th>',
  ].join('');

  const body = logs.map((row) => {
    const stats = row.batting ?? {};
    return `<tr>
      ${seasonCell(row)}
      <td>${escapeHtml(formatGameDate(row.time))}</td>
      <td class="left game-log-opponent">${escapeHtml(opponentName(row))}</td>
      <td class="left">${escapeHtml(leagueText(row))}</td>
      <td class="left game-log-position">${escapeHtml(positionText(row))}</td>
      <td>${asNumber(stats.AB)}</td>
      <td>${asNumber(stats.R)}</td>
      <td>${asNumber(stats.H)}</td>
      <td>${escapeHtml(gameEventValue(row, 'batting', '2B'))}</td>
      <td>${escapeHtml(gameEventValue(row, 'batting', '3B'))}</td>
      <td>${escapeHtml(gameEventValue(row, 'batting', 'HR'))}</td>
      <td>${asNumber(stats.RBI)}</td>
      <td>${asNumber(stats.BB)}</td>
      <td>${asNumber(stats.K)}</td>
      <td>${escapeHtml(gameEventValue(row, 'batting', 'SH'))}</td>
      <td>${escapeHtml(gameEventValue(row, 'batting', 'SF'))}</td>
      <td>${escapeHtml(gameEventValue(row, 'baserunning', 'SB'))}</td>
      <td>${escapeHtml(gameEventValue(row, 'baserunning', 'CS'))}</td>
      <td class="game-log-cumulative">${escapeHtml(latestCumulativeSnapshot(stats, 'AVG'))}</td>
      <td class="game-log-cumulative">${escapeHtml(latestCumulativeSnapshot(stats, 'OPS'))}</td>
    </tr>`;
  }).join('');
  return tableShell(head, body);
}

export function gameLogPanelHtml(result, {
  leagueKey = 'all',
  role = 'batting',
} = {}) {
  const rows = result?.logs ?? [];
  const selection = result?.selection ?? 'career';
  const isCareer = selection === 'career';
  const selectedYear = normalizedSeason(selection);

  const options = leagueFilterOptions(rows);
  const validKeys = new Set(options.map((option) => option.key));
  const effectiveLeagueKey = validKeys.has(leagueKey) ? leagueKey : 'all';
  const filtered = filterGameLogs(rows, { leagueKey: effectiveLeagueKey, role });

  const statusNote = isCareer && result?.missingSeasons?.length
    ? `<div class="game-log-availability">Noch nicht verfügbar: ${escapeHtml(result.missingSeasons.join(', '))}</div>`
    : '';

  const opsSections = role === 'batting'
    ? (isCareer
        ? [...new Set(filtered.map((row) => seasonFromTime(row.time)).filter(Boolean))]
            .sort((a, b) => b - a)
            .map((season) => monthlyOpsTrendHtml(
              filtered.filter((row) => seasonFromTime(row.time) === season),
              season,
            ))
            .join('')
        : monthlyOpsTrendHtml(filtered, selectedYear))
    : (isCareer
        ? [...new Set(filtered.map((row) => seasonFromTime(row.time)).filter(Boolean))]
            .sort((a, b) => b - a)
            .map((season) => monthlyPitchingTrendHtml(
              filtered.filter((row) => seasonFromTime(row.time) === season),
              season,
            ))
            .join('')
        : monthlyPitchingTrendHtml(filtered, selectedYear));

  return `
    <div class="game-log-panel">
      <div class="game-log-combined-heading">
        <div>
          <h2>${isCareer ? 'Spielprotokoll · Gesamtübersicht' : `Spielprotokoll ${escapeHtml(selectedYear)}`}</h2>
          <p>Nach Liga und Rolle filtern.</p>
        </div>
        <span class="meta-pill">${countLabel(filtered.length)}</span>
      </div>
      ${statusNote}
      <div class="game-log-filter-bar">
        <div class="game-log-filter-block">
          <span class="game-log-filter-label">Liga</span>
          <div class="game-log-league-tabs">${leagueFilterHtml(rows, effectiveLeagueKey)}</div>
        </div>
        <div class="game-log-filter-block game-log-role-block">
          <span class="game-log-filter-label">Ansicht</span>
          <div class="game-log-role-tabs">${roleFilterHtml(role)}</div>
        </div>
      </div>
      ${opsSections}
      <div class="game-log-role-table">${roleGameTable(filtered, role, isCareer)}</div>
      <div class="card-body game-log-note">
        ${role === 'batting'
          ? 'OPS-Verlauf und Schlagwerte beziehen sich auf die aktuell gewählte Liga.'
          : 'ERA stammt aus den kumulativen BSM-Snapshots; WHIP wird aus H, BB und Outs berechnet.'}
      </div>
    </div>`;
}


const MONTHS_DE = [
  ['Jan', 'Januar'],
  ['Feb', 'Februar'],
  ['Mär', 'März'],
  ['Apr', 'April'],
  ['Mai', 'Mai'],
  ['Jun', 'Juni'],
  ['Jul', 'Juli'],
  ['Aug', 'August'],
  ['Sep', 'September'],
  ['Okt', 'Oktober'],
  ['Nov', 'November'],
  ['Dez', 'Dezember'],
];

function parseDisplayedRate(value) {
  const raw = String(value ?? '').trim().replace(',', '.');
  if (!raw || raw === '–' || raw === '-') return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function latestDisplayedOps(row) {
  const snapshots = Array.isArray(row?.batting?.displayed_cumulative_snapshots)
    ? row.batting.displayed_cumulative_snapshots
    : [];

  for (let index = snapshots.length - 1; index >= 0; index -= 1) {
    const value = parseDisplayedRate(snapshots[index]?.OPS);
    if (value !== null) return value;
  }
  return null;
}

function gameMonth(value, season) {
  const match = String(value ?? '').match(/^(\d{4})-(\d{2})-\d{2}/);
  if (!match) return null;
  const rowSeason = Number(match[1]);
  const requestedSeason = normalizedSeason(season);
  if (requestedSeason && rowSeason !== requestedSeason) return null;
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? month : null;
}

export function monthlyOpsSeries(logs, season) {
  const byMonth = new Map();

  for (const row of logs ?? []) {
    const month = gameMonth(row?.time, season);
    if (!month) continue;

    const ops = latestDisplayedOps(row);
    if (ops === null) continue;

    const sortValue = timeSortValue(row?.time);
    const current = byMonth.get(month);
    if (!current || sortValue > current.sortValue) {
      byMonth.set(month, {
        ops,
        sortValue,
        matchId: row?.match_id ?? null,
        date: row?.time ?? null,
      });
    }
  }

  return MONTHS_DE.map(([shortLabel, fullLabel], index) => {
    const month = index + 1;
    const current = byMonth.get(month);
    const previous = byMonth.get(month - 1);

    return {
      month,
      shortLabel,
      fullLabel,
      ops: current?.ops ?? null,
      delta: current && previous ? current.ops - previous.ops : null,
      matchId: current?.matchId ?? null,
      date: current?.date ?? null,
    };
  });
}

function formatOps(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '–';
  return Number(value).toFixed(3).replace(/^0(?=\.)/, '');
}

function formatOpsDelta(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '–';
  const numeric = Number(value);
  if (Math.abs(numeric) < 0.0005) return '±.000';
  const sign = numeric > 0 ? '+' : '−';
  return `${sign}${Math.abs(numeric).toFixed(3).replace(/^0(?=\.)/, '')}`;
}

function opsChartSvg(series, season) {
  const valid = series.filter((item) => item.ops !== null);
  if (!valid.length) return '';

  const firstMonth = valid[0].month;
  const lastMonth = valid.at(-1).month;
  const visible = series.filter((item) => item.month >= firstMonth && item.month <= lastMonth);

  const width = 760;
  const height = 230;
  const padLeft = 52;
  const padRight = 22;
  const padTop = 24;
  const padBottom = 42;
  const chartWidth = width - padLeft - padRight;
  const chartHeight = height - padTop - padBottom;

  const values = valid.map((item) => item.ops);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = Math.max(rawMax - rawMin, 0.100);
  const minValue = Math.max(0, rawMin - spread * 0.18);
  const maxValue = rawMax + spread * 0.18;
  const ySpan = Math.max(maxValue - minValue, 0.001);

  const xFor = (month) => {
    if (lastMonth === firstMonth) return padLeft + chartWidth / 2;
    return padLeft + ((month - firstMonth) / (lastMonth - firstMonth)) * chartWidth;
  };
  const yFor = (ops) => padTop + ((maxValue - ops) / ySpan) * chartHeight;

  const gridLines = [0, 0.5, 1].map((ratio) => {
    const y = padTop + ratio * chartHeight;
    const value = maxValue - ratio * ySpan;
    return `<g class="ops-chart-grid">
      <line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${width - padRight}" y2="${y.toFixed(1)}"></line>
      <text x="${padLeft - 9}" y="${(y + 4).toFixed(1)}" text-anchor="end">${escapeHtml(formatOps(value))}</text>
    </g>`;
  }).join('');

  const monthLabels = visible.map((item) => {
    const x = xFor(item.month);
    return `<text class="ops-chart-month" x="${x.toFixed(1)}" y="${height - 14}" text-anchor="middle">${escapeHtml(item.shortLabel)}</text>`;
  }).join('');

  const linePoints = valid.map((point) =>
    `${xFor(point.month).toFixed(1)},${yFor(point.ops).toFixed(1)}`
  );

  const lines = linePoints.length > 1
    ? `<polyline class="ops-chart-line" points="${linePoints.join(' ')}"></polyline>`
    : '';

  const circles = valid.map((item) => {
    const x = xFor(item.month);
    const y = yFor(item.ops);
    return `<g class="ops-chart-point">
      <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5"></circle>
      <text x="${x.toFixed(1)}" y="${(y - 11).toFixed(1)}" text-anchor="middle">${escapeHtml(formatOps(item.ops))}</text>
    </g>`;
  }).join('');

  return `<svg class="ops-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Kumulativer OPS-Verlauf ${escapeHtml(season)}">
    ${gridLines}
    ${lines}
    ${circles}
    ${monthLabels}
  </svg>`;
}

export function monthlyOpsTrendHtml(logs, season) {
  const year = normalizedSeason(season) ?? season;
  const series = monthlyOpsSeries(logs, year);
  const valid = series.filter((item) => item.ops !== null);

  if (!valid.length) {
    return `
      <section class="ops-trend-panel">
        <div class="ops-trend-heading">
          <div>
            <h2>Kumulativer OPS-Verlauf ${escapeHtml(year)}</h2>
            <p>Monatsendstand aus dem zuletzt veröffentlichten BSM-OPS-Snapshot des jeweiligen Monats.</p>
          </div>
        </div>
        <div class="empty-state ops-trend-empty">Keine kumulativen OPS-Snapshots verfügbar.</div>
      </section>`;
  }

  const firstMonth = valid[0].month;
  const lastMonth = valid.at(-1).month;
  const visible = series.filter((item) => item.month >= firstMonth && item.month <= lastMonth);

  const rows = visible.map((item) => {
    const deltaClass = item.delta === null
      ? ''
      : item.delta > 0.0005
        ? ' is-up'
        : item.delta < -0.0005
          ? ' is-down'
          : ' is-flat';

    return `<tr>
      <td class="left">${escapeHtml(item.fullLabel)}</td>
      <td class="ops-value">${escapeHtml(formatOps(item.ops))}</td>
      <td class="ops-delta${deltaClass}">${escapeHtml(formatOpsDelta(item.delta))}</td>
    </tr>`;
  }).join('');

  return `
    <section class="ops-trend-panel">
      <div class="ops-trend-heading">
        <div>
          <h2>Kumulativer OPS-Verlauf ${escapeHtml(year)}</h2>
          <p>Monatsendstand aus dem zuletzt veröffentlichten BSM-OPS-Snapshot des jeweiligen Monats.</p>
        </div>
        <span class="meta-pill">${valid.length} ${valid.length === 1 ? 'Monat' : 'Monate'}</span>
      </div>
      <div class="ops-trend-layout">
        <div class="ops-chart-wrap">${opsChartSvg(series, year)}</div>
        <div class="table-scroll ops-month-table-wrap">
          <table class="stats-table ops-month-table">
            <thead><tr><th class="left">Monat</th><th>OPS</th><th>Δ Vormonat</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
      <p class="ops-trend-note">Die Kurve zeigt kumulative BSM-OPS-Werte zum Monatsende, nicht den isolierten OPS des einzelnen Monats.</p>
    </section>`;
}



function pitchingScopeKey(row) {
  const season = seasonFromTime(row?.time) ?? '';
  const leagues = logLeagueKeys(row).slice().sort().join('|');
  return `${season}|${leagues}`;
}

function pitchingOuts(row) {
  const stored = Number(row?.pitching?.outs);

  if (Number.isFinite(stored) && stored >= 0) {
    return Math.trunc(stored);
  }

  const raw = String(row?.pitching?.IP ?? '').trim();
  const match = raw.match(/^(\d+)\.(\d)$/);

  if (!match) return 0;

  const innings = Number(match[1]);
  const partial = Math.min(Number(match[2]), 2);

  return innings * 3 + partial;
}

function formatPitchIp(outs) {
  const numeric = Number(outs);

  if (!Number.isFinite(numeric) || numeric < 0) return '?';

  const whole = Math.floor(numeric / 3);
  const partial = Math.trunc(numeric % 3);

  return `${whole}.${partial}`;
}

function formatPitchRate(value) {
  if (
    value === null
    || value === undefined
    || !Number.isFinite(Number(value))
  ) {
    return '?';
  }

  return Number(value).toFixed(2);
}

function formatPitchKbb(strikeouts, walks) {
  const k = asNumber(strikeouts);
  const bb = asNumber(walks);

  if (bb <= 0) return '?';

  return (k / bb).toFixed(2);
}

function latestDisplayedEra(row) {
  const snapshots = Array.isArray(
    row?.pitching?.displayed_cumulative_snapshots
  )
    ? row.pitching.displayed_cumulative_snapshots
    : [];

  for (let index = snapshots.length - 1; index >= 0; index -= 1) {
    const value = parseDisplayedRate(snapshots[index]?.ERA);

    if (value !== null) return value;
  }

  return null;
}


/*
 * BSM does not publish WHIP in the per-game cumulative snapshots.
 * Build it from the game logs:
 *
 *   WHIP = (H + BB) / IP
 *        = (H + BB) * 3 / outs
 *
 * State is separated by season + league scope so a career view does
 * not accidentally carry one season/league into the next.
 */
export function cumulativePitchingState(logs) {
  const ordered = [...(logs ?? [])]
    .filter((row) => Boolean(row?.pitching))
    .sort((a, b) => {
      const timeDiff = timeSortValue(a?.time) - timeSortValue(b?.time);
      if (timeDiff) return timeDiff;

      return asNumber(a?.match_id) - asNumber(b?.match_id);
    });

  const scopeStates = new Map();
  const statesByRow = new Map();

  for (const row of ordered) {
    const scope = pitchingScopeKey(row);

    const state = scopeStates.get(scope) ?? {
      outs: 0,
      h: 0,
      bb: 0,
      k: 0,
    };

    state.outs += pitchingOuts(row);
    state.h += asNumber(row?.pitching?.H);
    state.bb += asNumber(row?.pitching?.BB);
    state.k += asNumber(row?.pitching?.K);

    scopeStates.set(scope, state);

    statesByRow.set(row, {
      ...state,
      era: latestDisplayedEra(row),
      whip: state.outs > 0
        ? ((state.h + state.bb) * 3) / state.outs
        : null,
    });
  }

  return statesByRow;
}


export function monthlyPitchingSeries(logs, season) {
  const year = normalizedSeason(season) ?? season;
  const cumulative = cumulativePitchingState(logs);
  const byMonth = new Map();

  for (const row of logs ?? []) {
    if (!row?.pitching) continue;

    const month = gameMonth(row?.time, year);
    if (!month) continue;

    const state = cumulative.get(row);
    if (!state) continue;

    const sortValue = timeSortValue(row?.time);
    const current = byMonth.get(month);

    if (!current || sortValue > current.sortValue) {
      byMonth.set(month, {
        era: state.era,
        whip: state.whip,
        outs: state.outs,
        h: state.h,
        bb: state.bb,
        k: state.k,
        sortValue,
        matchId: row?.match_id ?? null,
        date: row?.time ?? null,
      });
    }
  }

  return MONTHS_DE.map(([shortLabel, fullLabel], index) => {
    const month = index + 1;
    const current = byMonth.get(month);

    return {
      month,
      shortLabel,
      fullLabel,
      era: current?.era ?? null,
      whip: current?.whip ?? null,
      outs: current?.outs ?? null,
      h: current?.h ?? null,
      bb: current?.bb ?? null,
      k: current?.k ?? null,
      matchId: current?.matchId ?? null,
      date: current?.date ?? null,
    };
  });
}


function pitchingMetricChartSvg(series, metric, season) {
  const valid = series.filter(
    (item) => item?.[metric] !== null
      && Number.isFinite(Number(item?.[metric])),
  );

  if (!valid.length) return '';

  const firstMonth = valid[0].month;
  const lastMonth = valid.at(-1).month;

  const visible = series.filter(
    (item) => item.month >= firstMonth && item.month <= lastMonth,
  );

  const width = 760;
  const height = 230;

  const padLeft = 52;
  const padRight = 22;
  const padTop = 24;
  const padBottom = 42;

  const chartWidth = width - padLeft - padRight;
  const chartHeight = height - padTop - padBottom;

  const values = valid.map((item) => Number(item[metric]));

  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);

  const minimumSpread = metric === 'era' ? 1.00 : 0.25;
  const spread = Math.max(rawMax - rawMin, minimumSpread);

  const minValue = Math.max(0, rawMin - spread * 0.18);
  const maxValue = rawMax + spread * 0.18;
  const ySpan = Math.max(maxValue - minValue, 0.001);

  const xFor = (month) => {
    if (lastMonth === firstMonth) {
      return padLeft + chartWidth / 2;
    }

    return padLeft
      + ((month - firstMonth) / (lastMonth - firstMonth)) * chartWidth;
  };

  const yFor = (value) =>
    padTop + ((maxValue - value) / ySpan) * chartHeight;

  const gridLines = [0, 0.5, 1].map((ratio) => {
    const y = padTop + ratio * chartHeight;
    const value = maxValue - ratio * ySpan;

    return `<g class="ops-chart-grid">
      <line
        x1="${padLeft}"
        y1="${y.toFixed(1)}"
        x2="${width - padRight}"
        y2="${y.toFixed(1)}">
      </line>
      <text
        x="${padLeft - 9}"
        y="${(y + 4).toFixed(1)}"
        text-anchor="end">
        ${escapeHtml(formatPitchRate(value))}
      </text>
    </g>`;
  }).join('');

  const monthLabels = visible.map((item) => {
    const x = xFor(item.month);

    return `<text
      class="ops-chart-month"
      x="${x.toFixed(1)}"
      y="${height - 14}"
      text-anchor="middle">
      ${escapeHtml(item.shortLabel)}
    </text>`;
  }).join('');

  // Missing months do NOT break the line.
  const linePoints = valid.map((item) =>
    `${xFor(item.month).toFixed(1)},${yFor(Number(item[metric])).toFixed(1)}`
  );

  const line = linePoints.length > 1
    ? `<polyline
        class="ops-chart-line"
        points="${linePoints.join(' ')}">
       </polyline>`
    : '';

  const circles = valid.map((item) => {
    const x = xFor(item.month);
    const y = yFor(Number(item[metric]));

    return `<g class="ops-chart-point">
      <circle
        cx="${x.toFixed(1)}"
        cy="${y.toFixed(1)}"
        r="5">
      </circle>
      <text
        x="${x.toFixed(1)}"
        y="${(y - 11).toFixed(1)}"
        text-anchor="middle">
        ${escapeHtml(formatPitchRate(item[metric]))}
      </text>
    </g>`;
  }).join('');

  const label = metric === 'era' ? 'ERA' : 'WHIP';

  return `<svg
    class="ops-chart"
    viewBox="0 0 ${width} ${height}"
    role="img"
    aria-label="Kumulativer ${escapeHtml(label)}-Verlauf ${escapeHtml(season)}">
      ${gridLines}
      ${line}
      ${circles}
      ${monthLabels}
    </svg>`;
}


function pitchingSummaryHtml(series) {
  const final = [...series]
    .reverse()
    .find((item) =>
      item.outs !== null
      || item.era !== null
      || item.whip !== null
    );

  if (!final) return '';

  const metrics = [
    ['IP', formatPitchIp(final.outs)],
    ['ERA', formatPitchRate(final.era)],
    ['WHIP', formatPitchRate(final.whip)],
    ['SO', final.k ?? '?'],
    ['BB', final.bb ?? '?'],
    ['K/BB', formatPitchKbb(final.k, final.bb)],
  ];

  return `
    <div class="pitch-summary-grid">
      ${metrics.map(([label, value]) => `
        <div class="pitch-summary-item">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `).join('')}
    </div>`;
}


export function monthlyPitchingTrendHtml(logs, season) {
  const year = normalizedSeason(season) ?? season;
  const series = monthlyPitchingSeries(logs, year);

  const valid = series.filter(
    (item) => item.era !== null || item.whip !== null,
  );

  if (!valid.length) {
    return `
      <section class="ops-trend-panel pitch-trend-panel">
        <div class="ops-trend-heading">
          <div>
            <h2>Kumulativer ERA-/WHIP-Verlauf ${escapeHtml(year)}</h2>
            <p>ERA aus dem ver?ffentlichten BSM-Snapshot, WHIP aus H, BB und Outs.</p>
          </div>
        </div>
        <div class="empty-state ops-trend-empty">
          Keine kumulativen Wurf-Snapshots verf?gbar.
        </div>
      </section>`;
  }

  const firstMonth = valid[0].month;
  const lastMonth = valid.at(-1).month;

  const visible = series.filter(
    (item) => item.month >= firstMonth && item.month <= lastMonth,
  );

  const rows = visible.map((item) => `
    <tr>
      <td class="left">${escapeHtml(item.fullLabel)}</td>
      <td class="ops-value">${escapeHtml(formatPitchRate(item.era))}</td>
      <td class="ops-value">${escapeHtml(formatPitchRate(item.whip))}</td>
    </tr>
  `).join('');

  const token = String(year).replace(/[^0-9a-z_-]/gi, '');
  const eraId = `pitch-metric-era-${token}`;
  const whipId = `pitch-metric-whip-${token}`;

  return `
    <section class="ops-trend-panel pitch-trend-panel">

      <input
        class="pitch-metric-radio pitch-metric-era"
        type="radio"
        name="pitch-metric-${token}"
        id="${eraId}"
        checked>

      <input
        class="pitch-metric-radio pitch-metric-whip"
        type="radio"
        name="pitch-metric-${token}"
        id="${whipId}">

      <div class="ops-trend-heading">
        <div>
          <h2>Kumulativer ERA-/WHIP-Verlauf ${escapeHtml(year)}</h2>
          <p>
            ERA aus dem zuletzt ver?ffentlichten BSM-Snapshot;
            WHIP kumulativ aus H, BB und Outs.
          </p>
        </div>

        <div class="pitch-metric-toggle" aria-label="Wurfkennzahl ausw?hlen">
          <label for="${eraId}" data-pitch-metric="era">ERA</label>
          <label for="${whipId}" data-pitch-metric="whip">WHIP</label>
        </div>
      </div>

      ${pitchingSummaryHtml(series)}

      <div class="ops-trend-layout">
        <div class="ops-chart-wrap">

          <div class="pitch-chart-pane pitch-chart-era">
            ${pitchingMetricChartSvg(series, 'era', year)}
          </div>

          <div class="pitch-chart-pane pitch-chart-whip">
            ${pitchingMetricChartSvg(series, 'whip', year)}
          </div>

        </div>

        <div class="table-scroll ops-month-table-wrap">
          <table class="stats-table ops-month-table">
            <thead>
              <tr>
                <th class="left">Monat</th>
                <th>ERA</th>
                <th>WHIP</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>

      <p class="ops-trend-note">
        ERA verwendet den kumulativen BSM-Wert.
        WHIP = (H + BB) ? 3 / Outs.
        Monate ohne ver?ffentlichten Wert werden als ??? gezeigt;
        die Kurve verbindet die vorhandenen Monatsst?nde.
      </p>

    </section>`;
}


function statCell(value, className = '') {
  const classes = className ? ` class="${className}"` : '';
  if (value === null || value === undefined || value === '') {
    return `<td${classes}>–</td>`;
  }
  return `<td${classes}>${escapeHtml(value)}</td>`;
}

export function combinedGameLogContentHtml(input) {
  const result = Array.isArray(input)
    ? {
        selection: seasonFromTime(input[0]?.time) ?? 'career',
        logs: input,
        availableSeasons: [...new Set(input.map((row) => seasonFromTime(row.time)).filter(Boolean))].sort(),
        missingSeasons: [],
      }
    : (input ?? { selection: 'career', logs: [], availableSeasons: [], missingSeasons: [] });

  const rows = result.logs ?? [];
  const selection = result.selection;
  const isCareer = selection === 'career';
  const selectedYear = normalizedSeason(selection);
  const count = rows.length;

  if (!count) {
    const unavailable = selectedYear && result.missingSeasons?.includes(selectedYear);
    const message = unavailable
      ? `Für ${selectedYear} sind noch keine Spielprotokolle verfügbar.`
      : (selectedYear
          ? `Keine Spielprotokolle für ${selectedYear} vorhanden.`
          : 'Noch keine Spielprotokolle verfügbar.');

    return `
      <div class="game-log-combined">
        <div class="game-log-combined-heading">
          <div><h2>${isCareer ? 'Spielprotokoll · Gesamtübersicht' : `Spielprotokoll ${escapeHtml(selectedYear)}`}</h2><p>Einzelspielwerte aus den veröffentlichten BSM-Boxscores.</p></div>
          <span class="meta-pill">0 Spiele</span>
        </div>
        <div class="empty-state game-log-empty">${escapeHtml(message)}</div>
      </div>`;
  }

  const statusNote = isCareer && result.missingSeasons?.length
    ? `<div class="game-log-availability">Noch nicht verfügbar: ${escapeHtml(result.missingSeasons.join(', '))}</div>`
    : '';

  const opsSections = isCareer
    ? [...new Set(rows.map((row) => seasonFromTime(row.time)).filter(Boolean))]
        .sort((a, b) => b - a)
        .map((season) => monthlyOpsTrendHtml(
          rows.filter((row) => seasonFromTime(row.time) === season),
          season,
        ))
        .join('')
    : monthlyOpsTrendHtml(rows, selectedYear);

  const seasonHeader = isCareer ? '<th rowspan="2">Saison</th>' : '';
  const head = `
    <tr class="game-log-group-row">
      ${seasonHeader}
      <th rowspan="2">Datum</th>
      <th rowspan="2" class="left">Gegner</th>
      <th rowspan="2" class="left">Liga</th>
      <th rowspan="2" class="left">Pos.</th>
      <th colspan="6" class="game-log-group-label">Schlag</th>
      <th colspan="7" class="game-log-group-label">Wurf</th>
    </tr>
    <tr>
      <th>AB</th><th>R</th><th>H</th><th>RBI</th><th>BB</th><th>SO</th>
      <th>IP</th><th>H</th><th>R</th><th>ER</th><th>BB</th><th>SO</th><th>Entsch.</th>
    </tr>`;

  const body = rows.map((row) => {
    const batting = row?.batting ?? null;
    const pitching = row?.pitching ?? null;

    const battingCells = batting
      ? [
          statCell(asNumber(batting.AB)),
          statCell(asNumber(batting.R)),
          statCell(asNumber(batting.H)),
          statCell(asNumber(batting.RBI)),
          statCell(asNumber(batting.BB)),
          statCell(asNumber(batting.K)),
        ].join('')
      : '<td class="game-log-muted">–</td>'.repeat(6);

    const pitchingCells = pitching
      ? [
          statCell(pitching.IP ?? '0.0'),
          statCell(asNumber(pitching.H)),
          statCell(asNumber(pitching.R)),
          statCell(asNumber(pitching.ER)),
          statCell(asNumber(pitching.BB)),
          statCell(asNumber(pitching.K)),
          statCell(decisionText(pitching), 'game-log-decision'),
        ].join('')
      : '<td class="game-log-muted">–</td>'.repeat(7);

    return `<tr>
      ${isCareer ? `<td>${escapeHtml(seasonFromTime(row.time) ?? '–')}</td>` : ''}
      <td>${escapeHtml(formatGameDate(row.time))}</td>
      <td class="left game-log-opponent">${escapeHtml(opponentName(row))}</td>
      <td class="left">${escapeHtml(leagueText(row))}</td>
      <td class="left game-log-position">${escapeHtml(positionText(row))}</td>
      ${battingCells}
      ${pitchingCells}
    </tr>`;
  }).join('');

  return `
    <div class="game-log-combined">
      <div class="game-log-combined-heading">
        <div>
          <h2>${isCareer ? 'Spielprotokoll · Gesamtübersicht' : `Spielprotokoll ${escapeHtml(selectedYear)}`}</h2>
          <p>Einzelspielwerte aus den veröffentlichten BSM-Boxscores.</p>
        </div>
        <span class="meta-pill">${countLabel(count)}</span>
      </div>
      ${statusNote}
      ${opsSections}
      <div class="table-scroll game-log-scroll">
        <table class="stats-table game-log-table game-log-combined-table">
          <thead>${head}</thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      <div class="card-body game-log-note">
        AVG, OPS und ERA werden nicht als Einzelspielwerte gezeigt, da die BSM-Anzeige kumulative Saisonwerte enthalten kann.
      </div>
    </div>`;
}

export function gameLogContentHtml(kind, logs) {
  const rows = roleRows(kind, logs);
  const table = kind === 'pitching' ? pitchingTable(logs) : battingTable(logs);

  return `
    <div class="card-header game-log-header">
      <div class="game-log-heading">
        <h2>Spielprotokoll</h2>
        <p>Einzelspielwerte aus den veröffentlichten BSM-Boxscores.</p>
      </div>
      <span class="meta-pill">${countLabel(rows.length)}</span>
    </div>
    <div class="game-log-body">${table}</div>
    <div class="card-body game-log-note">
      AVG, OPS und ERA aus dem BSM-Boxscore werden hier nicht als Einzelspielwerte verwendet, da sie kumulative Saisonwerte darstellen können.
    </div>`;
}

export function renderGameLogSection(container, {
  selection,
  kind,
  state,
}) {
  if (!container) return;

  const visible = shouldShowGameLog(selection);
  container.hidden = !visible;
  if (!visible) {
    container.innerHTML = '';
    return;
  }

  if (state?.status === 'loading' || state?.status === 'idle') {
    container.innerHTML = `
      <div class="card-header game-log-header">
        <div class="game-log-heading"><h2>Spielprotokoll</h2><p>BSM-Boxscores werden geladen.</p></div>
      </div>
      <div class="empty-state game-log-empty">Spielprotokolle werden geladen…</div>`;
    return;
  }

  if (state?.status === 'error') {
    container.innerHTML = `
      <div class="card-header game-log-header">
        <div class="game-log-heading"><h2>Spielprotokoll</h2><p>Die Saisonstatistik bleibt weiterhin verfügbar.</p></div>
      </div>
      <div class="empty-state game-log-empty">Spielprotokolle konnten nicht geladen werden.</div>`;
    return;
  }

  container.innerHTML = gameLogContentHtml(kind, state?.logs ?? []);
}
