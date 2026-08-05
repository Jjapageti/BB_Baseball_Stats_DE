import { loadAllData, loadData } from './data.js';
import { buildBattingRows, buildLeagueContext, buildPitchingRows } from './stats.js';
import { renderTeamIdentity } from './team.js';
import { initGlobalSearch } from './search.js';
import {
  createSortableTable,
  escapeHtml,
  formatNumber,
  formatPct,
  formatRate,
  playerUrl,
  renderDataStatus,
  renderError,
  renderFooter,
  renderLeagueSelector,
  renderSiteHeader,
} from './ui.js';

export function getBattingColumns(leagueKey, teams = []) {
  return [
    { key: 'name', label: 'Spieler', align: 'left', sticky: true, defaultDirection: 'asc', render: (row) => `<a class="player-link" href="${playerUrl(row, leagueKey)}">${escapeHtml(row.name)}</a>` },
    { key: 'team', label: 'Mannschaft', align: 'left', render: (row) => renderTeamIdentity(row, teams, { size: 'xs', showAcronym: true, showName: true, className: 'records-team-identity' }) },
    { key: 'games', label: 'G' }, { key: 'pa', label: 'PA' }, { key: 'ab', label: 'AB' },
    { key: 'runs', label: 'R' }, { key: 'rbi', label: 'RBI' }, { key: 'hits', label: 'H' },
    { key: 'doubles', label: '2B' }, { key: 'triples', label: '3B' }, { key: 'hr', label: 'HR' },
    { key: 'bb', label: 'BB' }, { key: 'so', label: 'SO' }, { key: 'sb', label: 'SB' },
    { key: 'avg', label: 'AVG', render: (row) => formatRate(row.avg) },
    { key: 'obp', label: 'OBP', render: (row) => formatRate(row.obp) },
    { key: 'slg', label: 'SLG', render: (row) => formatRate(row.slg) },
    { key: 'ops', label: 'OPS', render: (row) => formatRate(row.ops) },
    { key: 'iso', label: 'ISO', render: (row) => formatRate(row.iso) },
    { key: 'bbPct', label: 'BB%', render: (row) => formatPct(row.bbPct) },
    { key: 'kPct', label: 'K%', render: (row) => formatPct(row.kPct) },
    { key: 'woba', label: 'wOBA*', render: (row) => formatRate(row.woba) },
    { key: 'opsPlus', label: 'OPS+*', render: (row) => formatNumber(row.opsPlus) },
    { key: 'wrcPlus', label: 'wRC+*', render: (row) => formatNumber(row.wrcPlus) },
    { key: 'war', label: 'WAR*', render: (row) => `<strong class="${row.war >= 0 ? 'stat-positive' : 'stat-negative'}">${formatNumber(row.war, 2)}</strong>` },
  ];
}

export function getPitchingColumns(leagueKey, teams = []) {
  return [
    { key: 'name', label: 'Spieler', align: 'left', sticky: true, defaultDirection: 'asc', render: (row) => `<a class="player-link" href="${playerUrl(row, leagueKey)}">${escapeHtml(row.name)}</a>` },
    { key: 'team', label: 'Mannschaft', align: 'left', render: (row) => renderTeamIdentity(row, teams, { size: 'xs', showAcronym: true, showName: true, className: 'records-team-identity' }) },
    { key: 'games', label: 'G' }, { key: 'gamesStarted', label: 'GS' },
    { key: 'ip', label: 'IP', render: (row) => escapeHtml(row.ipDisplay), sortValue: (row) => row.ip },
    { key: 'wins', label: 'W' }, { key: 'losses', label: 'L' }, { key: 'saves', label: 'SV' },
    { key: 'hits', label: 'H' }, { key: 'runs', label: 'R' }, { key: 'er', label: 'ER' },
    { key: 'hr', label: 'HR' }, { key: 'bb', label: 'BB' }, { key: 'so', label: 'SO' },
    { key: 'era', label: 'ERA', render: (row) => formatNumber(row.era, 2), defaultDirection: 'asc' },
    { key: 'whip', label: 'WHIP', render: (row) => formatNumber(row.whip, 2), defaultDirection: 'asc' },
    { key: 'fip', label: 'FIP*', render: (row) => formatNumber(row.fip, 2), defaultDirection: 'asc' },
    { key: 'k9', label: 'K/9', render: (row) => formatNumber(row.k9, 2) },
    { key: 'bb9', label: 'BB/9', render: (row) => formatNumber(row.bb9, 2), defaultDirection: 'asc' },
    { key: 'hr9', label: 'HR/9', render: (row) => formatNumber(row.hr9, 2), defaultDirection: 'asc' },
    { key: 'kbb', label: 'K/BB', render: (row) => formatNumber(row.kbb, 2) },
    { key: 'eraPlus', label: 'ERA+*', render: (row) => formatNumber(Math.min(row.eraPlus, 999)) },
    { key: 'fipMinus', label: 'FIP-*', render: (row) => formatNumber(row.fipMinus), defaultDirection: 'asc' },
    { key: 'war', label: 'WAR*', render: (row) => `<strong class="${row.war >= 0 ? 'stat-positive' : 'stat-negative'}">${formatNumber(row.war, 2)}</strong>` },
  ];
}

async function main() {
  const app = document.getElementById('app');
  try {
    const [data, allLeagueData] = await Promise.all([loadData(), loadAllData()]);
    const context = buildLeagueContext(data);
    const all = {
      batting: buildBattingRows(data.batting, context),
      pitching: buildPitchingRows(data.pitching, context),
    };
    let dataset = 'batting';

    renderSiteHeader('records', data);
    initGlobalSearch(allLeagueData);
    renderFooter(data);
    renderLeagueSelector('leagueSwitcher', data, { compact: true });
    renderDataStatus('dataStatus', data);
    document.getElementById('seasonText').textContent = `${data.league.name} ${data.league.season}`;

    const teamFilter = document.getElementById('teamFilter');
    teamFilter.innerHTML = '<option value="all">Alle Mannschaften</option>' + data.teams
      .map((team) => `<option value="${team.id}">${escapeHtml(team.name)}</option>`).join('');

    const minInput = document.getElementById('minValue');
    const minLabel = document.getElementById('minLabel');
    const qualified = document.getElementById('qualifiedOnly');
    const search = document.getElementById('searchInput');
    const notes = document.getElementById('metricNotes');

    const setDatasetUi = () => {
      document.querySelectorAll('[data-dataset]').forEach((button) => {
        button.classList.toggle('active', button.dataset.dataset === dataset);
      });
      minLabel.textContent = dataset === 'batting' ? 'Mindest-PA' : 'Mindest-IP';
      minInput.value = dataset === 'batting' ? context.minPA : context.minIP;
      notes.textContent = dataset === 'batting'
        ? `Standard: ${context.minPA} PA · OPS+, wRC+ und WAR* sind Schätzwerte ohne vollständige Park- und Defensivkorrektur.`
        : `Standard: ${context.minIP} IP · FIP, ERA+, FIP- und WAR* werden aus den veröffentlichten Rohdaten geschätzt.`;
    };

    const render = () => {
      const teamId = teamFilter.value;
      const query = search.value.trim().toLowerCase();
      const min = Number(minInput.value) || 0;
      const metric = dataset === 'batting' ? 'pa' : 'ip';
      const rows = all[dataset].filter((row) => {
        const matchesTeam = teamId === 'all' || String(row.teamId) === teamId;
        const matchesName = !query || `${row.name} ${row.team} ${row.acronym}`.toLowerCase().includes(query);
        const matchesMinimum = !qualified.checked || row[metric] >= min;
        return matchesTeam && matchesName && matchesMinimum;
      });
      const columns = dataset === 'batting'
        ? getBattingColumns(data.selectedLeagueKey, data.teams)
        : getPitchingColumns(data.selectedLeagueKey, data.teams);
      const table = createSortableTable({
        container: document.getElementById('tableRoot'),
        columns,
        initialSort: { key: 'war', direction: 'desc' },
      });
      table.update(rows);
      document.getElementById('recordCount').textContent = `${rows.length.toLocaleString('de-DE')} Spieler`;
    };

    document.querySelectorAll('[data-dataset]').forEach((button) => {
      button.addEventListener('click', () => {
        dataset = button.dataset.dataset;
        setDatasetUi();
        render();
      });
    });
    [teamFilter, minInput, qualified].forEach((element) => element.addEventListener('change', render));
    search.addEventListener('input', render);
    setDatasetUi();
    render();
  } catch (error) {
    renderError(app, error);
  }
}

if (typeof document !== 'undefined') main();
