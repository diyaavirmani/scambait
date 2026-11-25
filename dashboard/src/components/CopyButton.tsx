import { useEffect, useState } from 'react';
import { ClipboardCopy } from 'lucide-react';

/** Copy to the clipboard; falls back to a hidden text box where the Clipboard API is missing (plain http). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall back below */ }
  const active = document.activeElement as HTMLElement | null;
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  } finally {
    active?.focus();
  }
}

/** A copy button that says what it copies, and tells screen readers when it has. */
export const CopyButton = ({ text, what, label = 'Copy', primary = false }: {
  text: string | (() => string); what: string; label?: string; primary?: boolean;
}) => {
  const [state, setState] = useState<'idle' | 'copied' | 'failed' | 'empty'>('idle');
  useEffect(() => {
    if (state === 'idle') return;
    const t = window.setTimeout(() => setState('idle'), 2500);
    return () => window.clearTimeout(t);
  }, [state]);

  async function copy() {
    const value = typeof text === 'function' ? text() : text;
    if (!value.trim()) { setState('empty'); return; }
    setState((await copyText(value)) ? 'copied' : 'failed');
  }

  const tone = primary ? 'bg-slate-900 text-white border-slate-900 hover:bg-slate-800' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50';
  return (
    <>
      <button type="button" onClick={copy} aria-label={'Copy ' + what}
        className={`shrink-0 self-start sm:self-auto px-3 py-2 rounded-lg border text-sm font-medium inline-flex items-center gap-1.5 ${tone}`}>
        <ClipboardCopy size={15} aria-hidden /> {state === 'copied' ? 'Copied' : state === 'failed' ? 'Could not copy' : state === 'empty' ? 'Nothing to copy yet' : label}
      </button>
      <span className="sr-only" aria-live="polite">
        {state === 'copied' ? 'Copied ' + what : state === 'failed' ? 'Could not copy ' + what + '. Select the text and copy it by hand.'
          : state === 'empty' ? 'Nothing to copy yet: ' + what + ' is empty.' : ''}
      </span>
    </>
  );
};
