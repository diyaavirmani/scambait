import type { Case } from './types';

/** One identifier from GET /api/intel, with the case it came from. */
export interface IntelRow {
  id: number;
  case_id: string;
  kind: string;
  value: string;
  norm: string;
  message_id?: number | null;
  first_seen: string;
  scam_type: string;
  channel: string;
  proven: boolean;
}

/** An identifier that two or more cases in a network share. */
export interface NetworkShared { kind: string; value: string; case_count: number; }

/** One network from GET /api/networks: cases linked by a shared identifier. */
export interface ScamNetwork {
  network_id: string;
  case_ids: string[];
  shared: NetworkShared[];
  first_seen: string;
  last_seen: string;
  scam_types: string[];
}

/** GET /health. The server answers 503 with this same body when something is down. */
export interface Health {
  status: string; // ok | degraded
  database: boolean;
  brain: { ok: boolean; mode?: string; models?: string[]; error?: string };
  openai?: { configured: boolean; decisions_available: boolean; reason?: string };
}

/** The data of one scam.detected event. */
export interface Detection {
  stage?: string;
  verdict: string;
  p_scam?: number | null;
  p_cerebras?: number | null;
  p_decisions?: number | null;
  scam_type?: string;
  risk?: string;
  decided_by?: string;
  rule_score?: number | null;
  red_flags?: string[];
}

/** The data of one metrics.speed event, with the time it arrived. */
export interface SpeedSample {
  step: string;
  provider: string; // cerebras | openai
  model: string;
  ms: number;
  tokens_per_s?: number | null;
  ts: string;
}

/** One line of a call transcript: final once transcript.final arrives, partial while deltas are still coming. */
export interface TranscriptLine { speaker: string; text: string; final: boolean; ts: string; }

/** A case after case.updated has merged a call report into it. */
export type CaseWithReport = Case & { report?: unknown };
