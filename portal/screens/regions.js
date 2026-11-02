// Screen 5 — Regions and bid.
//
// The one screen that makes the patent's "lot" idea visible: what is for sale is a slot
// **in one region for one time block**, and every region runs its own auction. A big
// multi-region budget cannot steamroll a local bidder — it only wins a region if its
// share for that region is the highest there — so the portal offers a total and splits it
// by footfall (`/bids/split`), and then lets you adjust any row by hand.
//
// LB / RB step a row by 25, LT / RT by 100, A ticks a region, Y places the bid.

import * as ui from '../ui.js';
import { newestPerRegion } from './auction.js';

let slot = null;
let rows = [];               // {region, label, lot, ticked, amount}
let focus = 0;               // 0..rows.length-1 = a region, rows.length = the total control
let total = 0;
let splitTimer = null;
let nodes = {};

function lotOf(region) {
  const row = rows.find((r) => r.region === region);
  return row ? row.lot : null;
}

function ticked() {
  return rows.filter((r) => r.ticked);
}

function statusKey(row) {
  const lot = row.lot;
  if (!lot) return 'status_idle';
  if (lot.state === 'closed') return lot.won_by === 'you' ? 'status_won' : 'status_lost';
  if (lot.holder === 'you') return 'status_leading';
  if (lot.state === 'running' && row.ticked) return 'status_outbid';
  return row.ticked ? 'status_will_bid' : 'status_idle';
}

// ------------------------------------------------------------------ drawing

function headerRow() {
  return ui.el('div', { class: 'bid-row head' },
    ui.el('span', { class: 'tickbox' }),
    ui.el('span', { class: 'c-region' }, ui.tx('regions_region', 'label')),
    ui.el('span', { class: 'c-foot' }, ui.tx('regions_footfall', 'label')),
    ui.el('span', { class: 'c-high' }, ui.tx('regions_highest', 'label')),
    ui.el('span', { class: 'c-bid' }, ui.tx('regions_your_bid', 'label')),
    ui.el('span', { class: 'c-status' }, ui.tx('regions_status', 'label')));
}

function drawRows() {
  const body = ui.clear(nodes.rows);
  body.append(headerRow());
  rows.forEach((row, index) => {
    const lot = row.lot || {};
    const enough = row.amount >= (lot.next_bid || 0);
    const node = ui.el('div', { class: 'bid-row focusable no-scale' },
      ui.el('span', { class: `tickbox ${row.ticked ? 'on' : ''}`.trim(),
                      'data-datum': true }, row.ticked ? '✓' : ''),
      ui.el('span', { class: 'c-region' }, ui.txText(row.label)),
      ui.el('span', { class: 'c-foot mono', 'data-datum': true },
            ui.num(lot.footfall_per_demo_hour)),
      ui.el('span', { class: 'c-high' },
        ui.el('span', { class: 'mono', 'data-datum': true }, ui.num(lot.highest)),
        ui.tx(lot.holder === 'you' ? 'holder_you' : 'holder_rival', 'small')),
      ui.el('span', { class: `c-bid ${row.ticked ? '' : 'off'}`.trim() },
        ui.el('span', { class: 'mono big', 'data-datum': true },
              row.ticked ? ui.num(row.amount) : '—'),
        row.ticked && !enough
          ? ui.txText(`min ${ui.num(lot.next_bid)}`, 'small warn')
          : null),
      ui.el('span', { class: 'c-status' }, ui.tx(statusKey(row), 'small')));
    node.dataset.region = row.region;
    node.dataset.ticked = row.ticked ? '1' : '0';
    body.append(node);
  });
  paintFocus();
}

function paintFocus() {
  [...nodes.rows.querySelectorAll('.bid-row.focusable')].forEach((node, i) => {
    node.classList.toggle('focused', focus === i);
  });
  nodes.totalBox.classList.toggle('focused', focus === rows.length);
  document.getElementById('app').dataset.focus =
    focus < rows.length ? (rows[focus] ? rows[focus].region : '') : 'total';
}

function drawTotal() {
  ui.clear(nodes.totalValue).append(
    ui.el('span', { class: 'mono big', 'data-datum': true }, ui.num(total)));
  const purse = nodes.walletNow || { available: 0, held: 0 };
  ui.clear(nodes.wallet).append(
    ui.el('div', { class: 'footfall-strip' },
      ui.el('div', { class: 'cell' },
        ui.tx('wallet_available', 'small'),
        ui.el('span', { class: 'n', 'data-datum': true }, ui.num(purse.available))),
      ui.el('div', { class: 'cell' },
        ui.tx('wallet_held', 'small'),
        ui.el('span', { class: 'n held', 'data-datum': true }, ui.num(purse.held)))));
}

// ------------------------------------------------------------------ the split

function sumTicked() {
  return ticked().reduce((n, row) => n + row.amount, 0);
}

/** The server splits a total across the ticked regions by footfall. */
function applySplit(ctx) {
  if (splitTimer) clearTimeout(splitTimer);
  splitTimer = setTimeout(async () => {
    const regions = ticked().map((r) => r.region);
    if (!regions.length || total <= 0) return;
    try {
      const answer = await ctx.api.splitBid(slot, total, regions);
      for (const share of answer.bids) {
        const row = rows.find((r) => r.region === share.region);
        if (row) row.amount = share.amount;
      }
      drawRows();
    } catch (problem) {
      console.error(problem);
    }
  }, 140);
}

// ------------------------------------------------------------------ placing it

async function placeBid(ctx) {
  const wanted = ticked();
  if (!wanted.length) {
    ctx.toastKey('regions_pick_one', 'bad');
    return;
  }
  const answer = await ctx.api.placeBids(slot, ctx.state.contentId, wanted.map((row) => ({
    region: row.region, amount: row.amount, lot_id: row.lot ? row.lot.lot_id : null,
  })));
  ctx.state.wallet = answer.wallet || ctx.state.wallet;
  ctx.refreshHeader();
  for (const result of answer.results) {
    const row = rows.find((r) => r.region === result.region);
    if (row && result.lot) row.lot = result.lot;
    if (!result.accepted) ui.toast(result.reason, 'bad', 5000);
  }
  drawRows();
  if (answer.results.some((r) => r.accepted)) {
    ctx.state.slot = slot;
    ctx.state.bidRegions = wanted.map((r) => r.region);
    await ctx.go('auction', { slot });
  }
}

// ------------------------------------------------------------------ the screen

export default {
  id: 'regions',
  showHeader: true,
  pollMs: 1000,
  hints: [['DPAD', 'hint_move'], ['A', 'hint_tick'], ['LB/RB', 'hint_step_25'],
          ['LT/RT', 'hint_step_100'], ['Y', 'hint_place_bid'], ['B', 'hint_back']],

  async enter(ctx, root, params) {
    slot = (params && params.slot) || ctx.state.slot || 'A1';
    ctx.state.slot = slot;
    const answer = await ctx.api.lots({ slot });
    const main = (ctx.state.config.booth || {}).main_region || 'r1';
    // The newest lot per region is the one still for sale — "book the next block" is
    // exactly this screen again, one sequence number later.
    rows = newestPerRegion(answer.lots, slot).map((lot) => ({
      region: lot.region, label: lot.region_label, lot,
      ticked: lot.region === main,
      amount: lot.next_bid,
    }));
    focus = 0;
    total = sumTicked();
    nodes = { walletNow: answer.wallet };

    nodes.rows = ui.el('div', { class: 'bid-rows' });
    nodes.totalValue = ui.el('div', { class: 'row' });
    nodes.totalBox = ui.el('div', { class: 'panel-inset focusable no-scale' },
      ui.tx('regions_total', 'label'),
      nodes.totalValue,
      ui.tx('regions_total_help', 'small'));
    nodes.wallet = ui.el('div', { class: 'rows' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('regions_title', 'h1'),
        ui.el('span', { class: 'badge quiet' },
          ui.txText(`Slot ${slot}`, 'small')),
        ui.el('span', { class: 'sub' }, ui.tx('regions_sub', 'small'))),
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col grow' }, nodes.rows),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 32rem' } },
          nodes.totalBox,
          ui.el('div', { class: 'divider' }),
          nodes.wallet,
          ui.el('div', { class: 'credit-note' }, ui.tx('demo_credits_note')),
          ui.el('div', { class: 'grow' }),
          ui.el('div', { class: 'button primary' }, ui.glyph('Y'), ui.tx('regions_place')))));

    drawRows();
    drawTotal();
  },

  async refresh(ctx) {
    const answer = await ctx.api.lots({ slot });
    nodes.walletNow = answer.wallet;
    for (const lot of newestPerRegion(answer.lots, slot)) {
      const row = rows.find((r) => r.region === lot.region);
      if (!row) continue;
      const wasLeading = row.lot && row.lot.holder === 'you';
      row.lot = lot;
      // keep a row that has never been touched on the server's current asking price
      if (!row.touched && !wasLeading) row.amount = Math.max(row.amount, lot.next_bid);
    }
    drawRows();
    drawTotal();
  },

  pad(button, ctx) {
    const last = rows.length;                      // the total control sits after the rows
    if (button === 'UP') { focus = Math.max(0, focus - 1); paintFocus(); return; }
    if (button === 'DOWN') { focus = Math.min(last, focus + 1); paintFocus(); return; }
    if (button === 'B') { ctx.go('slotmap', { game: ctx.state.game }); return; }
    if (button === 'A') {
      if (focus === last) { applySplit(ctx); return; }
      const row = rows[focus];
      row.ticked = !row.ticked;
      if (row.ticked && !row.amount) row.amount = row.lot.next_bid;
      total = sumTicked();
      drawRows();
      drawTotal();
      return;
    }
    if (button === 'Y') {
      placeBid(ctx).catch((problem) => {
        console.error(problem);
        ui.toast(problem.sentence || String(problem), 'bad');
      });
      return;
    }
    const step = ui.bidStep(button);
    if (!step) return;
    if (focus === last) {
      total = Math.max(0, total + step);
      drawTotal();
      applySplit(ctx);
      return;
    }
    const row = rows[focus];
    if (!row.ticked) return;
    row.touched = true;
    row.amount = Math.max(0, row.amount + step);
    total = sumTicked();
    drawRows();
    drawTotal();
  },
};
