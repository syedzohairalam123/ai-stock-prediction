import { Suspense, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import PSXHeader from "./components/PSXHeader";
import GlobalSearch from "./components/GlobalSearch";
import RouteFallback from "./components/RouteFallback";
import { useSettingsStore, useUIStore } from "./store/useStore";

export default function Layout() {
  const [searchOpen, setSearchOpen] = useState(false);
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);
  const mobileMenuOpen = useUIStore((s) => s.mobileMenuOpen);
  const setMobileMenuOpen = useUIStore((s) => s.setMobileMenuOpen);

  // Apply the persisted theme to the document root so CSS variables switch.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return (
    <div className="psx-app">
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
        <div className="psx-footer-links">
          <a href="#/settings">Settings</a>
          <a href="#/alerts">Alerts</a>
          <a href="#/screener">Screener</a>
          <a href="#/sentiment">Sentiment</a>
        </div>
      </footer>
    </div>
  );
}