import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ask, getFile, listFiles } from "../api.js";
import { useApiKeyContext } from "../ApiKeyContext.jsx";
import ApiKeyField from "../components/ApiKeyField.jsx";
import { friendlyErrorMessage } from "../errorMessages.js";
import { useWorkspace } from "../pages/Workspace.jsx";

// Mirrors src/agent/verify.py's CITATION_RE (file.py:line or file.py:line-line)
// so a citation in an answer can be made clickable and jump the viewer to it.
const CITATION_RE = /([\w./\\-]+\.py):(\d+)(?:-(\d+))?/g;

function renderAnswerWithCitations(text, onJump) {
  const parts = [];
  let lastIndex = 0;
  let match;
  CITATION_RE.lastIndex = 0;
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    const [full, file, start, end] = match;
    parts.push(
      <button
        key={`${match.index}-${full}`}
        type="button"
        className="citation-link"
        onClick={() => onJump(file, Number(start), end ? Number(end) : Number(start))}
      >
        {full}
      </button>,
    );
    lastIndex = match.index + full.length;
  }
  parts.push(text.slice(lastIndex));
  return parts;
}

export default function ExplorerChatTab() {
  const { owner, repo } = useWorkspace();
  const { apiKey } = useApiKeyContext();
  const [searchParams, setSearchParams] = useSearchParams();

  const [filesStatus, setFilesStatus] = useState("loading"); // loading | ready | error
  const [paths, setPaths] = useState([]);
  const [activeFile, setActiveFile] = useState(null); // { path, content, highlight: [start, end] | null }
  const [question, setQuestion] = useState("");
  const [chat, setChat] = useState({ status: "idle", answer: null, toolCalls: [], error: null });

  useEffect(() => {
    setFilesStatus("loading");
    listFiles(owner, repo)
      .then((data) => {
        setPaths(data.paths);
        setFilesStatus("ready");
      })
      .catch(() => setFilesStatus("error"));
  }, [owner, repo]);

  async function openFile(path, highlight = null) {
    try {
      const data = await getFile(owner, repo, path);
      setActiveFile({ path, content: data.content, highlight });
    } catch (err) {
      setActiveFile({ path, content: null, highlight: null, error: err });
    }
  }

  // Jump-and-highlight from a link elsewhere (e.g. the Impact tab's
  // affected-call-site list) via ?file=&line= query params.
  useEffect(() => {
    const file = searchParams.get("file");
    const line = searchParams.get("line");
    if (!file || !line) return;
    openFile(file, [Number(line), Number(line)]);
    setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  async function handleAsk(e) {
    e.preventDefault();
    if (!question.trim() || !apiKey.trim()) return;
    setChat({ status: "loading", answer: null, toolCalls: [], error: null });
    try {
      const result = await ask(owner, repo, apiKey.trim(), question.trim());
      setChat({ status: "ready", answer: result.answer, toolCalls: result.tool_calls, error: null });
    } catch (err) {
      setChat({ status: "error", answer: null, toolCalls: [], error: err });
    }
  }

  return (
    <div className="explorer-chat-tab">
      <div className="file-explorer">
        <h3>Files</h3>
        {filesStatus === "loading" && <p className="status">Loading files…</p>}
        {filesStatus === "error" && <p className="error">Couldn't load the file list.</p>}
        {filesStatus === "ready" && paths.length === 0 && <p className="empty-state">No files indexed.</p>}
        {filesStatus === "ready" && paths.length > 0 && (
          <ul className="file-list">
            {paths.map((path) => (
              <li key={path}>
                <button
                  type="button"
                  onClick={() => openFile(path)}
                  className={activeFile?.path === path ? "active" : ""}
                >
                  {path}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="file-viewer">
        {activeFile?.error ? (
          <p className="error">Couldn't load {activeFile.path}: {friendlyErrorMessage(activeFile.error)}</p>
        ) : activeFile ? (
          <>
            <h3>{activeFile.path}</h3>
            <pre className="code-view">
              {activeFile.content.split("\n").map((line, i) => {
                const lineNo = i + 1;
                const isHighlighted =
                  activeFile.highlight && lineNo >= activeFile.highlight[0] && lineNo <= activeFile.highlight[1];
                return (
                  <div key={lineNo} className={isHighlighted ? "code-line highlighted" : "code-line"}>
                    <span className="line-no">{lineNo}</span>
                    <span className="line-text">{line}</span>
                  </div>
                );
              })}
            </pre>
          </>
        ) : (
          <p className="empty-state">Select a file to view its source.</p>
        )}
      </div>

      <div className="chat-panel">
        <h3>Ask a question</h3>
        <ApiKeyField />
        <form onSubmit={handleAsk}>
          <textarea
            rows={3}
            placeholder="e.g. What does the main entry point do?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={chat.status === "loading"}
            required
          />
          <button type="submit" disabled={chat.status === "loading" || !apiKey.trim()}>
            {chat.status === "loading" ? "Asking…" : "Ask"}
          </button>
        </form>

        {chat.status === "loading" && (
          <p className="status">Running the agent loop — this can take a few tool calls, please wait…</p>
        )}
        {chat.status === "error" && <p className="error">{friendlyErrorMessage(chat.error)}</p>}
        {chat.status === "ready" && (
          <div className="chat-answer">
            <p>{renderAnswerWithCitations(chat.answer, (file, start, end) => openFile(file, [start, end]))}</p>
            <details>
              <summary>Agent trace ({chat.toolCalls.length} tool calls)</summary>
              <ol>
                {chat.toolCalls.map((tc, i) => (
                  <li key={i}>
                    {tc.name}({JSON.stringify(tc.input)})
                  </li>
                ))}
              </ol>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}
