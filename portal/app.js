// The shell: what is on screen, who gets the buttons, and the three things that are
// always true — the header, the button-hint bar, and the idle reset.
//
// Screens are modules with one shape (see screens/attract.js). The shell owns the state
// every screen shares (the brand, the wallet, the demo clock, what was uploaded and which
// game was picked) and hands each screen a context object; a screen never reaches into
// another screen.

import { api } from './api.js';
import { Input } from './input.js';
import * as ui from './ui.js';
import { STRINGS } from './strings.js';

import * as menu from './menu.js';
import attract from './screens/attract.js';
import brand from './screens/brand.js';
import upload from './screens/upload.js';
import games from './screens/games.js';
import slotmap from './screens/slotmap.js';
import regions from './screens/regions.js';
import auction from './screens/auction.js';
import live from './screens/live.js';
import report from './screens/report.js';
import update from './screens/update.js';
import summary from './screens/summary.js';

const SCREENS = { attract, brand, upload, games, slotmap,
                  regions, auction, live, report, update, summary };

const appNode = document.getElementById('app');
const headerNode = document.getElementById('header');
const mainNode = document.getElementById('main');
const hintNode = document.getElementById('hintbar');

export const state = {
  config: null,            // /config/public
  brand: null,             // {colour, emblem}
  wallet: { available: 0, held: 0, charged: 0 },
  clock: null,             // the last /clock answer
  clockFetchedAt: 0,       // performance.now() when it arrived
  content: [],             // my content, from /content
  contentId: null,         // the piece the visitor is campaigning with
  game: null,              // the game id picked on screen 3
  slot: null,              // the slot being campaigned on, from screen 4 onwards
  bidRegions: null,        // the regions the visitor bid in, for the auction screen
  padOnline: false,
  controllers: [],
};

let current = null;         // the live screen module
let currentParams = {};
let input = null;           // the pad helper's socket, also the preview window's remote
let previewWindow = { found: null, shown: null };
let pollTimer = null;
let enterToken = 0;
let lastInputAt = performance.now();
let resetting = false;
let lastErrorToastAt = 0;

// --------------------------------------------------------------------- context

const ctx = {
  state,
  api,
  go,
  refreshHeader,
  setHints,
  toast: ui.toast,
  toastKey: ui.toastKey,
  async reloadContent() {
    const answer = await api.content();
    state.content = answer.content || [];
    state.brand = answer.brand || state.brand;
    if (!state.contentId && state.content.length) {
      state.contentId = state.content[state.content.length - 1].content_id;
    }
    return state.content;
  },
  chosenContent() {
    return state.content.find((c) => c.content_id === state.contentId) || null;
  },
  afterReset: () => afterReset(),
  restoreHints: () => restoreHints(),

  // Tour step 7: the second copy of the game is a window on this monitor, and the pad
  // helper is the only thing that can move it (a web page cannot). The portal asks when
  // the Region-check step opens and closes; `previewState()` is the helper's last answer,
  // so the step can say in plain words if the window is not running.
  previewWindow(show) {
    if (input) input.previewWindow(show);
  },
  previewState() {
    return previewWindow;
  },
};

// --------------------------------------------------------------------- the header

function demoClockText() {
  if (!state.clock) return '--:--';
  const elapsed = (performance.now() - state.clockFetchedAt) / 1000;
  const factor = Number(state.clock.demo_seconds_per_real_second || 60);
  const base = new Date(state.clock.demo_time).getTime();
  return ui.hhmm(new Date(base + elapsed * factor * 1000).toISOString());
}

function refreshHeader() {
  const show = !!current && current.showHeader !== false;
  headerNode.classList.toggle('hidden', !show);
  if (!show) return;

  ui.clear(headerNode);
  // append() turns a null into the string "null", so the pieces are filtered first.
  const pieces = [
    ui.el('span', { class: 'wordmark' },
      ui.el('span', { class: 'dot' }),
      ui.bi('app_name', 'name')),
    ui.el('span', { class: 'header-spacer' }),
    state.brand
      ? ui.el('span', { class: 'brand-chip' },
          ui.el('span', { class: 'swatch', style: { background: state.brand.colour },
                          html: ui.emblemSvg(state.brand.emblem, 'rgba(255,255,255,0.95)') }),
          ui.bi('your_brand', 'small'))
      : null,
    ui.el('span', { class: 'wallet' },
      ui.el('span', { class: 'cell' },
        ui.bi('wallet_available', 'label'),
        ui.el('span', { class: 'value mono', 'data-datum': true },
              ui.num(state.wallet.available))),
      ui.el('span', { class: 'cell held' },
        ui.bi('wallet_held', 'label'),
        ui.el('span', { class: 'value mono', 'data-datum': true },
              ui.num(state.wallet.held)))),
    ui.el('span', { class: 'clock' },
      ui.bi('clock_label', 'label'),
      ui.el('span', { class: 'value mono', id: 'demo-clock', 'data-datum': true },
            demoClockText())),
    ui.el('span', { class: 'pad-light', title: state.padOnline ? 'pad' : 'no pad' }),
  ];
  headerNode.append(...pieces.filter(Boolean));
}

function tickClockDisplay() {
  const node = document.getElementById('demo-clock');
  if (node) node.textContent = demoClockText();
}

// --------------------------------------------------------------------- hints

function setHints(hints, note = null) {
  ui.clear(hintNode);
  for (const [button, key] of hints) hintNode.append(ui.hint(button, key));
  // The "demo credits — not real money" line lives at the right of the bar, but a screen
  // with five button hints has no room for it; those screens carry it in the panel where
  // the credits are, which is where the spec wants it anyway.
  if (note || hints.length <= 4) {
    hintNode.append(ui.el('span', { class: 'note' },
      note ? ui.bi(note) : ui.bi('demo_credits_note')));
  }
}

/** Put back the hints the live screen asked for (after the menu borrowed the bar). */
function restoreHints() {
  if (!current) return;
  setHints(typeof current.hints === 'function' ? current.hints(ctx) : (current.hints || []),
           current.hintNote);
}

// --------------------------------------------------------------------- routing

export async function go(name, params = {}) {
  const screen = SCREENS[name];
  if (!screen) throw new Error(`no screen called ${name}`);
  const token = ++enterToken;

  if (current && current.exit) {
    try { current.exit(ctx); } catch (problem) { console.error(problem); }
  }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

  current = screen;
  currentParams = params;
  appNode.dataset.screen = name;
  appNode.dataset.state = '';
  ui.clear(mainNode);
  mainNode.className = screen.mainClass || '';
  refreshHeader();
  setHints(typeof screen.hints === 'function' ? screen.hints(ctx) : (screen.hints || []),
           screen.hintNote);

  await screen.enter(ctx, mainNode, params);
  if (token !== enterToken) return;            // a faster finger moved on already

  pollTimer = setInterval(() => poll(token), screen.pollMs || 1000);
}

async function poll(token) {
  if (token !== enterToken || !current) return;
  try {
    if (current.refresh) await current.refresh(ctx);
  } catch (problem) {
    if (performance.now() - lastErrorToastAt > 8000) {
      lastErrorToastAt = performance.now();
      ui.toastKey('error_server', 'bad');
    }
    console.error(problem);
  }
}

// --------------------------------------------------------------------- input

function onButton(event) {
  lastInputAt = performance.now();
  if (!current) return;
  try {
    // The Start menu is modal while it is up: it owns the pad and the hint bar.
    if (menu.isOpen()) {
      Promise.resolve(menu.pad(event.button, ctx)).catch((p) => console.error(p));
      return;
    }
    if (event.button === 'START' && current.showHeader !== false) {
      Promise.resolve(menu.show(ctx)).catch((p) => console.error(p));
      return;
    }
    current.pad(event.button, ctx, event);
  } catch (problem) {
    console.error(problem);
  }
}

async function onStaff(message) {
  lastInputAt = performance.now();
  const key = {
    reset: 'staff_reset', 'close-auction': 'staff_close',
    corrupt: 'staff_corrupt', freeze: 'staff_freeze',
  }[message.action];
  if (key) ui.toastKey(key, 'staff');
  if (message.action === 'reset') await afterReset();
}

function onConnection(online, controllers) {
  state.padOnline = online;
  state.controllers = controllers || [];
  appNode.dataset.pad = online ? 'online' : 'offline';
  refreshHeader();
}

function onPreview(message) {
  previewWindow = { found: !!message.found, shown: message.shown === true };
  appNode.dataset.preview = previewWindow.found
    ? (previewWindow.shown ? 'shown' : 'hidden') : 'missing';
  if (menu.isOpen()) menu.redraw(ctx);
}

// --------------------------------------------------------------------- the reset

async function afterReset() {
  if (menu.isOpen()) menu.hide(ctx);
  state.brand = null;
  state.content = [];
  state.contentId = null;
  state.game = null;
  state.slot = null;
  state.bidRegions = null;
  state.wallet = { available: state.config ? state.config.wallet : 0, held: 0, charged: 0 };
  await go('attract');
}

async function idleReset() {
  if (resetting) return;
  resetting = true;
  try {
    ui.toastKey('idle_resetting', '', 2500);
    await api.reset();
    await afterReset();
  } catch (problem) {
    console.error(problem);
  } finally {
    lastInputAt = performance.now();
    resetting = false;
  }
}

// --------------------------------------------------------------------- boot

async function boot() {
  state.config = await api.publicConfig();
  state.clock = state.config.clock;
  state.clockFetchedAt = performance.now();
  state.wallet = { available: state.config.wallet, held: 0, charged: 0 };

  const brandAnswer = await api.brand().catch(() => null);
  if (brandAnswer) {
    state.brand = brandAnswer.brand;
    state.wallet = brandAnswer.wallet || state.wallet;
  }

  const padPort = Number(new URLSearchParams(location.search).get('pad') || 8701);
  input = new Input({ port: padPort, onButton, onStaff, onConnection, onPreview }).start();

  setInterval(tickClockDisplay, 250);
  setInterval(async () => {
    try {
      const answer = await api.clock();
      state.clock = answer;
      state.clockFetchedAt = performance.now();
    } catch (problem) { /* the next tick will do */ }
  }, 5000);

  // `?idle=5` shortens the idle reset so a test (or a rehearsal) can watch it happen
  // without standing there for a minute. The booth URL has no query and gets the
  // server's own 60 seconds.
  const asked = Number(new URLSearchParams(location.search).get('idle') || 0);
  const idleSeconds = asked > 0 ? asked
    : Number((state.config && state.config.idle_reset_s) || 60);
  setInterval(() => {
    if (!current || current.id === 'attract') { lastInputAt = performance.now(); return; }
    if ((performance.now() - lastInputAt) / 1000 >= idleSeconds) idleReset();
  }, 1000);

  await go('attract');
}

boot().catch((problem) => {
  console.error(problem);
  mainNode.append(ui.el('div', { class: 'panel' },
    ui.biText(STRINGS.error_server.jp, `${STRINGS.error_server.en}: ${problem.message}`)));
});
