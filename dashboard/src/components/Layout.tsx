import type { ReactNode } from 'react';
import { FlaskConical, FolderSearch, LayoutDashboard, MessageSquareWarning, Search, ShieldAlert } from 'lucide-react';
import { useConnected } from '../lib/live';

export const NAV = [
  { path: '/check', label: 'Check a Message', icon: Search },
  { path: '/console', label: 'Scam Console', icon: MessageSquareWarning },
  { path: '/cases', label: 'Cases', icon: FolderSearch },
  { path: '/overview', label: 'Overview', icon: LayoutDashboard },
];

export const Layout = ({ path, navigate, children }: { path: string; navigate: (p: string) => void; children: ReactNode }) => {
  const connected = useConnected();
  const link = (p: string, label: string, Icon: typeof Search, compact = false) => (
    <a key={p} href={p} onClick={(e) => { e.preventDefault(); navigate(p); }} aria-current={path === p ? 'page' : undefined}
      className={`flex items-center gap-2.5 rounded-lg text-sm font-medium transition-colors ${compact ? 'px-3 py-2 shrink-0' : 'px-3 py-2.5'} ${
        path === p ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}`}>
      <Icon size={17} aria-hidden /> {label}
    </a>
  );
  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden lg:flex lg:w-60 lg:flex-col lg:fixed lg:inset-y-0 bg-white border-r border-slate-200">
        <div className="px-5 py-5 flex items-center gap-2.5 border-b border-slate-100">
          <span className="w-8 h-8 rounded-lg bg-red-600 text-white flex items-center justify-center"><ShieldAlert size={18} aria-hidden /></span>
          <span className="font-bold tracking-tight">SCAM-BAIT</span>
        </div>
        <nav className="flex-1 p-3 space-y-1" aria-label="Main">
          {NAV.map((n) => link(n.path, n.label, n.icon))}
          <a href="/lab" className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-600 hover:bg-slate-100">
            <FlaskConical size={17} aria-hidden /> Practice Lab
          </a>
        </nav>
        <div className="p-4 border-t border-slate-100 text-xs text-slate-500 flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-slate-300'}`} aria-hidden />
          {connected ? 'Live' : 'Connecting'}
        </div>
      </aside>
      <header className="lg:hidden sticky top-0 z-10 bg-white border-b border-slate-200">
        <div className="px-4 py-3 flex items-center gap-2 font-bold"><ShieldAlert size={18} className="text-red-600" aria-hidden /> SCAM-BAIT</div>
        <nav className="px-2 pb-2 flex gap-1 overflow-x-auto" aria-label="Main">{NAV.map((n) => link(n.path, n.label, n.icon, true))}</nav>
      </header>
      <main className="flex-1 lg:ml-60 min-w-0">
        <div className="max-w-6xl mx-auto px-4 py-6 lg:px-8 lg:py-8">{children}</div>
      </main>
    </div>
  );
};

export const PageHeader = ({ title, subtitle }: { title: string; subtitle: string; connected?: boolean }) => (
  <div className="mb-6">
    <h1 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
    <p className="text-slate-600 mt-1 text-sm max-w-3xl">{subtitle}</p>
  </div>
);

export const Panel = ({ title, right, children, className = '' }: { title?: string; right?: ReactNode; children: ReactNode; className?: string }) => (
  <section className={`bg-white rounded-xl border border-slate-200 p-5 ${className}`}>
    {title && (
      <div className="flex justify-between items-center gap-3 mb-4">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
        {right}
      </div>
    )}
    {children}
  </section>
);

export const Empty = ({ text }: { text: string }) => (
  <div className="py-8 text-center text-sm text-slate-500">{text}</div>
);

export const VerdictBadge = ({ verdict }: { verdict: string }) => {
  const tone = verdict === 'scam' ? 'bg-red-50 text-red-700 border-red-200'
    : verdict === 'not_scam' ? 'bg-green-50 text-green-700 border-green-200' : 'bg-slate-50 text-slate-500 border-slate-200';
  return <span className={`text-[11px] uppercase font-bold px-2 py-0.5 rounded border ${tone}`}>{verdict === 'not_scam' ? 'not a scam' : verdict}</span>;
};
