import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { FolderOpen, Phone, PhoneCall, PhoneIncoming, PhoneOff } from 'lucide-react';
import { onEvent, useCase, useCases } from '../lib/live';
import type { CaseData, Ev } from '../lib/types';
import type { CaseWithReport, TranscriptLine } from '../lib/extra-types';
import { Empty, PageHeader, Panel, VerdictBadge } from '../components/Layout';
import { EvidenceBoard } from '../components/EvidenceBoard';
import { DetectionLog } from '../components/DetectionLog';
import { CaseList, Pill, Toggle, clock, when, words } from '../components/LiveBits';

const RINGING = new Set(['ringing', 'queued', 'initiated']);
const LIVE = new Set(['live', 'in-progress', 'in_progress', 'answered']);
const ENDED = new Set(['ended', 'completed']);
const FAILED = new Set(['failed', 'busy', 'no-answer', 'no_answer', 'canceled', 'cancelled']);

function callLook(status: string): { tone: string; icon: LucideIcon; text: string; pulse: boolean } {
  if (RINGING.has(status)) return { tone: 'bg-amber-50 text-amber-800 border-amber-200', icon: PhoneIncoming, text: 'Ringing', pulse: true };
  if (LIVE.has(status)) return { tone: 'bg-green-50 text-green-800 border-green-200', icon: PhoneCall, text: 'Live', pulse: true };
  if (ENDED.has(status)) return { tone: 'bg-slate-50 text-slate-600 border-slate-200', icon: PhoneOff, text: 'Ended', pulse: false };
  if (FAILED.has(status)) return { tone: 'bg-red-50 text-red-700 border-red-200', icon: PhoneOff, text: words(status), pulse: false };
  return { tone: 'bg-slate-50 text-slate-500 border-slate-200', icon: Phone, text: status ? words(status) : 'No status yet', pulse: false };
}

const CallStatus = ({ status }: { status: string }) => {
  const look = callLook(status);
  return <Pill tone={look.tone} icon={look.icon} pulse={look.pulse}>{look.text}</Pill>;
};

const speakerName = (s: string) => (s === 'meena' || s === 'persona' ? 'Meena' : 'Caller');

/** Finished lines, plus the words still arriving for each speaker (partial deltas joined until their final line). */
function transcript(events: Ev[]): { lines: TranscriptLine[]; pending: TranscriptLine[] } {
  const lines: TranscriptLine[] = [];
  const pending = new Map<string, TranscriptLine>();
  for (const ev of events) {
    if (ev.type !== 'transcript.partial' && ev.type !== 'transcript.final') continue;
    const speaker = String(ev.data?.speaker || 'caller');
    const open = pending.get(speaker);
    if (ev.type === 'transcript.partial') {
      pending.set(speaker, { speaker, text: (open?.text || '') + String(ev.data?.delta ?? ''), final: false, ts: open?.ts || ev.ts });
    } else {
      pending.delete(speaker);
      const text = String(ev.data?.text || open?.text || '').trim();
      if (text) lines.push({ speaker, text, final: true, ts: ev.ts });
    }
  }
  return { lines, pending: [...pending.values()].filter((p) => p.text.trim()) };
}

function show(v: unknown): string {
  if (v == null || v === '') return 'none';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'string' || typeof v === 'number') return String(v);
  if (Array.isArray(v)) return v.length ? v.map(show).join(', ') : 'none';
  return Object.entries(v as Record<string, unknown>).map(([k, x]) => words(k) + ': ' + show(x)).join('; ');
}

/** The call report as the server sent it: plain text, a list, or named fields. */
const ReportView = ({ report }: { report: unknown }) => {
  if (typeof report === 'string') return <p className="text-sm text-slate-700 whitespace-pre-wrap break-words">{report}</p>;
  if (Array.isArray(report)) return <ul className="list-disc pl-5 text-sm space-y-1 text-slate-700">{report.map((r, i) => <li key={i} className="break-words">{show(r)}</li>)}</ul>;
  if (report && typeof report === 'object') {
    return (
      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-x-4 gap-y-1 sm:gap-y-2 text-sm">
        {Object.entries(report as Record<string, unknown>).map(([k, v]) => (
          <Fragment key={k}>
            <dt className="text-slate-500 sm:pt-0 pt-2">{words(k)}</dt>
            <dd className="sm:col-span-2 text-slate-800 break-words whitespace-pre-wrap">{show(v)}</dd>
          </Fragment>
        ))}
      </dl>
    );
  }
  return <p className="text-sm text-slate-700">{show(report)}</p>;
};

function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

/** One call: its status, the live transcript, the verdict, identifiers and the report. */
const CallView = ({ cd, openCase }: { cd: CaseData; openCase: (id: string) => void }) => {
  const statusEvents = cd.events.filter((e) => e.type === 'call.status' && e.data?.status);
  const last = statusEvents[statusEvents.length - 1];
  const status = last ? String(last.data.status) : (cd.case.status === 'closed' ? 'ended' : '');
  const sid = [...statusEvents].reverse().find((e) => e.data?.call_sid)?.data.call_sid as string | undefined;
  const liveAt = statusEvents.find((e) => LIVE.has(String(e.data.status)))?.ts;
  const endAt = statusEvents.find((e) => ENDED.has(String(e.data.status)) || FAILED.has(String(e.data.status)))?.ts;
  const isLive = LIVE.has(status);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isLive) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [isLive]);
  const length = liveAt ? (endAt ? Date.parse(endAt) : isLive ? now : NaN) - Date.parse(liveAt) : NaN;

  const { lines, pending } = useMemo(() => transcript(cd.events), [cd.events]);
  const fallback = lines.length === 0 && pending.length === 0;
  const report = useMemo(() => {
    const ev = [...cd.events].reverse().find((e) => e.type === 'case.updated' && e.data?.report != null && e.data.report !== '');
    return ev ? ev.data.report : (cd.case as CaseWithReport).report;
  }, [cd.events, cd.case]);

  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const size = lines.length + pending.reduce((n, p) => n + p.text.length, 0) + (fallback ? cd.messages.length : 0);
  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [size]);

  return (
    <div className="space-y-6 min-w-0">
      <Panel title="Call" right={<CallStatus status={status} />}>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div><dt className="text-xs text-slate-500">Verdict</dt><dd className="mt-0.5"><VerdictBadge verdict={cd.case.verdict} /></dd></div>
          <div><dt className="text-xs text-slate-500">Scam type</dt><dd className="font-medium">{words(cd.case.scam_type)}</dd></div>
          <div><dt className="text-xs text-slate-500">{isLive ? 'Live for' : 'Length'}</dt><dd className="tabular-nums">{Number.isFinite(length) ? duration(length) : 'not known'}</dd></div>
          <div><dt className="text-xs text-slate-500">Started</dt><dd>{when(cd.case.created_at)}</dd></div>
        </dl>
        {sid && <p className="text-xs text-slate-500 mt-3">Call reference <span className="font-mono break-all">{sid}</span></p>}
        {cd.case.summary && <p className="text-sm text-slate-700 mt-3">{cd.case.summary}</p>}
        <button type="button" onClick={() => openCase(cd.case.id)} aria-label={'Open case ' + cd.case.id + ' on the Cases page'}
          className="inline-flex items-center gap-1.5 text-sm text-blue-700 hover:underline mt-3">
          <FolderOpen size={15} aria-hidden /> Open full case
        </button>
      </Panel>

      <Panel title="Live transcript" right={pending.length > 0 ? <span className="text-xs text-green-700 font-semibold">speaking now</span> : undefined}>
        <div ref={box} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}
          className="h-80 overflow-y-auto rounded-lg bg-slate-50 border border-slate-100 p-3 sm:p-4">
          {fallback ? (
            cd.messages.length === 0 ? <Empty text={isLive || RINGING.has(status) ? 'Waiting for the first words...' : 'No transcript for this call.'} /> : (
              <ol className="space-y-2" aria-label="Call transcript">
                {cd.messages.map((m) => (
                  <li key={m.id} className="text-sm">
                    <span className={`text-[10px] font-bold uppercase mr-2 ${m.role === 'scammer' ? 'text-slate-500' : 'text-blue-700'}`}>{m.role === 'scammer' ? 'Caller' : 'Meena'}</span>
                    <span className="whitespace-pre-wrap break-words">{m.text}</span>
                  </li>
                ))}
              </ol>
            )
          ) : (<>
            <ol className="space-y-2" aria-label="Call transcript" aria-live="polite">
              {lines.map((l, i) => (
                <li key={i} className="text-sm">
                  <span className={`text-[10px] font-bold uppercase mr-2 ${speakerName(l.speaker) === 'Meena' ? 'text-blue-700' : 'text-slate-500'}`}>{speakerName(l.speaker)}</span>
                  <time dateTime={l.ts} className="text-[10px] text-slate-400 mr-2 tabular-nums">{clock(l.ts)}</time>
                  <span className="whitespace-pre-wrap break-words">{l.text}</span>
                </li>
              ))}
            </ol>
            {pending.length > 0 && (
              <ul className="space-y-2 mt-2" aria-label="Words still arriving">
                {pending.map((p) => (
                  <li key={p.speaker} className="text-sm text-slate-500 italic">
                    <span className={`text-[10px] font-bold uppercase not-italic mr-2 ${speakerName(p.speaker) === 'Meena' ? 'text-blue-700' : 'text-slate-500'}`}>{speakerName(p.speaker)}</span>
                    <span className="whitespace-pre-wrap break-words">{p.text}</span>
                    <span className="inline-block w-1.5 h-3.5 ml-1 align-middle bg-slate-400 animate-pulse" aria-hidden />
                  </li>
                ))}
              </ul>
            )}
          </>)}
        </div>
      </Panel>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Panel title="Verdict" right={<VerdictBadge verdict={cd.case.verdict} />}>
          <DetectionLog events={cd.events} max={3} />
        </Panel>
        <Panel title="Identifiers">
          <EvidenceBoard cd={cd} />
        </Panel>
      </div>

      <Panel title="Call report">
        {report != null && report !== '' ? <ReportView report={report} />
          : <p className="text-sm text-slate-500">{ENDED.has(status) ? 'No report for this call yet.' : 'The report arrives when the call ends.'}</p>}
      </Panel>
    </div>
  );
};

/** Phone calls Meena answered: status, the transcript as it is spoken, the verdict and the call report. */
export const Calls = ({ openCase }: { openCase: (id: string) => void }) => {
  const { cases } = useCases();
  const [showEnded, setShowEnded] = useState(true);
  const [picked, setPicked] = useState<string | null>(() => new URLSearchParams(window.location.search).get('case'));
  const [live, setLive] = useState<Record<string, string>>({});

  useEffect(() => onEvent((ev) => {
    const id = ev.case_id;
    if (ev.type !== 'call.status' || !id || !ev.data?.status) return;
    const status = String(ev.data.status);
    setLive((m) => ({ ...m, [id]: status }));
    if (RINGING.has(status)) setPicked((p) => p || id);
  }), []);

  const calls = cases.filter((c) => c.channel === 'call' && (showEnded || c.status === 'open' || c.id === picked));
  const current = picked && calls.some((c) => c.id === picked) ? picked : calls[0]?.id ?? null;
  const cd = useCase(current);
  const total = cases.filter((c) => c.channel === 'call').length;

  return (
    <div>
      <PageHeader title="Calls" subtitle="Scam phone calls Meena answered. Follow the call live as it is spoken, see the verdict, and read the report when it ends." />
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <Panel title={`Calls (${total})`} className="lg:col-span-4 self-start" right={<Toggle on={showEnded} onChange={setShowEnded} label="Show ended" />}>
          {calls.length === 0
            ? <Empty text={total === 0 ? 'No phone calls yet. Calls Meena answers show here, live.' : 'No calls in progress. Turn on Show ended to see earlier ones.'} />
            : <CaseList cases={calls} current={current} select={setPicked} label="Calls"
                meta={(c) => (live[c.id] ? callLook(live[c.id]).text.toLowerCase() : null)} />}
        </Panel>
        <div className="lg:col-span-8 min-w-0">
          {!current ? <Panel><Empty text="Pick a call to follow it." /></Panel>
            : !cd ? <Panel><Empty text="Loading the call..." /></Panel>
            : <CallView key={cd.case.id} cd={cd} openCase={openCase} />}
        </div>
      </div>
    </div>
  );
};
