import { buildSelectionUrl, persistSelection } from './data.js';

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

export function formatNumber(value, digits = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '–';
  return number.toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatRate(value, digits = 3) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '–';
  return number.toFixed(digits).replace(/^0(?=\.)/, '');
}

export function formatPct(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '–';
  return `${(number * 100).toFixed(digits).replace('.', ',')} %`;
}

export function formatSigned(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '–';
  const text = number.toFixed(digits).replace('.', ',');
  return number > 0 ? `+${text}` : text;
}

function currentRelativeUrl() {
  if (typeof window === 'undefined') return 'dashboard.html';
  const file = window.location.pathname.split('/').pop() || 'dashboard.html';
  return `${file}${window.location.search}${window.location.hash}`;
}

function selectionFromData(data) {
  return { season: data.selectedSeason, leagueKey: data.selectedLeagueKey };
}

export function leagueUrl(href, selectionOrData, leagueKey = null) {
  const selection = typeof selectionOrData === 'object'
    ? ('selectedSeason' in selectionOrData ? selectionFromData(selectionOrData) : selectionOrData)
    : { season: new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '').get('season') ?? 2026, leagueKey: leagueKey ?? selectionOrData };
  return buildSelectionUrl(href, selection);
}

export function playerUrl(row) {
  const params = new URLSearchParams({ id: row.personId });
  return `player.html?${params.toString()}`;
}

export function parseBsmDate(value) {
  if (!value) return null;
  const normalized = String(value).replace(' ', 'T').replace(/ ([+-]\d{2})(\d{2})$/, '$1:$2');
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatMatchDate(value, includeYear = false) {
  const date = parseBsmDate(value);
  if (!date) return '–';
  return new Intl.DateTimeFormat('de-DE', {
    ...(includeYear ? { year: 'numeric' } : {}), day: '2-digit', month: '2-digit', weekday: 'short', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

export function renderLeagueSelector(containerOrId, data, { compact = false, label = 'Saison und Liga' } = {}) {
  const container = typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
  if (!container) return;
  const seasons = data?.catalog?.seasons ?? [];
  const selectedSeason = seasons.find((row) => row.season === Number(data.selectedSeason)) ?? seasons[0];
  container.innerHTML = `
    <div class="season-league-selector ${compact ? 'compact' : ''}">
      <span>${escapeHtml(label)}</span>
      <div class="selector-fields">
        <label><small>Saison</small><select data-role="season" aria-label="Saison">
          ${seasons.map((row) => `<option value="${row.season}" ${row.season === data.selectedSeason ? 'selected' : ''}>${row.season}</option>`).join('')}
        </select></label>
        <label><small>Liga</small><select data-role="league" aria-label="Liga">
          ${(selectedSeason?.leagues ?? []).map((league) => `<option value="${escapeHtml(league.key)}" ${league.key === data.selectedLeagueKey ? 'selected' : ''}>${escapeHtml(league.name)}${league.stage === 'postseason' ? ' · Postseason' : ''}</option>`).join('')}
        </select></label>
      </div>
    </div>`;
  const seasonSelect = container.querySelector('[data-role="season"]');
  const leagueSelect = container.querySelector('[data-role="league"]');
  const navigate = (season, leagueKey) => {
    const selection = { season: Number(season), leagueKey };
    persistSelection(selection);
    window.location.href = buildSelectionUrl(currentRelativeUrl(), selection);
  };
  seasonSelect?.addEventListener('change', () => {
    const seasonRow = seasons.find((row) => row.season === Number(seasonSelect.value));
    navigate(seasonSelect.value, seasonRow?.leagues?.[0]?.key);
  });
  leagueSelect?.addEventListener('change', () => navigate(seasonSelect.value, leagueSelect.value));
}

export function renderSiteHeader(active, data) {
  const root = document.getElementById('siteHeader');
  if (!root) return;
  const items = [['dashboard', 'dashboard.html', 'Übersicht'], ['records', 'index.html', 'Spielerstatistiken'], ['player', 'player.html', 'Spielersuche']];
  root.innerHTML = `
    <div class="header-inner">
      <a class="brand" href="${leagueUrl('dashboard.html', data)}" aria-label="Zur Übersicht">
        <span class="brand-mark">B</span><span><strong>BB Baseball Stats</strong><small>${escapeHtml(data?.league?.season ?? '')} · ${escapeHtml(data?.league?.acronym ?? '')}</small></span>
      </a>
      <div class="header-actions">
        <div class="global-search" id="globalSearch">
          <label class="sr-only" for="globalSearchInput">Mannschaft oder Spieler suchen</label>
          <input id="globalSearchInput" type="search" placeholder="Mannschaft oder Spieler suchen" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="globalSearchResults">
          <div class="global-search-results" id="globalSearchResults" data-search-results role="listbox" hidden></div>
        </div>
        <nav class="site-nav" aria-label="Hauptnavigation">
          ${items.map(([key, href, text]) => `<a href="${leagueUrl(href, data)}" class="${active === key ? 'active' : ''}">${text}</a>`).join('')}
        </nav>
      </div>
    </div>`;
}

export function renderFooter(data) {
  const root = document.getElementById('siteFooter');
  if (!root) return;
  const generated = data?.generated_at ? new Date(data.generated_at) : null;
  const generatedText = generated && !Number.isNaN(generated.getTime()) ? generated.toLocaleString('de-DE') : 'noch nicht synchronisiert';
  root.innerHTML = `<div>Inoffizielle Auswertung öffentlich verfügbarer BSM-Statistiken.</div><div>Datenstand: ${escapeHtml(generatedText)} · Mit * gekennzeichnete Kennzahlen sind Schätzwerte.</div>`;
}

export function renderDataStatus(containerOrId, data) {
  const container = typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
  if (!container) return;
  container.innerHTML = data?.data_status === 'not_synced'
    ? '<section class="status-panel warning"><strong>Die Daten wurden noch nicht synchronisiert.</strong></section>'
    : '';
}

export function renderError(container, error) {
  container.innerHTML = `<section class="error-panel"><h2>Die Daten können nicht angezeigt werden.</h2><pre>${escapeHtml(error?.message ?? error)}</pre><p>Bitte die HTML-Datei nicht direkt öffnen, sondern Live Server oder <code>start_server.bat</code> verwenden.</p></section>`;
}

export function createSortableTable({ container, columns, initialSort, emptyText = 'Keine Datensätze vorhanden.' }) {
  let rows = [];
  let sort = initialSort ?? { key: columns[0]?.key, direction: 'asc' };
  const sortRows = () => {
    const column = columns.find((item) => item.key === sort.key);
    if (!column) return [...rows];
    const getValue = column.sortValue ?? ((row) => row[column.key]);
    return [...rows].sort((a, b) => {
      const left = getValue(a); const right = getValue(b);
      const result = Number.isFinite(Number(left)) && Number.isFinite(Number(right))
        ? Number(left) - Number(right)
        : String(left ?? '').localeCompare(String(right ?? ''), 'de');
      return sort.direction === 'asc' ? result : -result;
    });
  };
  const render = () => {
    if (!rows.length) { container.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`; return; }
    const sorted = sortRows();
    container.innerHTML = `<div class="table-scroll"><table class="stats-table"><thead><tr>${columns.map((column) => {
      const active = sort.key === column.key; const arrow = active ? (sort.direction === 'asc' ? '▲' : '▼') : '';
      return `<th class="${column.align === 'left' ? 'left' : ''} ${column.sticky ? 'sticky-col' : ''}" data-sort="${escapeHtml(column.key)}"><button type="button">${escapeHtml(column.label)} <span>${arrow}</span></button></th>`;
    }).join('')}</tr></thead><tbody>${sorted.map((row, index) => `<tr>${columns.map((column) => {
      const content = column.render ? column.render(row, index) : escapeHtml(row[column.key] ?? '–');
      return `<td class="${column.align === 'left' ? 'left' : ''} ${column.sticky ? 'sticky-col' : ''} ${column.className ?? ''}">${content}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table></div>`;
    container.querySelectorAll('th[data-sort]').forEach((th) => th.addEventListener('click', () => {
      const key = th.dataset.sort;
      sort = sort.key === key ? { key, direction: sort.direction === 'asc' ? 'desc' : 'asc' } : { key, direction: columns.find((column) => column.key === key)?.defaultDirection ?? 'desc' };
      render();
    }));
  };
  return { update(nextRows) { rows = nextRows; render(); }, setSort(key, direction = 'desc') { sort = { key, direction }; render(); } };
}
