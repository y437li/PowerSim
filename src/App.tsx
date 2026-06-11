import { Routes, Route, NavLink } from "react-router-dom";
import SiteView from "./routes/SiteView";
import TrainingPanel from "./routes/TrainingPanel";
import { EvalComparison } from "./routes/EvalComparison";
import { ErrorBoundary } from "./components/ErrorBoundary";

// App has NO BrowserRouter — the router is in main.tsx (or MemoryRouter in tests).
// Direct imports (not React.lazy) so tests can render synchronously.
export default function App() {
  return (
    <div className="app">
      <nav className="app__nav">
        <NavLink to="/" end className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
          Site View
        </NavLink>
        <NavLink to="/training" className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
          Training
        </NavLink>
        <NavLink to="/eval" className={({ isActive }) => isActive ? "nav-link nav-link--active" : "nav-link"}>
          Eval
        </NavLink>
      </nav>

      <main className="app__main">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<SiteView />} />
            <Route path="/training" element={<TrainingPanel />} />
            <Route path="/eval" element={<EvalComparison />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}

function NotFound() {
  return (
    <div className="not-found" data-testid="not-found">
      <h1>404 Not Found</h1>
      <p>The page you are looking for does not exist.</p>
    </div>
  );
}
