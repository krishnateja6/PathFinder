// Thin fetch wrappers for the 8 /api/* endpoints. Every function returns
// the parsed JSON body on success and throws an ApiError (carrying the
// backend's error code) on failure, so callers can branch on `err.code`
// for friendly, specific messaging rather than a generic "something
// went wrong."

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(data.error || `Request failed (${response.status})`, data.code, response.status);
  }
  return data;
}

export const analyzeRepo = (githubUrl) => request("POST", "/api/analyze", { github_url: githubUrl });

export const getAnalysis = (owner, repo) =>
  request("GET", `/api/analysis?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}`);

export const getArchitecture = (owner, repo) =>
  request("GET", `/api/architecture?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}`);

export const listFiles = (owner, repo) =>
  request("GET", `/api/files?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}`);

export const getFile = (owner, repo, path) =>
  request(
    "GET",
    `/api/files?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`,
  );

export const ask = (owner, repo, anthropicApiKey, question) =>
  request("POST", "/api/ask", { owner, repo, anthropic_api_key: anthropicApiKey, question });

export const getImpact = (owner, repo, symbol) =>
  request(
    "GET",
    `/api/impact?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo)}&symbol=${encodeURIComponent(symbol)}`,
  );

export const scanProfile = (githubUsername) => request("POST", "/api/profile_scan", { github_username: githubUsername });

export const getProfileFeedback = (repoFullName, anthropicApiKey) =>
  request("POST", "/api/profile_feedback", { repo_full_name: repoFullName, anthropic_api_key: anthropicApiKey });
