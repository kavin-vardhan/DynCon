// Screen 4 — the slot map.
//
// The picture is not a drawing: it is the orthographic capture the game developer's own
// editor tool took of the level and registered with the platform (`POST /games/register`),
// and every pin sits where that tool measured the slot to be on it. The side card is the
// slot contract in plain words — what fits, who is standing there now, what the spot is
// worth — plus the eye-level photograph of the empty spot, taken by the same tool.
//
// Slots the visitor's content cannot go in are greyed out, with the server's own reason.

import * as ui from '../ui.js';

const BAND_COLOURS = ['#2ea44f', '#f2c230', '#e23d3d'];      // low, middling, busiest
const BAND_KEYS = ['map_footfall_low', 'map_footfall_mid', 'map_footfall_high'];

let game = null;
let slots = [];
let bands = {};            // slot id -> 0 | 1 | 2
let pins = {};             // slot id -> pin node
let focusId = null;
let nodes = {};
let placeHandler = null;

function mainRegion(ctx) {
  return (ctx.state.config.booth && ctx.state.config.booth.main_region) || 'r1';
}

function fitFor(ctx, slot) {
  const id = ctx.state.contentId;
  if (!id || !slot.fits) return null;
  return slot.fits[id] || null;
}

// ------------------------------------------------------------------ the pins

function placePins() {
  const img = nodes.map;
  const wrap = nodes.wrap;
  if (!img || !img.naturalWidth) return;
  const cw = wrap.clientWidth;
  const ch = wrap.clientHeight;
  const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
  const dw = img.naturalWidth * scale;
  const dh = img.naturalHeight * scale;
  const left = (cw - dw) / 2;
  const top = (ch - dh) / 2;
  for (const slot of slots) {
    const pin = pins[slot.id];
    if (!pin) continue;
    pin.style.left = `${left + slot.px.x * dw}px`;
    pin.style.top = `${top + slot.px.y * dh}px`;
  }
}

function paintPins(ctx) {
  for (const slot of slots) {
    const pin = pins[slot.id];
    const fit = fitFor(ctx, slot);
    pin.classList.toggle('focused', slot.id === focusId);
    pin.classList.toggle('greyed', !!(fit && fit.ok === false));
  }
  document.getElementById('app').dataset.slot = focusId || '';
}

/** The next pin in a direction: the closest one, counting sideways drift double. */
function hop(direction) {
  const here = slots.find((s) => s.id === focusId);
  if (!here) return;
  const axis = (direction === 'LEFT' || direction === 'RIGHT') ? 'x' : 'y';
  const other = axis === 'x' ? 'y' : 'x';
  const sign = (direction === 'RIGHT' || direction === 'DOWN') ? 1 : -1;
  let best = null;
  let bestScore = Infinity;
  for (const slot of slots) {
    if (slot.id === focusId) continue;
    const along = (slot.px[axis] - here.px[axis]) * sign;
    if (along <= 0.001) continue;
    const score = along + 2 * Math.abs(slot.px[other] - here.px[other]);
    if (score < bestScore) { bestScore = score; best = slot; }
  }
  if (best) focusId = best.id;
}

// ------------------------------------------------------------------ the side card

/** One cell of the strip of numbers under the picture: a label, then the figure. */
function statCell(labelKey, value, under = null, accent = false) {
  const pieces = [
    ui.tx(labelKey, 'label'),
    ui.el('span', { class: `val mono ${accent ? 'accent' : ''}`.trim(),
                    'data-datum': true }, value),
    under,
  ];
  return ui.el('div', { class: 'cell' }, pieces.filter(Boolean));
}

function drawCard(ctx) {
  const slot = slots.find((s) => s.id === focusId);
  const body = ui.clear(nodes.card);
  if (!slot) return;
  const region = mainRegion(ctx);
  const lot = (slot.lots || {})[region] || null;
  const fit = fitFor(ctx, slot);
  const regions = game.regions || {};

  const hasClock = lot && lot.closes_in_s !== null && lot.closes_in_s !== undefined;

  const verdictBox = fit
    ? (fit.ok
        ? ui.el('div', { class: 'fits-note' },
            ui.tx('map_fits', 'small'),
            ui.txText(fit.reason, 'small'))
        : ui.el('div', { class: 'refusal' },
            ui.tx('map_no_fit', 'small'),
            ui.txText(fit.reason, 'small')))
    : ui.el('div', { class: 'muted' }, ui.tx('map_no_content', 'small'));

  // append() renders a null as the text "null", so the pieces are filtered first.
  const pieces = [
    ui.el('div', { class: 'row' },
      ui.txText(`Slot ${slot.id}`, 'h2-like'),
      ui.el('span', { class: 'grow' }),
      ui.el('span', { class: 'badge quiet' },
        ui.txText(`Class ${slot.size_class}`, 'small'))),
    ui.el('div', { class: 'card-split' },
      ui.el('div', { class: 'card-left' },
        ui.el('img', { class: 'thumb', src: slot.thumb_url, alt: '' }),
        ui.tx('map_eye_level', 'label')),
      ui.el('div', { class: 'card-right' },
        // No "what fits here" label: the sentence is the label.
        ui.el('span', { class: 'rule' }, ui.txText(slot.limits_words, 'small')),
        ui.el('div', { class: 'divider' }),
        ui.tx('map_footfall', 'small'),
        // Three regions across, not down: the same table in a third of the height.
        ui.el('div', { class: 'footfall-strip' },
          Object.entries(regions).map(([id, label]) => {
            const cell = (slot.footfall || {})[id] || {};
            return ui.el('div', { class: 'cell' },
              ui.txText(label, 'small'),
              ui.el('span', { class: 'n', 'data-datum': true }, ui.num(cell.per_demo_hour),
                ui.el('small', { 'data-datum': true }, ` +${ui.num(cell.live || 0)}`)));
          }))),
    ),
    ui.el('div', { class: 'stat-strip' },
      statCell('map_highest', lot ? ui.num(lot.highest) : '—',
               ui.tx(lot && lot.holder === 'you' ? 'holder_you' : 'holder_rival', 'small'),
               true),
      statCell('map_per_1000',
               lot && lot.credits_per_1000_views !== null
                 ? String(lot.credits_per_1000_views) : '—'),
      statCell('map_closes', hasClock ? ui.mmss(lot.closes_in_s) : '—')),
    // Why there is no countdown yet, said once and across the whole card rather than
    // squeezed into a third of it.
    hasClock ? null : ui.tx('map_clock_waiting', 'small'),
    verdictBox,
  ];
  body.append(...pieces.filter(Boolean));
}

// ------------------------------------------------------------------ the screen

export default {
  id: 'slotmap',
  showHeader: true,
  pollMs: 1000,
  hints: [['DPAD', 'hint_pick_slot'], ['Y', 'hint_bid'], ['B', 'hint_back']],

  async enter(ctx, root, params) {
    const id = (params && params.game) || ctx.state.game || 'A';
    game = await ctx.api.game(id);
    slots = game.slots || [];
    pins = {};

    const region = mainRegion(ctx);
    const ranked = [...slots].sort(
      (a, b) => ((a.footfall[region] || {}).per_demo_hour || 0)
              - ((b.footfall[region] || {}).per_demo_hour || 0));
    bands = {};
    ranked.forEach((slot, i) => {
      bands[slot.id] = Math.min(Math.floor(i * BAND_COLOURS.length / Math.max(ranked.length, 1)),
                                BAND_COLOURS.length - 1);
    });

    if (!focusId || !slots.some((s) => s.id === focusId)) focusId = slots[0] && slots[0].id;

    nodes.map = ui.el('img', { class: 'map', src: game.map_image_url, alt: '' });
    nodes.wrap = ui.el('div', { class: 'map-wrap' }, nodes.map,
                       ui.el('div', { class: 'tint' }));
    for (const slot of slots) {
      const pin = ui.el('div', { class: 'pin' },
        ui.el('div', { class: 'dot', style: { background: BAND_COLOURS[bands[slot.id]] } }),
        ui.el('div', { class: 'tag', 'data-datum': true }, slot.id));
      pin.dataset.pin = slot.id;
      pins[slot.id] = pin;
      nodes.wrap.append(pin);
    }
    nodes.card = ui.el('div', { class: 'body' });

    // The screen's title lives in the map's own column rather than across the top: the
    // card on the right needs every pixel of the 1080 it can get.
    root.append(
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'col grow' },
          ui.el('div', { class: 'screen-head' },
            ui.heading('map_title', 'h1'),
            ui.el('span', { class: 'sub' }, ui.tx('map_sub', 'small'))),
          nodes.wrap,
          ui.el('div', { class: 'legend' },
            BAND_COLOURS.map((colour, i) => ui.el('span', { class: 'item' },
              ui.el('span', { class: 'dot', style: { background: colour } }),
              ui.tx(BAND_KEYS[i]))))),
        ui.el('div', { class: 'panel col slot-card' }, nodes.card)));

    nodes.map.addEventListener('load', placePins);
    placeHandler = () => placePins();
    window.addEventListener('resize', placeHandler);
    placePins();
    paintPins(ctx);
    drawCard(ctx);
  },

  exit() {
    if (placeHandler) window.removeEventListener('resize', placeHandler);
    placeHandler = null;
  },

  async refresh(ctx) {
    const fresh = await ctx.api.game(game.id);
    game = fresh;
    slots = fresh.slots || [];
    ctx.state.wallet = fresh.wallet || ctx.state.wallet;
    ctx.refreshHeader();
    paintPins(ctx);
    drawCard(ctx);
  },

  pad(button, ctx) {
    if (['UP', 'DOWN', 'LEFT', 'RIGHT'].includes(button)) {
      hop(button);
      placePins();
      paintPins(ctx);
      drawCard(ctx);
      return;
    }
    if (button === 'B') { ctx.go('games'); return; }
    if (button === 'Y' || button === 'A') {
      const slot = slots.find((s) => s.id === focusId);
      const fit = slot ? fitFor(ctx, slot) : null;
      if (!ctx.state.contentId) { ctx.toastKey('map_no_content', 'bad'); return; }
      if (fit && fit.ok === false) {
        ui.toast(fit.reason, 'bad', 5000);
        return;
      }
      ctx.state.slot = focusId;
      ctx.go('regions', { slot: focusId, game: game.id });
    }
  },
};
