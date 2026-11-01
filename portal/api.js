// Everything the portal asks the demo server for. The portal is served from the same
// origin as the API (the server mounts portal/ at /portal/), so these are plain relative
// paths: no CORS, no base URL to configure, nothing to get wrong at the booth.

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function get(path) {
  const response = await fetch(path, { cache: 'no-store' });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, body.error || response.statusText, body);
  return body;
}

async function post(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload === undefined ? {} : payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, body.error || response.statusText, body);
  return body;
}

export class ApiError extends Error {
  constructor(status, sentence, body) {
    super(sentence);
    this.status = status;
    this.sentence = sentence;
    this.body = body || {};
  }
}

export const api = {
  publicConfig: () => get('/config/public'),
  clock: () => get('/clock'),
  brand: () => get('/brand'),
  setBrand: (colour, emblem) => post('/brand', { colour, emblem }),
  wallet: () => get('/wallet'),
  demoFiles: (purpose = 'upload') => get(`/demo-files?purpose=${encodeURIComponent(purpose)}`),
  content: () => get('/content'),
  games: () => get('/games'),
  game: (id) => get(`/games/${encodeURIComponent(id)}`),
  lots: (params = {}) => {
    const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v));
    return get(`/lots${query.toString() ? `?${query}` : ''}`);
  },
  liveStatus: () => get('/status/live'),
  reset: () => post('/admin/reset'),

  // ---- the auction, the report and the preview window --------------------------------
  lot: (id) => get(`/lots/${encodeURIComponent(id)}`),
  splitBid: (slot, total, regions) => get(
    `/bids/split?slot=${encodeURIComponent(slot)}&total=${total}`
    + `&regions=${encodeURIComponent(regions.join(','))}`),
  placeBids: (slot, contentId, bids) => post('/bids', {
    slot, content_id: contentId, bids,
  }),
  report: () => get('/report'),
  previewRegion: () => get('/preview/region'),
  setPreviewRegion: (region) => post('/preview/region', { region }),
  // The fallback when there is no second copy of the game: the main game plays as another
  // region for a few seconds and the slot swaps in front of the Player (plan v6 §11).
  liveFlip: (region, seconds) => post('/preview/flip', { region, seconds }),
  setPaused: (paused) => post('/campaign/pause', { paused }),

  /** The bytes of one file on "the brand's computer", with real read progress. */
  async readDemoFile(name, onProgress) {
    const response = await fetch(`/demo-files/${encodeURIComponent(name)}`, { cache: 'no-store' });
    if (!response.ok) throw new ApiError(response.status, `Could not read ${name}.`, {});
    const total = Number(response.headers.get('content-length') || 0);
    const reader = response.body.getReader();
    const chunks = [];
    let done = 0;
    for (;;) {
      const step = await reader.read();
      if (step.done) break;
      chunks.push(step.value);
      done += step.value.length;
      if (onProgress) onProgress(done, total);
    }
    return new Blob(chunks, { type: 'application/octet-stream' });
  },

  /** A real multipart upload, with the browser's own upload progress. */
  uploadContent(blob, filename, onProgress, contentId = null) {
    const path = contentId
      ? `/content/${encodeURIComponent(contentId)}/versions`
      : '/content';
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append('file', blob, filename);
      const request = new XMLHttpRequest();
      request.open('POST', path);
      request.upload.onprogress = (event) => {
        if (onProgress) onProgress(event.loaded, event.lengthComputable ? event.total : 0);
      };
      request.onload = () => {
        let body = {};
        try { body = JSON.parse(request.responseText); } catch (problem) { /* not JSON */ }
        if (request.status >= 200 && request.status < 300) resolve(body);
        else reject(new ApiError(request.status, body.error || request.statusText, body));
      };
      request.onerror = () => reject(new ApiError(0, 'The upload did not reach the server.', {}));
      request.send(form);
    });
  },
};
