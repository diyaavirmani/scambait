import type { Ev } from '../lib/types';
import type { Detection } from '../lib/extra-types';
import { Empty, VerdictBadge } from './Layout';
import { PercentMeter, clock, percent, words } from './LiveBits';

const DECIDED: Record<string, string> = {
  model: 'The model', rules: 'The rules', none: 'Not decided yet', cerebras: 'Cerebras',
  decisions: 'OpenAI Decisions', openai: 'OpenAI Decisions', both: 'Cerebras and OpenAI Decisions',
};

export interface DetectionEntry extends Detection { ts: string; key: string }

/** Every scam.detected event in a case, oldest first. */
export function detections(events: Ev[]): DetectionEntry[] {
  return events.filter((e) => e.type === 'scam.detected' && e.data).map((e, i) => ({
    ...(e.data as Detection), ts: e.ts, key: e.id != null ? 'e' + e.id : 'l' + i + e.ts,
  }));
}

/** Each verdict the detector gave, newest first: the probabilities, who decided, and the red flags. */
export const DetectionLog = ({ events, max = 8 }: { events: Ev[]; max?: number }) => {
  const list = detections(events).reverse().slice(0, max);
  if (list.length === 0) return <Empty text="No verdict yet. The detector answers after each scammer message." />;
  return (
    <ol className="space-y-3" aria-label="Verdicts from the detector, newest first">
      {list.map((d, i) => {
        const rows: [string, number | null][] = [
          ['Scam probability', percent(d.p_scam)],
          ['Cerebras', percent(d.p_cerebras)],
          ['OpenAI Decisions', percent(d.p_decisions)],
        ];
        const flags = Array.isArray(d.red_flags) ? d.red_flags : [];
        return (
          <li key={d.key} className={`rounded-lg border p-3 text-sm ${i === 0 ? 'border-slate-300 bg-white' : 'border-slate-200 bg-slate-50'}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <VerdictBadge verdict={d.verdict || 'unknown'} />
                {i === 0 && <span className="text-[10px] uppercase font-semibold text-slate-500">latest</span>}
              </span>
              <time dateTime={d.ts} className="text-xs text-slate-500 tabular-nums">{clock(d.ts)}</time>
            </div>
            <div className="mt-3 space-y-1.5">
              {rows.filter(([, v]) => v != null).map(([label, v]) => <PercentMeter key={label} label={label} value={v as number} />)}
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
              <div><dt className="text-xs text-slate-500">Decided by</dt><dd className="font-medium">{DECIDED[d.decided_by || ''] || words(d.decided_by, 'not given')}</dd></div>
              <div><dt className="text-xs text-slate-500">Scam type</dt><dd className="font-medium">{words(d.scam_type)}</dd></div>
              <div><dt className="text-xs text-slate-500">Risk</dt><dd>{words(d.risk)}</dd></div>
              {d.stage && <div><dt className="text-xs text-slate-500">Stage</dt><dd>{words(d.stage)}</dd></div>}
            </dl>
            {flags.length > 0 && (
              <div className="mt-3">
                <div className="text-xs text-slate-500 mb-1">Red flags</div>
                <ul className="flex flex-wrap gap-1" aria-label="Red flags">
                  {flags.map((f, j) => <li key={j + ':' + f} className="text-xs px-2 py-0.5 rounded-full bg-red-50 border border-red-200 text-red-800">{f}</li>)}
                </ul>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
};
