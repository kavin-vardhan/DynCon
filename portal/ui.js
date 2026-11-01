// Small DOM helpers. Everything the portal draws goes through here, which is how the
// "every string is Japanese and English, JP on top" rule stays true by construction:
// there is no way to put text on screen except bi() / biText().

import { STRINGS, REGION_JP, japaneseFor } from './strings.js';

/** The Japanese line for a sentence the server wrote. */
export const japanese = japaneseFor;

// The bid keys, in one place because two screens use them (spec §2): the shoulders step
// by the auction's own minimum raise, the triggers by four of them.
const BID_STEPS = { LB: -25, RB: 25, LT: -100, RT: 100 };

export function bidStep(button) {
  return BID_STEPS[button] || 0;
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key === 'html') node.innerHTML = value;
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** A bilingual block from the string table. */
export function bi(key, cls = '') {
  const entry = STRINGS[key] || { jp: key, en: key };
  return biText(entry.jp, entry.en, cls);
}

/** A bilingual block from two sentences the caller already has. */
export function biText(jp, en, cls = '') {
  return el('span', { class: `bi ${cls}`.trim() },
    el('span', { class: 'jp' }, jp === null || jp === undefined ? '' : jp),
    el('span', { class: 'en' }, en === null || en === undefined ? '' : en));
}

/** A sentence the server wrote, with a Japanese line put above it. */
export function biServer(sentence, cls = '') {
  return biText(japaneseFor(sentence), sentence, cls);
}

/** A region, named as the server names it, with Japanese when this build knows it. */
export function biRegion(label, cls = '') {
  return biText(REGION_JP[label] || label, label, cls);
}

/** The Japanese name of a region, for building a sentence around it. */
export function regionJp(label) {
  return REGION_JP[label] || label;
}

export function heading(key, level = 'h2') {
  const entry = STRINGS[key] || { jp: key, en: key };
  return el(level, { class: 'bi' },
    el('span', { class: 'jp' }, entry.jp),
    el('span', { class: 'en' }, entry.en));
}

// ------------------------------------------------------------------ emblems
// The eight preset emblems, drawn as paths so the portal needs no image files and the
// same shape can be tinted any brand colour. The names match demo.json's brand_presets.
const EMBLEM_PATHS = {
  circle:   '<circle cx="12" cy="12" r="9"/>',
  triangle: '<path d="M12 3 L21.5 20 H2.5 Z"/>',
  square:   '<rect x="3.5" y="3.5" width="17" height="17" rx="1.5"/>',
  diamond:  '<path d="M12 1.8 L22.2 12 L12 22.2 L1.8 12 Z"/>',
  star:     '<path d="M12 2.2 L14.95 9.3 L22.6 9.9 L16.76 14.9 L18.55 22.4 L12 18.3 '
            + 'L5.45 22.4 L7.24 14.9 L1.4 9.9 L9.05 9.3 Z"/>',
  ring:     '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="4.2"/>',
  chevron:  '<path d="M3 6.5 L12 15.5 L21 6.5 L21 13 L12 22 L3 13 Z"/>',
  hexagon:  '<path d="M12 1.8 L21.2 7 L21.2 17 L12 22.2 L2.8 17 L2.8 7 Z"/>',
};

export function emblemSvg(name, colour = 'currentColor') {
  const body = EMBLEM_PATHS[name] || EMBLEM_PATHS.circle;
  return `<svg viewBox="0 0 24 24" fill="${colour}" aria-hidden="true">${body}</svg>`;
}

export function emblem(name, colour = 'currentColor') {
  return el('span', { class: 'emblem-holder', html: emblemSvg(name, colour) }).firstChild;
}

/** The brand's colour disc with its emblem punched out of it, as used in the header. */
export function brandMark(brand, cls = '') {
  const colour = (brand && brand.colour) || '#2b3a4d';
  const shape = (brand && brand.emblem) || 'circle';
  return el('span', {
    class: `mark ${cls}`.trim(),
    style: { background: colour },
    html: emblemSvg(shape, 'rgba(255,255,255,0.92)'),
  });
}

// ------------------------------------------------------------------ button glyphs
const GLYPH_CLASS = { A: 'a', B: 'b', X: 'x', Y: 'y' };

export function glyph(name) {
  const wide = name.length > 1;
  const face = name === 'DPAD' ? '✛' : name;
  // data-datum: the face of a button is the same letter in both languages — it is the
  // thing printed on the pad in the visitor's hands, not a word to translate.
  return el('span', {
    'data-datum': true,
    class: `glyph ${GLYPH_CLASS[name] || (name === 'DPAD' ? 'dpad' : '')} ${wide ? 'wide' : ''}`.trim(),
  }, face);
}

export function hint(button, key) {
  return el('span', { class: 'hint' }, glyph(button), bi(key));
}

// ------------------------------------------------------------------ formatting
export function num(value) {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('en-US');
}

export function mmss(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const whole = Math.max(0, Math.round(seconds));
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function hhmm(isoString) {
  if (!isoString) return '--:--';
  const date = new Date(isoString);
  return `${String(date.getUTCHours()).padStart(2, '0')}:`
       + `${String(date.getUTCMinutes()).padStart(2, '0')}`;
}

export function bytes(n) {
  if (n === null || n === undefined) return '—';
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

// ------------------------------------------------------------------ toast
let toastLayer = null;

export function toast(jp, en, kind = '', ms = 3200) {
  if (!toastLayer) {
    toastLayer = el('div', { class: 'toast-layer' });
    document.body.append(toastLayer);
  }
  const node = el('div', { class: `toast ${kind}`.trim() }, biText(jp, en));
  toastLayer.append(node);
  setTimeout(() => node.remove(), ms);
  return node;
}

export function toastKey(key, kind = '', ms = 3200) {
  const entry = STRINGS[key] || { jp: key, en: key };
  return toast(entry.jp, entry.en, kind, ms);
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}
