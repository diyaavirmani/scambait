import { useState } from 'react';
import { Download, MessageSquareWarning } from 'lucide-react';
import { useCase, useCases } from '../lib/live';
import { Empty, PageHeader, Panel, VerdictBadge } from '../components/Layout';
import { KaneCard } from '../components/KaneCard';
import { EvidenceBoard } from '../components/EvidenceBoard';

const when = (ts: string) => new Date(ts).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' });

async function download(caseId: string, ext: 'csv' | 'pdf'): Promise<string> {
  const r = await fetch(`/api/cases/${caseId}/export.${ext}`);
  if (!r.ok) throw new Error('Export failed (HTTP ' + r.status + ')');
  const sha = r.headers.get('X-SHA256') || '';
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = `${caseId}.${ext}`;
  a.click();
  URL.revokeObjectURL(url);
  return sha;
}

/** Every case, and for the one selected: the chat, what Kane proved, the evidence board and the evidence pack. */
export const Cases = ({ selected, select }: { selected: string | null; select: (id: string) => void }) => {
  const { cases } = useCases();
  const current = selected || cases[0]?.id || null;
  const cd = useCase(current);
  const [hashes, setHashes] = useState<Record<string, string>>({});
  const [error, setError] = useState('');

  async function run(ext: 'csv' | 'pdf') {
    if (!cd) return;
    setError('');
    try {
      const sha = await download(cd.case.id, ext);
      setHashes((h) => ({ ...h, [cd.case.id + ext]: sha }));
    } catch (e: any) {
      setError(e?.message || 'Export failed');
    }
  }

  return (
    <div>
      <PageHeader title="Cases" subtitle="Every conversation with a scammer: what they said, what Kane proved, and an evidence pack ready for cybercrime.gov.in or 1930." />
      {cases.length === 0 ? <Panel><Empty text="No cases yet. Start one from the Scam Console." /></Panel> : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <Panel title="All cases" className="lg:col-span-4">
            <ul className="space-y-2 max-h-[40rem] overflow-y-auto" aria-label="Cases">
              {cases.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => select(c.id)} aria-current={c.id === current ? 'true' : undefined}
                    className={`w-full text-left p-3 rounded-lg border text-sm ${c.id === current ? 'bg-slate-900 text-white border-slate-900' : 'bg-slate-50 border-slate-200 hover:bg-slate-100'}`}>
                    <div className="flex justify-between items-center gap-2">
                      <span className="font-medium truncate">{(c.scam_type || 'unknown').replace(/_/g, ' ')}</span>
                      <VerdictBadge verdict={c.verdict} />
                    </div>
                    <div className={`text-xs mt-1 ${c.id === current ? 'text-slate-300' : 'text-slate-500'}`}>
                      {c.channel} &middot; {c.turns ?? 0} messages &middot; {when(c.updated_at)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
          <div className="lg:col-span-8 space-y-6 min-w-0">
            {!cd ? <Panel><Empty text="Loading the case..." /></Panel> : (<>
              <Panel title={'Case ' + cd.case.id} right={<VerdictBadge verdict={cd.case.verdict} />}>
                <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  <div><dt className="text-xs text-slate-500">Scam type</dt><dd className="font-medium">{(cd.case.scam_type || 'unknown').replace(/_/g, ' ')}</dd></div>
                  <div><dt className="text-xs text-slate-500">Channel</dt><dd>{cd.case.channel}</dd></div>
                  <div><dt className="text-xs text-slate-500">Status</dt><dd>{cd.case.status}</dd></div>
                  <div><dt className="text-xs text-slate-500">Opened</dt><dd>{when(cd.case.created_at)}</dd></div>
                </dl>
                {cd.case.summary && <p className="text-sm text-slate-700 mt-4">{cd.case.summary}</p>}
                {cd.related.length > 0 && (
                  <p className="text-sm mt-3"><span className="text-slate-500">Same scammer identifiers seen in: </span>
                    {[...new Set(cd.related.map((r) => r.case_id))].map((id) => (
                      <button key={id} type="button" onClick={() => select(id)} className="font-mono text-blue-700 hover:underline mr-2">{id}</button>))}
                  </p>
                )}
                <a href={'/console?case=' + cd.case.id} className="inline-flex items-center gap-1.5 text-sm text-blue-700 hover:underline mt-3">
                  <MessageSquareWarning size={15} aria-hidden /> Open in the Scam Console
                </a>
              </Panel>
              <Panel title="Links opened by Kane">
                {cd.investigations.length === 0 ? <p className="text-sm text-slate-500">The scammer sent no links in this case.</p>
                  : <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{cd.investigations.map((inv) => <KaneCard key={inv.id} inv={inv} />)}</div>}
              </Panel>
              <Panel title="Evidence board" right={<span className="text-xs text-slate-500">said in chat vs proven by Kane</span>}>
                <EvidenceBoard cd={cd} />
              </Panel>
              <Panel title="Conversation">
                <ol className="space-y-2 max-h-96 overflow-y-auto" aria-label="Conversation">
                  {cd.messages.map((m) => (
                    <li key={m.id} className={`text-sm rounded-lg px-3 py-2 ${m.role === 'scammer' ? 'bg-slate-900 text-white' : 'bg-slate-50 border border-slate-200'}`}>
                      <span className={`block text-[10px] font-bold uppercase ${m.role === 'scammer' ? 'text-slate-400' : 'text-blue-700'}`}>{m.role === 'scammer' ? 'Scammer' : 'Meena'}</span>
                      <span className="whitespace-pre-wrap break-words">{m.text}</span>
                    </li>
                  ))}
                </ol>
              </Panel>
              <Panel title="Evidence pack" right={<span className="text-xs text-slate-500">for cybercrime.gov.in or 1930</span>}>
                <div className="flex flex-wrap gap-3">
                  <button type="button" onClick={() => run('pdf')} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-900 text-white text-sm font-semibold hover:bg-black"><Download size={16} aria-hidden /> Download PDF</button>
                  <button type="button" onClick={() => run('csv')} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-300 text-sm font-semibold hover:bg-slate-50"><Download size={16} aria-hidden /> Download CSV</button>
                </div>
                {error && <p role="alert" className="text-sm text-red-600 mt-2">{error}</p>}
                {(['pdf', 'csv'] as const).map((ext) => hashes[cd.case.id + ext] && (
                  <p key={ext} className="text-xs font-mono text-slate-600 break-all mt-2">{ext.toUpperCase()} SHA-256: {hashes[cd.case.id + ext]}</p>))}
                {cd.evidence.length > 0 && (
                  <ul className="mt-3 space-y-1 text-xs font-mono text-slate-500">
                    {cd.evidence.map((e, i) => <li key={i} className="break-all">{e.kind}: {e.sha256}</li>)}
                  </ul>
                )}
              </Panel>
            </>)}
          </div>
        </div>
      )}
    </div>
  );
};
