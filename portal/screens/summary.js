// Screen 11 — the summary, and the end of the visit.
//
// The block has run out, the next winner has swapped in, and this is what the visitor
// walks away having seen: what they spent, what it bought, and what a view cost. Then the
// booth resets itself — twenty seconds, or A — so the next visitor starts from nothing.

import * as ui from '../ui.js';

const RESET_SECONDS = 20;

let data = null;
let left = RESET_SECONDS;
let timer = null;
let nodes = {};

function drawTable() {
  const body = ui.clear(nodes.table);
  body.append(ui.el('div', { class: 'rep-row head' },
    ui.el('span', { class: 'c-region' }, ui.bi('regions_region', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('summary_spent', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_views', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_visits', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_dwell', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('summary_cost_view', 'small'))));

  for (const row of data.regions) {
    body.append(ui.el('div', { class: `rep-row ${row.blocks ? '' : 'quiet'}`.trim() },
      ui.el('span', { class: 'c-region' }, ui.biRegion(row.label)),
      ui.el('span', { class: 'c mono accent', 'data-datum': true }, ui.num(row.charged)),
      ui.el('span', { class: 'c mono', 'data-datum': true }, ui.num(row.views)),
      ui.el('span', { class: 'c mono', 'data-datum': true }, ui.num(row.visits)),
      ui.el('span', { class: 'c mono', 'data-datum': true }, `${row.dwell_s.toFixed(1)} s`),
      ui.el('span', { class: 'c mono', 'data-datum': true },
            row.cost_per_view === null ? '—' : row.cost_per_view.toFixed(3))));
  }
}

function drawSide() {
  const totals = data.totals;
  ui.clear(nodes.side).append(
    ui.el('div', { class: 'card-row' },
      ui.bi('summary_spent', 'label'),
      ui.el('span', { class: 'val mono accent', 'data-datum': true },
            ui.num(totals.charged))),
    ui.el('div', { class: 'card-row' },
      ui.bi('report_views', 'label'),
      ui.el('span', { class: 'val mono', 'data-datum': true }, ui.num(totals.views))),
    ui.el('div', { class: 'card-row' },
      ui.bi('summary_cost_view', 'label'),
      ui.el('span', { class: 'val mono', 'data-datum': true },
            totals.cost_per_view === null ? '—' : totals.cost_per_view.toFixed(3))),
    ui.el('div', { class: 'grow' }),
    ui.el('div', { class: 'card-row' },
      ui.bi('summary_reset_in', 'label'),
      ui.el('span', { class: 'val mono', id: 'reset-left', 'data-datum': true },
            String(left))),
    ui.el('div', { class: 'button primary' }, ui.glyph('A'), ui.bi('summary_now')));
}

async function startOver(ctx) {
  if (timer) { clearInterval(timer); timer = null; }
  await ctx.api.reset().catch((problem) => console.error(problem));
  await ctx.afterReset();
}

export default {
  id: 'summary',
  showHeader: true,
  pollMs: 5000,
  hints: [['A', 'hint_start'], ['START', 'hint_menu']],

  async enter(ctx, root) {
    left = RESET_SECONDS;
    nodes = {};
    nodes.table = ui.el('div', { class: 'rep-rows' });
    nodes.side = ui.el('div', { class: 'body' });
    data = await ctx.api.report();

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('summary_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.bi('summary_sub', 'small'))),
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col grow' }, nodes.table),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 28rem' } }, nodes.side)));

    drawTable();
    drawSide();
    document.getElementById('app').dataset.state = 'summary';

    timer = setInterval(() => {
      left -= 1;
      const node = document.getElementById('reset-left');
      if (node) node.textContent = String(Math.max(0, left));
      if (left <= 0) startOver(ctx);
    }, 1000);
  },

  exit() {
    if (timer) { clearInterval(timer); timer = null; }
  },

  async refresh(ctx) {
    data = await ctx.api.report();
    drawTable();
  },

  pad(button, ctx) {
    if (button === 'A' || button === 'B') startOver(ctx);
  },
};
