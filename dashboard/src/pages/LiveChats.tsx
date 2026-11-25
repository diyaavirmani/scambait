import { useEffect, useMemo, useRef, useState } from 'react';
import { FolderOpen } from 'lucide-react';
import { useCase, useCases } from '../lib/live';
import type { CaseData } from '../lib/types';
import { Empty, PageHeader, Panel, VerdictBadge } from '../components/Layout';
import { EvidenceBoard } from '../components/EvidenceBoard';
import { DetectionLog } from '../components/DetectionLog';
import { CaseList, Toggle, clock, words } from '../components/LiveBits';

const CHANNEL: Record<string, string> = { web: 'Scam Console', telegram: 'Telegram', api: 'API' };
const MODE: Record<string, string> = { bait: 'baiting', neutral: 'neutral', wrap_up: 'wrapping up' };

interface ReplyMeta { mode?: string; degraded?: boolean; used?: number }

/** The live conversation of one chat, kept scrolled to the newest message unless you scroll up. */
const Conversation = ({ cd }: { cd: CaseData }) => {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const meta = useMemo(() => {
    const m = new Map<number, ReplyMeta>();
    for (const e of cd.events) {
      if (e.type === 'persona.reply' && e.data?.message_id != null) {
        m.set(e.data.message_id, { mode: e.data.mode, degraded: !!e.data.degraded, used: Number(e.data.kane_findings_used) || 0 });
      }
    }
    return m;
  }, [cd.events]);

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [cd.messages.length]);

  if (cd.messages.length === 0) return <Empty text="No messages in this chat yet." />;
  return (
    <div ref={box} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}
      className="h-[28rem] overflow-y-auto rounded-lg bg-slate-50 border border-slate-100 p-3 sm:p-4">
      <ol className="space-y-3" aria-label="Conversation" aria-live="polite">
        {cd.messages.map((m) => {
          const scammer = m.role === 'scammer';
          const r = scammer ? undefined : meta.get(m.id);
          return (
            <li key={m.id} className={`flex ${scammer ? 'justify-start' : 'justify-end'}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm shadow-sm ${scammer ? 'bg-slate-800 text-white rounded-bl-sm' : 'bg-white border border-slate-200 text-slate-800 rounded-br-sm'}`}>
                <div className={`text-[10px] font-bold uppercase mb-0.5 flex flex-wrap gap-x-2 ${scammer ? 'text-slate-300' : 'text-blue-600'}`}>
                  <span>{scammer ? 'Scammer' : 'Meena'}</span>
                  <time dateTime={m.ts} className="font-normal normal-case opacity-80">{clock(m.ts)}</time>
                  {r?.mode && MODE[r.mode] && <span className="font-normal normal-case text-slate-500">{MODE[r.mode]}</span>}
                  {r?.degraded && <span className="normal-case text-amber-700">scripted reply, model unavailable</span>}
                  {!!r?.used && <span className="normal-case text-green-700">used what Kane found</span>}
                </div>
                <span className="whitespace-pre-wrap break-words">{m.text}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
};

/** Open chat cases next to each other: pick one, watch the conversation live, and see every verdict the detector gave. */
export const LiveChats = ({ openCase }: { openCase: (id: string) => void }) => {
  const { cases } = useCases();
  const [showClosed, setShowClosed] = useState(false);
  const [picked, setPicked] = useState<string | null>(() => new URLSearchParams(window.location.search).get('case'));
  const chats = cases.filter((c) => c.channel !== 'call' && (showClosed || c.status === 'open' || c.id === picked));
  const current = picked && chats.some((c) => c.id === picked) ? picked : chats[0]?.id ?? null;
  const cd = useCase(current);
  const openCount = cases.filter((c) => c.channel !== 'call' && c.status === 'open').length;

  return (
    <div>
      <PageHeader title="Live Chats" subtitle="Scammers chatting with Meena right now. Watch each conversation as it happens, and see why the detector called it a scam." />
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <Panel title={`Chats (${openCount} open)`} className="lg:col-span-4 xl:col-span-3"
          right={<Toggle on={showClosed} onChange={setShowClosed} label="Show closed" />}>
          {chats.length === 0
            ? <Empty text={showClosed ? 'No chats yet. Start one from the Scam Console or message the Telegram bot.' : 'No open chats right now. Turn on Show closed to see earlier ones.'} />
            : <CaseList cases={chats} current={current} select={setPicked} label="Chats" />}
        </Panel>

        <div className="lg:col-span-8 xl:col-span-5 min-w-0">
          <Panel title="Conversation" right={cd ? <VerdictBadge verdict={cd.case.verdict} /> : undefined}>
            {!current ? <Empty text="Pick a chat to watch it live." /> : !cd ? <Empty text="Loading the chat..." /> : (<>
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3 text-sm">
                <span className="text-slate-600">
                  {CHANNEL[cd.case.channel] || cd.case.channel} &middot; {cd.messages.filter((m) => m.role === 'scammer').length} scammer messages &middot; {cd.case.status}
                </span>
                <button type="button" onClick={() => openCase(cd.case.id)} aria-label={'Open case ' + cd.case.id + ' on the Cases page'}
                  className="inline-flex items-center gap-1.5 text-blue-700 hover:underline">
                  <FolderOpen size={15} aria-hidden /> Open full case
                </button>
              </div>
              <Conversation key={cd.case.id} cd={cd} />
            </>)}
          </Panel>
        </div>

        <div className="lg:col-span-12 xl:col-span-4 min-w-0 grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-1 gap-6 content-start">
          <Panel title="Detection" right={cd ? <span className="flex items-center gap-1.5 text-xs text-slate-500">Final verdict <VerdictBadge verdict={cd.case.verdict} /></span> : undefined}>
            {cd ? <DetectionLog events={cd.events} /> : <Empty text="Verdicts show here once a chat is open." />}
          </Panel>
          <div className="space-y-6 min-w-0">
            <Panel title="Case summary">
              {!cd ? <Empty text="No chat selected." /> : (
                <div className="text-sm space-y-2">
                  <div><span className="text-slate-500">Scam type: </span><b>{words(cd.case.scam_type)}</b></div>
                  <div className="font-mono text-xs text-slate-500">{cd.case.id}</div>
                  {cd.case.summary ? <p className="text-slate-700">{cd.case.summary}</p> : <p className="text-slate-500">No summary yet. Meena writes one as the chat goes on.</p>}
                </div>
              )}
            </Panel>
            <Panel title="Identifiers" right={<span className="text-xs text-slate-500">said in chat vs proven by Kane</span>}>
              {cd ? <EvidenceBoard cd={cd} /> : <Empty text="No identifiers yet" />}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
};
