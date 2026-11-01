// Screen 9 — the report.
//
// Per region, what the campaign bought and what it got. Views are **simulated + live and
// shown apart**: the simulated half is the same footfall model the slot card quoted a
// price against, counted for every block that has started, and the live half is what the
// game really reported. Visits, dwell and interactions are live only — real events, with
// no simulated model to be mixed up with.
//
// Pause is the brand's own switch, and pausing takes your content down (the slot is never
// empty: the game's own content comes back).

import * as ui from '../ui.js';

let data = null;
let focus = 0;
let buttons = [];
let nodes = {};

function cell(main, cls = '') {
  return ui.el('span', { class: `c ${cls}`.trim() },
    ui.el('span', { class: 'mono', 'data-datum': true }, main));
}

/** The two halves of "views" are their own columns, so neither can be read as the other. */
function drawTable() {
  const body = ui.clear(nodes.table);
  body.append(ui.el('div', { class: 'rep-row head' },
    ui.el('span', { class: 'c-region' }, ui.bi('regions_region', 'label')),
    ui.el('span', { class: 'c' }, ui.bi('report_simulated', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_live_counted', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_visits', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_dwell', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_interactions', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_charged', 'small')),
    ui.el('span', { class: 'c' }, ui.bi('report_per_1000', 'small'))));

  for (const row of data.regions) {
    body.append(ui.el('div', { class: `rep-row ${row.blocks ? '' : 'quiet'}`.trim() },
      ui.el('span', { class: 'c-region' }, ui.biRegion(row.label)),
      cell(ui.num(row.views_simulated)),
      cell(ui.num(row.views_live)),
      cell(ui.num(row.visits)),
      cell(`${row.dwell_s.toFixed(1)} s`),
      cell(ui.num(row.interactions)),
      cell(ui.num(row.charged), 'accent'),
      cell(row.cost_per_1000_views === null ? '—' : String(row.cost_per_1000_views))));
  }

  const totals = data.totals;
  body.append(ui.el('div', { class: 'rep-row total' },
    ui.el('span', { class: 'c-region' }, ui.bi('report_totals', 'label')),
    cell(ui.num(totals.views_simulated)),
    cell(ui.num(totals.views_live)),
    cell(ui.num(totals.visits)),
    cell(`${totals.dwell_s.toFixed(1)} s`),
    cell(ui.num(totals.interactions)),
    cell(ui.num(totals.charged), 'accent'),
    cell(totals.cost_per_1000_views === null ? '—' : String(totals.cost_per_1000_views))));
}

function drawSide(ctx, screen) {
  const active = data.regions.find((r) => r.time_left_s > 0);
  const blockSeconds = Number((data.clock || {}).block_seconds || 180);
  const left = active ? active.time_left_s : 0;
  const body = ui.clear(nodes.side);

  buttons = [
    { key: data.paused ? 'report_resume' : 'report_pause',
      run: async () => {
        await ctx.api.setPaused(!data.paused);
        await screen.refresh(ctx);
      } },
    { key: 'report_book_next', run: () => ctx.go('regions', { slot: ctx.state.slot }) },
    { key: 'report_push', glyph: 'Y', run: () => ctx.go('update') },
  ];

  const pieces = [
    ui.bi('report_time_left', 'label'),
    ui.el('div', { class: 'progress' },
      ui.el('div', { class: 'track' },
        ui.el('div', { class: 'fill', style: {
          width: `${Math.max(0, Math.min(100, (left / blockSeconds) * 100)).toFixed(1)}%` } })),
      ui.el('div', { class: 'meta' },
        ui.el('span', { class: 'pct mono', 'data-datum': true }, ui.mmss(left)))),
    data.paused ? ui.el('div', { class: 'refusal' }, ui.bi('report_paused', 'small')) : null,
    ui.el('div', { class: 'divider' }),
    ...buttons.map((button, i) => {
      const node = ui.el('div', { class: `button focusable ${i === 0 ? 'primary' : ''}`.trim() },
        ui.glyph(button.glyph || 'A'), ui.bi(button.key));
      node.dataset.action = button.key;
      return node;
    }),
    ui.el('div', { class: 'grow' }),
    ui.el('div', { class: 'credit-note' }, ui.bi('demo_credits_note')),
  ];
  body.append(...pieces.filter(Boolean));      // append() draws a null as the text "null"
  paintFocus();
}

function paintFocus() {
  [...nodes.side.querySelectorAll('.button')].forEach((node, i) => {
    node.classList.toggle('focused', i === focus);
  });
}

export default {
  id: 'report',
  showHeader: true,
  pollMs: 1000,
  hints: [['DPAD', 'hint_move'], ['A', 'hint_select'], ['Y', 'hint_push'],
          ['START', 'hint_menu'], ['B', 'hint_back']],

  async enter(ctx, root) {
    focus = 0;
    nodes = {};
    nodes.table = ui.el('div', { class: 'rep-rows' });
    nodes.side = ui.el('div', { class: 'body' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('report_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.bi('report_sub', 'small'))),
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col grow' }, nodes.table),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 31rem' } }, nodes.side)));

    await this.refresh(ctx);
  },

  async refresh(ctx) {
    data = await ctx.api.report();
    ctx.state.wallet = data.wallet || ctx.state.wallet;
    ctx.refreshHeader();
    drawTable(ctx);
    drawSide(ctx, this);
    document.getElementById('app').dataset.state = data.paused ? 'paused' : 'running';
  },

  pad(button, ctx) {
    if (button === 'UP') { focus = Math.max(0, focus - 1); paintFocus(); return; }
    if (button === 'DOWN') { focus = Math.min(buttons.length - 1, focus + 1); paintFocus(); return; }
    if (button === 'B') { ctx.go('live', { slot: ctx.state.slot }); return; }
    if (button === 'Y') { ctx.go('update'); return; }
    if (button === 'A') {
      const chosen = buttons[focus];
      if (chosen) Promise.resolve(chosen.run()).catch((problem) => console.error(problem));
    }
  },
};
