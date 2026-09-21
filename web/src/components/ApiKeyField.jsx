import { useApiKeyContext } from "../ApiKeyContext.jsx";

// Shared between the Chat tab and Profile Scan's Deep AI feedback — one
// visitor-supplied key covers both, per spec.
export default function ApiKeyField() {
  const { apiKey, setApiKey } = useApiKeyContext();

  return (
    <div className="api-key-field">
      <label htmlFor="anthropic-key">
        Your Anthropic API key
        <span className="hint">
          Sent with each request only, used once, never stored or logged by this server. Kept in this browser tab
          only. <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer">
            Get a key
          </a>
          .
        </span>
      </label>
      <input
        id="anthropic-key"
        type="password"
        autoComplete="off"
        placeholder="sk-ant-..."
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
      />
    </div>
  );
}
