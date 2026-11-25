import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { ExternalLink, FileText, Landmark, MessageSquareWarning, Phone, Plus, Trash2, X } from 'lucide-react';
import type { Investigation } from '../lib/types';
import { kindWord, proved, rs } from '../lib/linkcheck';
import { CopyButton } from './CopyButton';

/** The NCRP form rejects these characters in free text (same list as app/evidence_pack.py). */
const NCRP_BANNED = new Set(Array.from('#$@^*`\'~|!\u2018\u2019'));

export function ncrpText(text: string): string {
  return Array.from(text || '').filter((ch) => !NCRP_BANNED.has(ch)).join('').replace(/\s+/g, ' ').trim();
}

/** The value for a datetime-local input, in the browser's own time zone. */
export function localInput(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function readable(value: string): string {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

const INPUT = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
const LABEL = 'block text-sm font-semibold text-slate-700 mb-1';
const LINK_BTN = 'px-3 py-2 rounded-lg border border-slate-300 text-sm font-medium inline-flex items-center gap-1.5 hover:bg-slate-50';
const FILL = '(fill in)';

interface Payment { key: number; utr: string; bank: string; amount: string; when: string; }
interface Suspect { label: string; value: string; }

const SOURCE: Record<string, string> = {
  upi: 'UPI ID in the message', bank_account: 'Bank account in the message', phone: 'Phone number in the message',
  url: 'Link in the message', apk: 'App link in the message',
};

function suspects(invs: Investigation[], intel: { kind: string; value: string }[]): Suspect[] {
  const out: Suspect[] = [];
  const seen = new Set<string>();
  const add = (label: string, value: string) => {
    const k = (value || '').trim().toLowerCase();
    if (!k || seen.has(k)) return;
    seen.add(k);
    out.push({ label, value: value.trim() });
  };
  for (const inv of invs.filter(proved)) {
    add((kindWord(inv.payee_kind) || 'Account') + ' that the payment page asks you to pay (seen by Kane)', inv.payee);
    add('Website of that payment page', inv.url);
  }
  for (const i of intel) if (SOURCE[i.kind]) add(SOURCE[i.kind], i.value);
  return out;
}

function story(message: string, scamWords: string, invs: Investigation[]): string {
  const found = invs.filter(proved);
  if (!message && !found.length) return '';
  const parts: string[] = [];
  if (message) parts.push(`I received this message: "${message}".`);
  if (scamWords) parts.push(`It was ${scamWords}.`);
  parts.push('I paid money because of it. The payments are listed in the transaction details.');
  for (const inv of found) {
    parts.push(`The link in the message opens a page that claims to be ${inv.claims_to_be || 'a payment page'} and asks to pay `
      + `${rs(inv.amount) || 'money'} to the ${kindWord(inv.payee_kind) || 'account'} given in the suspect details. `
      + 'A test browser (Kane CLI, through SCAM-BAIT) recorded this page without paying.');
  }
  return ncrpText(parts.join(' '));
}

function paymentText(p: Payment, n: number): string {
  return `Payment ${n}: UTR or transaction ID ${p.utr.trim() || FILL}; bank or app ${p.bank.trim() || FILL}; `
    + `amount ${p.amount.trim() ? 'Rs ' + p.amount.trim() : FILL}; date and time ${readable(p.when) || FILL}`;
}

const Step = ({ n, title, icon: Icon, children }: { n: number; title: string; icon: typeof Phone; children: ReactNode }) => {
  const id = useId();
  return (
    <section aria-labelledby={id} className="pt-5 border-t border-slate-200">
      <h3 id={id} className="text-base font-bold text-slate-900 flex items-center gap-2">
        <span className="w-7 h-7 rounded-full bg-slate-900 text-white text-sm flex items-center justify-center shrink-0" aria-hidden>{n}</span>
        <Icon size={18} className="text-slate-500 shrink-0" aria-hidden /> {title}
      </h3>
      <div className="mt-3">{children}</div>
    </section>
  );
};

/** A copyable line in the draft: a label, the value and a copy button that names it. */
const Line = ({ label, value, what }: { label: string; value: string; what: string }) => (
  <li className="flex flex-col sm:flex-row sm:items-center gap-2 py-2 border-b border-slate-100 last:border-0">
    <div className="min-w-0 flex-1">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-mono text-slate-800 break-all">{value}</div>
    </div>
    <CopyButton text={value} what={what} />
  </li>
);

/** No money lost: a draft for reporting the message on Chakshu (Sanchar Saathi). Nothing is sent for the person. */
export const ChakshuDraft = ({ message }: { message: string }) => {
  const id = useId();
  const [sender, setSender] = useState('');
  const [body, setBody] = useState(message);
  const [when, setWhen] = useState(localInput());
  useEffect(() => { setBody(message); }, [message]);
  const all = () => ['Report for Chakshu on Sanchar Saathi. Check it, then submit it yourself.',
    'Sender: ' + (sender.trim() || FILL), 'Received on: ' + (readable(when) || FILL), 'Message: ' + (body.trim() || FILL)].join('\n');
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-700">
        You can still help stop this sender. Report the message on Chakshu, on the government's Sanchar Saathi website.
        Copy these details into the form and submit it yourself.
      </p>
      <div>
        <label htmlFor={id + 'sender'} className={LABEL}>Who sent it</label>
        <div className="flex flex-col sm:flex-row gap-2">
          <input id={id + 'sender'} value={sender} onChange={(e) => setSender(e.target.value)} className={INPUT}
            placeholder="The phone number, WhatsApp number or name it came from" />
          <CopyButton text={sender.trim()} what="who sent the message" />
        </div>
      </div>
      <div>
        <label htmlFor={id + 'when'} className={LABEL}>When it arrived</label>
        <div className="flex flex-col sm:flex-row gap-2">
          <input id={id + 'when'} type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className={INPUT} />
          <CopyButton text={readable(when)} what="when the message arrived" />
        </div>
      </div>
      <div>
        <label htmlFor={id + 'msg'} className={LABEL}>The message</label>
        <textarea id={id + 'msg'} value={body} onChange={(e) => setBody(e.target.value)} rows={3} className={INPUT}
          placeholder="Paste the message you received" />
        <div className="mt-2"><CopyButton text={body.trim()} what="the message" /></div>
      </div>
      <div className="flex flex-wrap gap-2">
        <CopyButton text={all} what="the whole Chakshu report" label="Copy the whole report" primary />
        <a href="https://sancharsaathi.gov.in" target="_blank" rel="noreferrer noopener" className={LINK_BTN}>
          <ExternalLink size={15} aria-hidden /> Open Sanchar Saathi (Chakshu)
        </a>
      </div>
    </div>
  );
};

/**
 * I already paid: the golden-hour steps, in order. Call 1930 first, then the bank, then a complaint draft for
 * cybercrime.gov.in that the person checks and submits. Nothing is ever filed for them.
 */
export const Rescue = ({ message, scamWords, invs, intel, canCheckLink, onClose }: {
  message: string; scamWords: string; invs: Investigation[]; intel: { kind: string; value: string }[];
  canCheckLink: boolean; onClose: () => void;
}) => {
  const id = useId();
  const titleId = id + 'title';
  const [when, setWhen] = useState(localInput());
  const auto = useMemo(() => story(message, scamWords, invs), [message, scamWords, invs]);
  const [what, setWhat] = useState(auto);
  const [edited, setEdited] = useState(false);
  useEffect(() => { if (!edited) setWhat(auto); }, [auto, edited]);
  const [payments, setPayments] = useState<Payment[]>([{ key: 1, utr: '', bank: '', amount: '', when: '' }]);
  const people = useMemo(() => suspects(invs, intel), [invs, intel]);

  const setPay = (key: number, patch: Partial<Payment>) => setPayments((ps) => ps.map((p) => (p.key === key ? { ...p, ...patch } : p)));
  const addPay = () => setPayments((ps) => [...ps, { key: Math.max(0, ...ps.map((p) => p.key)) + 1, utr: '', bank: '', amount: '', when: '' }]);
  const removePay = (key: number) => setPayments((ps) => (ps.length > 1 ? ps.filter((p) => p.key !== key) : ps));

  const draft = () => [
    'Complaint draft for cybercrime.gov.in. Check it, then submit it yourself on the portal.',
    'When it happened: ' + (readable(when) || FILL),
    'What happened: ' + (ncrpText(what) || FILL),
    'Suspect details:',
    ...(people.length ? people.map((s) => s.label + ': ' + s.value) : ['None known yet']),
    'Payments:',
    ...payments.map((p, i) => paymentText(p, i + 1)),
  ].join('\n');

  return (
    <section aria-labelledby={titleId} className="bg-white rounded-xl border border-red-200 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id={titleId} className="text-xl font-bold text-slate-900">I already paid: what to do now</h2>
          <p className="text-sm text-slate-600 mt-1">Do these steps in this order. The first hours matter most.</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close the steps for after paying"
          className="shrink-0 p-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"><X size={18} aria-hidden /></button>
      </div>

      <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4">
        <h3 className="text-lg font-bold text-red-800">1. Call 1930 now</h3>
        <p className="mt-1 text-sm text-slate-800">
          1930 is the national cyber fraud helpline (free, 24x7). Your money can only be frozen if it is reported fast, so
          call before you do anything else.
        </p>
        <a href="tel:1930" className="mt-3 w-full sm:w-auto px-6 py-4 rounded-xl bg-red-600 text-white text-lg font-bold inline-flex items-center justify-center gap-2 hover:bg-red-700">
          <Phone size={22} aria-hidden /> Call 1930 now
        </a>
        <p className="mt-2 text-xs text-slate-600">If the call does not get through, file the complaint at cybercrime.gov.in (step 3).</p>
      </div>

      <div className="mt-5 space-y-5">
        <Step n={2} title="Call your bank" icon={Landmark}>
          <ul className="list-disc pl-5 space-y-1.5 text-sm text-slate-800">
            <li>Use only the number printed on your card or shown in your bank's own app.</li>
            <li>Never use a number from a search result or a message. Scammers put up fake helpline numbers.</li>
            <li>Ask them to block your card or UPI, and to raise a fraud dispute for each payment.</li>
            <li>Write down the complaint number they give you.</li>
          </ul>
        </Step>

        <Step n={3} title="Complaint draft for cybercrime.gov.in" icon={FileText}>
          <p className="text-sm text-slate-700">
            The portal asks for these details. Fill in what you know, copy each part into the form, and submit it
            yourself. Nothing is filed for you. Keep your mobile phone (for an OTP) and an ID card ready.
          </p>
          <div className="mt-4 space-y-5">
            <div>
              <label htmlFor={id + 'when'} className={LABEL}>When it happened</label>
              <div className="flex flex-col sm:flex-row gap-2">
                <input id={id + 'when'} type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className={INPUT} />
                <CopyButton text={readable(when)} what="when it happened" />
              </div>
              <p className="mt-1 text-xs text-slate-500">Change it if it happened earlier.</p>
            </div>

            <div>
              <label htmlFor={id + 'what'} className={LABEL}>What happened</label>
              <textarea id={id + 'what'} value={what} rows={5} className={INPUT}
                onChange={(e) => { setWhat(e.target.value); setEdited(true); }}
                placeholder="Say who contacted you, what they said and how you paid. For example: I got an SMS saying my KYC was pending. I opened the link and paid by UPI." />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <CopyButton text={() => ncrpText(what)} what="what happened" />
                <span className="text-xs text-slate-500">The portal does not accept symbols such as @, # and !, so they are left out when you copy.</span>
              </div>
            </div>

            <div>
              <h4 className={LABEL}>Who got the money, and where it came from</h4>
              {people.length > 0 ? (
                <ul aria-label="Suspect details">{people.map((s) => <Line key={s.value} label={s.label} value={s.value} what={s.label} />)}</ul>
              ) : (
                <p className="text-sm text-slate-600">Nothing known yet. Add the UPI ID or account number shown in your bank SMS or payment app.</p>
              )}
              {canCheckLink && !invs.some(proved) && (
                <p className="mt-2 text-sm text-slate-600">Tip: press "Check who gets the money" under the message check, and Kane adds the account the link pays.</p>
              )}
            </div>

            <div>
              <h4 className={LABEL}>Your payments</h4>
              <p className="text-xs text-slate-500 mb-2">
                One row for each payment. The UTR is the 12-digit number in your bank SMS or in the payment details in your UPI app.
              </p>
              <ol className="space-y-3">
                {payments.map((p, i) => {
                  const n = i + 1;
                  const short = /^\d+$/.test(p.utr.trim()) && p.utr.trim().length !== 12;
                  return (
                    <li key={p.key} className="rounded-xl border border-slate-200 p-3">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <span className="text-sm font-semibold text-slate-800">Payment {n}</span>
                        {payments.length > 1 && (
                          <button type="button" onClick={() => removePay(p.key)} aria-label={'Remove payment ' + n}
                            className="px-2 py-1 rounded-lg border border-slate-200 text-xs text-slate-600 inline-flex items-center gap-1 hover:bg-slate-50">
                            <Trash2 size={13} aria-hidden /> Remove
                          </button>
                        )}
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label htmlFor={`${id}utr${p.key}`} className={LABEL}>UTR or transaction ID</label>
                          <input id={`${id}utr${p.key}`} value={p.utr} onChange={(e) => setPay(p.key, { utr: e.target.value })} className={INPUT}
                            autoComplete="off" />
                          {short && <p className="mt-1 text-xs text-slate-500">A UTR usually has 12 digits. Check your bank SMS.</p>}
                        </div>
                        <div>
                          <label htmlFor={`${id}bank${p.key}`} className={LABEL}>Bank or app you paid from</label>
                          <input id={`${id}bank${p.key}`} value={p.bank} onChange={(e) => setPay(p.key, { bank: e.target.value })} className={INPUT}
                            placeholder="For example: your bank's name or UPI app" />
                        </div>
                        <div>
                          <label htmlFor={`${id}amt${p.key}`} className={LABEL}>Amount (Rs)</label>
                          <input id={`${id}amt${p.key}`} value={p.amount} inputMode="decimal" onChange={(e) => setPay(p.key, { amount: e.target.value })}
                            className={INPUT} />
                        </div>
                        <div>
                          <label htmlFor={`${id}at${p.key}`} className={LABEL}>Date and time</label>
                          <input id={`${id}at${p.key}`} type="datetime-local" value={p.when} onChange={(e) => setPay(p.key, { when: e.target.value })}
                            className={INPUT} />
                        </div>
                      </div>
                      <div className="mt-3"><CopyButton text={() => paymentText(p, n)} what={'payment ' + n} label={'Copy payment ' + n} /></div>
                    </li>
                  );
                })}
              </ol>
              <button type="button" onClick={addPay}
                className="mt-3 px-3 py-2 rounded-lg border border-slate-300 text-sm font-medium inline-flex items-center gap-1.5 hover:bg-slate-50">
                <Plus size={15} aria-hidden /> Add another payment
              </button>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              <CopyButton text={draft} what="the whole complaint draft" label="Copy the whole draft" primary />
              <a href="https://cybercrime.gov.in" target="_blank" rel="noreferrer noopener" className={LINK_BTN}>
                <ExternalLink size={15} aria-hidden /> Open cybercrime.gov.in
              </a>
            </div>
          </div>
        </Step>

        <p className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-800">
          New RBI rules for frauds from 1 Jan 2027: on losses up to Rs 50,000, you can get part of the money back only if
          you report to both your bank and 1930 or cybercrime.gov.in within 5 days. So do both today.
        </p>

        <section aria-labelledby={id + 'nolost'} className="pt-5 border-t border-slate-200">
          <h3 id={id + 'nolost'} className="text-base font-semibold text-slate-900 flex items-center gap-2">
            <MessageSquareWarning size={18} className="text-slate-500" aria-hidden /> No money lost?
          </h3>
          <div className="mt-3"><ChakshuDraft message={message} /></div>
        </section>
      </div>
    </section>
  );
};
