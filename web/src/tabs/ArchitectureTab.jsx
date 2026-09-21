import { useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, MiniMap, Panel, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { getArchitecture } from "../api.js";
import { friendlyErrorMessage } from "../errorMessages.js";
import { useWorkspace } from "../pages/Workspace.jsx";

const NODE_STYLE = {
  background: "var(--panel)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: "8px",
  fontFamily: "var(--mono)",
  fontSize: "0.8rem",
  padding: "0.4rem 0.6rem",
};

// Simple grid layout: derive_components() gives us components + edges,
// not positions — clicking a node shows its key files only, per spec
// (no dependents/dependencies/flow panel).
function layoutNodes(components) {
  const columns = Math.ceil(Math.sqrt(components.length)) || 1;
  return components.map((c, i) => ({
    id: c.id,
    data: { label: `${c.id} (${c.files.length})`, files: c.files },
    position: { x: (i % columns) * 260, y: Math.floor(i / columns) * 160 },
    style: NODE_STYLE,
  }));
}

export default function ArchitectureTab() {
  const { owner, repo } = useWorkspace();
  const [state, setState] = useState({ status: "loading", data: null, error: null });
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getArchitecture(owner, repo)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data, error: null });
      })
      .catch((err) => {
        if (!cancelled) setState({ status: "error", data: null, error: err });
      });
    return () => {
      cancelled = true;
    };
  }, [owner, repo]);

  const nodes = useMemo(() => (state.data ? layoutNodes(state.data.components) : []), [state.data]);
  const edges = useMemo(
    () =>
      state.data
        ? state.data.edges.map((e) => ({
            id: `${e.source}->${e.target}`,
            source: e.source,
            target: e.target,
            label: `${e.import_count}`,
            markerEnd: { type: MarkerType.ArrowClosed },
          }))
        : [],
    [state.data],
  );

  if (state.status === "loading") return <p className="status">Deriving architecture…</p>;
  if (state.status === "error") return <p className="error">{friendlyErrorMessage(state.error)}</p>;
  if (state.data.components.length === 0) {
    return <p className="empty-state">No structurally-analyzed files found to build a diagram from.</p>;
  }

  return (
    <div className="architecture-tab">
      {!state.data.within_recommended_range && (
        <p className="warning">
          This repo has {state.data.components.length} top-level components — more than fits a clean diagram.
          Shown as-is rather than forcing an artificial grouping.
        </p>
      )}
      <div className="architecture-canvas">
        <ReactFlow nodes={nodes} edges={edges} onNodeClick={(_, node) => setSelected(node.data)} fitView minZoom={0.2}>
          <Background />
          <Controls />
          {nodes.length > 8 && <MiniMap pannable zoomable />}
          <Panel position="top-right" className="architecture-legend">
            Arrow = imports · label = import count
          </Panel>
        </ReactFlow>
      </div>
      {selected && (
        <aside className="component-detail">
          <h3>{selected.label}</h3>
          <ul>
            {selected.files.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </aside>
      )}
    </div>
  );
}
