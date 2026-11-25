import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { FileText, Loader2, RotateCcw, Send, Sparkles } from 'lucide-react';
import { useCase } from '../lib/live';
import type { LabSite } from '../lib/types';
import { Empty, PageHeader, Panel, VerdictBadge } from '../components/Layout';
import { KaneCard } from '../components/KaneCard';
import { EvidenceBoard } from '../components/EvidenceBoard';

const SESSION_KEY = 'scambait.console.session';
const CASE_KEY = 'scambait.console.case';

interface Line { role: 'scammer' | 'persona'; text: string; usedKane?: boolean }

function newSession(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return 'web_' + Array.from(bytes, (x) => x.toString(16).padStart(2, '0')).join('');
}

function stored(key: string): string | null {
  try { return sessionStorage.getItem(key); } catch { return null; }
}

function keep(key: string, value: string | null) {
  try { if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key); } catch { /* private mode */ }
}

const SHORT: Record<string, string> = {
  kyc: 'Bank KYC update', parcel: 'Parcel customs fee', trading: 'Trading profit withdrawal',
  job: 'Part-time task job', electricity: 'Electricity disconnection', loan: 'Instant loan fee',
};

/** Play the scammer against Meena in the browser. Every link you send is opened by Kane. */
export const Console = () => {
  const [session, setSession] = useState<string>(() => stored(SESSION_KEY) || newSession());
  const [caseId, setCaseId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('case') || stored(CASE_KEY));
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sites, setSites] = useState<LabSite[]>([]);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => keep(SESSION_KEY, session), [session]);
  useEffect(() => keep(CASE_KEY, caseId), [caseId]);
  useEffect(() => {
    fetch('/lab/api/sites').then((r) => r.json()).then((d) => setSites(d.sites || [])).catch(() => setSites([]));
  }, []);

  const cd = useCase(caseId);

  // After a reload the chat comes back from the case itself.
  const shown: Line[] = useMemo(() => {
    if (lines.length || !cd) return lines;
    return cd.messages.map((m) => ({ role: m.role, text: m.text }));
  }, [lines, cd]);

  const kaneReplies = useMemo(() => new Set((cd?.events || [])
    .filter((e) => e.type === 'persona.reply' && e.data?.kane_findings_used > 0).map((e) => e.data.text as string)), [cd]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [shown.length, busy]);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const msg = text.trim();
    if (!msg || busy) return;
    setBusy(true);
    setError('');
    setLines((l) => [...(l.length || !cd ? l : cd.messages.map((m) => ({ role: m.role, text: m.text }))), { role: 'scammer', text: msg }]);
    setText('');
    try {
      const r = await fetch('/api/console/messages', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session, text: msg }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'Meena could not answer (HTTP ' + r.status + ')');
      setCaseId(d.case_id);
      if (d.reply) setLines((l) => [...l, { role: 'persona', text: d.reply }]);
    } catch (err: any) {
      setError(err?.message || 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  async function endChat() {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const r = await fetch('/api/console/end', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: session }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'Could not end the chat (HTTP ' + r.status + ')');
    } catch (err: any) {
      setError(err?.message || 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setSession(newSession());
    setCaseId(null);
    setLines([]);
    setError('');
  }

  const invs = cd?.investigations || [];
  return (
    <div>
      <PageHeader title="Scam Console" subtitle="Play the scammer. Meena answers, and Kane opens every link you send in a real browser." />
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
        <div className="xl:col-span-3">
          <Panel title="Chat with Meena" right={
            <div className="flex gap-2">
              {cd && cd.case.status !== 'closed' && (
                <button type="button" onClick={endChat} disabled={busy} aria-label="End this chat and write the case report"
                  className="text-sm flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                  <FileText size={14} aria-hidden /> End chat
                </button>
              )}
              <button type="button" onClick={reset} aria-label="Start a new chat" className="text-sm flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50">
                <RotateCcw size={14} /> New chat
              </button>
            </div>}>
            <div className="mb-4">
              <div className="text-xs font-semibold uppercase text-slate-500 mb-2 flex items-center gap-1.5"><Sparkles size={13} /> Try a practice scam (fictional sites)</div>
              <div className="flex flex-wrap gap-2">
                {sites.map((s) => (
                  <button key={s.key} type="button" aria-label={'Use the practice scam: ' + (SHORT[s.key] || s.brand)}
                    onClick={() => setText(s.lure + ' ' + window.location.origin + s.path)}
                    className="text-sm px-3 py-1.5 rounded-full border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100">
                    {SHORT[s.key] || s.brand}
                  </button>
                ))}
              </div>
            </div>
            <div className="h-[26rem] overflow-y-auto rounded-lg bg-slate-50 border border-slate-100 p-4 space-y-3" aria-label="Conversation" aria-live="polite">
              {shown.length === 0 && <Empty text="Send a message as the scammer to start" />}
              {shown.map((l, i) => (
                <div key={i} className={`flex ${l.role === 'scammer' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm shadow-sm ${l.role === 'scammer' ? 'bg-slate-800 text-white rounded-br-sm' : 'bg-white border border-slate-200 text-slate-800 rounded-bl-sm'}`}>
                    <div className={`text-[10px] font-bold uppercase mb-0.5 ${l.role === 'scammer' ? 'text-slate-300' : 'text-blue-600'}`}>
                      {l.role === 'scammer' ? 'You (scammer)' : 'Meena'}
                      {l.role === 'persona' && kaneReplies.has(l.text) && <span className="ml-2 text-green-700 normal-case">used what Kane found</span>}
                    </div>
                    <span className="whitespace-pre-wrap break-words">{l.text}</span>
                  </div>
                </div>
              ))}
              {busy && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Meena is typing...</div>}
              <div ref={bottom} />
            </div>
            {cd && cd.case.status === 'closed' && (
              <p role="status" className="mt-4 text-sm rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-slate-700">
                This chat has ended. {cd.case.report ? 'Its case report is ready' : 'Its case report is being written'}:{' '}
                <a href={'/cases?case=' + cd.case.id} className="text-blue-700 hover:underline">open the case</a>. Press New chat to start another.
              </p>
            )}
            <form onSubmit={send} className="mt-4 flex gap-2">
              <label htmlFor="console-input" className="sr-only">Message to Meena</label>
              <input id="console-input" value={text} onChange={(e) => setText(e.target.value)} maxLength={4000}
                placeholder="Type as the scammer, for example: Your account will be blocked, update KYC now"
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <button type="submit" disabled={busy || !text.trim()} aria-label="Send message"
                className="px-4 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold flex items-center gap-1.5 disabled:opacity-50 hover:bg-blue-700">
                <Send size={15} /> Send
              </button>
            </form>
            {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
          </Panel>
        </div>
        <div className="xl:col-span-2 space-y-6">
          <Panel title="Case" right={cd ? <VerdictBadge verdict={cd.case.verdict} /> : undefined}>
            {!cd ? <p className="text-sm text-slate-500">The case opens with your first message.</p> : (
              <div className="text-sm space-y-1">
                <div><span className="text-slate-500">Scam type: </span><b>{(cd.case.scam_type || 'unknown').replace(/_/g, ' ')}</b></div>
                {cd.case.summary && <p className="text-slate-700">{cd.case.summary}</p>}
              </div>
            )}
          </Panel>
          <Panel title="Kane investigations">
            {invs.length === 0 ? <p className="text-sm text-slate-500">Send a link as the scammer. Kane opens it like a victim would, stops before paying, and proves where the money goes.</p>
              : <div className="space-y-3">{[...invs].reverse().map((inv) => <KaneCard key={inv.id} inv={inv} />)}</div>}
          </Panel>
          <Panel title="Evidence board">
            {cd ? <EvidenceBoard cd={cd} /> : <Empty text="No identifiers yet" />}
          </Panel>
        </div>
      </div>
    </div>
  );
};
