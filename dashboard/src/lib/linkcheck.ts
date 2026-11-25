import { useCallback, useEffect, useRef, useState } from 'react';
import type { Investigation } from './types';
import type { LinkCheck } from './check-types';
import { getJSON, onEvent, postJSON } from './live';

const POLL_MS = 3000;

export function working(inv: Investigation | null | undefined): boolean {
  return !!inv && (inv.status === 'queued' || inv.status === 'running');
}

/** Kane proved who the page would pay. */
export function proved(inv: Investigation): boolean {
  return inv.verdict === 'payment_request_found' && !!inv.payee;
}

export function kindWord(kind: string): string {
  return kind === 'bank_account' ? 'bank account' : kind === 'upi' ? 'UPI ID' : kind === 'phone' ? 'phone number' : '';
}

/** "Rs 33,210" for an amount Kane read off the page, '' when there is none. */
export function rs(amount: string | number | null | undefined): string {
  if (amount === '' || amount == null) return '';
  const n = Number(amount);
  return Number.isFinite(n) ? 'Rs ' + n.toLocaleString('en-IN') : '';
}

/**
 * The links the person sent to Kane from the Check page, kept live. Each one is followed by investigation id over the
 * server-sent events (kane.started, kane.finished), and polled as a fallback while Kane is still working.
 */
export function useLinkChecks() {
  const [checks, setChecks] = useState<Record<string, LinkCheck>>({});
  const ids = useRef(new Map<number, string>()); // investigation id -> url
  const round = useRef(0); // a new message starts a new round; late answers from an older round are dropped

  const put = useCallback((url: string, patch: Partial<LinkCheck>) => {
    setChecks((prev) => (prev[url] ? { ...prev, [url]: { ...prev[url], ...patch } } : prev));
  }, []);

  const refresh = useCallback(async (id: number) => {
    const url = ids.current.get(id);
    if (url == null) return;
    const r = round.current;
    try {
      const inv = await getJSON<Investigation>('/api/investigations/' + id);
      if (r === round.current) put(url, { inv });
    } catch { /* the next event or poll tries again */ }
  }, [put]);

  useEffect(() => onEvent((ev) => {
    if (ev.type !== 'kane.started' && ev.type !== 'kane.finished') return;
    const id = ev.data?.investigation_id;
    const url = typeof id === 'number' ? ids.current.get(id) : undefined;
    if (url == null) return;
    if (ev.type === 'kane.started') {
      setChecks((prev) => {
        const c = prev[url];
        return c?.inv && working(c.inv) ? { ...prev, [url]: { ...c, inv: { ...c.inv, status: 'running' } } } : prev;
      });
    } else {
      refresh(id);
    }
  }), [refresh]);

  const pending = Object.values(checks).filter((c) => working(c.inv)).map((c) => c.inv!.id).join(',');
  useEffect(() => {
    if (!pending) return;
    const t = window.setInterval(() => pending.split(',').forEach((id) => refresh(Number(id))), POLL_MS);
    return () => window.clearInterval(t);
  }, [pending, refresh]);

  const start = useCallback(async (url: string) => {
    const r = round.current;
    setChecks((prev) => ({ ...prev, [url]: { url, starting: true, error: '', inv: null, askedAt: Date.now() } }));
    try {
      const inv = await postJSON<Investigation>('/api/check/link', { url });
      if (r !== round.current) return;
      ids.current.set(inv.id, url);
      put(url, { starting: false, inv });
      if (working(inv)) refresh(inv.id); // Kane may have finished before the id was known here
    } catch (err) {
      if (r === round.current) put(url, { starting: false, error: err instanceof Error ? err.message : 'Something went wrong.' });
    }
  }, [put, refresh]);

  const reset = useCallback(() => {
    round.current += 1;
    ids.current.clear();
    setChecks({});
  }, []);

  const invs = Object.values(checks).flatMap((c) => (c.inv ? [c.inv] : []));
  return { checks, invs, start, reset };
}
