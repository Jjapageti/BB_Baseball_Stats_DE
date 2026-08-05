import { clamp, percentile } from './stats.js';
import { escapeHtml } from './ui.js';

function polygonPoints(axes, point, radius) {
  return axes.map((axis, index) => {
    const score = clamp(Number(axis?.value ?? 0), 0, 100);
    return point(index, radius * score / 100).join(',');
  }).join(' ');
}

export function renderRadar(container, axes, {
  width = 500,
  height = 390,
  comparisonAxes = null,
  playerLabel = 'Spieler',
  comparisonLabel = 'Liga-Durchschnitt',
} = {}) {
  if (!axes?.length) {
    container.innerHTML = '';
    return;
  }

  const centerX = width / 2;
  const centerY = height / 2 - 5;
  const radius = Math.min(width * 0.23, height * 0.31);
  const labelDistance = radius + 48;
  const angle = (index) => (Math.PI * 2 * index) / axes.length - Math.PI / 2;
  const point = (index, distance) => {
    const a = angle(index);
    return [centerX + Math.cos(a) * distance, centerY + Math.sin(a) * distance];
  };

  const rings = [0.25, 0.5, 0.75, 1].map((ratio) => {
    const points = axes.map((_, index) => point(index, radius * ratio).join(',')).join(' ');
    return `<polygon points="${points}" class="radar-ring"/>`;
  }).join('');

  const spokes = axes.map((axis, index) => {
    const [x, y] = point(index, radius);
    const [lx, ly] = point(index, labelDistance);
    const anchor = Math.abs(lx - centerX) < 8 ? 'middle' : lx > centerX ? 'start' : 'end';
    return `
      <line x1="${centerX}" y1="${centerY}" x2="${x}" y2="${y}" class="radar-spoke"/>
      <text x="${lx}" y="${ly}" text-anchor="${anchor}" dominant-baseline="middle" class="radar-label">${escapeHtml(axis.label)}</text>
    `;
  }).join('');

  const values = polygonPoints(axes, point, radius);
  const comparable = Array.isArray(comparisonAxes) && comparisonAxes.length === axes.length;
  const comparisonPolygon = comparable
    ? `<polygon points="${polygonPoints(comparisonAxes, point, radius)}" class="radar-comparison"/>`
    : '';

  container.innerHTML = `
    <svg class="radar-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Leistungsprofil des Spielers im Vergleich zum Liga-Durchschnitt">
      ${rings}${spokes}
      ${comparisonPolygon}
      <polygon points="${values}" class="radar-value"/>
      <circle cx="${centerX}" cy="${centerY}" r="3" class="radar-center"/>
    </svg>
    <div class="radar-series-legend" aria-label="Legende">
      <span><i class="radar-key radar-key--player"></i>${escapeHtml(playerLabel)}</span>
      ${comparable ? `<span><i class="radar-key radar-key--comparison"></i>${escapeHtml(comparisonLabel)}</span>` : ''}
    </div>
    <div class="radar-legend">Perzentil innerhalb der Vergleichsgruppe · höher ist besser</div>
  `;
}

export function batterRadar(row, allRows) {
  const pool = allRows.filter((item) => item.pa > 0);
  return [
    { label: 'Kontakt', value: percentile(1 - row.kPct, pool, (item) => 1 - item.kPct) },
    { label: 'Schlagkraft', value: percentile(row.iso, pool, (item) => item.iso) },
    { label: 'Disziplin', value: percentile(row.bbPct, pool, (item) => item.bbPct) },
    { label: 'Basisquote', value: percentile(row.obp, pool, (item) => item.obp) },
    { label: 'Laufspiel', value: percentile(row.pa > 0 ? row.sb / row.pa : 0, pool, (item) => item.pa > 0 ? item.sb / item.pa : 0) },
    { label: 'Produktion', value: percentile(row.wrcPlus, pool, (item) => item.wrcPlus) },
  ];
}

export function pitcherRadar(row, allRows) {
  const pool = allRows.filter((item) => item.ip > 0);
  return [
    { label: 'Wurfqualität', value: percentile(row.k9, pool, (item) => item.k9) },
    { label: 'Kontrolle', value: percentile(row.bb9, pool, (item) => item.bb9, false) },
    { label: 'Punktevermeidung', value: percentile(row.eraPlus, pool, (item) => item.eraPlus) },
    { label: 'WHIP', value: percentile(row.whip, pool, (item) => item.whip, false) },
    { label: 'FIP', value: percentile(row.fipMinus, pool, (item) => item.fipMinus, false) },
    { label: 'Innings', value: percentile(row.ip, pool, (item) => item.ip) },
  ];
}
