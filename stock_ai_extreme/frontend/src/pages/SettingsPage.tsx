import { useEffect, useState } from "react";
import BaseCard from "../components/BaseCard";
import BaseTabs from "../components/BaseTabs";
import { useSettingsStore } from "../store/useStore";

const REFRESH_OPTIONS = [
  { id: "10000", label: "10 seconds" },
  { id: "20000", label: "20 seconds" },
  { id: "30000", label: "30 seconds" },
  { id: "60000", label: "1 minute" },
];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("appearance");
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);
  const autoRefresh = useSettingsStore((s) => s.autoRefresh);
  const setAutoRefresh = useSettingsStore((s) => s.setAutoRefresh);
  const refreshInterval = useSettingsStore((s) => s.refreshInterval);
  const setRefreshInterval = useSettingsStore((s) => s.setRefreshInterval);

  // Keep the document theme in sync when changed from this page too.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>Preferences, persisted locally</p>
          <h1>Settings</h1>
        </div>
      </div>

      <BaseTabs
        tabs={[
          { id: "appearance", label: "Appearance" },
          { id: "data", label: "Data & Refresh" },
          { id: "account", label: "Account" },
        ]}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        variant="pills"
      />

      {activeTab === "account" && (
        <BaseCard padding="lg">
          <h2 className="settings-section-title">Account</h2>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Sign in status</div>
              <div className="settings-row-desc">Authentication arrives in a later phase.</div>
            </div>
            <a href="#/login" className="psx-btn psx-btn-secondary">
              Sign In
            </a>
          </div>
        </BaseCard>
      )}

      {activeTab === "data" && (
        <BaseCard padding="lg">
          <h2 className="settings-section-title">Data & Refresh</h2>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Auto-refresh live quotes</div>
              <div className="settings-row-desc">Poll the backend at your chosen interval.</div>
            </div>
            <label className="switch">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              <span className="slider" />
            </label>
          </div>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Refresh interval</div>
              <div className="settings-row-desc">How often quote data refreshes.</div>
            </div>
            <select
              value={String(refreshInterval)}
              onChange={(e) => setRefreshInterval(Number(e.target.value))}
            >
              {REFRESH_OPTIONS.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </BaseCard>
      )}

      {activeTab === "appearance" && (
      <div className="grid-2">
        <BaseCard padding="lg">
          <h2 className="settings-section-title">Appearance</h2>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Theme</div>
              <div className="settings-row-desc">Dark or light terminal — saved on this device.</div>
            </div>
            <div className="chips">
              <button
                className={`chip as-btn ${theme === "dark" ? "active" : ""}`}
                onClick={() => setTheme("dark")}
                style={theme === "dark" ? { borderColor: "#2dd4bf", color: "#2dd4bf" } : undefined}
              >
                Dark
              </button>
              <button
                className={`chip as-btn ${theme === "light" ? "active" : ""}`}
                onClick={() => setTheme("light")}
                style={theme === "light" ? { borderColor: "#2dd4bf", color: "#2dd4bf" } : undefined}
              >
                Light
              </button>
            </div>
          </div>
        </BaseCard>

        <BaseCard padding="lg">
          <h2 className="settings-section-title">Data & Refresh</h2>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Theme</div>
              <div className="settings-row-desc">Applies everywhere in the terminal.</div>
            </div>
            <select value={theme} onChange={(e) => setTheme(e.target.value as "dark" | "light")}>
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </select>
          </div>
        </BaseCard>

        <BaseCard padding="lg">
          <h2 className="settings-section-title">About</h2>
          <div className="settings-row">
            <div>
              <div className="settings-row-label">Version</div>
              <div className="settings-row-desc">Neural Market PSX terminal.</div>
            </div>
            <span className="chip">v2.3.0</span>
          </div>
        </BaseCard>
      </div>
      )}
    </main>
  );
}