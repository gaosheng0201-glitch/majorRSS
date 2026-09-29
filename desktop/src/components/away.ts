import { useSyncExternalStore } from 'react';
import client from '../api/client';

// 醒来不漏 (2026-09-28). A tray app's pages stay mounted for days, so "since you
// last looked" can't be "since the page loaded". This tracks when you were
// actually looking (window visible and focused), notices when you come back —
// after hiding the window or after the machine slept — and holds the list of
// what you missed (GET /intelligence/away) until you dismiss it. While you are
// away the count sits next to the menu-bar icon: no notification permission
// needed, and it is still there when you return. The machine is never kept
// awake for this (the user's device); P8 is the always-on path.

export interface AwayHighlight {
  thread_id: number;
  title: string;
  reasons: string[];
  lifecycle: string;
  is_resonant: boolean;
  distinct_source_count: number;
  targets: string[];
  first_seen_at: string | null;
  url: string | null;
}

interface AwayState {
  since: string | null;       // set when you came back; null while here / after dismiss
  highlights: AwayHighlight[];
  count: number;
}

const LAST_ACTIVE_KEY = 'radar_last_active_at';
const AWAY_SINCE_KEY = 'radar_away_since';
const AWAY_MIN_MS = 15 * 60 * 1000;   // shorter absences are not "away"
const TICK_MS = 60 * 1000;

let state: AwayState = { since: null, highlights: [], count: 0 };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

const get = (k: string): string | null => {
  try { return localStorage.getItem(k); } catch { return null; }
};
const put = (k: string, v: string | null) => {
  try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* ignore */ }
};

const isActive = () => document.visibilityState === 'visible' && document.hasFocus();

let inTauri = false;
let lastBadge = -1;
async function setBadge(n: number) {
  if (!inTauri || n === lastBadge) return;
  lastBadge = n;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('set_tray_badge', { count: n });
  } catch { /* badge is best effort */ }
}

async function refresh() {
  const awaySince = get(AWAY_SINCE_KEY);
  // While you are here and nothing is pending, there is nothing to show.
  const since = awaySince || (isActive() ? null : get(LAST_ACTIVE_KEY));
  if (!since) {
    if (state.count || state.since) { state = { since: null, highlights: [], count: 0 }; emit(); }
    setBadge(0);
    return;
  }
  try {
    const r = await client.get('/intelligence/away', { params: { since } });
    state = { since: awaySince, highlights: r.data.highlights || [], count: r.data.count || 0 };
    emit();
    setBadge(state.count);
  } catch { /* transient: keep the last list */ }
}

function tick() {
  const now = Date.now();
  if (isActive()) {
    const last = Date.parse(get(LAST_ACTIVE_KEY) || '');
    // Back after an absence (window hidden, or the machine slept while it was
    // in front — then the last "still here" mark is from before the sleep).
    if (!get(AWAY_SINCE_KEY) && !Number.isNaN(last) && now - last >= AWAY_MIN_MS) {
      put(AWAY_SINCE_KEY, new Date(last).toISOString());
    }
    put(LAST_ACTIVE_KEY, new Date(now).toISOString());
  }
  refresh();
}

let started = false;
export function startAwayWatcher(isTauri: boolean) {
  if (started) return;
  started = true;
  inTauri = isTauri;
  if (!get(LAST_ACTIVE_KEY)) put(LAST_ACTIVE_KEY, new Date().toISOString());
  tick();
  setInterval(tick, TICK_MS);
  window.addEventListener('focus', tick);
  document.addEventListener('visibilitychange', tick);
}

/** "Got it": the list is read; the next absence starts from now. */
export function dismissAway() {
  put(AWAY_SINCE_KEY, null);
  put(LAST_ACTIVE_KEY, new Date().toISOString());
  state = { since: null, highlights: [], count: 0 };
  emit();
  setBadge(0);
}

export function useAway(): AwayState {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => state,
  );
}
