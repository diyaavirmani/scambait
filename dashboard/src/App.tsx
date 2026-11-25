import { useEffect, useState } from 'react';
import { Layout, NAV } from './components/Layout';
import { Check } from './pages/Check';
import { Console } from './pages/Console';
import { Cases } from './pages/Cases';
import { Overview } from './pages/Overview';
import { LiveChats } from './pages/LiveChats';
import { Calls } from './pages/Calls';
import { Intelligence } from './pages/Intelligence';
import { Networks } from './pages/Networks';
import { System } from './pages/System';

function pathNow(): string {
  const p = window.location.pathname.replace(/\/+$/, '') || '/check';
  return NAV.some((n) => n.path === p) ? p : '/check';
}

export default function App() {
  const [path, setPath] = useState(pathNow());
  const [caseId, setCaseId] = useState<string | null>(new URLSearchParams(window.location.search).get('case'));
  useEffect(() => {
    const onPop = () => { setPath(pathNow()); setCaseId(new URLSearchParams(window.location.search).get('case')); };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const navigate = (p: string) => { window.history.pushState(null, '', p); setPath(p); setCaseId(null); };
  const openCase = (id: string) => { window.history.pushState(null, '', '/cases?case=' + id); setPath('/cases'); setCaseId(id); };
  return (
    <Layout path={path} navigate={navigate}>
      {path === '/check' && <Check />}
      {path === '/console' && <Console />}
      {path === '/cases' && <Cases selected={caseId} select={openCase} />}
      {path === '/overview' && <Overview openCase={openCase} />}
      {path === '/chats' && <LiveChats openCase={openCase} />}
      {path === '/calls' && <Calls openCase={openCase} />}
      {path === '/intel' && <Intelligence openCase={openCase} />}
      {path === '/networks' && <Networks openCase={openCase} />}
      {path === '/system' && <System />}
    </Layout>
  );
}
