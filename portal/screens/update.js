// Screen 10 — push an update.
//
// A brand will want to change its content while it is live. The patent's promise is that
// this never interrupts a player: if someone is inside when the new version arrives, the
// game keeps the old one until they walk out, then swaps, and carries over whatever they
// had changed inside.
//
// What this screen can honestly show, and where each line comes from:
//   1 approved   — the server's four checks on the version 2 upload (the same gate);
//   2 serving v2 — `/status/live` says the platform now answers this slot with v2;
//   3 swapped    — the game reported a mount after the upload (`/report`'s mount count
//                  for this region went up). Until then it says, in both languages, that
//                  it will swap when the player walks out. The portal never claims the
//                  swap happened on its own.

import * as ui from '../ui.js';

const MIN_READ_MS = 700;
const MIN_SEND_MS = 1200;
const CHECK_STEP_MS = 380;
const CHECK_KEYS = { package: 'check_package', rating: 'check_rating',
                     fit: 'check_fit', sign: 'check_sign' };

let files = [];
let focus = 0;
let mode = 'files';             // files | busy | watching
let baseMounts = 0;
let liveVersion = null;
let swapped = false;
let nodes = {};

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

function appState(value) {
  document.getElementById('app').dataset.state = value;
}

function pieceWords(piece, version) {
  const n = String(piece || '').replace(/^content/, '');
  return ui.txText(`Content ${n}${version ? ` · ${version}` : ''}`);
}

function drawFiles() {
  const body = ui.clear(nodes.files);
  files.forEach((row, index) => {
    const node = ui.el('div', { class: 'file-row focusable no-scale' },
      ui.el('span', { class: 'name' }, pieceWords(row.piece, row.version)),
      ui.el('span', { class: 'filename', 'data-datum': true }, row.name),
      ui.el('span', { class: 'tag', 'data-datum': true }, row.size_class),
      ui.el('span', { class: 'size', 'data-datum': true }, ui.bytes(row.bytes)));
    node.dataset.file = row.name;
    body.append(node);
  });
  paintFocus();
}

function paintFocus() {
  [...nodes.files.querySelectorAll('.file-row')].forEach((node, i) => {
    node.classList.toggle('focused', mode === 'files' && i === focus);
  });
}

function drawStage(ctx, checks) {
  const body = ui.clear(nodes.stage);
  const approved = !!checks;
  const serving = liveVersion === 'v2';

  body.append(
    ui.el('div', { class: 'steps' },
      ui.el('div', { class: `step ${approved ? 'done' : ''}`.trim() },
        ui.el('span', { class: 'mark', 'data-datum': true }, approved ? '✓' : '1'),
        ui.el('span', { class: 'what' }, ui.tx('update_step_ok'))),
      ui.el('div', { class: `step ${serving ? 'done' : approved ? 'busy' : ''}`.trim() },
        ui.el('span', { class: 'mark', 'data-datum': true }, serving ? '✓' : '2'),
        ui.el('span', { class: 'what' }, ui.tx('update_step_serving'))),
      ui.el('div', { class: `step ${swapped ? 'done' : serving ? 'busy' : ''}`.trim() },
        ui.el('span', { class: 'mark', 'data-datum': true }, swapped ? '✓' : '3'),
        ui.el('span', { class: 'what' }, ui.tx('update_step_swapped')))),
    ui.el('div', { class: swapped ? 'fits-note' : 'panel-inset' },
      ui.tx(swapped ? 'update_swapped' : 'update_inside', 'small')));
  if (checks) {
    // The same four checks as the first upload, as four ticks: the sentences behind them
    // were read on the upload screen, and this screen's story is the swap.
    body.append(ui.el('div', { class: 'check-pills' }, checks.map((check) => ui.el(
      'div', { class: `pill ${check.ok === true ? 'ok' : check.ok === false ? 'bad' : ''}`.trim() },
      ui.el('span', { class: 'mark', 'data-datum': true },
            check.ok === true ? '✓' : check.ok === false ? '✕' : '·'),
      ui.tx(CHECK_KEYS[check.check] || check.check, 'small')))));
  }
}

async function runPhase(phase, minMs, work) {
  const started = performance.now();
  let real = 0;
  const timer = setInterval(() => {
    const shown = Math.min(real, Math.min(1, (performance.now() - started) / minMs));
    phase.fill.style.width = `${(shown * 100).toFixed(1)}%`;
    phase.pct.textContent = `${Math.round(shown * 100)}%`;
  }, 60);
  try {
    const result = await work((done, total) => { if (total) real = done / total; });
    const left = minMs - (performance.now() - started);
    if (left > 0) await sleep(left);
    phase.fill.style.width = '100%';
    phase.pct.textContent = '100%';
    return result;
  } finally {
    clearInterval(timer);
  }
}

async function upload(ctx) {
  const row = files[focus];
  if (!row) return;
  mode = 'busy';
  ctx.setHints([]);
  appState('working');

  const fill = ui.el('div', { class: 'fill' });
  const pct = ui.el('span', { class: 'pct mono', 'data-datum': true }, '0%');
  const label = ui.tx('upload_reading');
  const bar = ui.el('div', { class: 'progress' },
    ui.el('div', { class: 'meta' }, label, pct),
    ui.el('div', { class: 'track' }, fill));
  ui.clear(nodes.stage).append(bar);
  const phase = { fill, pct, label };

  const blob = await runPhase(phase, MIN_READ_MS,
    (onProgress) => ctx.api.readDemoFile(row.name, onProgress));
  const sending = ui.tx('upload_sending');
  phase.label.replaceWith(sending);
  phase.label = sending;
  fill.style.width = '0%';

  const answer = await runPhase(phase, MIN_SEND_MS,
    (onProgress) => ctx.api.uploadContent(blob, row.name, onProgress, ctx.state.contentId));

  if (answer.status !== 'approved') {
    appState('rejected');
    ui.toast(answer.reason, 'bad', 6000);
    mode = 'files';
    drawFiles();
    drawStage(ctx, answer.checks);
    return;
  }

  nodes.checks = answer.checks;
  drawStage(ctx, answer.checks);
  await sleep(CHECK_STEP_MS);
  mode = 'watching';
  appState('pushed');
  ctx.setHints([['A', 'hint_back'], ['START', 'hint_menu']]);
  await ctx.reloadContent().catch(() => null);
}

export default {
  id: 'update',
  showHeader: true,
  pollMs: 1000,
  hints: [['DPAD', 'hint_move'], ['A', 'hint_upload'], ['B', 'hint_back']],

  async enter(ctx, root) {
    mode = 'files';
    focus = 0;
    swapped = false;
    liveVersion = null;
    nodes = { checks: null };

    const mineContent = ctx.chosenContent();
    const answer = await ctx.api.demoFiles('update');
    files = (answer.files || []).filter(
      (row) => !mineContent || row.piece === mineContent.piece);
    if (!files.length) files = answer.files || [];

    // where the mount count stands before the update, so an increase afterwards is the
    // game really swapping, not a mount from before
    const report = await ctx.api.report();
    const region = (ctx.state.config.booth || {}).main_region || 'r1';
    baseMounts = ((report.regions || []).find((r) => r.region === region) || {}).mounts || 0;

    nodes.files = ui.el('div', { class: 'body' });
    nodes.stage = ui.el('div', { class: 'stage' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('update_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.tx('update_sub', 'small'))),
      ui.el('div', { class: 'columns' },
        ui.el('div', { class: 'panel col', style: { flex: '0 0 34rem' } },
          ui.heading('upload_your_computer'),
          nodes.files),
        ui.el('div', { class: 'panel col grow' }, nodes.stage)));

    drawFiles();
    drawStage(ctx, null);
    appState('idle');
  },

  async refresh(ctx) {
    if (mode === 'busy') return;
    const region = (ctx.state.config.booth || {}).main_region || 'r1';
    const [live, report] = await Promise.all([ctx.api.liveStatus(), ctx.api.report()]);
    const row = (live.showing || []).find(
      (r) => r.slot === ctx.state.slot && r.region === region && r.kind === 'visitor');
    liveVersion = row ? row.version : null;
    const mounts = ((report.regions || []).find((r) => r.region === region) || {}).mounts || 0;
    if (mode === 'watching' && liveVersion === 'v2' && mounts > baseMounts) swapped = true;
    if (mode === 'watching') {
      drawStage(ctx, nodes.checks);
      appState(swapped ? 'swapped' : 'pushed');
    }
  },

  pad(button, ctx) {
    if (mode === 'busy') return;
    if (button === 'B') { ctx.go('report'); return; }
    if (mode === 'watching') {
      if (button === 'A' || button === 'Y') ctx.go('report');
      return;
    }
    if (button === 'UP') focus = Math.max(0, focus - 1);
    else if (button === 'DOWN') focus = Math.min(files.length - 1, focus + 1);
    else if (button === 'A' || button === 'Y') {
      upload(ctx).catch((problem) => {
        console.error(problem);
        mode = 'files';
        ui.toast(problem.sentence || String(problem), 'bad');
      });
      return;
    }
    paintFocus();
  },
};
