import { createContext, useContext, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { getAnalysis } from "../api.js";
import { friendlyErrorMessage } from "../errorMessages.js";

const WorkspaceContext = createContext(null);

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside Workspace");
  return ctx;
}

export default function Workspace() {
  const { owner, repo } = useParams();
  const [state, setState] = useState({ status: "loading", analysis: null, error: null });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading", analysis: null, error: null });
    getAnalysis(owner, repo)
      .then((analysis) => {
        if (!cancelled) setState({ status: "ready", analysis, error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ status: "error", analysis: null, error: err });
      });
    return () => {
      cancelled = true;
    };
  }, [owner, repo]);

  if (state.status === "loading") {
    return <p className="status">Loading {owner}/{repo}…</p>;
  }

  if (state.status === "error") {
    return (
      <div className="empty-state">
        <p className="error">{friendlyErrorMessage(state.error)}</p>
        <Link to={`/analyze?url=https://github.com/${owner}/${repo}`}>Analyze it now</Link>
      </div>
    );
  }

  return (
    <WorkspaceContext.Provider value={{ owner, repo, analysis: state.analysis }}>
      <div className="workspace">
        <div className="workspace-header">
          <h1>
            {owner}/{repo}
          </h1>
          <p className="workspace-meta">
            {state.analysis.file_count} files · {state.analysis.chunk_count} indexed chunks · commit{" "}
            {state.analysis.commit_sha.slice(0, 7)}
          </p>
        </div>
        <nav className="workspace-tabs">
          <NavLink to="overview">Overview</NavLink>
          <NavLink to="architecture">Architecture</NavLink>
          <NavLink to="explorer">Explorer + Chat</NavLink>
          <NavLink to="impact">Impact</NavLink>
        </nav>
        <div className="workspace-content">
          <Outlet />
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
