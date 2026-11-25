import type { Investigation } from './types';

/** A link in the checked message that Kane will not open here, with the reason in plain words. */
export interface LinkNotOpened { url: string; reason: string; }

/** POST /api/check. Nothing is opened yet: `links` are the links the person can send to Kane. */
export interface CheckResult {
  verdict: 'scam' | 'not_scam' | 'unknown';
  headline: string;
  scam_type: string;
  scam_words: string; // for example "a fake KYC update scam", empty unless the verdict is scam
  risk: string;
  red_flags: string[];
  intel: { kind: string; value: string }[];
  links: string[];
  links_not_opened: LinkNotOpened[];
  apks: string[];
  advice: string[];
}

/** One link the person asked Kane to open (POST /api/check/link), followed live until Kane finishes. */
export interface LinkCheck {
  url: string;
  starting: boolean;
  error: string;
  inv: Investigation | null;
  askedAt: number; // Date.now() when the person pressed the button
}
