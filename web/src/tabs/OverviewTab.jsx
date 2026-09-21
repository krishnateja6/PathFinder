import { useWorkspace } from "../pages/Workspace.jsx";

const STRUCTURAL_LANGUAGES = new Set(["Python"]);

export default function OverviewTab() {
  const { owner, repo, analysis } = useWorkspace();
  const languages = Object.entries(analysis.languages || {});

  return (
    <div className="overview-tab">
      <section>
        <h2>Summary</h2>
        <dl className="summary-grid">
          <div>
            <dt>Repository</dt>
            <dd>
              {owner}/{repo}
            </dd>
          </div>
          <div>
            <dt>Default branch</dt>
            <dd>{analysis.default_branch}</dd>
          </div>
          <div>
            <dt>Indexed commit</dt>
            <dd>{analysis.commit_sha.slice(0, 7)}</dd>
          </div>
          <div>
            <dt>Files</dt>
            <dd>{analysis.file_count}</dd>
          </div>
          <div>
            <dt>Indexed chunks</dt>
            <dd>{analysis.chunk_count}</dd>
          </div>
        </dl>
      </section>

      <section>
        <h2>Detected tech stack</h2>
        {languages.length === 0 ? (
          <p className="empty-state">No recognized source files detected.</p>
        ) : (
          <ul className="language-list">
            {languages.map(([language, count]) => (
              <li key={language} className={STRUCTURAL_LANGUAGES.has(language) ? "structural" : "search-only"}>
                <span className="language-name">{language}</span>
                <span className="language-count">{count} files</span>
                <span className="language-badge">
                  {STRUCTURAL_LANGUAGES.has(language) ? "Full structural analysis" : "Searchable, not graphed"}
                </span>
              </li>
            ))}
          </ul>
        )}
        {analysis.frameworks_hint?.length > 0 && (
          <p className="frameworks-hint">Detected manifests: {analysis.frameworks_hint.join(", ")}</p>
        )}
      </section>
    </div>
  );
}
