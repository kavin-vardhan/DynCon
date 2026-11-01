// The Start menu — and with it, tour step 8, the region check.
//
// The point of the region check: the slot, the game and the moment are the same, and the
// content is not, because the *player* is somewhere else. At the booth there is a second
// copy of the game running as a player in another region; this menu is what flips it, and
// it says in plain words what the other screen is showing and why.
//
// The preview *window* is that second copy, borderless, on this monitor. The portal cannot
// move another program's window, so it asks the pad helper to show it when this step opens
// and to hide it when the step closes (`ctx.previewWindow`). The right half of the screen
// is left empty for it while the menu is up — `.preview-reserve` below is exactly the
// rectangle the window lands on, and the game computes the same one from the monitor
// (DCPreview.cpp): the right half, vertically centred, half the monitor's width and height.

import * as ui from './ui.js';

let layer = null;
let open = false;
let focus = 0;
let regionIndex = 0;
let regionIds = [];
let preview = null;
let live = [];
let paused = false;
let items = [];

/** How long the live flip lasts (plan v6 §11's fallback: "for 20 s"). */
const flipSeconds = 20;

export function isOpen() {
  return open;
}

function sentenceFor(label) {
  return ui.biText(`これは同じゲームを「${ui.regionJp(label)}」のプレイヤーが見たときの画面です`,
                   `This is the same game, for a player in ${label}`, 'small');
}

/** The empty rectangle the preview window covers, with a line saying so underneath it. */
function reserve(ctx) {
  const window = ctx.previewState ? ctx.previewState() : {};
  return ui.el('div', { class: 'preview-reserve', 'data-state': window.found === false
    ? 'missing' : (window.shown ? 'shown' : 'waiting') },
    ui.el('div', { class: 'label' },
      window.found === false ? ui.bi('preview_window_missing', 'small')
        : ui.bi('preview_window_here', 'small')));
}

function draw(ctx) {
  const body = ui.clear(layer);
  const regions = ctx.state.config.regions;
  const chosen = regionIds[regionIndex];
  const chosenLabel = (regions[chosen] || {}).label || chosen;

  items = [
    { key: 'menu_preview' },
    { key: 'menu_flip' },
    { key: paused ? 'menu_resume' : 'menu_pause' },
    { key: 'menu_summary' },
    { key: 'menu_close' },
  ];

  const slot = ctx.state.slot;
  body.append(ui.el('div', { class: 'menu panel' },
    ui.heading('menu_title'),
    ui.el('div', { class: `menu-item focusable ${focus === 0 ? 'focused' : ''}`.trim() },
      ui.bi('menu_preview', 'label'),
      ui.el('div', { class: 'region-pick' },
        regionIds.map((id, i) => ui.el('span', {
          class: `pill ${i === regionIndex ? 'on' : ''} ${id === (preview || {}).region ? 'live' : ''}`.trim(),
        }, ui.biRegion((regions[id] || {}).label || id, 'small')))),
      sentenceFor(chosenLabel)),
    slot ? ui.el('div', { class: 'region-table' },
      regionIds.map((id) => {
        const row = live.find((r) => r.slot === slot && r.region === id);
        const kind = row ? row.kind : 'none';
        return ui.el('div', { class: `r ${kind === 'visitor' ? 'yours' : ''}`.trim() },
          ui.brandMark(row && row.brand),
          ui.el('span', { class: 'name' },
                ui.biRegion((regions[id] || {}).label || id, 'small')),
          ui.bi(kind === 'visitor' ? 'showing_you'
                : kind === 'rival' ? 'showing_rival'
                : kind === 'default' ? 'showing_default' : 'showing_none', 'small'));
      })) : null,
    // One line each, and no explanation under the flip row: the region picker above it
    // already says which region, and a sixth line of text makes the panel taller than a
    // 1080p screen (the exit test's layout audit catches it).
    ...items.slice(1).map((item, index) => ui.el('div', {
      class: `button focusable ${focus === index + 1 ? 'focused' : ''}`.trim(),
      'data-item': item.key,
    }, ui.glyph('A'), ui.bi(item.key))),
  ));
  body.append(reserve(ctx));
  document.getElementById('app').dataset.menu = 'open';
}

/** The shell calls this when the pad helper answers about the window. */
export function redraw(ctx) {
  if (open && layer) draw(ctx);
}

export async function show(ctx) {
  if (!layer) {
    layer = ui.el('div', { class: 'menu-layer' });
    document.body.append(layer);
  }
  open = true;
  focus = 0;
  layer.classList.remove('hidden');
  // Ask first, draw second: the window takes a moment to come back from off-screen, and
  // the fetches below are a round trip anyway.
  ctx.previewWindow(true);
  regionIds = Object.keys(ctx.state.config.regions);
  const [previewAnswer, liveAnswer, report] = await Promise.all([
    ctx.api.previewRegion(), ctx.api.liveStatus(), ctx.api.report().catch(() => null),
  ]);
  preview = previewAnswer;
  live = liveAnswer.showing || [];
  paused = !!(report && report.paused);
  regionIndex = Math.max(0, regionIds.indexOf(preview.region));
  draw(ctx);
  ctx.setHints([['DPAD', 'hint_move'], ['A', 'hint_select'], ['START', 'hint_back']],
               'menu_hint');
}

export function hide(ctx) {
  open = false;
  if (layer) layer.classList.add('hidden');
  document.getElementById('app').dataset.menu = '';
  // The portal gets the whole screen back the rest of the time (plan v6 §7).
  ctx.previewWindow(false);
  ctx.restoreHints();
}

export async function pad(button, ctx) {
  if (button === 'START' || button === 'B') { hide(ctx); return; }
  if (button === 'UP') { focus = Math.max(0, focus - 1); draw(ctx); return; }
  if (button === 'DOWN') { focus = Math.min(items.length - 1, focus + 1); draw(ctx); return; }
  if (button === 'LEFT' && focus === 0) {
    regionIndex = Math.max(0, regionIndex - 1);
    draw(ctx);
    return;
  }
  if (button === 'RIGHT' && focus === 0) {
    regionIndex = Math.min(regionIds.length - 1, regionIndex + 1);
    draw(ctx);
    return;
  }
  if (button !== 'A') return;

  if (focus === 0) {
    preview = await ctx.api.setPreviewRegion(regionIds[regionIndex]);
    const label = (ctx.state.config.regions[preview.region] || {}).label || preview.region;
    ui.toast(`プレビュー画面を「${ui.regionJp(label)}」にしました`,
             `The preview window is now a player in ${label}`, '', 4000);
    draw(ctx);
  } else if (focus === 1) {
    // The fallback of plan v6 §11: no second window, the main game itself plays as the
    // chosen region for twenty seconds and the slot swaps in front of the Player.
    const id = regionIds[regionIndex];
    const label = (ctx.state.config.regions[id] || {}).label || id;
    await ctx.api.liveFlip(id, flipSeconds);
    ui.toast(`メインのゲームが ${flipSeconds} 秒だけ「${ui.regionJp(label)}」になります`,
             `The main game is a player in ${label} for ${flipSeconds} seconds`, '',
             flipSeconds * 1000);
    draw(ctx);
  } else if (focus === 2) {
    paused = !paused;
    await ctx.api.setPaused(paused);
    ui.toastKey(paused ? 'report_paused' : 'report_resume', 'staff', 3000);
    draw(ctx);
  } else if (focus === 3) {
    hide(ctx);
    await ctx.go('summary');
  } else {
    hide(ctx);
  }
}
