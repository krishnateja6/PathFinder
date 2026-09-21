import { createContext, useContext } from "react";
import { useApiKey } from "./useApiKey.js";

const ApiKeyContext = createContext(null);

export function ApiKeyProvider({ children }) {
  const [apiKey, setApiKey] = useApiKey();
  return <ApiKeyContext.Provider value={{ apiKey, setApiKey }}>{children}</ApiKeyContext.Provider>;
}

export function useApiKeyContext() {
  const ctx = useContext(ApiKeyContext);
  if (!ctx) throw new Error("useApiKeyContext must be used inside ApiKeyProvider");
  return ctx;
}
