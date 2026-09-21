// One shared place for turning an ApiError's `code` into plain-language
// copy, so wording stays consistent across the analyze flow, workspace
// tabs, and profile scan rather than each screen inventing its own.
export function friendlyErrorMessage(err) {
  switch (err?.code) {
    case "invalid_url":
      return "That doesn't look like a public GitHub repository URL. Try something like https://github.com/owner/repo.";
    case "not_found":
      return "That repository couldn't be found. Double-check the URL — it may also be private.";
    case "private_repo":
      return "That repository is private. PathFinder only analyzes public repositories.";
    case "rate_limited":
      return "GitHub's API rate limit was hit. Please try again in a few minutes.";
    case "too_large":
      return err.message || "That repository is too large for this demo's limits.";
    case "network_error":
    case "github_error":
      return "Couldn't reach GitHub right now. Please try again.";
    case "not_analyzed":
      return "This repository hasn't been analyzed yet.";
    case "invalid_username":
      return "That doesn't look like a valid GitHub username.";
    default:
      return err?.message || "Something went wrong. Please try again.";
  }
}
