// Screen 3 — Pick a game.
//
// Two games, one platform, one piece of content: the point of this screen is that the
// thing just approved is not tied to the game it was made for. The badge says which copy
// is being played at the booth, so a visitor can tell which screen their content will
// show up on.

import * as ui from '../ui.js';

let tiles = [];
let rows = [];
let focus = 0;

function paint() {
  tiles.forEach((tile, i) => tile.classList.toggle('focused', i === focus));
  const app = document.getElementById('app');
  app.dataset.game = rows[focus] ? rows[focus].id : '';
}

function tile(game) {
  const node = ui.el('div', { class: 'game-tile focusable' },
    ui.el('div', { class: 'shot', style: { backgroundImage: `url('${game.map_image_url}')` } }),
    ui.el('div', { class: 'badge-row' },
      game.live_at_booth
        ? ui.el('span', { class: 'badge' }, ui.bi('games_badge_booth'))
        : ui.el('span', { class: 'badge quiet' }, ui.bi('games_registered'))),
    ui.el('div', { class: 'foot' },
      ui.el('span', { class: 'grow' },
        ui.biText(`ゲーム ${game.id}`, game.label, 'h2-like')),
      ui.el('span', { class: 'stat' },
        ui.el('span', { class: 'value mono', 'data-datum': true }, String(game.slot_count)),
        ui.bi('games_slots', 'label')),
      ui.el('span', { class: 'stat' },
        ui.el('span', { class: 'value mono', 'data-datum': true },
              ui.num(game.players_online)),
        ui.bi('games_players', 'label'))));
  node.dataset.gameTile = game.id;
  return node;
}

export default {
  id: 'games',
  showHeader: true,
  pollMs: 2000,
  hints: [['DPAD', 'hint_move'], ['A', 'hint_select'], ['B', 'hint_back']],

  async enter(ctx, root) {
    const answer = await ctx.api.games();
    rows = answer.games || [];
    focus = Math.max(0, rows.findIndex((g) => g.id === (ctx.state.game || 'A')));
    tiles = rows.map(tile);

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('games_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.bi('games_sub', 'small'))),
      ui.el('div', { class: 'game-tiles' }, tiles));
    paint();
  },

  async refresh(ctx) {
    const answer = await ctx.api.games();
    for (const game of answer.games || []) {
      const index = rows.findIndex((row) => row.id === game.id);
      if (index < 0) continue;
      rows[index] = game;
      const stat = tiles[index].querySelectorAll('.foot .stat .value')[1];
      if (stat) stat.textContent = ui.num(game.players_online);
    }
  },

  pad(button, ctx) {
    if (button === 'LEFT') { focus = Math.max(0, focus - 1); paint(); return; }
    if (button === 'RIGHT') { focus = Math.min(rows.length - 1, focus + 1); paint(); return; }
    if (button === 'B') { ctx.go('upload'); return; }
    if (button === 'A') {
      ctx.state.game = rows[focus].id;
      ctx.go('slotmap', { game: rows[focus].id });
    }
  },
};
