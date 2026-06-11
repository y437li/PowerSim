import { useEffect } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import SiteView from "./routes/SiteView";
import TrainingPanel from "./routes/TrainingPanel";
import { EvalComparison } from "./routes/EvalComparison";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { telemetryWsClient, trainingWsClient } from "./clients/wsClientSingleton";
import { useTelemetryStore } from "./stores/telemetryStore";

// App has NO BrowserRouter — the router is in main.tsx (or MemoryRouter in tests).
// Direct imports (not React.lazy) so tests can render synchronously.
export default function App() {
  // Connect both WS clients on mount; disconnect on unmount.
  // Contract: contracts/frontend/app_integration.md §3
  // wsClient.connect() is idempotent (no-op if already connecting/connected),
  // so React 18 StrictMode's double-invocation is safe.
  useEffect(() => {
    telemetryWsClient.connect();
    trainingWsClient.connect();
    return () => {
      telemetryWsClient.disconnect();
      trainingWsClient.disconnect();
    };
  }, []);

  // runId advances with each new training session; use it as the ErrorBoundary
  // resetKey so the boundary self-heals on session advance.
  // Contract: contracts/frontend/error_boundary_reset_key.md §3
  const runId = useTelemetryStore((s) => s.runId);

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
        <ErrorBoundary resetKey={runId ?? ""}>
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
