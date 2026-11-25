import type { Intel, Investigation } from './types';

/** Same normalisation idea as app/networks.py: UPI lowercased, account numbers digits only. */
export function norm(kind: string, value: string): string {
  const v = (value || '').trim();
  if (kind === 'upi' || kind === 'email') return v.toLowerCase();
  if (kind === 'bank_account' || kind === 'card' || kind === 'phone') return v.replace(/\D/g, '');
  return v.toLowerCase();
}

/** Payees that Kane saw on the scam page itself, as "kind:normalised" keys. */
export function provenKeys(invs: Investigation[]): Set<string> {
  const out = new Set<string>();
  for (const inv of invs || []) {
    if (inv.payee && inv.payee_kind) out.add(inv.payee_kind + ':' + norm(inv.payee_kind, inv.payee));
  }
  return out;
}

export function isProven(item: Intel, keys: Set<string>): boolean {
  return keys.has(item.kind + ':' + norm(item.kind, item.value));
}

export function rupees(amount: string | number | null | undefined): string {
  const n = Number(amount);
  if (amount === '' || amount == null || Number.isNaN(n)) return '';
  return '₹' + n.toLocaleString('en-IN');
}

export function isRunning(inv: Investigation): boolean {
  return inv.status === 'queued' || inv.status === 'running';
}

export function statusText(inv: Investigation): string {
  if (isRunning(inv)) return 'Kane is opening this link in a real browser';
  if (inv.verdict === 'unsafe_run') return 'Safety rule broken: not counted as proof';
  if (inv.status === 'skipped') return 'Not opened';
  if (inv.verdict === 'payment_request_found') return 'Proven by Kane';
  if (inv.status === 'not_started') return 'Kane could not start';
  if (inv.status === 'timeout') return 'Kane timed out';
  if (inv.status === 'error') return 'Kane error';
  return 'No payment request found';
}

/** A fresh-visitor re-check of a link whose payee Kane already proved (the payee-rotation probe). */
export function isRecheck(inv: Investigation): boolean {
  return inv.recheck_of != null;
}

/** Counts as its own proven payee: a first run that proved one, or a re-check that showed a new one. */
export function provesNewPayee(inv: Investigation): boolean {
  return inv.verdict === 'payment_request_found' && (!isRecheck(inv) || !!inv.rotation?.new_payee);
}

export function shortUrl(url: string, max = 48): string {
  const u = (url || '').replace(/^https?:\/\//, '');
  return u.length > max ? u.slice(0, max - 3) + '...' : u;
}
