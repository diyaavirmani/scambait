export interface Ev {
  id: number | null;
  ts: string;
  case_id: string | null;
  channel: string;
  type: string;
  data: any;
}

export interface Case {
  id: string;
  channel: string;
  external_id: string;
  status: string; // open | closed
  verdict: string; // scam | not_scam | unknown
  scam_type: string;
  summary: string;
  created_at: string;
  updated_at: string;
  turns?: number;
}

export interface Msg { id: number; case_id: string; role: 'scammer' | 'persona'; text: string; ts: string; }

export interface Intel { kind: string; value: string; message_id?: number | null; first_seen?: string; proven?: boolean; }

/** One Kane CLI run on a link the scammer sent. */
export interface Investigation {
  id: number;
  case_id?: string | null;
  url: string;
  status: string; // queued | running | passed | failed | skipped | not_started | timeout | error
  verdict: string; // payment_request_found | no_payee_found | inconclusive | unsafe_run | skipped | ...
  claims_to_be: string;
  payee: string;
  payee_kind: string; // upi | bank_account | ''
  amount: string;
  asked_for: string[];
  summary: string;
  reason: string;
  steps?: { step: number; status: string; remark: string }[];
  credits?: number | null;
  duration_s?: number | null;
  evidence: boolean;
  evidence_sha256: string;
  unsafe_actions?: string[];
  replayed?: boolean;
  created_at?: string;
  finished_at?: string | null;
}

export interface LabSite {
  key: string;
  brand: string;
  scam_type: string;
  path: string;
  lure: string;
  answer: { payee: string; amount: number; claims_to_be: string };
}

export interface CaseData {
  case: Case;
  messages: Msg[];
  intel: Intel[];
  events: Ev[];
  evidence: { kind: string; sha256: string; created_at: string }[];
  investigations: Investigation[];
  related: { case_id: string; kind: string }[];
}
