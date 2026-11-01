// Screen 7 — it goes live by itself.
//
// There is no publish button in this demo and there is no publish button in the patent:
// winning the lot writes the allocation, the game finds out by polling, and the content
// is fetched when a player walks near the slot. So this screen is a watch, not a wizard.
//
// Two of the four steps are things this server really knows and two are not, and the
// screen says which is which:
//   * Resolve  — `/status/live` says the platform now answers this slot with your
//                content: real, server-side, true the moment the lot closed.
//   * Download, Verify — these happen on the player's machine. The portal cannot see
//                them; the game's own status strip can, and does, on the other monitor.
//   * Mount    — the game reports it as telemetry, and `/report` counts it per region.
// So the middle two are drawn as in flight until the mount is reported, and they are
// labelled with where they are happening. Nothing here is a timer pretending to be work.

import * as ui from '../ui.js';

const STEPS = [
  ['live_step_alloc', 'live_step_alloc_sub'],
  ['live_step_download', 'live_step_dl_sub'],
  ['live_step_verify', 'live_step_verify_sub'],
  ['live_step_mount', 'live_step_mount_sub'],
];

let slot = null;
let region = null;
let nodes = {};
let mounted = false;
let resolved = false;

function drawSteps() {
  const body = ui.clear(nodes.steps);
  STEPS.forEach(([key, subKey], index) => {
    const done = index === 0 ? resolved : (index === 3 ? mounted : mounted);
    const busy = !done && resolved;
    body.append(ui.el('div', { class: `step ${done ? 'done' : busy ? 'busy' : ''}`.trim() },
      ui.el('span', { class: 'mark', 'data-datum': true },
            done ? '✓' : busy ? '…' : String(index + 1)),
      ui.el('span', { class: 'what' }, ui.bi(key)),
      ui.bi(subKey, 'small tail')));
  });
  document.getElementById('app').dataset.state = mounted ? 'mounted'
    : resolved ? 'resolved' : 'waiting';
}

function drawSide(ctx, live, report) {
  const body = ui.clear(nodes.side);
  const mineRow = live.find((r) => r.slot === slot && r.region === region
                                   && r.kind === 'visitor');
  const brand = (mineRow && mineRow.brand) || ctx.state.brand;
  const regionRow = (report.regions || []).find((r) => r.region === region) || {};

  body.append(
    ui.el('div', { class: 'row' },
      ui.brandMark(brand, 'big'),
      ui.biText(`スロット ${slot}`, `Slot ${slot}`, 'h2-like'),
      ui.el('span', { class: 'grow' }),
      ui.el('span', { class: 'badge quiet' },
        ui.biRegion((ctx.state.config.regions[region] || {}).label || region, 'small'))),
    ui.el('div', { class: 'card-row' },
      ui.bi('live_ends_in', 'small'),
      ui.el('span', { class: 'val mono', 'data-datum': true },
            ui.mmss(regionRow.time_left_s))),
    ui.el('div', { class: 'divider' }),
    ui.el('div', { class: 'region-table' },
      Object.entries(ctx.state.config.regions).map(([id, meta]) => {
        const row = live.find((r) => r.slot === slot && r.region === id);
        const kind = row ? row.kind : 'none';
        return ui.el('div', { class: `r ${kind === 'visitor' ? 'yours' : ''}`.trim() },
          ui.brandMark(row && row.brand),
          ui.el('span', { class: 'name' }, ui.biRegion(meta.label, 'small')),
          ui.bi(kind === 'visitor' ? 'showing_you'
                : kind === 'rival' ? 'showing_rival'
                : kind === 'default' ? 'showing_default' : 'showing_none', 'small'));
      })),
    ui.el('div', { class: 'grow' }),
    ui.el('div', { class: 'button primary' }, ui.glyph('A'), ui.bi('live_to_report')));
}

export default {
  id: 'live',
  showHeader: true,
  pollMs: 1000,
  hints: [['A', 'hint_next'], ['START', 'hint_menu'], ['B', 'hint_back']],

  async enter(ctx, root, params) {
    slot = (params && params.slot) || ctx.state.slot || 'A1';
    region = (ctx.state.config.booth || {}).main_region || 'r1';
    mounted = false;
    resolved = false;

    nodes = {};
    nodes.steps = ui.el('div', { class: 'steps' });
    nodes.side = ui.el('div', { class: 'body' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('live_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.bi('live_sub', 'small'))),
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col grow' },
          nodes.steps,
          ui.el('div', { class: 'grow' }),
          ui.el('div', { class: 'marker-note' }, ui.bi('live_marker'))),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 30rem' } }, nodes.side)));

    drawSteps();
    await this.refresh(ctx);
  },

  async refresh(ctx) {
    const [live, report] = await Promise.all([ctx.api.liveStatus(), ctx.api.report()]);
    const rows = live.showing || [];
    resolved = rows.some((r) => r.slot === slot && r.region === region
                                && r.kind === 'visitor');
    const regionRow = (report.regions || []).find((r) => r.region === region) || {};
    mounted = resolved && (regionRow.mounts || 0) > 0;
    ctx.state.wallet = report.wallet || ctx.state.wallet;
    ctx.refreshHeader();
    drawSteps();
    drawSide(ctx, rows, report);
  },

  pad(button, ctx) {
    if (button === 'A' || button === 'Y') ctx.go('report');
    else if (button === 'B') ctx.go('slotmap', { game: ctx.state.game });
  },
};
