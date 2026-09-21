import { Link } from "react-router-dom";

export default function Landing() {
  return (
    <div className="landing">
      <h1>PathFinder</h1>
      <p className="tagline">
        Paste a public GitHub repository and get a grounded architecture overview, ask it questions, and run
        change-impact analysis — backed by a real call/import graph, not just an LLM's guess.
      </p>

      <div className="entry-cards">
        <Link to="/analyze" className="entry-card">
          <h2>Analyze a repository</h2>
          <p>Overview, architecture diagram, file explorer + chat, and change-impact analysis for one repo.</p>
        </Link>
        <Link to="/profile" className="entry-card">
          <h2>Scan a GitHub profile</h2>
          <p>Score and categorize a person's public repos — Products, Projects, and Experiments.</p>
        </Link>
      </div>

      <p className="try-it">
        Not sure where to start?{" "}
        <Link to="/analyze?url=https://github.com/krishnateja6/PathFinder">Try PathFinder on itself</Link> — no
        API key needed to browse the overview, architecture, or impact analysis.
      </p>
    </div>
  );
}
