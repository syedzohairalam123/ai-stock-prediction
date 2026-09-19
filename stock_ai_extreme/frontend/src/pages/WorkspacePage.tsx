/**
 * Phase 12 — the workspace route (§1).
 *
 * A thin shell: hydrates the persisted store once and renders the grid. All
 * behaviour lives in the engine, the store and the grid — this page never
 * touches widget internals, so it stays out of the render-critical path.
 */
import { useEffect } from "react";
import WorkspaceGrid from "../components/workspace/WorkspaceGrid";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

export default function WorkspacePage() {
  const ready = useWorkspaceStore((s) => s.ready);
  const hydrate = useWorkspaceStore((s) => s.hydrate);

  useEffect(() => {
    if (!ready) void hydrate();
  }, [ready, hydrate]);

  if (!ready) {
    return (
      <main className="ws-page" aria-busy="true">
        <div className="ws-loading">
          <p>Loading workspace…</p>
          <div className="skeleton" style={{ height: 320 }} />
        </div>
      </main>
    );
  }

  return (
    <main className="ws-page">
      <header className="ws-page-head">
        <div>
          <p>Modular financial desktop</p>
          <h1>Workspace</h1>
        </div>
        <span className="ws-page-note">
          Drag headers to move · drag edges to resize · layouts persist per preset
        </span>
      </header>
      <WorkspaceGrid />
    </main>
  );
}
