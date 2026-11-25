import { useCallback, useEffect, useRef, useState } from 'react';
import type { Case, CaseData, Ev, Investigation } from './types';

/** Every event the server sends (app/models.py EVENT_TYPES). Server-sent events reach only listeners registered for
 * their name, so a type missing here never reaches the page; tests/test_event_contract.py checks this list. */
export const EVENT_TYPES = [
  'message.received', 'persona.reply', 'scam.detected', 'intel.extracted', 'case.updated', 'kane.started',
  'kane.finished',
];

type Listener = (ev: Ev) => void;
const listeners = new Set<Listener>();
const statusListeners = new Set<(up: boolean) => void>();
let source: EventSource | null = null;
let up = false;

function setUp(v: boolean) {
  up = v;
  statusListeners.forEach((fn) => fn(v));
}

/** One EventSource for the whole page. It reconnects by itself and replays the gap with Last-Event-ID. */
function connect() {
  if (source) return;
  source = new EventSource('/api/events');
  source.onopen = () => setUp(true);
  source.onerror = () => setUp(false);
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (msg) => {
      let ev: Ev;
      try { ev = JSON.parse((msg as MessageEvent).data); } catch { return; }
      listeners.forEach((fn) => fn(ev));
    });
  }
}

export function onEvent(fn: Listener): () => void {
  connect();
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function useConnected(): boolean {
  const [v, setV] = useState(up);
  useEffect(() => {
    connect();
    statusListeners.add(setV);
    return () => { statusListeners.delete(setV); };
  }, []);
  return v;
}

export async function getJSON<T = any>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(url + ' answered ' + r.status);
  return r.json();
}

export async function postJSON<T = any>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d as any).detail || url + ' answered ' + r.status);
  return d as T;
}

function applyKane(list: Investigation[], ev: Ev): Investigation[] {
  const d = ev.data || {};
  const id = d.investigation_id;
  if (id == null) return list;
  const i = list.findIndex((x) => x.id === id);
  const base: Investigation = i >= 0 ? list[i] : {
    id, url: d.url || '', status: 'queued', verdict: '', claims_to_be: '', payee: '', payee_kind: '', amount: '',
    asked_for: [], summary: '', reason: '', evidence: false, evidence_sha256: '', created_at: ev.ts,
  };
  const next: Investigation = ev.type === 'kane.started'
    ? { ...base, status: 'running', url: d.url || base.url }
    : { ...base, ...d, id, asked_for: d.asked_for || base.asked_for, finished_at: ev.ts };
  return i >= 0 ? list.map((x, j) => (j === i ? next : x)) : [...list, next];
}

/** Apply one live event to a loaded case. Events already in the case (same id) are skipped. */
export function applyEvent(cd: CaseData, ev: Ev): CaseData {
  if (ev.id != null && cd.events.some((e) => e.id === ev.id)) return cd;
  const d = ev.data || {};
  const next: CaseData = { ...cd, events: [...cd.events, ev] };
  if ((ev.type === 'message.received' || ev.type === 'persona.reply') && d.message_id != null
      && !cd.messages.some((m) => m.id === d.message_id)) {
    next.messages = [...cd.messages, { id: d.message_id, case_id: cd.case.id, role: ev.type === 'persona.reply' ? 'persona' : 'scammer', text: d.text, ts: ev.ts }];
  }
  if (ev.type === 'intel.extracted' && !cd.intel.some((i) => i.kind === d.kind && i.value === d.value)) {
    next.intel = [...cd.intel, { kind: d.kind, value: d.value, message_id: d.message_id, first_seen: ev.ts }];
  }
  if (ev.type === 'scam.detected' && d.verdict && d.verdict !== 'unknown') {
    next.case = { ...next.case, verdict: d.verdict, scam_type: d.verdict === 'scam' ? d.scam_type : next.case.scam_type };
  }
  if (ev.type === 'case.updated') next.case = { ...next.case, ...d };
  if (ev.type === 'kane.started' || ev.type === 'kane.finished') next.investigations = applyKane(cd.investigations, ev);
  return next;
}

/** A case, kept live. Events that arrive while it is loading are held and applied once it has loaded. */
export function useCase(caseId: string | null): CaseData | null {
  const [cd, setCd] = useState<CaseData | null>(null);
  const held = useRef<Ev[]>([]);
  const loaded = useRef(false);

  useEffect(() => {
    setCd(null);
    held.current = [];
    loaded.current = false;
    if (!caseId) return;
    let alive = true;
    const off = onEvent((ev) => {
      if (ev.case_id !== caseId) return;
      if (!loaded.current) held.current.push(ev);
      else setCd((prev) => (prev ? applyEvent(prev, ev) : prev));
    });
    const load = async (attempt: number) => {
      try {
        const d = await getJSON<CaseData>('/api/cases/' + caseId);
        if (!alive) return;
        let data = d;
        for (const ev of held.current) data = applyEvent(data, ev);
        held.current = [];
        loaded.current = true;
        setCd(data);
      } catch {
        if (alive && attempt < 5) window.setTimeout(() => load(attempt + 1), 500 * (attempt + 1));
      }
    };
    load(0);
    return () => { alive = false; off(); };
  }, [caseId]);
  return cd;
}

/** The case list, refreshed (at most every 700 ms) whenever a case changes. */
export function useCases(): { cases: Case[]; reload: () => void } {
  const [cases, setCases] = useState<Case[]>([]);
  const timer = useRef<number | undefined>(undefined);
  const reload = useCallback(() => {
    getJSON<{ cases: Case[] }>('/api/cases?limit=200').then((d) => setCases(d.cases || [])).catch(() => undefined);
  }, []);
  useEffect(() => {
    reload();
    const off = onEvent(() => {
      if (timer.current) return;
      timer.current = window.setTimeout(() => { timer.current = undefined; reload(); }, 700);
    });
    return () => { off(); if (timer.current) window.clearTimeout(timer.current); };
  }, [reload]);
  return { cases, reload };
}
