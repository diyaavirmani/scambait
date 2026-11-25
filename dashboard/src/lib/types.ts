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
  report?: CaseReport | null;
  moderation?: string[];
}

/** The case report for 1930 / NCRP, written when a case closes. Identifiers are only ones said in chat or proven by Kane. */
export interface CaseReport {
  summary: string;
  scam_type: string;
  modus_operandi: string;
  key_points: string[];
  suspect_identifiers: { kind: string; value: string }[];
  risk: string;
  recommended_action: string;
  generated_by: string;
  generated_at: string;
}

export interface Msg { id: number; case_id: string; role: 'scammer' | 'persona'; text: string; ts: string; }

export interface Intel { kind: string; value: string; message_id?: number | null; first_seen?: string; proven?: boolean; }

/** One payee Kane proved on a link, at the visit that first showed it. */
export interface RotationPayee { payee: string; payee_kind: string; visit: number; investigation_id: number; }

/** The payee-rotation probe on one link (app/investigate/__init__.py, rotation_facts): Kane opened it again as a
 *  fresh first-time visitor and compared the payees. The same facts are on every run of the link, each with its own
 *  visit number (1 is the first run) and new_payee (this re-check showed a payee no earlier visit showed). */
export interface Rotation {
  first_id: number;
  rechecks: number[];
  payees: RotationPayee[];
  proven_visits: number;
  rotated: boolean;
  replayed: boolean;
  visit: number;
  new_payee: boolean;
}

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
  recheck_of?: number | null; // the first run of this link, on a fresh-visitor payee re-check
  rotation?: Rotation | null; // null until the link has a re-check
  created_at?: string;
  finished_at?: string | null;
}

export interface LabSite {
  key: string;
  brand: string;
  scam_type: string;
  path: string;
  lure: string;
  answer: { payee: string; amount: number; claims_to_be: string; payees?: string[] };
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
