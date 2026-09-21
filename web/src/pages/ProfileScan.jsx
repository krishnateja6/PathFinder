import { useState } from "react";
import { getProfileFeedback, scanProfile } from "../api.js";
import { useApiKeyContext } from "../ApiKeyContext.jsx";
import ApiKeyField from "../components/ApiKeyField.jsx";
import { friendlyErrorMessage } from "../errorMessages.js";

const BUCKETS = ["Products", "Projects", "Experiments"];

export default function ProfileScan() {
  const [username, setUsername] = useState("");
  const [state, setState] = useState({ status: "idle", repos: null, error: null });

  async function handleSubmit(e) {
    e.preventDefault();
    if (!username.trim()) return;
    setState({ status: "loading", repos: null, error: null });
    try {
      const result = await scanProfile(username.trim());
      setState({ status: "ready", repos: result.repos, error: null });
    } catch (err) {
      setState({ status: "error", repos: null, error: err });
    }
  }

  return (
    <div className="profile-scan">
      <h1>Scan a GitHub profile</h1>
      <p className="tab-intro">
        Scores each public, non-fork repo out of 100 from stars, recent activity, completeness (README, license,
        CI), and community engagement — deterministic, not an LLM guess. Deep AI feedback on any repo's README is
        available on demand below.
      </p>

      <form onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="GitHub username, e.g. octocat"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={state.status === "loading"}
          required
        />
        <button type="submit" disabled={state.status === "loading"}>
          {state.status === "loading" ? "Scanning…" : "Scan"}
        </button>
      </form>

      {state.status === "error" && (
        <p className="error">
          {state.error.code === "not_found" ? `No GitHub user named "${username}" was found.` : friendlyErrorMessage(state.error)}
        </p>
      )}

      {state.status === "ready" && (
        <>
          {state.repos.length === 0 ? (
            <p className="empty-state">This user has no public, non-fork repositories.</p>
          ) : (
            BUCKETS.map((bucket) => {
              const repos = state.repos.filter((r) => r.bucket === bucket);
              if (repos.length === 0) return null;
              return (
                <section key={bucket} className="bucket-section">
                  <h2>
                    {bucket} <span className="bucket-count">({repos.length})</span>
                  </h2>
                  <div className="repo-cards">
                    {repos.map((repo) => (
                      <RepoCard key={repo.full_name} repo={repo} />
                    ))}
                  </div>
                </section>
              );
            })
          )}
        </>
      )}
    </div>
  );
}

function RepoCard({ repo }) {
  const { apiKey } = useApiKeyContext();
  const [feedback, setFeedback] = useState({ status: "idle", text: null, error: null });
  const [showKeyField, setShowKeyField] = useState(false);

  async function handleDeepFeedback() {
    if (!apiKey.trim()) {
      setShowKeyField(true);
      return;
    }
    setFeedback({ status: "loading", text: null, error: null });
    try {
      const result = await getProfileFeedback(repo.full_name, apiKey.trim());
      setFeedback({ status: "ready", text: result.feedback, error: null });
    } catch (err) {
      setFeedback({ status: "error", text: null, error: err });
    }
  }

  return (
    <div className="repo-card">
      <div className="repo-card-header">
        <h3>{repo.name}</h3>
        <span className="repo-score">{repo.score}/100</span>
      </div>
      <ul className="factor-list">
        {Object.entries(repo.factors).map(([label, value]) => (
          <li key={label}>
            {label}: {value}
          </li>
        ))}
      </ul>

      {feedback.status === "idle" && (
        <button type="button" className="deep-feedback-btn" onClick={handleDeepFeedback}>
          Deep AI feedback
        </button>
      )}
      {showKeyField && feedback.status === "idle" && (
        <div className="inline-key-field">
          <ApiKeyField />
          <button type="button" onClick={handleDeepFeedback}>
            Get feedback
          </button>
        </div>
      )}
      {feedback.status === "loading" && <p className="status">Reviewing README…</p>}
      {feedback.status === "error" && <p className="error">{friendlyErrorMessage(feedback.error)}</p>}
      {feedback.status === "ready" && (
        <div className="feedback-result">
          <p>{feedback.text}</p>
          <p className="disclaimer">AI interpretation of the README only, not a verified fact about the code.</p>
        </div>
      )}
    </div>
  );
}
