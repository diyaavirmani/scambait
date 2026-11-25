import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, FolderOpen, Fingerprint, Users, Waypoints } from 'lucide-react';
import type { ScamNetwork } from '../lib/extra-types';
import { Empty, PageHeader, Panel } from '../components/Layout';
import { Pill, RefreshButton, StatTile, kindLabel, mask, useLiveJSON, when, words } from '../components/LiveBits';

const FLASH_MS = 4000;

/** Accept a bare list or {networks: [...]}, and fill missing lists so one odd row cannot break the page. */
function networksOf(data: unknown): ScamNetwork[] {
  const list = Array.isArray(data) ? data : (data && typeof data === 'object' && Array.isArray((data as { networks?: unknown }).networks))
    ? (data as { networks: unknown[] }).networks : [];
  return (list as Partial<ScamNetwork>[]).filter((n) => n && n.network_id != null).map((n) => ({
    network_id: String(n.network_id), case_ids: n.case_ids || [], shared: n.shared || [],
    first_seen: n.first_seen || '', last_seen: n.last_seen || '', scam_types: n.scam_types || [],
  }));
}

/** Cases that are one scam operation: they share a UPI ID, account, phone number or link. */
export const Networks = ({ openCase }: { openCase: (id: string) => void }) => {
  const [flash, setFlash] = useState<Record<string, number>>({});
  const [said, setSaid] = useState('');
  const timers = useRef<number[]>([]);
  useEffect(() => () => { timers.current.forEach((t) => window.clearTimeout(t)); }, []);

  const bump = (keys: string[], by: number) => setFlash((f) => {
    const next = { ...f };
    for (const k of keys) {
      const v = (next[k] || 0) + by;
      if (v > 0) next[k] = v; else delete next[k];
    }
    return next;
  });

  const { data, error, loading, reload } = useLiveJSON<unknown>('/api/networks', ['network.updated'], (_type, d) => {
    const keys = [d.network_id != null ? 'n:' + d.network_id : '', ...(Array.isArray(d.case_ids) ? d.case_ids.map((c: unknown) => 'c:' + c) : [])].filter(Boolean);
    if (keys.length === 0) return;
    bump(keys, 1);
    setSaid('A network was updated' + (Array.isArray(d.case_ids) ? ', it now links ' + d.case_ids.length + ' cases' : ''));
    timers.current.push(window.setTimeout(() => bump(keys, -1), FLASH_MS));
  });

  const networks = useMemo(() => networksOf(data).sort((a, b) => (b.last_seen || '').localeCompare(a.last_seen || '')), [data]);
  const linked = new Set(networks.flatMap((n) => n.case_ids)).size;
  const shared = networks.reduce((n, x) => n + x.shared.length, 0);
  const hot = (n: ScamNetwork) => !!flash['n:' + n.network_id] || n.case_ids.some((c) => flash['c:' + c]);

  return (
    <div className="space-y-6">
      <PageHeader title="Networks" subtitle="Cases that are one scam operation, because the scammers reused the same UPI ID, account, phone number or link. Identifiers are masked except their last 4 characters." />
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatTile icon={Waypoints} value={networks.length} label="Networks found" tone="bg-red-50 text-red-700" />
        <StatTile icon={Users} value={linked} label="Cases linked" tone="bg-slate-100 text-slate-700" />
        <StatTile icon={Fingerprint} value={shared} label="Shared identifiers" tone="bg-amber-50 text-amber-700" />
      </div>
      <p className="sr-only" aria-live="polite">{said}</p>

      {error && !data ? (
        <Panel title="Networks" right={<RefreshButton onClick={reload} busy={loading} label="Try loading networks again" />}>
          <p role="alert" className="text-sm text-slate-600">The network view is not available right now ({error}). It will load once the server provides it.</p>
        </Panel>
      ) : networks.length === 0 ? (
        <Panel title="Networks" right={<RefreshButton onClick={reload} busy={loading} label="Reload networks" />}>
          <Empty text={loading && !data ? 'Loading networks...' : 'No networks yet. A network forms when two cases share an identifier, such as the same UPI ID.'} />
        </Panel>
      ) : (<>
        <div className="flex justify-end"><RefreshButton onClick={reload} busy={loading} label="Reload networks" /></div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {networks.map((n) => {
            const on = hot(n);
            return (
              <article key={n.network_id} aria-label={`Network of ${n.case_ids.length} cases`}
                className={`rounded-xl border p-5 transition-colors duration-700 ${on ? 'bg-amber-50 border-amber-300 ring-2 ring-amber-300' : 'bg-white border-slate-200'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-slate-900">{n.case_ids.length} linked cases</h2>
                    <div className="text-xs text-slate-500 font-mono truncate" title={n.network_id}>{n.network_id}</div>
                  </div>
                  {on && <Pill tone="bg-amber-100 text-amber-800 border-amber-300" icon={Activity} pulse>Just updated</Pill>}
                </div>

                {n.scam_types.length > 0 && (
                  <ul className="mt-3 flex flex-wrap gap-1" aria-label="Scam types">
                    {n.scam_types.map((t) => <li key={t} className="text-xs px-2 py-0.5 rounded-full bg-red-50 border border-red-200 text-red-800">{words(t)}</li>)}
                  </ul>
                )}

                <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Shared identifiers</h3>
                {n.shared.length === 0 ? <p className="text-sm text-slate-500 mt-1">None listed.</p> : (
                  <ul className="mt-1 space-y-1.5" aria-label="Shared identifiers">
                    {n.shared.map((s, i) => (
                      <li key={s.kind + i} className="flex items-center justify-between gap-3 text-sm p-2 rounded-lg bg-white/70 border border-slate-200">
                        <span className="min-w-0">
                          <span className="block text-[11px] uppercase font-semibold text-slate-500">{kindLabel(s.kind)}</span>
                          <span className="font-mono text-slate-800 break-all" aria-hidden>{mask(s.value)}</span>
                          <span className="sr-only">ending in {(s.value || '').trim().slice(-4)}</span>
                        </span>
                        <span className="shrink-0 text-xs text-slate-600">in {s.case_count} cases</span>
                      </li>
                    ))}
                  </ul>
                )}

                <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Cases</h3>
                <ul className="mt-1 flex flex-wrap gap-2" aria-label="Cases in this network">
                  {n.case_ids.map((id) => (
                    <li key={id}>
                      <button type="button" onClick={() => openCase(id)} aria-label={'Open case ' + id}
                        className="inline-flex items-center gap-1 text-xs font-mono px-2 py-1 rounded border border-slate-200 bg-white text-blue-700 hover:bg-slate-50">
                        <FolderOpen size={12} aria-hidden /> {id}
                      </button>
                    </li>
                  ))}
                </ul>

                <p className="mt-4 text-xs text-slate-500">
                  {n.first_seen && <>First seen {when(n.first_seen)}</>}
                  {n.first_seen && n.last_seen && <> &middot; </>}
                  {n.last_seen && <>last seen {when(n.last_seen)}</>}
                </p>
              </article>
            );
          })}
        </div>
      </>)}
      {error && data != null && <p role="alert" className="text-xs text-red-600">The last reload failed: {error}</p>}
    </div>
  );
};
