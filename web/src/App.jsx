import { Link, Outlet } from "react-router-dom";
import { ApiKeyProvider } from "./ApiKeyContext.jsx";

export default function App() {
  return (
    <ApiKeyProvider>
      <div className="app-shell">
        <header className="app-header">
          <Link to="/" className="brand">
            PathFinder
          </Link>
          <nav>
            <Link to="/analyze">Analyze a repository</Link>
            <Link to="/profile">Scan a GitHub profile</Link>
          </nav>
        </header>
        <main>
          <Outlet />
        </main>
      </div>
    </ApiKeyProvider>
  );
}
