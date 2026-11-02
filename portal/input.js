// Where button presses come from.
//
// Two sources, one stream of events:
//   1. the pad helper (booth/pad_helper.py) reads controller 2 in the background and
//      relays every press over a WebSocket. Background input is the whole point: the
//      browser window never has to have focus for the pad to work, so staff can click
//      anywhere on the other monitor without the visitor's pad going dead.
//   2. the keyboard, as the hidden emergency fallback.
//
// Everything downstream sees the same button names, so a screen cannot tell which was
// used — and the scripted walkthrough (pad_helper.py --simulate) drives the real path.
//
// The same socket carries one message the other way: show or hide the region preview
// window (tour step 7). A web page cannot move another program's window, and the helper
// can, so the portal asks and the helper does it.

export const BUTTONS = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'A', 'B', 'X', 'Y',
                        'LB', 'RB', 'LT', 'RT', 'START', 'BACK'];

const KEY_MAP = {
  ArrowUp: 'UP', ArrowDown: 'DOWN', ArrowLeft: 'LEFT', ArrowRight: 'RIGHT',
  Enter: 'A', ' ': 'A', Escape: 'B', Backspace: 'B',
  y: 'Y', Y: 'Y', x: 'X', X: 'X',
  '-': 'LB', _: 'LB', '=': 'RB', '+': 'RB',      // bid down / up by the small step
  '[': 'LT', '{': 'LT', ']': 'RT', '}': 'RT',    // bid down / up by the big step
  Home: 'START', End: 'BACK',
};

export class Input {
  constructor({ port = 8701, onButton = () => {}, onStaff = () => {},
                onConnection = () => {}, onPreview = () => {} } = {}) {
    this.port = port;
    this.onButton = onButton;
    this.onStaff = onStaff;
    this.onConnection = onConnection;
    this.onPreview = onPreview;
    this.socket = null;
    this.online = false;
    this.controllers = [];
    this.retry = null;
  }

  start() {
    this.connect();
    window.addEventListener('keydown', (event) => this.handleKey(event));
    return this;
  }

  connect() {
    if (this.retry) { clearTimeout(this.retry); this.retry = null; }
    let socket;
    try {
      socket = new WebSocket(`ws://127.0.0.1:${this.port}`);
    } catch (problem) {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;
    socket.onopen = () => { this.online = true; this.onConnection(true, this.controllers); };
    socket.onclose = () => {
      if (this.online) this.onConnection(false, this.controllers);
      this.online = false;
      this.scheduleRetry();
    };
    socket.onerror = () => { try { socket.close(); } catch (problem) { /* already gone */ } };
    socket.onmessage = (event) => this.handleMessage(event.data);
  }

  scheduleRetry() {
    if (this.retry) return;
    this.retry = setTimeout(() => { this.retry = null; this.connect(); }, 1500);
  }

  /** Ask the helper to show or hide the region preview window. */
  previewWindow(show) {
    this.send({ type: 'preview', show: !!show });
  }

  send(message) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    try {
      this.socket.send(JSON.stringify(message));
      return true;
    } catch (problem) {
      return false;                 // the helper has gone; onclose will reconnect
    }
  }

  handleMessage(raw) {
    let message;
    try { message = JSON.parse(raw); } catch (problem) { return; }
    if (message.type === 'hello') {
      this.controllers = message.controllers || [];
      this.onConnection(true, this.controllers);
    } else if (message.type === 'button' && message.pressed) {
      this.emit(message.button, 'pad', !!message.repeat);
    } else if (message.type === 'staff') {
      this.onStaff(message);
    } else if (message.type === 'preview') {
      this.onPreview(message);
    }
  }

  handleKey(event) {
    if (event.repeat && !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      return;
    }
    let button = KEY_MAP[event.key];
    if (event.key === 'Tab') button = event.shiftKey ? 'LEFT' : 'RIGHT';
    if (!button) return;
    event.preventDefault();
    this.emit(button, 'key', !!event.repeat);
  }

  emit(button, source, repeat) {
    if (!BUTTONS.includes(button)) return;
    this.onButton({ button, source, repeat });
  }
}
