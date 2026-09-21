import { useState } from "react";
import { Link } from "react-router-dom";
import { getImpact } from "../api.js";
import { friendlyErrorMessage } from "../errorMessages.js";
import { useWorkspace } from "../pages/Workspace.jsx";

export default function ImpactTab() {
  const { owner, repo } = useWorkspace();
  const [symbol, setSymbol] = useState("");
  const [state, setState] = useState({ status: "idle", result: null, error: null });

  async function handleSubmit(e) {
    e.preventDefault();
    if (!symbol.trim()) return;
    setState({ status: "loading", result: null, error: null });
    try {
      const result = await getImpact(owner, repo, symbol.trim());
      setState({ status: "ready", result, error: null });
    } catch (err) {
      setState({ status: "error", result: null, error: err });
    }
  }

  return (
    <div className="impact-tab">
      <p className="tab-intro">
        Deterministic graph traversal, no LLM involved — enter a function, method, class, or file path to see
        what depends on it.
      </p>
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="e.g. validate_token, MyClass, utils.py"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          required
        />
        <button type="submit" disabled={state.status === "loading"}>
          {state.status === "loading" ? "Analyzing…" : "Show impact"}
        </button>
      </form>

      {state.status === "error" && (
        <p className="error">
          {state.error.status === 404
            ? `No function, class, or file named "${symbol}" was found.`
            : friendlyErrorMessage(state.error)}
        </p>
      )}

      {state.status === "ready" && (
        <div className="impact-result">
          <h3>
            Changing:{" "}
            {state.result.targets.map((t) => (
              <code key={t.qualified_name}>
                {t.qualified_name} ({t.file}:{t.start_line})
              </code>
            ))}
          </h3>

          {state.result.affected.length === 0 ? (
            <p className="empty-state">No call sites depend on this.</p>
          ) : (
            <>
              <p>{state.result.affected.length} affected call site(s):</p>
              <ul className="impact-list">
                {state.result.affected.map((a) => (
                  <li key={a.qualified_name}>
                    <Link
                      to={`../explorer?file=${encodeURIComponent(a.file)}&line=${a.start_line}`}
                      relative="path"
                    >
                      {a.qualified_name} ({a.file}:{a.start_line})
                    </Link>{" "}
                    <span className="impact-via">[{a.via}]</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
