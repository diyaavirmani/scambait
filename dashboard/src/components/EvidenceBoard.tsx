import type { CaseData, Investigation } from '../lib/types';
import { isProven, norm, provenKeys } from '../lib/kane';
import { Empty } from './Layout';

const LABEL: Record<string, string> = {
  upi: 'UPI ID', bank_account: 'Bank account', ifsc: 'IFSC', phone: 'Phone', url: 'Link', apk: 'App file',
  name: 'Name', organisation: 'Claims to be', amount: 'Amount', reference_code: 'Code', email: 'Email', card: 'Card',
};

/** Intel the scammer only said (grey) next to intel Kane proved on the scam page (green). */
export const EvidenceBoard = ({ cd }: { cd: CaseData }) => {
  const keys = provenKeys(cd.investigations);
  const said = new Set(cd.intel.map((i) => i.kind + ':' + norm(i.kind, i.value)));
  const payeeKey = (inv: Investigation) => inv.payee_kind + ':' + norm(inv.payee_kind, inv.payee);
  // once each: a fresh-visit re-check often shows the same payee again
  const kaneOnly = cd.investigations.filter((inv, i, all) => inv.payee && inv.payee_kind
    && !said.has(payeeKey(inv)) && all.findIndex((o) => o.payee && payeeKey(o) === payeeKey(inv)) === i);
  const rows = [
    ...cd.intel.map((i) => ({ kind: i.kind, value: i.value, proven: isProven(i, keys), saidIt: true })),
    ...kaneOnly.map((inv) => ({ kind: inv.payee_kind, value: inv.payee, proven: true, saidIt: false })),
  ];
  if (rows.length === 0) return <Empty text="No identifiers yet" />;
  return (
    <ul className="space-y-2" aria-label="Evidence board">
      {rows.map((r) => (
        <li key={r.kind + r.value} className={`flex items-center justify-between gap-3 p-2.5 rounded-lg border text-sm ${r.proven ? 'bg-green-50 border-green-200' : 'bg-slate-50 border-slate-200'}`}>
          <span className="min-w-0">
            <span className="block text-[11px] uppercase font-semibold text-slate-500">{LABEL[r.kind] || r.kind}</span>
            <span className="font-mono text-slate-800 break-all">{r.value}</span>
          </span>
          <span className={`shrink-0 text-[10px] uppercase font-bold px-2 py-0.5 rounded border ${r.proven ? 'bg-green-100 text-green-800 border-green-300' : 'bg-white text-slate-500 border-slate-200'}`}>
            {r.proven ? (r.saidIt ? 'Said and proven' : 'Proven by Kane') : 'Said in chat'}
          </span>
        </li>
      ))}
    </ul>
  );
};
