import { Suspense, useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import PSXHeader from "./components/PSXHeader";
import GlobalSearch from "./components/GlobalSearch";
import RouteFallback from "./components/RouteFallback";
import { AIAssistantPanel } from "./components/ai/AIAssistantPanel";
import { useAIStore } from "./store/useAIStore";
import { useSettingsStore, useUIStore } from "./store/useStore";

export default function Layout() {
  const [searchOpen, setSearchOpen] = useState(false);
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);
  const mobileMenuOpen = useUIStore((s) => s.mobileMenuOpen);
  const setMobileMenuOpen = useUIStore((s) => s.setMobileMenuOpen);

  // Phase 10: when the assistant rail is open the page gets a gutter so no
  // content hides underneath it. Expanded mode overlays instead (it is a
  // focused reading view), so it never reflows the page.
  const aiPanelOpen = useAIStore((s) => s.isPanelOpen);
  const aiExpanded = useAIStore((s) => s.isExpanded);
  const aiDocked = aiPanelOpen && !aiExpanded;

  // Apply the persisted theme to the document root so CSS variables switch.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    document.body.classList.toggle("ai-panel-open", aiPanelOpen);
    return () => document.body.classList.remove("ai-panel-open");
  }, [aiPanelOpen]);

  return (
    <div className={`psx-app${aiDocked ? " ai-docked" : ""}`}>
      <PSXHeader
        theme={theme}
        toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        isMobileMenuOpen={mobileMenuOpen}
        toggleMobileMenu={() => setMobileMenuOpen(!mobileMenuOpen)}
        onSearchOpen={() => setSearchOpen(true)}
      />
      <GlobalSearch isOpen={searchOpen} onClose={() => setSearchOpen(false)} />
      <main className="psx-main">
        {/* Pages are code-split; keep the shell mounted while a chunk loads. */}
        <Suspense fallback={<RouteFallback />}>
          <Outlet />
        </Suspense>
      </main>
      <footer className="psx-footer">
        <span className="psx-footer-brand">NEURAL MARKET</span>
        <span>AI-powered market analytics — educational purposes only, not investment advice.</span>
        {/* `Link` (not `href="#/…"`): the app mounts a BrowserRouter, so a bare
            hash link only sets a fragment and never changes the route. */}
        <div className="psx-footer-links">
          <Link to="/workspace">Workspace</Link>
          <Link to="/charts">Charts</Link>
          <Link to="/settings">Settings</Link>
          <Link to="/alerts">Alerts</Link>
          <Link to="/screener">Screener</Link>
          <Link to="/sentiment">Sentiment</Link>
        </div>
      </footer>

      {/* Phase 10: context-aware AI assistant (docked rail / mobile sheet) */}
      <AIAssistantPanel />
    </div>
  );
}
