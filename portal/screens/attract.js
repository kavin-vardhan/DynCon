// Screen 0 — Attract.
//
// What a passer-by sees: the platform's own slots filling and emptying by themselves as
// the demo clock rolls from one three-minute block to the next, and the other brands'
// auctions ticking along without anybody at the booth. Nothing here needs a visitor; it
// is the live state of the server, polled once a second.

import * as ui from '../ui.js';

const MAX_AUCTION_ROWS = 5;

let showingPanel = null;
let auctionPanel = null;
let openedLots = false;

function whoKey(kind) {
  if (kind === 'visitor') return 'showing_you';
  if (kind === 'rival') return 'showing_rival';
  if (kind === 'default') return 'showing_default';
  return 'showing_none';
}

function regionChip(row) {
  const brand = row && row.brand;
  return ui.el('span', { class: 'region-chip' },
    ui.brandMark(brand),
    ui.el('span', { class: 'who' }, ui.bi(whoKey(row && row.kind))));
}

function drawShowing(ctx, rows) {
  const regions = ctx.state.config.regions;
  const byKey = new Map();
  for (const row of rows) byKey.set(`${row.game}/${row.slot}/${row.region}`, row);

  const body = ui.clear(showingPanel.querySelector('.body'));
  body.append(ui.el('div', { class: 'region-head' },
    Object.values(regions).map((region) =>
      ui.el('span', { class: 'cell' }, ui.biRegion(region.label)))));
  for (const [gameId, game] of Object.entries(ctx.state.config.games)) {
    for (const slot of game.slots) {
      body.append(ui.el('div', { class: 'ticker-row' },
        ui.el('span', { class: 'slot-id', 'data-datum': true }, slot.id),
        ui.el('span', { class: 'region-chips' },
          Object.keys(regions).map((id) => regionChip(
            byKey.get(`${gameId}/${slot.id}/${id}`))))));
    }
  }
}

function drawAuctions(lots) {
  const body = ui.clear(auctionPanel.querySelector('.body'));
  const rows = [...lots]
    .filter((lot) => lot.state !== 'closed')
    .sort((a, b) => b.highest - a.highest)
    .slice(0, MAX_AUCTION_ROWS);
  if (!rows.length) {
    body.append(ui.el('div', { class: 'muted' }, ui.bi('upload_empty', 'small')));
    return;
  }
  for (const lot of rows) {
    body.append(ui.el('div', { class: 'ticker-row' },
      ui.el('span', { class: 'slot-id', 'data-datum': true }, lot.slot),
      ui.el('span', { class: 'where' }, ui.biRegion(lot.region_label, 'small')),
      ui.el('span', { class: 'spacer' }),
      ui.bi(lot.holder === 'you' ? 'holder_you' : 'holder_rival', 'small'),
      ui.el('span', { class: 'value mono', 'data-datum': true,
                      style: { minWidth: '7rem', textAlign: 'right' } },
        ui.num(lot.highest))));
  }
}

export default {
  id: 'attract',
  showHeader: false,
  mainClass: 'attract',
  pollMs: 1000,
  hints: [['A', 'hint_start']],

  async enter(ctx, root) {
    root.append(
      ui.el('div', { class: 'hero' },
        ui.bi('app_name', 'mark'),
        ui.el('div', { class: 'tagline' }, ui.bi('attract_tagline'))),
      ui.el('div', { class: 'columns' },
        showingPanel = ui.el('div', { class: 'panel col grow' },
          ui.heading('attract_now_showing'),
          ui.el('div', { class: 'body' })),
        auctionPanel = ui.el('div', { class: 'panel col grow' },
          ui.heading('attract_auctions'),
          ui.el('div', { class: 'body' }))),
      ui.el('div', { class: 'start-cue' },
        ui.el('span', { class: 'ring' }, ui.glyph('A'), ui.bi('attract_start'))),
    );

    // Lots are opened on demand, so ask for each slot's once: that is what puts the other
    // brands' auctions on the attract screen before anybody has touched the pad.
    if (!openedLots) {
      openedLots = true;
      const slots = Object.values(ctx.state.config.games).flatMap((g) => g.slots);
      await Promise.all(slots.map((s) => ctx.api.lots({ slot: s.id }).catch(() => null)));
    }
    await this.refresh(ctx);
  },

  async refresh(ctx) {
    const [live, lots] = await Promise.all([ctx.api.liveStatus(), ctx.api.lots()]);
    drawShowing(ctx, live.showing || []);
    drawAuctions(lots.lots || []);
  },

  pad(button, ctx) {
    if (button === 'A' || button === 'START') ctx.go('brand');
  },
};
