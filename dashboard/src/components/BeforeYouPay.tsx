import { useEffect, useState } from 'react';
import { AlertOctagon, AlertTriangle, BadgeCheck, Ban, CircleSlash, Loader2, Search, Smartphone, Wallet } from 'lucide-react';
import type { Investigation } from '../lib/types';
import type { CheckResult, LinkCheck } from '../lib/check-types';
import { getJSON } from '../lib/live';
import { kindWord, proved, rs, working } from '../lib/linkcheck';
import { KaneCard } from './KaneCard';

/** Why the payee gives the scam away, by the scam type the message was judged to be. */
const WHY: Record<string, string> = {
  kyc_phishing: 'Banks do not collect KYC fees into a UPI ID or a bank account sent in a message.',
  utility_bill: 'Electricity boards do not collect bills into a UPI ID or a bank account sent in a message.',
  delivery_phishing: 'Courier and customs fees are not paid into a UPI ID or a bank account sent in a message.',
  investment_trading: 'Real trading apps do not take deposits into a UPI ID or a bank account sent in a chat.',
  job_task: 'A real job never asks you to pay money to start work or to get your earnings.',
  digital_arrest: 'Police, CBI, customs and RBI never ask you to send money to a UPI ID or a bank account.',
  lottery_prize: 'You never have to pay a fee to receive a real prize.',
  customer_care: 'Real customer care never asks you to pay money to get help or a refund.',
  loan_offer: 'Do not pay a fee into a UPI ID or a bank account to get a loan.',
  upi_collect: 'You never need to pay or type your UPI PIN to receive money.',
};
const WHY_DEFAULT = 'A real company does not ask you to pay through a link sent in a message.';
const NOT_SAFE = 'This does not mean the link is safe. Do not pay or type any details on it.';
const SECRET = /pin|otp|cvv|card|password/i;

function listWords(items: string[]): string {
  return items.length <= 1 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
}

/** The first sentence when Kane finished without proving a payee. It is always followed by NOT_SAFE. */
function noPayeeLine(inv: Investigation): string {
  if (inv.verdict === 'unsafe_run') return 'Kane broke its own safety rule on this run, so its answer is not used.';
  if (inv.status === 'skipped') return 'Kane did not open this link.';
  if (inv.status === 'timeout') return 'Kane ran out of time before it reached a payment page.';
  if (inv.status === 'not_started' || inv.status === 'error') return 'Kane could not open the link this time.';
  return 'Kane did not reach a payment page.';
}

/** The plain-language answer for a finished Kane run, in one or two sentences (also read out to screen readers). */
export function answerLine(inv: Investigation): string {
  if (proved(inv)) return 'Do not pay. This page would send ' + (rs(inv.amount) || 'your money') + ' to ' + inv.payee + '.';
  return noPayeeLine(inv) + ' ' + NOT_SAFE;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [active]);
  return now;
}

function elapsed(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

/** Kane's screenshots of every step, loaded only when the person opens the list. */
const AllSteps = ({ inv }: { inv: Investigation }) => {
  const [steps, setSteps] = useState<number[] | null>(null);
  const [failed, setFailed] = useState(false);
  function load(open: boolean) {
    if (!open || steps) return;
    getJSON<{ steps: number[] }>(`/api/investigations/${inv.id}/screenshots`)
      .then((d) => setSteps(d.steps || [])).catch(() => setFailed(true));
  }
  return (
    <details className="mt-3" onToggle={(e) => load((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-sm font-medium text-slate-700">See every step Kane took</summary>
      {failed && <p className="mt-2 text-sm text-slate-500">The screenshots could not be loaded.</p>}
      {steps && steps.length === 0 && <p className="mt-2 text-sm text-slate-500">No step screenshots were saved.</p>}
      {steps && steps.length > 0 && (
        <ul className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-2">
          {steps.map((n) => (
            <li key={n}>
              <a href={`/api/investigations/${inv.id}/screenshots/${n}`} target="_blank" rel="noreferrer"
                aria-label={'Open the screenshot of step ' + n} className="block">
                <img src={`/api/investigations/${inv.id}/screenshots/${n}`} alt={'Step ' + n + ' as Kane saw it'} loading="lazy"
                  className="rounded-md border border-slate-200 bg-white w-full h-28 object-cover object-top" />
                <span className="text-[11px] text-slate-500">Step {n}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
};

/** What Kane proved: who the page would pay, how much, what it claims to be and what it asks for. */
const Found = ({ inv, scamType, onPaid }: { inv: Investigation; scamType: string; onPaid: () => void }) => {
  const asked = (inv.asked_for || []).filter(Boolean);
  const kind = kindWord(inv.payee_kind);
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-3 sm:p-4">
      <div className="flex items-start gap-3">
        <AlertOctagon size={22} className="mt-0.5 shrink-0 text-red-600" aria-hidden />
        <div className="min-w-0 space-y-2 text-sm text-slate-800">
          <p className="text-base font-bold text-red-800">Do not pay.</p>
          <p className="text-base">This page would send <strong>{rs(inv.amount) || 'your money'}</strong> to{' '}
            <strong className="font-mono break-words">{inv.payee}</strong>{kind && <span className="text-slate-600"> ({kind})</span>}.</p>
          {inv.claims_to_be && <p>It claims to be <strong>{inv.claims_to_be}</strong>.</p>}
          <p>{WHY[scamType] || WHY_DEFAULT} Pay a company only on its official website or app, never on a link from a message.</p>
          {asked.length > 0 && (
            <p>It also asks for your {listWords(asked)}.{asked.some((a) => SECRET.test(a)) && ' Never type a UPI PIN, OTP or card number on a page like this.'}</p>
          )}
          <p className="flex flex-wrap items-center gap-2 pt-1">
            <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border border-green-200 bg-green-50 text-green-800">
              <BadgeCheck size={13} aria-hidden /> Kane saw this on the payment page</span>
            {inv.replayed && (
              <span className="text-xs px-2 py-0.5 rounded-full border border-slate-300 bg-white text-slate-600">
                Replay of a real Kane run recorded on the practice lab</span>
            )}
          </p>
        </div>
      </div>
      {inv.evidence && (
        <a href={`/api/investigations/${inv.id}/screenshots/last`} target="_blank" rel="noreferrer" className="block mt-3"
          aria-label="Open Kane's screenshot of the payment page">
          <img src={`/api/investigations/${inv.id}/screenshots/last`} alt="The payment page as Kane saw it, before paying"
            className="rounded-md border border-red-200 max-h-64 w-auto max-w-full bg-white" loading="lazy"
            onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none'; }} />
          <span className="text-xs text-slate-500">What Kane saw, where it stopped. It did not pay.</span>
        </a>
      )}
      {inv.evidence && <AllSteps inv={inv} />}
      <div className="mt-3 pt-3 border-t border-red-200 flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-700">Already paid this?</span>
        <button type="button" onClick={onPaid}
          className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700">I already paid</button>
      </div>
    </div>
  );
};

/** Kane finished but did not prove a payee. This must never read as "safe". */
const NotFound = ({ inv }: { inv: Investigation }) => {
  const skipped = inv.status === 'skipped';
  const Icon = skipped ? CircleSlash : AlertTriangle;
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 sm:p-4">
      <div className="flex items-start gap-3">
        <Icon size={20} className="mt-0.5 shrink-0 text-amber-700" aria-hidden />
        <div className="min-w-0 space-y-1.5 text-sm text-slate-800">
          <p className="text-base font-bold text-slate-900">{noPayeeLine(inv)}</p>
          <p className="font-semibold">{NOT_SAFE}</p>
          {inv.reason && <p className="text-slate-600">Kane's note: {inv.reason}</p>}
        </div>
      </div>
    </div>
  );
};

const LinkRow = ({ url, check, scamType, onCheck, onPaid, now }: {
  url: string; check?: LinkCheck; scamType: string; onCheck: (url: string) => void; onPaid: () => void; now: number;
}) => {
  const inv = check?.inv || null;
  const busy = !!check?.starting || working(inv);
  const live = check?.starting ? 'Sending the link to Kane.'
    : inv?.status === 'queued' ? 'Waiting for the test browser.'
      : inv?.status === 'running' ? 'Kane is opening the link.'
        : inv ? 'Kane has finished. ' + answerLine(inv) : check?.error ? check.error : '';
  return (
    <li className="rounded-xl border border-slate-200 p-3 sm:p-4">
      <div className="text-xs font-semibold uppercase text-slate-500">Link in the message</div>
      <div className="mt-0.5 text-sm font-mono text-slate-800 break-all">{url}</div>
      <p className="sr-only" aria-live="polite">{live}</p>
      {!check && (
        <button type="button" onClick={() => onCheck(url)} aria-label={'Check who gets the money: ' + url}
          className="mt-3 w-full sm:w-auto px-4 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold inline-flex items-center justify-center gap-2 hover:bg-blue-700">
          <Search size={16} aria-hidden /> Check who gets the money
        </button>
      )}
      {check?.error && !busy && (
        <div className="mt-3">
          <p role="alert" className="text-sm text-red-700">{check.error}</p>
          <button type="button" onClick={() => onCheck(url)} aria-label={'Try again: ' + url}
            className="mt-2 px-3 py-2 rounded-lg border border-slate-300 text-sm font-medium hover:bg-slate-50">Try again</button>
        </div>
      )}
      {busy && (
        <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 flex items-start gap-3">
          <Loader2 size={20} className="mt-0.5 shrink-0 text-blue-600 animate-spin" aria-hidden />
          <div className="text-sm text-slate-800 space-y-1">
            <p className="font-semibold">{check?.starting ? 'Sending the link to Kane...'
              : inv?.status === 'queued' ? 'Waiting for the test browser. Kane opens one link at a time.'
                : 'Kane is opening the link in a test browser, as a first-time visitor.'}</p>
            <p>It will stop at the payment page and will not pay. This usually takes one to two minutes.</p>
            {check && <p className="text-xs text-slate-500" aria-hidden>Working for {elapsed(now - check.askedAt)}</p>}
          </div>
        </div>
      )}
      {inv && !working(inv) && (
        <div className="mt-3 space-y-3">
          {proved(inv) ? <Found inv={inv} scamType={scamType} onPaid={onPaid} /> : <NotFound inv={inv} />}
          <details>
            <summary className="cursor-pointer text-xs font-medium text-slate-500">Kane's technical report</summary>
            <div className="mt-2"><KaneCard inv={inv} /></div>
          </details>
        </div>
      )}
    </li>
  );
};

/**
 * Before you pay: the person sends a link from the message to Kane, which opens it in a test browser as a first-time
 * visitor, stops at the payment page and says who would get the money. App files are never opened.
 */
export const BeforeYouPay = ({ result, checks, onCheck, onPaid }: {
  result: CheckResult; checks: Record<string, LinkCheck>; onCheck: (url: string) => void; onPaid: () => void;
}) => {
  const now = useNow(Object.values(checks).some((c) => c.starting || working(c.inv)));
  const payees = result.verdict === 'scam' ? result.intel.filter((i) => i.kind === 'upi' || i.kind === 'bank_account') : [];
  const nothing = !result.links.length && !result.links_not_opened.length && !result.apks.length;
  return (
    <div className="space-y-3">
      {result.links.length > 0 && (
        <p className="text-sm text-slate-700">
          Kane can open the link for you in a separate test browser and show who would get the money. It uses made-up
          details, never yours. It stops at the payment page: it never pays, never types a PIN, OTP or card number, and
          never downloads anything.
        </p>
      )}
      {nothing && payees.length === 0 && <p className="text-sm text-slate-500">This message has no link, so there is nothing for Kane to open.</p>}
      <ul className="space-y-3" aria-label="Links in the message">
        {result.links.map((url) => (
          <LinkRow key={url} url={url} check={checks[url]} scamType={result.scam_type} onCheck={onCheck} onPaid={onPaid} now={now} />
        ))}
        {result.links_not_opened.map((l) => (
          <li key={l.url} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-start gap-3">
              <Ban size={20} className="mt-0.5 shrink-0 text-slate-500" aria-hidden />
              <div className="min-w-0 text-sm text-slate-800 space-y-1">
                <div className="font-mono break-all">{l.url}</div>
                <p className="font-semibold">Kane did not open this link. {l.reason}</p>
                <p>{NOT_SAFE}</p>
              </div>
            </div>
          </li>
        ))}
        {result.apks.map((url) => (
          <li key={url} className="rounded-xl border border-red-200 bg-red-50 p-4">
            <div className="flex items-start gap-3">
              <Smartphone size={20} className="mt-0.5 shrink-0 text-red-600" aria-hidden />
              <div className="min-w-0 text-sm text-slate-800 space-y-1">
                <div className="font-mono break-all">{url}</div>
                <p className="font-bold text-red-800">This link downloads an app (an APK file). Do not install it.</p>
                <p>Kane never opens app files. An app from a link can take over your phone.</p>
              </div>
            </div>
          </li>
        ))}
        {payees.map((p) => (
          <li key={p.kind + p.value} className="rounded-xl border border-slate-200 p-4 flex items-start gap-3">
            <Wallet size={20} className="mt-0.5 shrink-0 text-slate-500" aria-hidden />
            <p className="min-w-0 text-sm text-slate-800">The message itself gives this {kindWord(p.kind)}:{' '}
              <strong className="font-mono break-words">{p.value}</strong>. Do not send money to it.</p>
          </li>
        ))}
      </ul>
    </div>
  );
};
