const form = document.getElementById("ask-form");
const apiKeyInput = document.getElementById("api-key");
const questionInput = document.getElementById("question");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
const answerTextEl = document.getElementById("answer-text");
const traceListEl = document.getElementById("trace-list");
const traceCountEl = document.getElementById("trace-count");

const STORAGE_KEY = "pathfinder-demo-anthropic-key";

// Convenience only: kept in this tab's sessionStorage so you don't have to
// re-paste the key between questions. Cleared automatically when the tab
// closes, and never sent anywhere except this page's own /api/ask request.
try {
  const savedKey = sessionStorage.getItem(STORAGE_KEY);
  if (savedKey) apiKeyInput.value = savedKey;
} catch {
  // sessionStorage can throw in private-browsing contexts; ignore.
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Asking..." : "Ask";
  statusEl.hidden = !isLoading;
  if (isLoading) statusEl.textContent = "Running the agent loop — this can take a few tool calls, please wait...";
}

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
  resultEl.hidden = true;
}

function showResult(answer, toolCalls) {
  errorEl.hidden = true;
  resultEl.hidden = false;
  answerTextEl.textContent = answer;

  traceCountEl.textContent = String(toolCalls.length);
  traceListEl.innerHTML = "";
  for (const call of toolCalls) {
    const li = document.createElement("li");
    li.textContent = `${call.name}(${JSON.stringify(call.input)})`;
    traceListEl.appendChild(li);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const apiKey = apiKeyInput.value.trim();
  const question = questionInput.value.trim();
  if (!apiKey || !question) return;

  try {
    sessionStorage.setItem(STORAGE_KEY, apiKey);
  } catch {
    // ignore storage failures, the request still works without it
  }

  setLoading(true);
  errorEl.hidden = true;
  resultEl.hidden = true;

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ anthropic_api_key: apiKey, question }),
    });
    const data = await response.json();

    if (!response.ok) {
      showError(data.error || `request failed with status ${response.status}`);
      return;
    }

    showResult(data.answer, data.tool_calls || []);
  } catch {
    showError("Network error — the request didn't reach the server.");
  } finally {
    setLoading(false);
  }
});
