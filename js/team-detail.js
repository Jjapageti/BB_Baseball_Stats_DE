import { renderTeamIdentity, resolveTeam } from './team.js';
import {
  createSortableTable,
  escapeHtml,
  formatNumber,
  formatRate,
  playerUrl,
} from './ui.js';

export function filterTeamRows(rows, teamId) {
  return (rows ?? []).filter((row) => String(row?.teamId) === String(teamId));
}

export function teamDetailHeading(team, league) {
  return {
    title: String(team?.name ?? 'Mannschaft'),
    subtitle: `${String(team?.acronym ?? '–')} · ${String(league?.name ?? 'Liga')} ${String(league?.season ?? '')}`.trim(),
  };
}

function battingColumns() {
  return [
    { key: 'name', label: 'Spieler', align: 'left', sticky: true, defaultDirection: 'asc', render: (row) => `<a class="player-link" href="${playerUrl(row)}">${escapeHtml(row.name)}</a>` },
    { key: 'games', label: 'G' }, { key: 'pa', label: 'PA' }, { key: 'ab', label: 'AB' },
    { key: 'runs', label: 'R' }, { key: 'rbi', label: 'RBI' }, { key: 'hits', label: 'H' },
    { key: 'doubles', label: '2B' }, { key: 'triples', label: '3B' }, { key: 'hr', label: 'HR' },
    { key: 'bb', label: 'BB' }, { key: 'so', label: 'SO' },
    { key: 'avg', label: 'AVG', render: (row) => formatRate(row.avg) },
    { key: 'obp', label: 'OBP', render: (row) => formatRate(row.obp) },
    { key: 'slg', label: 'SLG', render: (row) => formatRate(row.slg) },
    { key: 'ops', label: 'OPS', render: (row) => formatRate(row.ops) },
    { key: 'war', label: 'WAR*', render: (row) => `<strong class="${row.war >= 0 ? 'stat-positive' : 'stat-negative'}">${formatNumber(row.war, 2)}</strong>` },
  ];
}

function pitchingColumns() {
  return [
    { key: 'name', label: 'Spieler', align: 'left', sticky: true, defaultDirection: 'asc', render: (row) => `<a class="player-link" href="${playerUrl(row)}">${escapeHtml(row.name)}</a>` },
    { key: 'games', label: 'G' }, { key: 'gamesStarted', label: 'GS' },
    { key: 'ip', label: 'IP', render: (row) => escapeHtml(row.ipDisplay), sortValue: (row) => row.ip },
    { key: 'wins', label: 'W' }, { key: 'losses', label: 'L' }, { key: 'saves', label: 'SV' },
    { key: 'hits', label: 'H' }, { key: 'runs', label: 'R' }, { key: 'er', label: 'ER' },
    { key: 'hr', label: 'HR' }, { key: 'bb', label: 'BB' }, { key: 'so', label: 'SO' },
    { key: 'era', label: 'ERA', render: (row) => formatNumber(row.era, 2), defaultDirection: 'asc' },
    { key: 'whip', label: 'WHIP', render: (row) => formatNumber(row.whip, 2), defaultDirection: 'asc' },
    { key: 'fip', label: 'FIP*', render: (row) => formatNumber(row.fip, 2), defaultDirection: 'asc' },
    { key: 'war', label: 'WAR*', render: (row) => `<strong class="${row.war >= 0 ? 'stat-positive' : 'stat-negative'}">${formatNumber(row.war, 2)}</strong>` },
  ];
}

function openDialog(dialog) {
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
  document.body.classList.add('dialog-open');
}

function closeDialog(dialog) {
  if (typeof dialog.close === 'function') dialog.close();
  else dialog.removeAttribute('open');
  document.body.classList.remove('dialog-open');
}

export function initTeamDetailDialog({
  dialog,
  data,
  battingRows,
  pitchingRows,
  teams = [],
  onOpen = null,
  onClose = null,
}) {
  const titleRoot = dialog.querySelector('[data-team-detail-title]');
  const subtitleRoot = dialog.querySelector('[data-team-detail-subtitle]');
  const identityRoot = dialog.querySelector('[data-team-detail-identity]');
  const tableRoot = dialog.querySelector('[data-team-detail-table]');
  const countRoot = dialog.querySelector('[data-team-detail-count]');
  const tabs = [...dialog.querySelectorAll('[data-team-dataset]')];
  let selectedTeam = null;
  let dataset = 'batting';

  const draw = () => {
    if (!selectedTeam) return;
    const rows = dataset === 'batting'
      ? filterTeamRows(battingRows, selectedTeam.id)
      : filterTeamRows(pitchingRows, selectedTeam.id);
    tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.teamDataset === dataset));
    const table = createSortableTable({
      container: tableRoot,
      columns: dataset === 'batting' ? battingColumns() : pitchingColumns(),
      initialSort: { key: 'war', direction: 'desc' },
      emptyText: dataset === 'batting'
        ? 'Für diese Mannschaft sind keine Schlagdaten vorhanden.'
        : 'Für diese Mannschaft sind keine Wurfdaten vorhanden.',
    });
    table.update(rows);
    countRoot.textContent = `${rows.length.toLocaleString('de-DE')} Spieler`;
  };

  const open = (teamId) => {
    selectedTeam = resolveTeam({ teamId }, teams);
    if (!selectedTeam) return false;
    const heading = teamDetailHeading(selectedTeam, data.league);
    titleRoot.textContent = heading.title;
    subtitleRoot.textContent = heading.subtitle;
    identityRoot.innerHTML = renderTeamIdentity(selectedTeam, [selectedTeam], {
      size: 'lg', showAcronym: true, showName: false, className: 'team-dialog-identity',
    });
    const batting = filterTeamRows(battingRows, selectedTeam.id);
    const pitching = filterTeamRows(pitchingRows, selectedTeam.id);
    dataset = batting.length || !pitching.length ? 'batting' : 'pitching';
    draw();
    openDialog(dialog);
    onOpen?.(selectedTeam);
    return true;
  };

  const close = () => {
    closeDialog(dialog);
    onClose?.(selectedTeam);
  };

  tabs.forEach((tab) => tab.addEventListener('click', () => {
    dataset = tab.dataset.teamDataset;
    draw();
  }));
  dialog.querySelectorAll('[data-team-detail-close]').forEach((button) => button.addEventListener('click', close));
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) close();
  });
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    close();
  });

  return { open, close };
}
