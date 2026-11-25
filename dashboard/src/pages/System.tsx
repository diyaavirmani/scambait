import { useCallback, useEffect, useState, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, BadgeCheck, CheckCircle2, Coins, Gauge, Link2, MinusCircle, Repeat, ShieldAlert, Timer, XCircle } from 'lucide-react';
import { onEvent, useConnected } from '../lib/live';
import type { Investigation } from '../lib/types';
import type { Health, SpeedSample } from '../lib/extra-types';
import { norm } from '../lib/kane';
import { Empty, PageHeader, Panel } from '../components/Layout';
import { RefreshButton, StatTile, clock, useLiveJSON, words } from '../components/LiveBits';

const PROVIDER: Record<string, string> = { cerebras: 'Cerebras', openai: 'OpenAI' };
const HEALTH_EVERY_MS = 30000;

type State = 'good' | 'warn' | 'bad' | 'none';
const LOOK: Record<State, { icon: LucideIcon; tone: string; word: string }> = {
  good: { icon: CheckCircle2, tone: 'text-green-600', word: 'OK' },
  warn: { icon: AlertTriangle, tone: 'text-amber-600', word: 'Limited' },
  bad: { icon: XCircle, tone: 'text-red-600', word: 'Down' },
  none: { icon: MinusCircle, tone: 'text-slate-400', word: 'Not reported' },
};

/** One health line: an icon and a word for the state (never colour alone), the name, and the detail. */
const HealthRow = ({ state, name, children }: { state: State; name: string; children?: ReactNode }) => {
  const look = LOOK[state];
  const Icon = look.icon;
  return (
    <li className="flex items-start gap-3 py-3">
      <Icon size={18} className={`mt-0.5 shrink-0 ${look.tone}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="text-sm font-semibold text-slate-900">{name}</span>
          <span className={`text-xs font-bold uppercase ${look.tone}`}>{look.word}</span>
        </div>
        {children && <div className="text-sm text-slate-600 mt-0.5 break-words">{children}</div>}
      </div>
    </li>
  );
};

/** /health answers 503 with the same JSON body when something is down, so read the body whatever the status. */
async function loadHealth(): Promise<Health> {
  const r = await fetch('/health', { headers: { Accept: 'application/json' } });
  const d = await r.json().catch(() => null);
  if (!d || typeof d !== 'object' || !('brain' in d)) throw new Error('/health answered ' + r.status);
  return d as Health;
}

function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState('');
  const load = useCallback(() => {
    setBusy(true);
    loadHealth()
      .then((h) => { setHealth(h); setError(''); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not reach the server'))
      .finally(() => { setBusy(false); setChecked(new Date().toISOString()); });
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, HEALTH_EVERY_MS);
    return () => window.clearInterval(t);
  }, [load]);
  return { health, error, busy, checked, load };
}

interface Speed { order: string[]; latest: Record<string, SpeedSample>; count: Record<string, number>; totalMs: Record<string, number> }

/** The latest metrics.speed per step, kept since this page opened. */
function useSpeed(): Speed {
  const [s, setS] = useState<Speed>({ order: [], latest: {}, count: {}, totalMs: {} });
  useEffect(() => onEvent((ev) => {
    if (ev.type !== 'metrics.speed') return;
    const d = ev.data || {};
    const ms = Number(d.ms);
    if (!d.step || !Number.isFinite(ms)) return;
    const tps = d.tokens_per_s == null ? null : Number(d.tokens_per_s);
    const sample: SpeedSample = { step: String(d.step), provider: String(d.provider || ''), model: String(d.model || ''), ms,
      tokens_per_s: tps != null && Number.isFinite(tps) ? tps : null, ts: ev.ts };
    const k = sample.step;
    setS((p) => ({
      order: p.order.includes(k) ? p.order : [...p.order, k],
      latest: { ...p.latest, [k]: sample },
      count: { ...p.count, [k]: (p.count[k] || 0) + 1 },
      totalMs: { ...p.totalMs, [k]: (p.totalMs[k] || 0) + ms },
    }));
  }), []);
  return s;
}

const fmtMs = (ms: number) => (ms >= 1000 ? (ms / 1000).toFixed(ms >= 10000 ? 0 : 1) + ' s' : Math.round(ms) + ' ms');

/** Health of the server and its models, how fast each model step is right now, and what Kane has cost. */
export const System = () => {
  const { health, error, busy, checked, load } = useHealth();
  const speed = useSpeed();
  const connected = useConnected();
  const kane = useLiveJSON<{ investigations: Investigation[] }>('/api/investigations?limit=100', ['kane.finished']);

  const brain = health?.brain;
  const offline = brain?.mode === 'offline';
  const brainState: State = !health ? 'none' : !brain?.ok ? 'bad' : offline ? 'warn' : 'good';
  const openai = health?.openai;
  const openaiState: State = !openai ? 'none' : !openai.configured ? 'warn' : openai.decisions_available ? 'good' : 'warn';

  const maxMs = Math.max(1, ...speed.order.map((k) => speed.latest[k].ms));

  const invs = kane.data?.investigations || [];
  const runs = invs.filter((i) => i.status !== 'skipped');
  const provenRuns = invs.filter((i) => i.verdict === 'payment_request_found' && i.payee);
  const payees = new Set(provenRuns.map((i) => i.payee_kind + ':' + norm(i.payee_kind, i.payee))).size;
  const unsafe = invs.filter((i) => i.verdict === 'unsafe_run').length;
  const durs = runs.map((i) => i.duration_s).filter((x): x is number => typeof x === 'number' && Number.isFinite(x));
  const avg = durs.length ? durs.reduce((a, b) => a + b, 0) / durs.length : null;
  const credits = invs.reduce((n, i) => n + (typeof i.credits === 'number' && Number.isFinite(i.credits) ? i.credits : 0), 0);
  const replayed = invs.filter((i) => i.replayed).length;

  return (
    <div className="space-y-6">
      <PageHeader title="System" subtitle="Is everything up, how fast the models answer right now, and what Kane's browser runs have found and cost." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Health" right={<RefreshButton onClick={load} busy={busy} label="Check health again" />}>
          {!health && error ? <p role="alert" className="text-sm text-red-600">Could not reach the server: {error}</p>
            : !health ? <Empty text="Checking health..." /> : (<>
              <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${health.status === 'ok' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-amber-50 border-amber-200 text-amber-800'}`} role="status">
                {health.status === 'ok' ? <CheckCircle2 size={16} aria-hidden /> : <AlertTriangle size={16} aria-hidden />}
                {health.status === 'ok' ? 'Everything is up' : 'Something is down or limited'}
              </div>
              <ul className="divide-y divide-slate-100">
                <HealthRow state={health.database ? 'good' : 'bad'} name="Database">{health.database ? 'Connected' : 'Not reachable'}</HealthRow>
                <HealthRow state={brainState} name="Model brain">
                  <span>{offline ? 'Offline mode: scripted replies, no model calls' : brain?.mode === 'cerebras' ? 'Cerebras models' : words(brain?.mode, 'mode not reported')}</span>
                  {brain?.models && brain.models.length > 0 && (
                    <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="Models">
                      {brain.models.map((m) => <li key={m} className="text-xs font-mono px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-700">{m}</li>)}
                    </ul>
                  )}
                  {brain?.error && <p className="mt-1 text-red-700">{brain.error}</p>}
                </HealthRow>
                <HealthRow state={openaiState} name="OpenAI">
                  {!openai ? 'This server does not report OpenAI.' : (<>
                    <span className="block">{openai.configured ? 'Configured' : 'Not configured'} &middot; Decisions {openai.decisions_available ? 'available' : 'not available'}</span>
                    {openai.reason && <span className="block text-slate-500">{openai.reason}</span>}
                  </>)}
                </HealthRow>
              </ul>
              <p className="text-xs text-slate-500 mt-1">Checked at {clock(checked)}, again every 30 seconds.{error && <span className="text-red-600"> The last check failed: {error}</span>}</p>
            </>)}
        </Panel>

        <Panel title="Model speed" right={<span className="flex items-center gap-1.5 text-xs text-slate-500"><span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-slate-300'}`} aria-hidden />{connected ? 'Live' : 'Connecting'}</span>}>
          {speed.order.length === 0 ? <Empty text="Waiting for the next model call. Send a message in the Scam Console to see live timings." /> : (<>
            <ul className="space-y-4" aria-label="Latest time per model step">
              {speed.order.map((k) => {
                const s = speed.latest[k];
                const n = speed.count[k] || 1;
                const width = Math.max(2, Math.round((s.ms / maxMs) * 100));
                return (
                  <li key={k} className="grid grid-cols-[1fr_auto] sm:grid-cols-[9rem_1fr_6.5rem] items-center gap-x-3 gap-y-1"
                    title={`${words(s.step)}: ${fmtMs(s.ms)} on ${PROVIDER[s.provider] || s.provider} ${s.model} at ${clock(s.ts)}`}>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-900 truncate">{words(s.step)}</div>
                      <div className="text-xs text-slate-500 truncate">{PROVIDER[s.provider] || words(s.provider, 'provider not given')}{s.model && <> &middot; <span className="font-mono">{s.model}</span></>}</div>
                    </div>
                    <div className="text-right tabular-nums sm:order-last">
                      <div className="text-sm font-semibold text-slate-900">{fmtMs(s.ms)}</div>
                      <div className="text-xs text-slate-500">{s.tokens_per_s != null ? Math.round(s.tokens_per_s).toLocaleString('en-IN') + ' tokens/s' : 'tokens/s not given'}</div>
                    </div>
                    <div className="col-span-2 sm:col-span-1">
                      <div className="h-2 rounded-full bg-slate-100 overflow-hidden" role="meter" aria-label={words(s.step) + ' time, compared with the slowest step'}
                        aria-valuemin={0} aria-valuemax={Math.round(maxMs)} aria-valuenow={Math.round(s.ms)} aria-valuetext={fmtMs(s.ms)}>
                        <div className="h-full rounded-full bg-slate-700 transition-[width] duration-500" style={{ width: width + '%' }} />
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">{n > 1 ? `average ${fmtMs(speed.totalMs[k] / n)} over ${n} calls` : '1 call'} &middot; {clock(s.ts)}</div>
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="text-xs text-slate-500 mt-4">Latest call per step since this page opened. Bar length is time taken, compared with the slowest step.</p>
          </>)}
        </Panel>
      </div>

      <Panel title="Kane runs" right={<RefreshButton onClick={kane.reload} busy={kane.loading} label="Reload Kane runs" />}>
        {kane.error && !kane.data ? <p role="alert" className="text-sm text-red-600">Could not load Kane runs: {kane.error}</p> : (<>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            <StatTile icon={Link2} value={runs.length} label="Links opened" tone="bg-slate-100 text-slate-700" />
            <StatTile icon={BadgeCheck} value={payees} label="Payees proven" note={provenRuns.length + ' runs found a payment request'} tone="bg-green-50 text-green-700" />
            <StatTile icon={ShieldAlert} value={unsafe} label="Unsafe runs" note="broke a safety rule, not counted" tone="bg-red-50 text-red-700" />
            <StatTile icon={Timer} value={avg == null ? 'none' : Math.round(avg) + ' s'} label="Average run time" tone="bg-blue-50 text-blue-700" />
            <StatTile icon={Coins} value={Math.round(credits).toLocaleString('en-IN')} label="Credits used" tone="bg-amber-50 text-amber-700" />
            <StatTile icon={Repeat} value={replayed} label="Replayed runs" note="recorded real runs, replayed" tone="bg-slate-100 text-slate-700" />
          </div>
          <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5"><Gauge size={13} aria-hidden /> From the latest {invs.length} investigations (up to 100). Updates when Kane finishes a run.</p>
        </>)}
      </Panel>
    </div>
  );
};
