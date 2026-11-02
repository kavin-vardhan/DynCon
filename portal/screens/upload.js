// Screen 2 — Upload.
//
// The one screen where the demo is doing something real rather than showing something
// real: the file comes off "the brand's computer" over HTTP, goes back up to the server
// as a genuine multipart upload, and the four checks that tick across the screen are the
// server's own answers (package → rating → fit → sign), not an animation with a happy
// ending written in. One file in the list is built to fail, and it fails with the
// server's own sentence.

import * as ui from '../ui.js';
import { STRINGS } from '../strings.js';

// The read and the send are over a loopback socket, so both finish faster than an eye can
// follow. The bar is therefore shown over a floor of this many milliseconds — but it never
// shows more progress than has really happened (see runPhase: it takes the LOWER of the
// real fraction and the elapsed fraction), so it can lag the truth and never lead it.
const MIN_READ_MS = 900;
const MIN_SEND_MS = 1400;
const CHECK_STEP_MS = 420;

const CHECK_KEYS = { package: 'check_package', rating: 'check_rating',
                     fit: 'check_fit', sign: 'check_sign' };

let files = [];
let mode = 'files';            // 'files' | 'actions' | 'busy'
let fileFocus = 0;
let actionFocus = 0;
let actions = [];              // [{key, run}]
let nodes = {};

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

function appState(value) {
  document.getElementById('app').dataset.state = value;
}

/** Which of the four checks a rejection stopped at. */
function stoppedAt(check) {
  const name = STRINGS[CHECK_KEYS[check]] || check;
  return ui.txText(`Stopped at: ${String(name).toLowerCase()}`, 'small tail');
}

function pieceWords(row) {
  const n = String(row.piece || '').replace(/^content/, '');
  return ui.txText(`Content ${n}${row.version ? ` · ${row.version}` : ''}`);
}

function fileRow(row, index) {
  const node = ui.el('div', { class: 'file-row focusable no-scale' },
    ui.el('span', { class: 'name' }, pieceWords(row)),
    ui.el('span', { class: 'filename', 'data-datum': true }, row.name),
    row.size_class ? ui.el('span', { class: 'tag', 'data-datum': true }, row.size_class) : null,
    row.note ? ui.el('span', { class: 'tag bad' }, ui.txText(row.note, 'small')) : null,
    ui.el('span', { class: 'size', 'data-datum': true }, ui.bytes(row.bytes)));
  node.dataset.file = row.name;
  node.dataset.index = index;
  return node;
}

function paintFocus() {
  nodes.fileNodes.forEach((node, i) => {
    node.classList.toggle('focused', mode === 'files' && i === fileFocus);
  });
  nodes.actionNodes.forEach((node, i) => {
    node.classList.toggle('focused', mode === 'actions' && i === actionFocus);
  });
}

function setHints(ctx) {
  if (mode === 'files') {
    ctx.setHints([['DPAD', 'hint_move'], ['A', 'hint_upload'], ['B', 'hint_back']]);
  } else if (mode === 'actions') {
    ctx.setHints([['DPAD', 'hint_move'], ['A', 'hint_select'], ['B', 'hint_back']]);
  } else {
    ctx.setHints([]);
  }
}

// ------------------------------------------------------------------ the stage

function clearStage() {
  return ui.clear(nodes.stage);
}

/** Swap the panel's heading for the verdict, or back to the question it asks. */
function verdict(node) {
  ui.clear(nodes.verdict).append(node || ui.heading('upload_checking'));
}

function idleStage() {
  clearStage().append(ui.el('div', { class: 'idle' },
    ui.glyph('A'), ui.tx('upload_pick')));
  verdict(null);
  appState('idle');
}

function progressStage(labelKey) {
  const fill = ui.el('div', { class: 'fill' });
  const pct = ui.el('span', { class: 'pct', 'data-datum': true }, '0%');
  const label = ui.tx(labelKey);
  const bar = ui.el('div', { class: 'progress' },
    ui.el('div', { class: 'meta' }, label, pct),
    ui.el('div', { class: 'track' }, fill));
  return { bar, fill, pct, label };
}

function checkRows(checks) {
  return checks.map((check) => {
    const state = check.ok === true ? 'ok' : check.ok === false ? 'failed' : '';
    const mark = check.ok === true ? '✓' : check.ok === false ? '✕' : '·';
    return ui.el('div', { class: `check-row ${state}`.trim() },
      ui.el('span', { class: 'mark', 'data-datum': true }, mark),
      ui.el('span', { class: 'what' }, ui.tx(CHECK_KEYS[check.check] || check.check)),
      ui.el('span', { class: 'detail' },
        check.detail ? ui.txText(check.detail, 'small') : ui.tx('check_skipped', 'small')));
  });
}

async function runPhase(phase, minMs, work) {
  const started = performance.now();
  let real = 0;
  const timer = setInterval(() => {
    const byTime = Math.min(1, (performance.now() - started) / minMs);
    const shown = Math.min(real, byTime);
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

// ------------------------------------------------------------------ my content

function fitPills(content) {
  const fits = content.fits || {};
  return Object.entries(fits).map(([slot, verdict]) => ui.el('span', {
    class: `fit-pill ${verdict.ok ? '' : 'no'}`.trim(),
    title: verdict.reason,
    'data-datum': true,
  }, slot));
}

function drawMyContent(ctx) {
  const body = ui.clear(nodes.mine);
  const list = ctx.state.content || [];
  if (!list.length) {
    body.append(ui.el('div', { class: 'muted' }, ui.tx('upload_empty', 'small')));
    return;
  }
  for (const content of list) {
    const latest = content.latest_approved;
    body.append(ui.el('div', { class: 'content-card' },
      ui.el('span', { class: 'row' },
        ui.el('span', { class: 'piece' },
          pieceWords({ piece: content.piece, version: latest ? latest.version : null })),
        ui.el('span', { class: 'tag', 'data-datum': true }, content.size_class)),
      ui.el('span', { class: 'fits' }, fitPills(content))));
  }
}

// ------------------------------------------------------------------ the upload

async function uploadFocused(ctx) {
  const row = files[fileFocus];
  if (!row) return;
  mode = 'busy';
  setHints(ctx);
  paintFocus();
  appState('working');

  const stage = clearStage();
  const phase = progressStage('upload_reading');
  stage.append(phase.bar);

  const blob = await runPhase(phase, MIN_READ_MS,
    (onProgress) => ctx.api.readDemoFile(row.name, onProgress));

  const sending = ui.tx('upload_sending');
  phase.label.replaceWith(sending);
  phase.label = sending;
  phase.fill.style.width = '0%';

  const answer = await runPhase(phase, MIN_SEND_MS,
    (onProgress) => ctx.api.uploadContent(blob, row.name, onProgress));

  // The checks are the server's own four answers; they are revealed one at a time so a
  // visitor can read what the platform did, in the order it did it. The bar goes away
  // as they start: this is a ten-foot screen, and there is only room for one story.
  phase.bar.remove();
  const checksBox = ui.el('div', { class: 'checks' });
  stage.append(checksBox);
  appState('checking');
  const rows = checkRows(answer.checks || []);
  for (const node of rows) {
    checksBox.append(node);
    await sleep(CHECK_STEP_MS);
    node.classList.add('done');
  }

  if (answer.status === 'approved') {
    ctx.state.contentId = answer.content_id;
    await ctx.reloadContent();
    drawMyContent(ctx);
    // The verdict takes the panel's own heading rather than adding a box under the
    // checks: it is the answer to the question the heading asked.
    verdict(ui.el('div', { class: 'verdict' },
      ui.el('span', { class: 'badge', 'data-datum': true }, '✓'),
      ui.el('span', { class: 'what' }, ui.tx('upload_approved')),
      ui.txText(`Class ${answer.size_class}`, 'small tail')));
    actions = [{ key: 'upload_continue', run: () => ctx.go('games') },
               { key: 'upload_again', run: () => { idleStage(); mode = 'files'; setHints(ctx);
                                                   paintFocus(); } }];
    appState('approved');
  } else {
    // The reason is already on the check that failed, word for word, so the verdict
    // itself only has to say which way it went.
    verdict(ui.el('div', { class: 'verdict bad' },
      ui.el('span', { class: 'badge', 'data-datum': true }, '✕'),
      ui.el('span', { class: 'what' }, ui.tx('upload_rejected')),
      stoppedAt(answer.failed_check)));
    actions = [{ key: 'upload_again', run: () => { idleStage(); mode = 'files'; setHints(ctx);
                                                   paintFocus(); } }];
    if (ctx.state.contentId) {
      actions.push({ key: 'upload_continue', run: () => ctx.go('games') });
    }
    appState('rejected');
  }

  ui.clear(nodes.actions);
  nodes.actionNodes = actions.map((action, i) => {
    const node = ui.el('div', { class: 'button focusable' + (i === 0 ? ' primary' : '') },
      ui.glyph('A'), ui.tx(action.key));
    node.dataset.action = action.key;
    return node;
  });
  nodes.actions.append(...nodes.actionNodes);
  mode = 'actions';
  actionFocus = 0;
  setHints(ctx);
  paintFocus();
}

export default {
  id: 'upload',
  showHeader: true,
  pollMs: 4000,
  hints: [['DPAD', 'hint_move'], ['A', 'hint_upload'], ['B', 'hint_back']],

  async enter(ctx, root) {
    mode = 'files';
    fileFocus = 0;
    actionFocus = 0;
    actions = [];
    nodes = { fileNodes: [], actionNodes: [] };

    const answer = await ctx.api.demoFiles('upload');
    files = answer.files || [];

    nodes.fileNodes = files.map((row, i) => fileRow(row, i));
    nodes.verdict = ui.el('div', { class: 'verdict-slot' });
    nodes.stage = ui.el('div', { class: 'stage' });
    nodes.actions = ui.el('div', { class: 'row', style: { gap: '1.25rem' } });
    nodes.mine = ui.el('div', { class: 'mine-cards body' });

    root.append(
      ui.el('div', { class: 'screen-head' },
        ui.heading('upload_title', 'h1'),
        ui.el('span', { class: 'sub' }, ui.tx('upload_pick', 'small'))),
      ui.el('div', { class: 'columns' },
        // Three columns, left to right: the files the brand has, what the platform does
        // with the one it is given, and what the brand ends up owning. Each is its own
        // panel so none of them can squeeze another off the screen.
        ui.el('div', { class: 'panel col', style: { flex: '0 0 32rem' } },
          ui.heading('upload_your_computer'),
          ui.el('div', { class: 'body' }, nodes.fileNodes)),
        ui.el('div', { class: 'panel col grow' },
          nodes.verdict,
          nodes.stage,
          nodes.actions),
        ui.el('div', { class: 'panel col', style: { flex: '0 0 18rem' } },
          ui.heading('upload_my_content'),
          nodes.mine)),
    );

    idleStage();
    await ctx.reloadContent().catch(() => null);
    drawMyContent(ctx);
    paintFocus();
  },

  async refresh(ctx) {
    if (mode === 'busy') return;
    await ctx.reloadContent();
    drawMyContent(ctx);
  },

  pad(button, ctx) {
    if (mode === 'busy') return;
    if (button === 'B') {
      if (mode === 'actions') { idleStage(); mode = 'files'; setHints(ctx); paintFocus(); }
      else ctx.go('brand');
      return;
    }
    if (mode === 'files') {
      if (button === 'UP') fileFocus = Math.max(0, fileFocus - 1);
      else if (button === 'DOWN') fileFocus = Math.min(files.length - 1, fileFocus + 1);
      else if (button === 'RIGHT' && nodes.actionNodes.length) { mode = 'actions'; actionFocus = 0; }
      else if (button === 'A' || button === 'Y') {
        uploadFocused(ctx).catch((problem) => {
          console.error(problem);
          mode = 'files';
          setHints(ctx);
          ui.toast(problem.sentence || String(problem), 'bad');
          idleStage();
        });
        return;
      }
      paintFocus();
      setHints(ctx);
      return;
    }
    if (mode === 'actions') {
      if (button === 'LEFT' && actionFocus === 0) { mode = 'files'; }
      else if (button === 'LEFT') actionFocus = Math.max(0, actionFocus - 1);
      else if (button === 'RIGHT') actionFocus = Math.min(actions.length - 1, actionFocus + 1);
      else if (button === 'A') { actions[actionFocus].run(); return; }
      paintFocus();
      setHints(ctx);
    }
  },
};
