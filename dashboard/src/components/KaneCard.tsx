import { CheckCircle2, CircleSlash, Loader2, AlertTriangle, Shuffle } from 'lucide-react';
import type { Investigation } from '../lib/types';
import { isRecheck, isRunning, rupees, shortUrl, statusText } from '../lib/kane';

const BADGE = 'ml-2 inline-block whitespace-nowrap align-middle text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded bg-white border border-slate-300 text-slate-600';

/** The payee-rotation probe on this card's link: which payees Kane saw when it opened the link as fresh visitors. */
const RotationNote = ({ inv }: { inv: Investigation }) => {
  const rot = inv.rotation;
  if (!rot) return null;
  if (!rot.rotated) {
    if (rot.proven_visits < 2 || inv.verdict !== 'payment_request_found') return null;
    return <p className="mt-2 text-xs text-slate-600">{isRecheck(inv) ? 'Same payee as on the first visit.'
      : `Opened again as a new visitor: same payee${rot.proven_visits > 2 ? ` on all ${rot.proven_visits} visits` : ''}.`}</p>;
  }
  return (
    <div role="note" aria-label="Payee changed on a fresh visit" className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-2.5">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-amber-900"><Shuffle size={15} aria-hidden /> Payee changed on a fresh visit</div>
      <p className="mt-0.5 text-xs text-amber-800">Kane opened this link again as a new first-time visitor and the page named someone else to pay. Payees Kane saw:</p>
      <ul className="mt-1.5 space-y-1" aria-label="Payees Kane saw on this link">
        {rot.payees.map((p) => (
          <li key={p.investigation_id} className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <span className="w-14 shrink-0 text-[11px] text-amber-800">Visit {p.visit}</span>
            <span className="font-mono font-semibold text-slate-800 break-all">{p.payee}</span>
            {p.investigation_id === inv.id && <span className="text-[10px] uppercase text-amber-700">this run</span>}
          </li>
        ))}
      </ul>
    </div>
  );
};

/** One Kane investigation: live while Kane works, then what the scam page itself proved. */
export const KaneCard = ({ inv }: { inv: Investigation }) => {
  const running = isRunning(inv);
  const recheck = isRecheck(inv);
  const proven = inv.verdict === 'payment_request_found';
  const skipped = inv.status === 'skipped';
  const unsafe = inv.verdict === 'unsafe_run';
  const tone = running ? 'border-blue-200 bg-blue-50' : unsafe ? 'border-red-300 bg-red-50' : proven ? 'border-green-200 bg-green-50'
    : skipped ? 'border-slate-200 bg-slate-50' : 'border-amber-200 bg-amber-50';
  const Icon = running ? Loader2 : proven ? CheckCircle2 : skipped ? CircleSlash : AlertTriangle;
  const iconTone = running ? 'text-blue-600 animate-spin' : unsafe ? 'text-red-600' : proven ? 'text-green-600' : skipped ? 'text-slate-400' : 'text-amber-600';
  return (
    <section role="status" aria-label={(recheck ? 'Kane fresh-visit re-check of ' : 'Kane investigation of ') + inv.url} className={`rounded-lg border p-4 ${tone}`}>
      <div className="flex items-start gap-3">
        <Icon size={20} className={`mt-0.5 shrink-0 ${iconTone}`} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold text-slate-800">{statusText(inv)}
            {recheck && <span className={BADGE} title="Kane opened the same link again as a new first-time visitor, to see whether the page names someone else to pay">fresh-visit re-check{inv.rotation?.visit ? `, visit ${inv.rotation.visit}` : ''}</span>}
            {inv.replayed && <span className={BADGE} title="This server has no browser, so it replays a real Kane CLI run recorded from the practice lab">replay of a real Kane run</span>}</div>
          <div className="text-xs font-mono text-slate-500 break-all" title={inv.url}>{shortUrl(inv.url, 64)}</div>
        </div>
      </div>
      {proven && (
        <dl className="mt-3 grid grid-cols-3 gap-x-3 gap-y-1.5 text-sm">
          {inv.claims_to_be && (<><dt className="text-slate-500">Pretends to be</dt><dd className="col-span-2 font-medium text-slate-800">{inv.claims_to_be}</dd></>)}
          <dt className="text-slate-500">Money goes to</dt>
          <dd className="col-span-2 font-mono font-semibold text-green-800 break-all" aria-label="Proven payee">{inv.payee}
            <span className="ml-2 text-[10px] font-sans uppercase text-green-700">{inv.payee_kind === 'bank_account' ? 'bank account' : inv.payee_kind}</span></dd>
          {inv.amount && (<><dt className="text-slate-500">Amount</dt><dd className="col-span-2 font-semibold text-slate-800">{rupees(inv.amount)}</dd></>)}
          {inv.asked_for?.length > 0 && (<><dt className="text-slate-500">Asked for</dt>
            <dd className="col-span-2 flex flex-wrap gap-1">{inv.asked_for.map((a) => (
              <span key={a} className="text-xs px-2 py-0.5 rounded-full bg-white border border-green-200 text-slate-700">{a}</span>))}</dd></>)}
        </dl>
      )}
      <RotationNote inv={inv} />
      {proven && inv.evidence && (
        <a href={`/api/investigations/${inv.id}/screenshots/last`} target="_blank" rel="noreferrer" className="block mt-3"
          aria-label="Open Kane's screenshot of the payment page">
          <img src={`/api/investigations/${inv.id}/screenshots/last`} alt="Kane's screenshot of the page where it stopped, before paying"
            className="rounded-md border border-green-200 max-h-56 w-auto bg-white" loading="lazy"
            onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none'; }} />
          <span className="text-[11px] text-slate-500">Kane's screenshot where it stopped, before paying</span>
        </a>
      )}
      {!running && !proven && inv.reason && <p className="mt-2 text-sm text-slate-600">{inv.reason}</p>}
      {!running && !skipped && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
          {inv.steps && <span>{inv.steps.length} steps</span>}
          {typeof inv.duration_s === 'number' && <span>{Math.round(inv.duration_s)} s</span>}
          {typeof inv.credits === 'number' && <span>{Math.round(inv.credits)} credits</span>}
          {inv.evidence_sha256 && <span className="font-mono" title={inv.evidence_sha256}>evidence sha256 {inv.evidence_sha256.slice(0, 12)}</span>}
        </div>
      )}
    </section>
  );
};
