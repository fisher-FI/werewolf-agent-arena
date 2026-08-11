import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import Lobby from './pages/Lobby';
import Room from './pages/Room';
import Settings from './pages/Settings';
import './styles/global.css';

function Header() {
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path ? 'active' : '';

  return (
    <header className="app-header">
      <h1><Link to="/" style={{ color: 'inherit', textDecoration: 'none' }}>🐺 AI 狼人杀</Link></h1>
      <nav>
        <Link to="/" className={isActive('/')}>大厅</Link>
        <Link to="/settings" className={isActive('/settings')}>设置</Link>
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Header />
        <main className="app-content">
          <Routes>
            <Route path="/" element={<Lobby />} />
            <Route path="/room/:roomId" element={<Room />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
