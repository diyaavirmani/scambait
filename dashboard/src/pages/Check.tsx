import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AlertOctagon, CheckCircle2, ExternalLink, HelpCircle, LifeBuoy, Phone, Search } from 'lucide-react';
import type { Investigation, LabSite } from '../lib/types';
import type { CheckResult } from '../lib/check-types';
import { proved, rs, useLinkChecks } from '../lib/linkcheck';
import { PageHeader, Panel } from '../components/Layout';
import { BeforeYouPay } from '../components/BeforeYouPay';
import { CopyButton } from '../components/CopyButton';
import { ChakshuDraft, Rescue } from '../components/Rescue';

const LEGIT_SAMPLE = 'Your OTP for HDFC Bank login is 482913. Do not share it with anyone.';

function reportText(text: string, r: CheckResult, invs: Investigation[]): string {
  const lines = [
    'Suspicious message checked with SCAM-BAIT on ' + new Date().toLocaleString('en-IN'),
    'Verdict: ' + r.headline,
    'Message received: "' + text + '"',
  ];
  if (r.red_flags.length) lines.push('Red flags: ' + r.red_flags.join('; '));
  for (const inv of invs) {
    if (proved(inv)) {
      lines.push(`Link ${inv.url}: opened by Kane CLI in a real browser. The page pretends to be ${inv.claims_to_be || 'a payment page'}`
        + ` and asks to pay ${rs(inv.amount) || 'money'} to ${inv.payee}`
        + (inv.evidence_sha256 ? ` (evidence pack sha256 ${inv.evidence_sha256})` : '') + '.');
    } else {
      lines.push(`Link ${inv.url}: ${inv.reason || inv.status}`);
    }
  }
  for (const l of r.links_not_opened) lines.push(`Link ${l.url}: not opened. ${l.reason}`);
  for (const a of r.apks) lines.push(`App file ${a}: not opened (never install apps from messages).`);
  const ids = r.intel.filter((i) => ['upi', 'bank_account', 'phone', 'apk'].includes(i.kind));
  if (ids.length) lines.push('Identifiers in the message: ' + ids.map((i) => `${i.kind} ${i.value}`).join(', '));
  lines.push('Report at https://cybercrime.gov.in or call 1930.');
  return lines.join('\n');
}

/**
 * Anyone pastes a suspicious message. Before paying, Kane can open its link safely and show who would get the money.
 * After paying, the rescue steps put 1930 first, then the bank, then a complaint draft the person submits.
 */
export const Check = () => {
  const [text, setText] = useState('');
  const [checked, setChecked] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<CheckResult | null>(null);
  const [sites, setSites] = useState<LabSite[]>([]);
  const [rescue, setRescue] = useState(false);
  const kane = useLinkChecks();
  const rescueBox = useRef<HTMLDivElement>(null);
  const paidButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    fetch('/lab/api/sites').then((r) => r.json()).then((d) => setSites(d.sites || [])).catch(() => setSites([]));
  }, []);

  // Move to the rescue steps as soon as they open, wherever the person pressed "I already paid".
  useEffect(() => {
    if (!rescue || !rescueBox.current) return;
    rescueBox.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    rescueBox.current.focus({ preventScroll: true });
  }, [rescue]);

  function openRescue() {
    if (rescue) rescueBox.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setRescue(true);
  }

  function closeRescue() {
    setRescue(false);
    paidButton.current?.focus();
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const msg = text.trim();
    if (!msg || busy) return;
    setBusy(true); setError(''); setResult(null); kane.reset();
    try {
      const r = await fetch('/api/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: msg }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || 'Check failed (HTTP ' + r.status + ')');
      setChecked(msg); setResult(d);
    } catch (err: any) {
      setError(err?.message || 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  const tone = !result ? '' : result.verdict === 'scam' ? 'bg-red-50 border-red-200 text-red-800'
    : result.verdict === 'not_scam' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-amber-50 border-amber-200 text-amber-800';
  const VerdictIcon = !result ? HelpCircle : result.verdict === 'scam' ? AlertOctagon : result.verdict === 'not_scam' ? CheckCircle2 : HelpCircle;

  return (
    <div>
      <PageHeader title="Check a Message" subtitle="Got a worrying SMS or WhatsApp message? Paste it here. Before you pay, Kane can open its link for you, safely, and show who would get your money." />

      <div className="mb-6 rounded-xl border border-red-200 bg-white p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <p className="font-semibold text-slate-900">Already paid, or shared an OTP or PIN?</p>
          <p className="text-sm text-slate-600">Act now. Money can only be frozen if it is reported fast.</p>
        </div>
        <button ref={paidButton} type="button" onClick={openRescue} aria-expanded={rescue} aria-controls="rescue-steps"
          className="w-full sm:w-auto px-5 py-3 rounded-lg bg-red-600 text-white font-semibold inline-flex items-center justify-center gap-2 hover:bg-red-700">
          <LifeBuoy size={18} aria-hidden /> I already paid
        </button>
      </div>

      {rescue && (
        <div id="rescue-steps" ref={rescueBox} tabIndex={-1} className="mb-6 scroll-mt-28 focus:outline-none">
          <Rescue message={checked} scamWords={result?.scam_words || ''} invs={kane.invs} intel={result?.intel || []}
            canCheckLink={!!result?.links.length} onClose={closeRescue} />
        </div>
      )}

      <Panel>
        <form onSubmit={submit}>
          <label htmlFor="check-input" className="block text-sm font-semibold text-slate-700 mb-2">Paste the message you received</label>
          <textarea id="check-input" value={text} onChange={(e) => setText(e.target.value)} rows={4} maxLength={4000}
            placeholder="For example: Dear customer, your account will be blocked today. Update KYC now: ..."
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase text-slate-500 mr-1">Try an example:</span>
            {sites.map((s) => (
              <button key={s.key} type="button" aria-label={'Example scam message: ' + s.brand}
                onClick={() => setText(s.lure + ' ' + window.location.origin + s.path)}
                className="text-xs px-2.5 py-1 rounded-full border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100">{s.brand}</button>
            ))}
            <button type="button" aria-label="Example real bank message" onClick={() => setText(LEGIT_SAMPLE)}
              className="text-xs px-2.5 py-1 rounded-full border border-green-200 bg-green-50 text-green-700 hover:bg-green-100">A real bank OTP</button>
          </div>
          <button type="submit" disabled={busy || !text.trim()} aria-label="Check this message"
            className="mt-4 w-full sm:w-auto px-5 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold inline-flex items-center justify-center gap-2 disabled:opacity-50 hover:bg-blue-700">
            <Search size={16} aria-hidden /> {busy ? 'Checking...' : 'Check this message'}
          </button>
          {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
        </form>
      </Panel>

      {result && (
        <div className="mt-6 space-y-6">
          <div role="status" aria-label="Verdict" className={`rounded-xl border p-5 flex items-start gap-4 ${tone}`}>
            <VerdictIcon size={32} className="shrink-0" aria-hidden />
            <div>
              <div className="text-xl font-bold">{result.headline}</div>
              {result.verdict === 'scam' && <div className="text-sm mt-1">Type: {result.scam_type.replace(/_/g, ' ')}{result.risk && result.risk !== 'unknown' ? ', risk ' + result.risk : ''}</div>}
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Why">
              {result.red_flags.length === 0 ? <p className="text-sm text-slate-500">No common scam signs in the text.</p> : (
                <ul className="space-y-2" aria-label="Red flags">
                  {result.red_flags.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-slate-800"><span className="w-2 h-2 rounded-full bg-red-500 shrink-0" aria-hidden />{f}</li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Before you pay: who gets the money?">
              <BeforeYouPay result={result} checks={kane.checks} onCheck={kane.start} onPaid={openRescue} />
            </Panel>
          </div>
          <Panel title="What to do now">
            <ol className="list-decimal pl-5 space-y-1.5 text-sm text-slate-800">{result.advice.map((a) => <li key={a}>{a}</li>)}</ol>
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" onClick={openRescue}
                className="px-3 py-2 rounded-lg bg-red-600 text-white text-sm font-semibold inline-flex items-center gap-1.5 hover:bg-red-700">
                <LifeBuoy size={15} aria-hidden /> I already paid
              </button>
              <a href="tel:1930" className="px-3 py-2 rounded-lg border border-red-200 text-red-700 text-sm font-semibold inline-flex items-center gap-1.5 hover:bg-red-50">
                <Phone size={15} aria-hidden /> Call 1930
              </a>
              <CopyButton text={() => reportText(checked, result, kane.invs)} what="the report about this message" label="Copy the report" />
              <a href="https://cybercrime.gov.in" target="_blank" rel="noreferrer noopener"
                className="px-3 py-2 rounded-lg border border-slate-300 text-sm font-medium inline-flex items-center gap-1.5 hover:bg-slate-50">
                <ExternalLink size={15} aria-hidden /> Report at cybercrime.gov.in
              </a>
            </div>
          </Panel>
          {result.verdict !== 'not_scam' && !rescue && (
            <Panel title="No money lost? Report the message">
              <ChakshuDraft message={checked} />
            </Panel>
          )}
        </div>
      )}
    </div>
  );
};
