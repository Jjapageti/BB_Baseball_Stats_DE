import { loadAllData, loadData } from './data.js';
import {
  buildLeagueContext,
  buildBattingRows,
  buildPitchingRows,
  buildCombinedWar,
} from './stats.js';
import {
  renderMatchTeamIdentity,
  renderTeamIdentity,
  resolveTeam,
} from './team.js';
import { initGlobalSearch } from './search.js';
import { initTeamDetailDialog } from './team-detail.js';
import {
  escapeHtml,
  formatMatchDate,
  formatNumber,
  formatRate,
  playerUrl,
  renderDataStatus,
  renderError,
  renderFooter,
  renderLeagueSelector,
  renderSiteHeader,
} from './ui.js';

function renderSummary(data, context) {
  const mergeNote = data.league.merged ? 'DivA und DivB zusammengeführt' : data.league.acronym;
  const cards = [
    ['Mannschaften', data.counts.teams, mergeNote],
    ['Spiele', data.counts.matches, `${data.counts.played_matches} abgeschlossen`],
    ['Batter', data.counts.batters, `Qualifikation: ${context.minPA} PA`],
    ['Pitcher', data.counts.pitchers, `Qualifikation: ${context.minIP} IP`],
    ['Liga-OPS', context.lgOPS, 'PA-gewichteter Mittelwert'],
  ];
  document.getElementById('summaryCards').innerHTML = cards.map(([label, value, note], index) => `
    <article class="summary-card">
      <span>${escapeHtml(label)}</span>
      <strong>${index === 4 ? formatRate(value) : formatNumber(value)}</strong>
      <small>${escapeHtml(note)}</small>
    </article>
  `).join('');
}

export function resolveStandingTeam(row, teams = []) {
  return resolveTeam({
    teamId: row?.league_entry_id,
    team: row?.team,
    acronym: row?.acronym,
  }, teams);
}

export function renderStandingTeamIdentity(row, teams = []) {
  return renderTeamIdentity({
    teamId: row?.league_entry_id,
    team: row?.team,
    acronym: row?.acronym,
  }, teams, { size: 'sm', strongName: true, className: 'standing-team' });
}

export function renderStandingTeamButton(row, teams = []) {
  const team = resolveStandingTeam(row, teams);
  const teamId = team?.id ?? row?.league_entry_id;
  return `<button type="button" class="standing-team-button" data-team-id="${escapeHtml(teamId)}" aria-label="Teamstatistik öffnen: ${escapeHtml(row?.team ?? team?.name ?? 'Mannschaft')}">${renderStandingTeamIdentity(row, teams)}</button>`;
}

function renderStandings(rows, teams = []) {
  document.getElementById('standings').innerHTML = rows.length ? `
    <div class="table-scroll">
      <table class="stats-table">
        <thead><tr><th>Pl.</th><th class="left">Mannschaft</th><th>Sp.</th><th>S</th><th>N</th><th>Quote</th><th>Diff.</th></tr></thead>
        <tbody>
          ${rows.map((row) => `
            <tr>
              <td class="rank">${row.rank}</td>
              <td class="left">${renderStandingTeamButton(row, teams)}</td>
              <td>${row.games}</td><td>${row.wins}</td><td>${row.losses}</td>
              <td>${formatRate(row.win_pct)}</td>
              <td class="${row.run_diff > 0 ? 'stat-positive' : row.run_diff < 0 ? 'stat-negative' : ''}">${row.run_diff > 0 ? '+' : ''}${row.run_diff}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  ` : '<div class="empty-state">Noch keine Tabellenwerte vorhanden.</div>';
}

export function renderWarTeamIdentity(row, teams = []) {
  return renderTeamIdentity(row, teams, {
    size: 'xs',
    showAcronym: true,
    showName: true,
    className: 'war-team-identity',
  });
}

function renderWar(rows, leagueKey, teams = []) {
  document.getElementById('warTop').innerHTML = rows.length ? `
    <div class="table-scroll">
      <table class="stats-table">
        <thead><tr><th>Pl.</th><th class="left">Spieler</th><th class="left">Mannschaft</th><th>Bat*</th><th>Pitch*</th><th>WAR*</th></tr></thead>
        <tbody>
          ${rows.slice(0, 10).map((row, index) => `
            <tr>
              <td class="rank">${index + 1}</td>
              <td class="left"><a class="player-link" href="${playerUrl(row, leagueKey)}">${escapeHtml(row.name)}</a></td>
              <td class="left">${renderWarTeamIdentity(row, teams)}</td>
              <td>${formatNumber(row.battingWar, 2)}</td>
              <td>${formatNumber(row.pitchingWar, 2)}</td>
              <td class="stat-positive">${formatNumber(row.war, 2)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  ` : '<div class="empty-state">Noch keine WAR-Werte vorhanden.</div>';
}

export function leaderBox(title, rows, value, leagueKey, teams = []) {
  return `
    <section class="leader-box">
      <h4>${escapeHtml(title)}</h4>
      ${rows.length ? rows.slice(0, 3).map((row, index) => `
        <div class="leader-row">
          <span class="position">${index + 1}</span>
          <div class="leader-player">
            <a class="name player-link" href="${playerUrl(row, leagueKey)}">${escapeHtml(row.name)}</a>
            <span class="leader-team-mark">${renderTeamIdentity(row, teams, { size: 'xs', showAcronym: true, showName: false })}</span>
          </div>
          <span class="value">${escapeHtml(value(row))}</span>
        </div>
      `).join('') : '<div class="leader-empty">Keine Daten</div>'}
    </section>
  `;
}

function renderLeaders(battingRows, pitchingRows, context, leagueKey, teams = []) {
  const qualifiedBatters = battingRows.filter((row) => row.pa >= context.minPA);
  const qualifiedPitchers = pitchingRows.filter((row) => row.ip >= context.minIP);
  const descending = (key) => (a, b) => b[key] - a[key];
  const ascending = (key) => (a, b) => a[key] - b[key];

  document.getElementById('hitterLeaders').innerHTML = [
    leaderBox('OPS', [...qualifiedBatters].sort(descending('ops')), (row) => formatRate(row.ops), leagueKey, teams),
    leaderBox('AVG', [...qualifiedBatters].sort(descending('avg')), (row) => formatRate(row.avg), leagueKey, teams),
    leaderBox('Home Runs', [...battingRows].sort(descending('hr')), (row) => String(row.hr), leagueKey, teams),
    leaderBox('wRC+*', [...qualifiedBatters].sort(descending('wrcPlus')), (row) => formatNumber(row.wrcPlus), leagueKey, teams),
  ].join('');

  document.getElementById('pitcherLeaders').innerHTML = [
    leaderBox('ERA', [...qualifiedPitchers].sort(ascending('era')), (row) => formatNumber(row.era, 2), leagueKey, teams),
    leaderBox('FIP*', [...qualifiedPitchers].sort(ascending('fip')), (row) => formatNumber(row.fip, 2), leagueKey, teams),
    leaderBox('Strikeouts', [...pitchingRows].sort(descending('so')), (row) => String(row.so), leagueKey, teams),
    leaderBox('WHIP', [...qualifiedPitchers].sort(ascending('whip')), (row) => formatNumber(row.whip, 2), leagueKey, teams),
  ].join('');
}

export function renderMatchList(matches, finished, teams = []) {
  return matches.length ? matches.map((match) => `
    <div class="match-row">
      <div class="date">${formatMatchDate(match.time)}</div>
      <div class="match-team match-team--home">${renderMatchTeamIdentity(match, 'home', teams, { align: 'right', showAcronym: false })}</div>
      <div class="score">${finished ? `${match.home_runs ?? '–'} : ${match.away_runs ?? '–'}` : 'VS'}</div>
      <div class="match-team match-team--away">${renderMatchTeamIdentity(match, 'away', teams, { align: 'left', showAcronym: false })}</div>
    </div>
  `).join('') : '<div class="empty-state">Keine Spiele vorhanden.</div>';
}

function renderMatches(data) {
  const played = [...data.matches]
    .filter((match) => ['played', 'manually_valued'].includes(match.state))
    .sort((a, b) => String(b.time).localeCompare(String(a.time)))
    .slice(0, 6);
  const upcoming = [...data.matches]
    .filter((match) => match.state === 'planned')
    .sort((a, b) => String(a.time).localeCompare(String(b.time)))
    .slice(0, 6);

  document.getElementById('recentMatches').innerHTML = renderMatchList(played, true, data.teams);
  document.getElementById('upcomingMatches').innerHTML = renderMatchList(upcoming, false, data.teams);
}

async function main() {
  const root = document.getElementById('app');
  try {
    const [data, allLeagueData] = await Promise.all([loadData(), loadAllData()]);
    const context = buildLeagueContext(data);
    const battingRows = buildBattingRows(data.batting, context);
    const pitchingRows = buildPitchingRows(data.pitching, context);
    const warRows = buildCombinedWar(battingRows, pitchingRows);
    renderSiteHeader('dashboard', data);
    initGlobalSearch(allLeagueData);
    renderFooter(data);
    renderLeagueSelector('leagueSwitcher', data);
    renderDataStatus('dataStatus', data);
    document.getElementById('leagueTitle').textContent = `${data.league.name} ${data.league.season}`;
    document.getElementById('leagueDescription').textContent = data.leagueConfig.description;
    const generated = data.data_status === 'not_synced'
      ? 'Noch keine Daten synchronisiert'
      : `Datenstand: ${new Date(data.generated_at).toLocaleString('de-DE')}`;
    document.getElementById('generatedAt').textContent = generated;
    renderSummary(data, context);
    renderStandings(data.standings, data.teams);
    renderWar(warRows, data.selectedLeagueKey, data.teams);
    renderLeaders(battingRows, pitchingRows, context, data.selectedLeagueKey, data.teams);
    renderMatches(data);

    const dialog = document.getElementById('teamDetailDialog');
    const updateTeamParameter = (teamId = null) => {
      const url = new URL(window.location.href);
      if (teamId === null) url.searchParams.delete('team');
      else url.searchParams.set('team', String(teamId));
      window.history.replaceState(null, '', url);
    };
    const teamDetail = initTeamDetailDialog({
      dialog,
      data,
      battingRows,
      pitchingRows,
      teams: data.teams,
      onOpen: (team) => updateTeamParameter(team.id),
      onClose: () => updateTeamParameter(null),
    });
    document.querySelectorAll('[data-team-id]').forEach((button) => {
      button.addEventListener('click', () => teamDetail.open(button.dataset.teamId));
    });
    const requestedTeam = new URLSearchParams(window.location.search).get('team');
    if (requestedTeam) teamDetail.open(requestedTeam);
  } catch (error) {
    renderError(root, error);
  }
}

if (typeof document !== 'undefined') main();
