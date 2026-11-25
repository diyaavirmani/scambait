import { useMemo } from 'react';
import { Download, ShieldAlert } from 'lucide-react';
import type { CaseData, Investigation } from '../lib/types';
import { CopyButton } from './CopyButton';

/** Plain names for each scam type, in English and Hindi. */
const TYPE: Record<string, [string, string]> = {
  kyc_phishing: ['Fake KYC update', 'नकली KYC अपडेट'],
  delivery_phishing: ['Fake parcel or delivery fee', 'नकली पार्सल या डिलीवरी शुल्क'],
  investment_trading: ['Fake investment or trading profits', 'नकली निवेश या ट्रेडिंग मुनाफ़ा'],
  job_task: ['Fake part-time job or online tasks', 'नकली पार्ट-टाइम जॉब या ऑनलाइन टास्क'],
  utility_bill: ['Fake electricity or gas bill', 'नकली बिजली या गैस बिल'],
  digital_arrest: ['Fake police or "digital arrest" call', 'नकली पुलिस या "डिजिटल अरेस्ट" कॉल'],
  lottery_prize: ['Fake lottery or prize', 'नकली लॉटरी या इनाम'],
  upi_collect: ['Fake UPI payment request', 'नकली UPI पेमेंट रिक्वेस्ट'],
  customer_care: ['Fake customer care number', 'नकली कस्टमर केयर नंबर'],
  loan_offer: ['Fake loan offer', 'नकली लोन ऑफ़र'],
  sextortion: ['Blackmail with photos or videos', 'फ़ोटो या वीडियो से ब्लैकमेल'],
};

/** Hide what could identify a person: mule account holders are often unwitting, so only the last 4 characters show. */
export const mask = (value: string) => (value.length <= 4 ? '****' : '****' + value.slice(-4));

/** The scammer's words with links, UPI IDs, emails and long numbers taken out. */
export function scrub(text: string): string {
  return text
    .replace(/\b(?:https?:\/\/|www\.)\S+/gi, '[link]')
    .replace(/[\w.+-]+@[\w.-]+/g, (m) => mask(m))
    .replace(/(?:\+?\d[\d -]{8,}\d)/g, (m) => mask(m.replace(/\D/g, '')))
    .replace(/\s+/g, ' ')
    .trim();
}

interface Card { en: string[]; hi: string[]; title: [string, string]; }

export function buildCard(cd: CaseData): Card {
  const title = TYPE[cd.case.scam_type] || ['Scam message', 'धोखाधड़ी वाला मैसेज'];
  const first = cd.messages.find((m) => m.role === 'scammer')?.text || '';
  const quote = scrub(first);
  const shortQuote = quote.length > 140 ? quote.slice(0, 137).trimEnd() + '...' : quote;
  const proof: Investigation | undefined = cd.investigations.find((i) => i.verdict === 'payment_request_found' && !i.replayed)
    || cd.investigations.find((i) => i.verdict === 'payment_request_found');
  const en = [`SCAM ALERT: ${title[0]}.`];
  const hi = [`सावधान: ${title[1]}।`];
  if (shortQuote) {
    en.push(`The message says: "${shortQuote}"`);
    hi.push(`मैसेज में लिखा है: "${shortQuote}"`);
  }
  if (proof) {
    const asks = proof.amount ? `Rs ${proof.amount}` : 'money';
    const asked = proof.asked_for.length ? ` and your ${proof.asked_for.join(', ')}` : '';
    en.push(`Its link pretends to be ${proof.claims_to_be || 'a real company'} and asks for ${asks}${asked}. `
      + `The money would go to an account ending in ${mask(proof.payee).slice(-4)}, not the company.`);
    hi.push(`इसका लिंक खुद को ${proof.claims_to_be || 'असली कंपनी'} बताता है और ${proof.amount ? proof.amount + ' रुपये' : 'पैसे'} माँगता है। `
      + `पैसा ${mask(proof.payee).slice(-4)} पर ख़त्म होने वाले खाते में जाएगा, कंपनी को नहीं।`);
  }
  en.push('Never share an OTP, PIN or card number. Real banks and companies never ask for them.');
  hi.push('OTP, PIN या कार्ड नंबर किसी को न बताएँ। असली बैंक और कंपनियाँ ये कभी नहीं माँगतीं।');
  en.push('If you already paid, call 1930 at once.');
  hi.push('अगर पैसे भेज दिए हैं, तो तुरंत 1930 पर कॉल करें।');
  return { en, hi, title };
}

const shareText = (c: Card) => [...c.en, '', ...c.hi, '', 'Checked by SCAM-BAIT, with Kane CLI.'].join('\n');

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  let line = '';
  for (const word of text.split(' ')) {
    const next = line ? line + ' ' + word : word;
    if (ctx.measureText(next).width > width && line) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

/** Draw the card as a 1080 x 1350 PNG (a portrait image that WhatsApp shows whole). */
function drawPng(c: Card): string {
  const W = 1080, H = 1350, pad = 72;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return '';
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#dc2626';
  ctx.fillRect(0, 0, W, 190);
  ctx.fillStyle = '#ffffff';
  ctx.font = 'bold 64px system-ui, sans-serif';
  ctx.fillText('SCAM ALERT  |  सावधान', pad, 118);
  let y = 270;
  const block = (lines: string[], size: number, color: string, gap: number) => {
    ctx.fillStyle = color;
    lines.forEach((text, i) => {
      ctx.font = `${i === 0 ? 'bold ' : ''}${i === 0 ? size + 6 : size}px system-ui, "Noto Sans Devanagari", sans-serif`;
      for (const l of wrap(ctx, text, W - pad * 2)) {
        ctx.fillText(l, pad, y);
        y += size * 1.35;
      }
      y += gap;
    });
  };
  block(c.en, 34, '#0f172a', 14);
  y += 24;
  ctx.fillStyle = '#e2e8f0';
  ctx.fillRect(pad, y - 30, W - pad * 2, 3);
  y += 30;
  block(c.hi, 34, '#0f172a', 14);
  ctx.fillStyle = '#64748b';
  ctx.font = '28px system-ui, sans-serif';
  ctx.fillText('Checked by SCAM-BAIT, with Kane CLI. Helpline: 1930, cybercrime.gov.in', pad, H - 60);
  return canvas.toDataURL('image/png');
}

/** A warning to forward to family groups, built from this case: what the message said and what Kane proved. */
export const WarningCard = ({ cd }: { cd: CaseData }) => {
  const card = useMemo(() => buildCard(cd), [cd]);
  const download = () => {
    const url = drawPng(card);
    if (!url) return;
    const a = document.createElement('a');
    a.href = url;
    a.download = `scam-alert-${cd.case.id}.png`;
    a.click();
  };
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-red-200 overflow-hidden" aria-label="Warning card preview">
        <div className="bg-red-600 text-white px-4 py-2.5 font-bold flex items-center gap-2">
          <ShieldAlert size={18} aria-hidden /> SCAM ALERT <span aria-hidden>|</span> <span lang="hi">सावधान</span>
        </div>
        <div className="p-4 grid gap-4 md:grid-cols-2 text-sm text-slate-800">
          <div className="space-y-1.5">{card.en.map((l, i) => <p key={i} className={i === 0 ? 'font-semibold' : ''}>{l}</p>)}</div>
          <div className="space-y-1.5" lang="hi">{card.hi.map((l, i) => <p key={i} className={i === 0 ? 'font-semibold' : ''}>{l}</p>)}</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <CopyButton text={shareText(card)} what="the warning text for WhatsApp" label="Copy for WhatsApp" primary />
        <button type="button" onClick={download}
          className="px-3 py-2 rounded-lg border border-slate-300 text-sm font-medium inline-flex items-center gap-1.5 hover:bg-slate-50">
          <Download size={15} aria-hidden /> Download image
        </button>
      </div>
      <p className="text-xs text-slate-500">Account numbers and phone numbers show only their last 4 characters: the account holder may be a victim too.</p>
    </div>
  );
};
