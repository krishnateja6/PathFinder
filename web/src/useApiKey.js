import { useCallback, useState } from "react";

// The visitor's own Anthropic key. Kept only in this tab's sessionStorage
// as a convenience (so it doesn't need re-pasting between the Chat tab
// and Profile Scan's Deep AI feedback — the spec calls for one key
// covering both). Never sent anywhere except the /api/ask and
// /api/profile_feedback requests it's explicitly attached to.
const STORAGE_KEY = "pathfinder-anthropic-key";

export function useApiKey() {
  const [apiKey, setApiKeyState] = useState(() => {
    try {
      return sessionStorage.getItem(STORAGE_KEY) || "";
    } catch {
      return "";
    }
  });

  const setApiKey = useCallback((value) => {
    setApiKeyState(value);
    try {
      sessionStorage.setItem(STORAGE_KEY, value);
    } catch {
      // sessionStorage can throw in private-browsing contexts; ignore.
    }
  }, []);

  return [apiKey, setApiKey];
}
