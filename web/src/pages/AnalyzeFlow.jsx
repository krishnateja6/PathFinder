import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { analyzeRepo } from "../api.js";
import { friendlyErrorMessage } from "../errorMessages.js";

// /api/analyze is a single synchronous request — the backend doesn't
// stream real stage-by-stage progress (see the backend's own notes on
// why: Vercel's Python runtime streaming with a plain BaseHTTPRequestHandler
// isn't something we could verify would hold up). So this shows one
// honest indeterminate state while the request is in flight, not fake
// staged messages we have no way to back up.
export default function AnalyzeFlow() {
  const [searchParams] = useSearchParams();
  const [url, setUrl] = useState(searchParams.get("url") || "");
  const [status, setStatus] = useState("idle"); // idle | loading | error
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    if (!url.trim()) return;
    setStatus("loading");
    setError(null);
    try {
      const result = await analyzeRepo(url.trim());
      navigate(`/r/${result.owner}/${result.repo}/overview`);
    } catch (err) {
      setError(err);
      setStatus("error");
    }
  }

  return (
    <div className="analyze-flow">
      <h1>Analyze a repository</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="github-url">Public GitHub repository URL</label>
        <input
          id="github-url"
          type="text"
          placeholder="https://github.com/owner/repo"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={status === "loading"}
          required
        />
        <button type="submit" disabled={status === "loading"}>
          {status === "loading" ? "Analyzing…" : "Analyze"}
        </button>
      </form>

      {status === "loading" && (
        <p className="status" role="status">
          Fetching, scanning, parsing, and embedding the repository — this can take up to a minute for larger
          repos. Please don't close this tab.
        </p>
      )}

      {status === "error" && (
        <p className="error" role="alert">
          {friendlyErrorMessage(error)}
        </p>
      )}
    </div>
  );
}
