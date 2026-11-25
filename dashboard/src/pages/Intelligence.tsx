import { useMemo, useState } from 'react';
import { BadgeCheck, Fingerprint, Link2, Search } from 'lucide-react';
import type { IntelRow } from '../lib/extra-types';
import { Empty, PageHeader, Panel } from '../components/Layout';
import { Pill, RefreshButton, StatTile, Toggle, kindLabel, useLiveJSON, when, words } from '../components/LiveBits';

const PAGE = 150;
const keyOf = (r: IntelRow) => r.kind + ':' + (r.norm || r.value.toLowerCase());

/** Every identifier scammers gave away, across all cases, with what Kane proved. */
export const Intelligence = ({ openCase }: { openCase: (id: string) => void }) => {
  const { data, error, loading, reload } = useLiveJSON<{ intel: IntelRow[] }>('/api/intel?limit=2000', ['intel.extracted', 'kane.finished']);
  const rows = useMemo(() => data?.intel || [], [data]);
  const [kind, setKind] = useState('all');
  const [provenOnly, setProvenOnly] = useState(false);
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows) m.set(r.kind, (m.get(r.kind) || 0) + 1);
    return [...m].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [rows]);

  const spread = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const r of rows) {
      const k = keyOf(r);
      if (!m.has(k)) m.set(k, new Set());
      m.get(k)!.add(r.case_id);
    }
    return m;
  }, [rows]);

  const q = query.trim().toLowerCase();
  const shown = rows.filter((r) => (kind === 'all' || r.kind === kind) && (!provenOnly || r.proven)
    && (!q || r.value.toLowerCase().includes(q) || (r.norm || '').includes(q) || r.case_id.includes(q)));
  const proven = rows.filter((r) => r.proven).length;
  const repeated = [...spread.values()].filter((s) => s.size > 1).length;

  const chip = (value: string, text: string, n: number) => (
    <button key={value} type="button" onClick={() => { setKind(value); setLimit(PAGE); }} aria-pressed={kind === value}
      className={`text-sm px-3 py-1.5 rounded-full border ${kind === value ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'}`}>
      {text} <span className={`ml-1 tabular-nums ${kind === value ? 'text-slate-300' : 'text-slate-500'}`}>{n}</span>
    </button>
  );

  return (
    <div className="space-y-6">
      <PageHeader title="Intelligence" subtitle="Every UPI ID, account, phone number and link scammers gave away, across all cases. Green means Kane saw it on the scam page itself." />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile icon={Fingerprint} value={rows.length} label="Identifiers collected" tone="bg-slate-100 text-slate-700" />
        <StatTile icon={Search} value={spread.size} label="Different identifiers" tone="bg-blue-50 text-blue-700" />
        <StatTile icon={BadgeCheck} value={proven} label="Proven by Kane" tone="bg-green-50 text-green-700" />
        <StatTile icon={Link2} value={repeated} label="Seen in more than one case" tone="bg-amber-50 text-amber-700" />
      </div>

      <Panel title="Identifiers" right={<RefreshButton onClick={reload} busy={loading} label="Reload identifiers" />}>
        <div className="space-y-3 mb-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by kind">
            {chip('all', 'All', rows.length)}
            {counts.map(([k, n]) => chip(k, kindLabel(k), n))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="intel-search" className="sr-only">Search identifiers</label>
            <input id="intel-search" type="search" value={query} onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }}
              placeholder="Search a UPI ID, number, link or case"
              className="flex-1 min-w-0 basis-56 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <Toggle on={provenOnly} onChange={(v) => { setProvenOnly(v); setLimit(PAGE); }} label="Proven by Kane only" />
          </div>
        </div>

        {error && !data ? <p role="alert" className="text-sm text-red-600">Could not load identifiers: {error}</p>
          : rows.length === 0 ? <Empty text={loading ? 'Loading identifiers...' : 'No identifiers yet. They appear as scammers share UPI IDs, numbers and links.'} />
          : shown.length === 0 ? <Empty text="Nothing matches these filters." />
          : (<>
            <p className="text-xs text-slate-500 mb-2" aria-live="polite">Showing {Math.min(limit, shown.length)} of {shown.length}</p>
            <ul className="divide-y divide-slate-100" aria-label="Identifiers">
              {shown.slice(0, limit).map((r) => {
                const cases = spread.get(keyOf(r))?.size || 1;
                return (
                  <li key={r.id} className="py-3 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] uppercase font-semibold text-slate-500">{kindLabel(r.kind)}</div>
                      <div className={`font-mono text-sm break-all ${r.proven ? 'text-green-800 font-semibold' : 'text-slate-900'}`}>{r.value}</div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {words(r.scam_type)} &middot; {r.channel} &middot; first seen {when(r.first_seen)}
                        {cases > 1 && <> &middot; <span className="text-amber-700 font-medium">in {cases} cases</span></>}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {r.proven
                        ? <Pill tone="bg-green-100 text-green-800 border-green-300" icon={BadgeCheck}>Proven by Kane</Pill>
                        : <Pill tone="bg-white text-slate-500 border-slate-200">Said in chat</Pill>}
                      <button type="button" onClick={() => openCase(r.case_id)} aria-label={'Open case ' + r.case_id}
                        className="font-mono text-xs text-blue-700 hover:underline">{r.case_id}</button>
                    </div>
                  </li>
                );
              })}
            </ul>
            {shown.length > limit && (
              <button type="button" onClick={() => setLimit((n) => n + PAGE)} aria-label="Show more identifiers"
                className="mt-3 w-full text-sm py-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
                Show {Math.min(PAGE, shown.length - limit)} more
              </button>
            )}
          </>)}
        {error && data && <p role="alert" className="text-xs text-red-600 mt-2">The last reload failed: {error}</p>}
      </Panel>
    </div>
  );
};
