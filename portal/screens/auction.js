// Screen 6 — the auction.
//
// Polled twice a second, because the two things this screen exists to show are both
// sudden: the rival's single counter-bid (three seconds after your first bid) and the
// soft close (a bid inside the last ten seconds puts the clock back to ten). The server
// has no timers — the poll itself is what makes a due counter-bid or a due close happen
// — so a visitor watching this screen is what settles the auction.
//
// Nothing here is scripted in the portal: the banner appears because a lot the visitor
// was leading came back from the server held by the rival.

import * as ui from '../ui.js';

const BANNER_MS = 6000;
const SOFT_BADGE_MS = 4000;

let slot = null;
let rows = [];               // {region, label, lot, bid}
let focus = 0;
let previous = new Map();    // lot_id -> the last card we saw
let bannerUntil = 0;
let bannerRegion = null;
let softUntil = new Map();
let settled = false;
let nodes = {};

/** `/lots` answers with every block's lot for a slot; the live one is the newest. */
export function newestPerRegion(lots, slot) {
  const best = new Map();
  for (const lot of lots) {
    if (lot.slot !== slot) continue;
    const have = best.get(lot.region);
    if (!have || lot.seq > have.seq) best.set(lot.region, lot);
  }
  return [...best.values()];
}

function statusKey(row) {
  const lot = row.lot;
  if (!lot) return 'status_idle';
  if (lot.state === 'closed') return lot.won_by === 'you' ? 'status_won' : 'status_lost';
  if (lot.holder === 'you') return 'status_leading';
  if (lot.state === 'running') return 'status_outbid';
  return 'status_idle';
}

function soonest() {
  const live = rows.map((r) => r.lot)
    .filter((lot) => lot && lot.state === 'running' && lot.closes_in_s !== null);
  if (!live.length) return null;
  return Math.min(...live.map((lot) => lot.closes_in_s));
}

// ------------------------------------------------------------------ drawing

function drawRows() {
  const body = ui.clear(nodes.rows);
  body.append(ui.el('div', { class: 'bid-row head' },
    ui.el('span', { class: 'c-region' }, ui.bi('regions_region', 'label')),
    ui.el('span', { class: 'c-high' }, ui.bi('regions_highest', 'label')),
    ui.el('span', { class: 'c-bid' }, ui.bi('regions_your_bid', 'label')),
    ui.el('span', { class: 'c-status' }, ui.bi('regions_status', 'label')),
    ui.el('span', { class: 'c-clock' }, ui.bi('auction_closes_in', 'label'))));

  rows.forEach((row, index) => {
    const lot = row.lot || {};
    const soft = (softUntil.get(row.region) || 0) > performance.now();
    const node = ui.el('div', { class: `bid-row focusable no-scale ${statusKey(row)}` },
      ui.el('span', { class: 'c-region' }, ui.biRegion(row.label)),
      ui.el('span', { class: 'c-high' },
        ui.el('span', { class: 'mono', 'data-datum': true }, ui.num(lot.highest)),
        ui.bi(lot.holder === 'you' ? 'holder_you' : 'holder_rival', 'small')),
      ui.el('span', { class: 'c-bid' },
        ui.el('span', { class: 'mono big', 'data-datum': true }, ui.num(row.bid)),
        lot.state === 'closed' ? null
          : ui.biText(`次は ${ui.num(lot.next_bid)} から`, `next ${ui.num(lot.next_bid)}`,
                      'small')),
      ui.el('span', { class: 'c-status' },
        ui.bi(statusKey(row), 'small'),
        soft ? ui.bi('auction_soft_close', 'small warn') : null),
      ui.el('span', { class: 'c-clock mono', 'data-datum': true },
            lot.state === 'closed' ? '—' : ui.mmss(lot.closes_in_s)));
    node.dataset.region = row.region;
    body.append(node);
  });
  paintFocus();
}

function paintFocus() {
  [...nodes.rows.querySelectorAll('.bid-row.focusable')].forEach((node, i) => {
    node.classList.toggle('focused', focus === i);
  });
  document.getElementById('app').dataset.focus = rows[focus] ? rows[focus].region : '';
}

function drawClock() {
  const left = soonest();
  ui.clear(nodes.clock).append(
    ui.bi('auction_closes_in', 'label'),
    ui.el('div', { class: 'countdown mono', 'data-datum': true },
          left === null ? '—' : ui.mmss(left)));
  nodes.clock.classList.toggle('urgent', left !== null && left <= 10);
}

function drawBanner() {
  const on = bannerRegion && performance.now() < bannerUntil;
  nodes.banner.classList.toggle('hidden', !on);
  if (!on) return;
  const label = (rows.find((r) => r.region === bannerRegion) || {}).label || '';
  ui.clear(nodes.banner).append(
    ui.el('span', { class: 'badge-dot' }),
    ui.biText(`${ui.regionJp(label)}で上回られました`, `Outbid in ${label}`, 'h2-like'),
    ui.bi('auction_rival_once', 'small'));
}

function drawResult(ctx) {
  settled = true;
  document.getElementById('app').dataset.state = 'settled';
  const body = ui.clear(nodes.rows);
  body.append(ui.el('div', { class: 'row' }, ui.heading('auction_result')));
  for (const row of rows) {
    const won = row.lot && row.lot.won_by === 'you';
    body.append(ui.el('div', { class: `result-card ${won ? 'won' : 'lost'}` },
      ui.el('span', { class: 'badge', 'data-datum': true }, won ? '✓' : '✕'),
      ui.el('span', { class: 'what' },
        ui.biRegion(row.label, 'h2-like'),
        ui.bi(won ? 'auction_won_note' : 'auction_lost_note', 'small')),
      ui.el('span', { class: 'tail' },
        ui.bi(won ? 'auction_charged' : 'auction_lost', 'label'),
        ui.el('span', { class: 'val mono', 'data-datum': true },
              won ? ui.num(row.lot.charged) : ui.num(row.lot.highest)))));
  }
  ui.clear(nodes.action).append(
    ui.el('div', { class: 'button primary' }, ui.glyph('A'), ui.bi('auction_continue')));
  ctx.setHints([['A', 'hint_next'], ['START', 'hint_menu']]);
}

// ------------------------------------------------------------------ the screen

export default {
  id: 'auction',
  showHeader: true,
  pollMs: 500,                 // the spec's rate: this screen is where seconds matter
  hints: [['DPAD', 'hint_move'], ['LB/RB', 'hint_step_25'], ['LT/RT', 'hint_step_100'],
          ['Y', 'hint_raise'], ['START', 'hint_menu']],

  async enter(ctx, root, params) {
    slot = (params && params.slot) || ctx.state.slot || 'A1';
    settled = false;
    previous = new Map();
    softUntil = new Map();
    bannerRegion = null;
    focus = 0;

    const answer = await ctx.api.lots({ slot });
    const wanted = ctx.state.bidRegions || Object.keys(ctx.state.config.regions);
    rows = newestPerRegion(answer.lots, slot)
      .filter((lot) => wanted.includes(lot.region))
      .map((lot) => ({ region: lot.region, label: lot.region_label, lot,
                       bid: lot.holder === 'you' ? lot.highest : lot.next_bid }));
    for (const row of rows) previous.set(row.lot.lot_id, row.lot);

    nodes = {};
    nodes.rows = ui.el('div', { class: 'bid-rows' });
    nodes.clock = ui.el('div', { class: 'clock-box' });
    nodes.banner = ui.el('div', { class: 'banner hidden' });
    nodes.action = ui.el('div', { class: 'row' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('auction_title', 'h1'),
        ui.el('span', { class: 'badge quiet' },
          ui.biText(`スロット ${slot}`, `Slot ${slot}`, 'small')),
        ui.el('span', { class: 'sub' }, ui.bi('auction_sub', 'small'))),
      nodes.banner,
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col grow' }, nodes.rows),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 28rem' } },
          nodes.clock,
          ui.el('div', { class: 'divider' }),
          ui.bi('auction_rival_once', 'small'),
          ui.el('div', { class: 'grow' }),
          // the hint bar is full of buttons on this screen, so the money line lives here
          ui.el('div', { class: 'credit-note' }, ui.bi('demo_credits_note')),
          nodes.action)));

    ui.clear(nodes.action).append(
      ui.el('div', { class: 'button primary' }, ui.glyph('Y'), ui.bi('auction_raise')));
    drawRows();
    drawClock();
  },

  async refresh(ctx) {
    const answer = await ctx.api.lots({ slot });
    ctx.state.wallet = answer.wallet || ctx.state.wallet;
    ctx.refreshHeader();
    for (const lot of answer.lots) {
      // By lot id, never by region: the moment a lot closes the server opens the next
      // block's lot for the same slot and region, and `/lots` then answers with both.
      // Matching on the region would quietly swap this screen onto the next auction.
      const row = rows.find((r) => r.lot && r.lot.lot_id === lot.lot_id);
      if (!row) continue;
      const before = previous.get(lot.lot_id);
      // the rival's counter-bid: a lot we were leading has come back held by them
      if (before && before.holder === 'you' && lot.holder === 'rival') {
        bannerRegion = row.region;
        bannerUntil = performance.now() + BANNER_MS;
        focus = rows.indexOf(row);                 // the cursor jumps to that row
        row.bid = lot.next_bid;
      }
      if (before && lot.soft_closes > before.soft_closes) {
        softUntil.set(row.region, performance.now() + SOFT_BADGE_MS);
      }
      if (lot.holder === 'you') row.bid = lot.highest;
      else if (row.bid < lot.next_bid) row.bid = lot.next_bid;
      previous.set(lot.lot_id, lot);
      row.lot = lot;
    }
    if (!settled && rows.length && rows.every((r) => r.lot && r.lot.state === 'closed')) {
      drawResult(ctx);
      drawClock();
      drawBanner();
      return;
    }
    if (settled) return;
    drawRows();
    drawClock();
    drawBanner();
  },

  async raise(ctx) {
    const row = rows[focus];
    if (!row || !row.lot || row.lot.state === 'closed') return;
    const answer = await ctx.api.placeBids(slot, ctx.state.contentId,
      [{ region: row.region, amount: row.bid, lot_id: row.lot.lot_id }]);
    ctx.state.wallet = answer.wallet || ctx.state.wallet;
    ctx.refreshHeader();
    const result = answer.results[0];
    if (result.lot) {
      row.lot = result.lot;
      previous.set(result.lot.lot_id, result.lot);
    }
    if (!result.accepted) ui.toast(ui.japanese(result.reason), result.reason, 'bad', 5000);
    else ui.toast(ui.japanese(result.reason), result.reason, '', 2500);
    drawRows();
    drawClock();
  },

  pad(button, ctx) {
    if (settled) {
      if (button === 'A' || button === 'Y') {
        const won = rows.some((r) => r.lot && r.lot.won_by === 'you');
        if (won) ctx.go('live', { slot });
        else ctx.go('slotmap', { game: ctx.state.game });
      }
      return;
    }
    if (button === 'UP') { focus = Math.max(0, focus - 1); paintFocus(); return; }
    if (button === 'DOWN') { focus = Math.min(rows.length - 1, focus + 1); paintFocus(); return; }
    if (button === 'Y') {
      this.raise(ctx).catch((problem) => {
        console.error(problem);
        ui.toast(ui.japanese(problem.sentence || ''), problem.sentence || String(problem), 'bad');
      });
      return;
    }
    const step = ui.bidStep(button);
    if (!step) return;
    const row = rows[focus];
    if (!row || !row.lot || row.lot.state === 'closed') return;
    row.bid = Math.max(0, row.bid + step);
    drawRows();
  },
};
