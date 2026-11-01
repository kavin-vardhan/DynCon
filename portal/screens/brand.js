// Screen 1 — Create your brand.
//
// Eight colours, eight emblems, no names and nothing to type: that pair *is* the brand
// account for the rest of the tour, and it is what the server signs into the manifest and
// the game paints onto the sign at mount time. The preview on the right is the same two
// values drawn as the sign the content will carry.

import * as ui from '../ui.js';

let colours = [];
let emblems = [];
let focus = { row: 0, col: 0 };
let chosen = { colour: null, emblem: null };
let nodes = { colourCells: [], emblemCells: [], confirm: null, plate: null };

function previewColour() {
  if (focus.row === 0) return colours[focus.col];
  return chosen.colour || colours[0];
}

function previewEmblem() {
  if (focus.row === 1) return emblems[focus.col];
  return chosen.emblem || emblems[0];
}

function paint() {
  nodes.colourCells.forEach((cell, i) => {
    cell.classList.toggle('focused', focus.row === 0 && focus.col === i);
    cell.classList.toggle('chosen', chosen.colour === colours[i]);
  });
  nodes.emblemCells.forEach((cell, i) => {
    cell.classList.toggle('focused', focus.row === 1 && focus.col === i);
    cell.classList.toggle('chosen', chosen.emblem === emblems[i]);
  });
  nodes.confirm.classList.toggle('focused', focus.row === 2);

  const colour = previewColour();
  const shape = previewEmblem();
  nodes.plate.style.background = colour;
  nodes.plate.innerHTML = ui.emblemSvg(shape, 'rgba(255,255,255,0.95)');
}

export default {
  id: 'brand',
  showHeader: true,
  pollMs: 2000,
  hints: [['DPAD', 'hint_move'], ['A', 'hint_select'], ['B', 'hint_back']],

  async enter(ctx, root) {
    const presets = ctx.state.config.brand_presets;
    colours = presets.colours;
    emblems = presets.emblems;
    focus = { row: 0, col: 0 };
    chosen = { colour: ctx.state.brand ? ctx.state.brand.colour : null,
               emblem: ctx.state.brand ? ctx.state.brand.emblem : null };
    nodes.colourCells = [];
    nodes.emblemCells = [];

    const colourGrid = ui.el('div', { class: 'swatch-grid' },
      colours.map((colour) => {
        const cell = ui.el('div', { class: 'cell colour focusable no-scale',
                                    style: { background: colour } },
          ui.el('span', { class: 'tick', 'data-datum': true }, '✓'));
        nodes.colourCells.push(cell);
        return cell;
      }));

    const emblemGrid = ui.el('div', { class: 'swatch-grid' },
      emblems.map((name) => {
        const cell = ui.el('div', { class: 'cell emblem focusable no-scale',
                                    html: ui.emblemSvg(name, '#cfe3f7') },
        );
        cell.append(ui.el('span', { class: 'tick', 'data-datum': true }, '✓'));
        nodes.emblemCells.push(cell);
        return cell;
      }));

    nodes.confirm = ui.el('div', { class: 'button primary focusable' },
      ui.glyph('A'), ui.bi('brand_confirm'));

    nodes.plate = ui.el('div', { class: 'sign-plate' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('brand_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.bi('brand_sub', 'small'))),
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col grow' },
          ui.bi('brand_colours', 'label'),
          colourGrid,
          ui.el('div', { class: 'divider' }),
          ui.bi('brand_emblems', 'label'),
          emblemGrid,
          ui.el('div', { class: 'grow' }),
          nodes.confirm),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 38rem' } },
          ui.heading('brand_preview'),
          ui.el('div', { class: 'sign-preview' }, nodes.plate),
          ui.el('div', {},
            ui.bi('brand_wallet', 'small'),
            ui.el('div', { class: 'credit-note' }, ui.bi('demo_credits_note'))),
          ui.bi('brand_no_names', 'small'))),
    );
    paint();
  },

  pad(button, ctx) {
    const widths = [colours.length, emblems.length, 1];
    if (button === 'LEFT') { focus.col = Math.max(0, focus.col - 1); paint(); return; }
    if (button === 'RIGHT') {
      focus.col = Math.min(widths[focus.row] - 1, focus.col + 1); paint(); return;
    }
    if (button === 'UP' || button === 'DOWN') {
      const row = Math.min(2, Math.max(0, focus.row + (button === 'DOWN' ? 1 : -1)));
      focus.row = row;
      focus.col = Math.min(focus.col, widths[row] - 1);
      paint();
      return;
    }
    if (button === 'B') { ctx.go('attract'); return; }
    if (button !== 'A') return;

    if (focus.row === 0) {
      chosen.colour = colours[focus.col];
      focus = { row: 1, col: Math.max(0, emblems.indexOf(chosen.emblem)) };
      paint();
    } else if (focus.row === 1) {
      chosen.emblem = emblems[focus.col];
      focus = { row: 2, col: 0 };
      paint();
    } else {
      this.confirm(ctx);
    }
  },

  async confirm(ctx) {
    const colour = chosen.colour || previewColour();
    const emblem = chosen.emblem || previewEmblem();
    const answer = await ctx.api.setBrand(colour, emblem);
    ctx.state.brand = answer.brand;
    ctx.state.wallet = answer.wallet || ctx.state.wallet;
    ctx.refreshHeader();
    await ctx.go('upload');
  },
};
