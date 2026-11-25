import { useEffect, useState } from 'react';
import { BadgeCheck, Link2, MessagesSquare, ShieldAlert } from 'lucide-react';
import { getJSON, onEvent, useCases } from '../lib/live';
import type { Investigation } from '../lib/types';
import { PageHeader, Panel, VerdictBadge } from '../components/Layout';
import { KaneCard } from '../components/KaneCard';

const Tile = ({ icon: Icon, value, label, tone }: { icon: typeof ShieldAlert; value: number; label: string; tone: string }) => (
  <div className="bg-white rounded-xl border border-slate-200 p-5 flex items-center gap-4">
    <span className={`p-3 rounded-lg ${tone}`}><Icon size={22} aria-hidden /></span>
    <div><div className="text-2xl font-bold">{value}</div><div className="text-sm text-slate-600">{label}</div></div>
  </div>
);

export const Overview = ({ openCase }: { openCase: (id: string) => void }) => {
  const { cases } = useCases();
  const [invs, setInvs] = useState<Investigation[]>([]);
  useEffect(() => {
    const load = () => getJSON<{ investigations: Investigation[] }>('/api/investigations?limit=100')
      .then((d) => setInvs(d.investigations || [])).catch(() => undefined);
    load();
    return onEvent((ev) => { if (ev.type === 'kane.finished') load(); });
  }, []);
  const proven = invs.filter((i) => i.verdict === 'payment_request_found');
  const latest = invs.filter((i) => i.status !== 'skipped').slice(0, 3);
  return (
    <div className="space-y-6">
      <PageHeader title="Overview" subtitle="Scams caught, scammer messages Meena answered, and payees Kane proved on the scam pages themselves." />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Tile icon={ShieldAlert} value={cases.filter((c) => c.verdict === 'scam').length} label="Scams caught" tone="bg-red-50 text-red-700" />
        <Tile icon={MessagesSquare} value={cases.reduce((n, c) => n + (c.turns || 0), 0)} label="Scammer messages answered" tone="bg-blue-50 text-blue-700" />
        <Tile icon={Link2} value={invs.filter((i) => i.status !== 'skipped').length} label="Links opened by Kane" tone="bg-slate-100 text-slate-700" />
        <Tile icon={BadgeCheck} value={proven.length} label="Payees proven by Kane" tone="bg-green-50 text-green-700" />
      </div>
      <Panel title="Latest Kane proof" right={<span className="text-xs text-slate-500">links scammers sent, opened by Kane CLI</span>}>
        {latest.length === 0 ? <p className="text-sm text-slate-500">No links investigated yet. Send one from the Scam Console or Check a Message.</p>
          : <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">{latest.map((inv) => <KaneCard key={inv.id} inv={inv} />)}</div>}
      </Panel>
      <Panel title="Recent cases">
        {cases.length === 0 ? <p className="text-sm text-slate-500">No cases yet.</p> : (
          <ul className="divide-y divide-slate-100">
            {cases.slice(0, 6).map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => openCase(c.id)} className="w-full flex items-center justify-between gap-3 py-3 text-left text-sm hover:bg-slate-50 px-2 rounded">
                  <span className="min-w-0"><span className="font-medium">{(c.scam_type || 'unknown').replace(/_/g, ' ')}</span>
                    <span className="text-slate-500"> &middot; {c.channel} &middot; {c.turns ?? 0} messages</span>
                    {c.summary && <span className="block text-slate-600 truncate">{c.summary}</span>}</span>
                  <VerdictBadge verdict={c.verdict} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
};
