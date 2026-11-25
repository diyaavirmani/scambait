import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { RefreshCw } from 'lucide-react';
import { getJSON, onEvent } from '../lib/live';
import type { Case } from '../lib/types';
import { VerdictBadge } from './Layout';

/** Shared bits for the live pages (chats, calls, intelligence, networks, system). */

export const KIND_LABEL: Record<string, string> = {
  upi: 'UPI ID', bank_account: 'Bank account', ifsc: 'IFSC', phone: 'Phone', url: 'Link', apk: 'App file',
  name: 'Name', organisation: 'Claims to be', amount: 'Amount', reference_code: 'Code', email: 'Email', card: 'Card',
};

export const kindLabel = (kind: string) => KIND_LABEL[kind] || words(kind);

export function words(s: string | null | undefined, empty = 'unknown'): string {
  return (s || empty).replace(/_/g, ' ');
}

function parsed(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Date and time in India time, like the Cases page. */
export function when(ts: string | null | undefined): string {
  const d = parsed(ts);
  return d ? d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) : '';
}

/** Time of day with seconds, for live feeds. */
export function clock(ts: string | null | undefined): string {
  const d = parsed(ts);
  return d ? d.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
}

/** A probability (0 to 1, or already a percentage) as a whole percentage, or null when there is none. */
export function percent(p: unknown): number | null {
  if (p == null || p === '') return null;
  const n = typeof p === 'number' ? p : Number(p);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, Math.round(n > 1 ? n : n * 100)));
}

/** Hide all but the last 4 characters of an identifier. */
export function mask(value: string): string {
  const v = (value || '').trim();
  if (v.length <= 4) return v;
  return '\u2022'.repeat(Math.min(v.length - 4, 8)) + v.slice(-4);
}

/**
 * JSON from the server, reloaded (at most every 600 ms) when one of the given live events arrives.
 * onLive sees every matching event before the reload.
 */
export function useLiveJSON<T>(url: string, types: readonly string[], onLive?: (type: string, data: any) => void) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const live = useRef(onLive);
  useEffect(() => { live.current = onLive; });
  const key = types.join(',');

  const reload = useCallback(() => {
    const mine = ++seq.current;
    setLoading(true);
    getJSON<T>(url)
      .then((d) => { if (mine === seq.current) { setData(d); setError(''); } })
      .catch((e: unknown) => { if (mine === seq.current) setError(e instanceof Error ? e.message : 'Could not load ' + url); })
      .finally(() => { if (mine === seq.current) setLoading(false); });
  }, [url]);

  useEffect(() => {
    reload();
    const want = new Set(key.split(',').filter(Boolean));
    let timer: number | undefined;
    const off = onEvent((ev) => {
      if (!want.has(ev.type)) return;
      live.current?.(ev.type, ev.data || {});
      if (timer) return;
      timer = window.setTimeout(() => { timer = undefined; reload(); }, 600);
    });
    return () => { off(); if (timer) window.clearTimeout(timer); seq.current++; };
  }, [reload, key]);

  return { data, error, loading, reload };
}

export const RefreshButton = ({ onClick, busy, label }: { onClick: () => void; busy?: boolean; label: string }) => (
  <button type="button" onClick={onClick} aria-label={label} title={label}
    className="text-sm flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
    <RefreshCw size={14} className={busy ? 'animate-spin' : ''} aria-hidden /> Refresh
  </button>
);

export const StatTile = ({ icon: Icon, value, label, note, tone }: { icon: LucideIcon; value: ReactNode; label: string; note?: string; tone: string }) => (
  <div className="bg-white rounded-xl border border-slate-200 p-4 sm:p-5 flex items-center gap-3 sm:gap-4 min-w-0">
    <span className={`p-2.5 sm:p-3 rounded-lg shrink-0 ${tone}`}><Icon size={20} aria-hidden /></span>
    <div className="min-w-0">
      <div className="text-xl sm:text-2xl font-bold tabular-nums">{value}</div>
      <div className="text-sm text-slate-600">{label}</div>
      {note && <div className="text-xs text-slate-500 truncate" title={note}>{note}</div>}
    </div>
  </div>
);

/** A small labelled state chip. The icon and text carry the meaning, the colour only backs it up. */
export const Pill = ({ tone, icon: Icon, children, pulse }: { tone: string; icon?: LucideIcon; children: ReactNode; pulse?: boolean }) => (
  <span className={`inline-flex items-center gap-1.5 text-[11px] uppercase font-bold px-2 py-0.5 rounded border ${tone}`}>
    {Icon && <Icon size={12} className={pulse ? 'animate-pulse' : ''} aria-hidden />}
    {children}
  </span>
);

/** A row meter for a 0 to 100 value: label, aligned bar, figure. */
export const PercentMeter = ({ label, value }: { label: string; value: number }) => (
  <div className="grid grid-cols-[7.5rem_1fr_2.75rem] items-center gap-2 text-sm">
    <span className="text-slate-500 truncate" title={label}>{label}</span>
    <span className="h-2 rounded-full bg-slate-100 overflow-hidden" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}>
      <span className="block h-full rounded-full bg-slate-700" style={{ width: value + '%' }} />
    </span>
    <span className="text-right font-semibold tabular-nums text-slate-800">{value}%</span>
  </div>
);

/** A list of cases to pick from, styled like the Cases page. */
export const CaseList = ({ cases, current, select, label, meta }: {
  cases: Case[]; current: string | null; select: (id: string) => void; label: string; meta?: (c: Case) => ReactNode;
}) => (
  <ul className="space-y-2 max-h-[22rem] xl:max-h-[40rem] overflow-y-auto" aria-label={label}>
    {cases.map((c) => {
      const on = c.id === current;
      const extra = meta ? meta(c) : null;
      return (
        <li key={c.id}>
          <button type="button" onClick={() => select(c.id)} aria-current={on ? 'true' : undefined}
            className={`w-full text-left p-3 rounded-lg border text-sm ${on ? 'bg-slate-900 text-white border-slate-900' : 'bg-slate-50 border-slate-200 hover:bg-slate-100'}`}>
            <div className="flex justify-between items-center gap-2">
              <span className="font-medium truncate">{words(c.scam_type)}</span>
              <VerdictBadge verdict={c.verdict} />
            </div>
            <div className={`text-xs mt-1 ${on ? 'text-slate-300' : 'text-slate-500'}`}>
              {c.channel} &middot; {c.turns ?? 0} messages &middot; {c.status === 'open' ? 'open' : 'closed'}
              {extra != null && extra !== '' && <> &middot; {extra}</>}
            </div>
            {c.summary && <div className={`text-xs mt-1 line-clamp-2 ${on ? 'text-slate-200' : 'text-slate-600'}`}>{c.summary}</div>}
          </button>
        </li>
      );
    })}
  </ul>
);

/** Two-way switch used for filters. */
export const Toggle = ({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) => (
  <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}
    className={`text-xs font-semibold px-3 py-1.5 rounded-full border ${on ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}>
    {label}
  </button>
);
