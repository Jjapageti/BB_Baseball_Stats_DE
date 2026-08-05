import { loadAllData, loadData } from './data.js';
import { buildBattingRows, buildLeagueContext, buildPitchingRows } from './stats.js';
import { buildBattingHistory, buildPitchingHistory, formatInnings } from './career.js';
import { comparisonAverage, comparisonTotals, filterHistoryForSelection, selectedTotal } from './player-view.js';
import { batterRadar, pitcherRadar, renderRadar } from './radar.js';
import { buildTeamCatalog, renderTeamIdentity, renderTeamMark, resolveTeam } from './team.js';
import { initGlobalSearch } from './search.js';
import {
  escapeHtml, formatNumber, formatRate, leagueUrl, playerUrl,
  renderDataStatus, renderError, renderFooter, renderLeagueSelector, renderSiteHeader,
} from './ui.js';

function prepareRows(allLeagueData) {
  const batting = [];
  const pitching = [];
  for (const data of allLeagueData) {
    const context = buildLeagueContext(data);
    batting.push(...buildBattingRows(data.batting, context));
    pitching.push(...buildPitchingRows(data.pitching, context));
  }
  return { batting, pitching };
}

function renderPicker(container, rows, data, teamCatalog = []) {
  const unique = new Map();
  for (const row of rows.sort((a, b) => Number(b.season) - Number(a.season))) {
    if (!unique.has(String(row.personId))) unique.set(String(row.personId), row);
  }
  const list = [...unique.values()].sort((a, b) => a.name.localeCompare(b.name, 'de'));
  container.innerHTML = `
    <div class="page-heading league-page-heading"><div><h1>Spielersuche</h1><p>Alle Spieler aus den Spielzeiten 2023 bis 2026.</p></div><div id="leagueSwitcher"></div></div>
    <div id="dataStatus"></div>
    <section class="card player-picker"><div class="control search"><label for="playerSearch">Spieler oder Mannschaft</label><input id="playerSearch" type="search" placeholder="Name, Mannschaft oder Kürzel"></div><div class="player-picker-list" id="playerPickerList"></div></section>`;
  renderLeagueSelector('leagueSwitcher', data, { compact: true });
  renderDataStatus('dataStatus', data);
  const target = container.querySelector('#playerPickerList');
  const input = container.querySelector('#playerSearch');
  const draw = () => {
    const query = input.value.trim().toLowerCase();
    const filtered = list.filter((row) => !query || `${row.name} ${row.team} ${row.acronym}`.toLowerCase().includes(query)).slice(0, 100);
    target.innerHTML = filtered.map((row) => `<a class="player-picker-item" href="${playerUrl(row, data)}"><span class="player-picker-mark">${renderTeamMark(resolveTeam(row, teamCatalog) ?? { name: row.team }, { size: 'md' })}</span><span class="player-picker-copy"><strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.team)} · zuletzt ${row.season}</span></span></a>`).join('') || '<div class="empty-state">Keine Treffer.</div>';
  };
  input.addEventListener('input', draw);
  draw();
}


export function renderPlayerHeroMark(base, teamCatalog = []) {
  const team = resolveTeam(base, teamCatalog) ?? { name: base?.team ?? base?.name ?? 'Spieler' };
  return `<div class="player-avatar">${renderTeamMark(team, { size: 'lg', className: 'player-hero-team-mark' })}</div>`;
}

export function renderPlayerTeamList(rows, teamCatalog = []) {
  const unique = new Map();
  for (const row of rows ?? []) {
    const key = `team:${String(row?.team ?? '').trim().toLocaleLowerCase('de-DE')}:${String(row?.acronym ?? '').trim().toLocaleUpperCase('de-DE')}`;
    if (!unique.has(key)) unique.set(key, row);
  }
  return [...unique.values()].map((row) => renderTeamIdentity(row, teamCatalog, {
    size: 'xs', showAcronym: false, showName: true, className: 'player-career-team',
  })).join('');
}

function rowClass(row) {
  return row.rowType === 'career-total' ? 'career-total-row' : row.rowType === 'season-total' ? 'season-total-row' : '';
}

export function renderHistoryTeamIdentity(row, teamCatalog = []) {
  if (row?.rowType !== 'league') return `<span class="history-team-total">${escapeHtml(row?.team ?? '–')}</span>`;
  return renderTeamIdentity(row, teamCatalog, { size: 'xs', showAcronym: true, showName: true, className: 'history-team-identity' });
}

function battingTable(rows, teamCatalog = []) {
  if (!rows.length) return '<div class="empty-state">Keine Schlagstatistik für diesen Zeitraum vorhanden.</div>';
  return `<div class="table-scroll"><table class="stats-table history-table"><thead><tr><th>Saison</th><th class="left">Liga</th><th class="left">Mannschaft</th><th>G</th><th>PA</th><th>AB</th><th>R</th><th>RBI</th><th>H</th><th>2B</th><th>3B</th><th>HR</th><th>BB</th><th>SO</th><th>AVG</th><th>OBP</th><th>SLG</th><th>OPS</th><th>WAR*</th></tr></thead><tbody>${rows.map((row) => `<tr class="${rowClass(row)}"><td>${escapeHtml(row.season)}</td><td class="left">${escapeHtml(row.leagueName)}</td><td class="left">${renderHistoryTeamIdentity(row, teamCatalog)}</td><td>${row.games}</td><td>${row.pa}</td><td>${row.ab}</td><td>${row.runs}</td><td>${row.rbi}</td><td>${row.hits}</td><td>${row.doubles}</td><td>${row.triples}</td><td>${row.hr}</td><td>${row.bb}</td><td>${row.so}</td><td>${formatRate(row.avg)}</td><td>${formatRate(row.obp)}</td><td>${formatRate(row.slg)}</td><td>${formatRate(row.ops)}</td><td>${formatNumber(row.war, 2)}</td></tr>`).join('')}</tbody></table></div>`;
}

function pitchingTable(rows, teamCatalog = []) {
  if (!rows.length) return '<div class="empty-state">Keine Wurfstatistik für diesen Zeitraum vorhanden.</div>';
  return `<div class="table-scroll"><table class="stats-table history-table"><thead><tr><th>Saison</th><th class="left">Liga</th><th class="left">Mannschaft</th><th>G</th><th>GS</th><th>IP</th><th>W</th><th>L</th><th>SV</th><th>H</th><th>R</th><th>ER</th><th>HR</th><th>BB</th><th>SO</th><th>ERA</th><th>WHIP</th><th>FIP*</th><th>WAR*</th></tr></thead><tbody>${rows.map((row) => `<tr class="${rowClass(row)}"><td>${escapeHtml(row.season)}</td><td class="left">${escapeHtml(row.leagueName)}</td><td class="left">${renderHistoryTeamIdentity(row, teamCatalog)}</td><td>${row.games}</td><td>${row.gamesStarted}</td><td>${row.ipDisplay ?? formatInnings(row.ip)}</td><td>${row.wins}</td><td>${row.losses}</td><td>${row.saves}</td><td>${row.hits}</td><td>${row.runs}</td><td>${row.er}</td><td>${row.hr}</td><td>${row.bb}</td><td>${row.so}</td><td>${formatNumber(row.era, 2)}</td><td>${formatNumber(row.whip, 2)}</td><td>${formatNumber(row.fip, 2)}</td><td>${formatNumber(row.war, 2)}</td></tr>`).join('')}</tbody></table></div>`;
}


export function renderHistoryPanel(tableHtml, kind) {
  const note = kind === 'batting'
    ? 'Ligazeilen, Saison-Gesamtwerte und Karriere-Gesamtwert. WAR* ist ein Schätzwert.'
    : 'Ligazeilen, Saison-Gesamtwerte und Karriere-Gesamtwert. FIP und WAR* sind Schätzwerte.';
  return `<div class="player-history-pane">${tableHtml}<div class="player-history-note">${note}</div></div>`;
}

function leagueCount(rows, selection) {
  const selectedRows = selection === 'career'
    ? rows
    : rows.filter((row) => Number(row.season) === Number(selection));
  return new Set(selectedRows.map((row) => row.leagueKey).filter(Boolean)).size;
}

function seasonCardContent(kind, total, rows, selection, seasonCount) {
  const leagues = leagueCount(rows, selection);
  if (!total) {
    return `<strong>Keine Daten</strong><small>Für diese Spielzeit ist in der gewählten Kategorie keine Statistik vorhanden.</small>`;
  }
  if (kind === 'batting') {
    return `<strong>OPS ${formatRate(total.ops)}</strong><small>${total.games} Spiele · ${total.pa} PA · ${total.hr} HR<br>${leagues} ${leagues === 1 ? 'Liga' : 'Ligen'} · WAR* ${formatNumber(total.war, 2)}</small>`;
  }
  return `<strong>ERA ${formatNumber(total.era, 2)}</strong><small>${total.games} Spiele · ${formatInnings(total.ip)} IP · ${total.so} SO<br>${leagues} ${leagues === 1 ? 'Liga' : 'Ligen'} · WAR* ${formatNumber(total.war, 2)}</small>`;
}

function renderSeasonFilters(container, {
  kind, historyRows, rawRows, seasons, selectedSeason, onSelect,
}) {
  const career = selectedTotal(historyRows, 'career');
  const cards = [
    `<button type="button" class="summary-card career-season-card ${selectedSeason === 'career' ? 'active' : ''}" data-season="career" aria-pressed="${selectedSeason === 'career'}"><span>Gesamtübersicht</span>${seasonCardContent(kind, career, rawRows, 'career', seasons.length)}<em>${seasons.length} ${seasons.length === 1 ? 'Spielzeit' : 'Spielzeiten'}</em></button>`,
    ...seasons.map((season) => {
      const total = selectedTotal(historyRows, season);
      return `<button type="button" class="summary-card career-season-card ${Number(selectedSeason) === Number(season) ? 'active' : ''}" data-season="${season}" aria-pressed="${Number(selectedSeason) === Number(season)}"><span>${season}</span>${seasonCardContent(kind, total, rawRows, season, seasons.length)}<em>Saisonansicht</em></button>`;
    }),
  ];
  container.innerHTML = `<div class="season-filter-heading"><div><h2>Zeitraum auswählen</h2><p>Gesamtübersicht oder einzelne Spielzeit anzeigen.</p></div></div><div class="career-season-grid">${cards.join('')}</div>`;
  container.querySelectorAll('[data-season]').forEach((button) => button.addEventListener('click', () => {
    const value = button.dataset.season === 'career' ? 'career' : Number(button.dataset.season);
    onSelect(value);
  }));
}

function battingSummary(total) {
  return [
    ['Spiele', total.games], ['PA', total.pa], ['AVG', formatRate(total.avg)],
    ['OPS', formatRate(total.ops)], ['HR', total.hr], ['WAR*', formatNumber(total.war, 2)],
  ];
}

function pitchingSummary(total) {
  return [
    ['Spiele', total.games], ['IP', formatInnings(total.ip)], ['ERA', formatNumber(total.era, 2)],
    ['WHIP', formatNumber(total.whip, 2)], ['SO', total.so], ['WAR*', formatNumber(total.war, 2)],
  ];
}

function renderProfile(container, kind, total, pool, selection) {
  if (!total) {
    container.innerHTML = `<div class="empty-state profile-empty">Keine ${kind === 'batting' ? 'Schlagstatistik' : 'Wurfstatistik'} für diesen Zeitraum vorhanden.</div>`;
    return;
  }
  const title = selection === 'career' ? 'Karriereprofil' : `Saisonprofil ${selection}`;
  const subtitle = selection === 'career' ? 'Alle Spielzeiten zusammengefasst' : `Gesamtwerte der Spielzeit ${selection}`;
  const metrics = kind === 'batting' ? battingSummary(total) : pitchingSummary(total);
  const average = comparisonAverage(pool, kind);
  const axes = kind === 'batting' ? batterRadar(total, pool) : pitcherRadar(total, pool);
  const comparisonAxes = average
    ? (kind === 'batting' ? batterRadar(average, pool) : pitcherRadar(average, pool))
    : null;
  const comparisonText = selection === 'career'
    ? 'Gewichteter Liga-Durchschnitt aller Spielzeiten'
    : `Gewichteter Liga-Durchschnitt der Saison ${selection}`;
  container.innerHTML = `
    <div class="radar-heading"><strong>${title}</strong><span>${subtitle}</span></div>
    <div class="radar-chart-root"></div>
    <div class="radar-comparison-note">${comparisonText}</div>
    <div class="profile-summary-grid">${metrics.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join('')}</div>`;
  renderRadar(container.querySelector('.radar-chart-root'), axes, { comparisonAxes });
}

function updateSeasonInUrl(selection) {
  const url = new URL(window.location.href);
  if (selection === 'career') url.searchParams.delete('season');
  else url.searchParams.set('season', String(selection));
  window.history.replaceState(null, '', url);
}

async function main() {
  const app = document.getElementById('app');
  try {
    const [selectedData, allLeagueData] = await Promise.all([loadData(), loadAllData()]);
    const allRows = prepareRows(allLeagueData);
    const teamCatalog = buildTeamCatalog(allLeagueData);
    renderSiteHeader('player', selectedData);
    initGlobalSearch(allLeagueData);
    renderFooter(selectedData);
    const params = new URLSearchParams(location.search);
    const id = params.get('id');
    if (!id) {
      renderPicker(app, [...allRows.batting, ...allRows.pitching], selectedData, teamCatalog);
      return;
    }

    const batting = allRows.batting.filter((row) => String(row.personId) === id).sort((a, b) => Number(b.season) - Number(a.season));
    const pitching = allRows.pitching.filter((row) => String(row.personId) === id).sort((a, b) => Number(b.season) - Number(a.season));
    const base = batting[0] ?? pitching[0];
    if (!base) {
      app.innerHTML = `<div class="error-panel"><h2>Spieler nicht gefunden.</h2><p><a class="player-link" href="${leagueUrl('player.html', selectedData)}">Zur Spielersuche</a></p></div>`;
      return;
    }

    const battingHistory = buildBattingHistory(batting);
    const pitchingHistory = buildPitchingHistory(pitching);
    const battingCareer = selectedTotal(battingHistory, 'career');
    const pitchingCareer = selectedTotal(pitchingHistory, 'career');
    const years = [...new Set([...batting, ...pitching].map((row) => Number(row.season)))].sort((a, b) => b - a);
    const playerRows = [...batting, ...pitching];
    const requestedSeason = Number(params.get('season'));
    let selectedSeason = years.includes(requestedSeason) ? requestedSeason : 'career';
    let activeTab = batting.length ? 'batting' : 'pitching';

    app.innerHTML = `
      <div class="profile-topline"><a class="back-link" href="${leagueUrl('player.html', selectedData)}">← Zur Spielersuche</a><div id="leagueSwitcher"></div></div>
      <section class="card player-hero">${renderPlayerHeroMark(base, teamCatalog)}<div class="player-title"><h1>${escapeHtml(base.name)}</h1><div class="player-team-list">${renderPlayerTeamList(playerRows, teamCatalog)}</div><p class="player-years">${years.at(-1)}–${years[0]}</p></div><div class="player-total-war"><span>Karriere-WAR*</span><strong>${formatNumber((battingCareer?.war ?? 0) + (pitchingCareer?.war ?? 0), 2)}</strong></div></section>
      <section class="season-filter-section" id="seasonFilterRoot"></section>
      <section class="card career-card"><div class="card-header"><div class="record-tabs">${batting.length ? '<button class="active" type="button" data-tab="batting">Schlagstatistik</button>' : ''}${pitching.length ? '<button type="button" data-tab="pitching">Wurfstatistik</button>' : ''}</div><span class="meta-pill" id="selectionLabel">Gesamtübersicht</span></div><div class="player-history-layout"><div class="radar-panel" id="radarRoot"></div><div id="historyRoot"></div></div></section>`;
    renderLeagueSelector('leagueSwitcher', selectedData, { compact: true });

    const renderView = () => {
      const kind = activeTab;
      const historyRows = kind === 'batting' ? battingHistory : pitchingHistory;
      const rawRows = kind === 'batting' ? batting : pitching;
      const allKindRows = kind === 'batting' ? allRows.batting : allRows.pitching;
      const total = selectedTotal(historyRows, selectedSeason);
      const pool = comparisonTotals(allKindRows, kind, selectedSeason);
      const visibleRows = filterHistoryForSelection(historyRows, selectedSeason);

      document.querySelectorAll('[data-tab]').forEach((button) => button.classList.toggle('active', button.dataset.tab === activeTab));
      document.getElementById('selectionLabel').textContent = selectedSeason === 'career' ? 'Gesamtübersicht' : `Saison ${selectedSeason}`;
      renderSeasonFilters(document.getElementById('seasonFilterRoot'), {
        kind, historyRows, rawRows, seasons: years, selectedSeason,
        onSelect: (selection) => {
          selectedSeason = selection;
          updateSeasonInUrl(selection);
          renderView();
        },
      });
      renderProfile(document.getElementById('radarRoot'), kind, total, pool, selectedSeason);
      const historyTable = kind === 'batting'
        ? battingTable(visibleRows, teamCatalog)
        : pitchingTable(visibleRows, teamCatalog);
      document.getElementById('historyRoot').innerHTML = renderHistoryPanel(historyTable, kind);
    };

    document.querySelectorAll('[data-tab]').forEach((button) => button.addEventListener('click', () => {
      activeTab = button.dataset.tab;
      renderView();
    }));
    renderView();
  } catch (error) {
    renderError(app, error);
  }
}

if (typeof document !== 'undefined') main();
