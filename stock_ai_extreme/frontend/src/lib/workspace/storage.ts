/**
 * Phase 12 — WorkspaceStorage (spec §15).
 *
 * The store only talks to the `WorkspaceStorage` interface (types.ts), never to
 * `window.localStorage` directly, so an authenticated backend can take over
 * without touching a single widget:
 *
 *   localStorageWorkspaceStorage  — today's implementation (zustand-persist
 *                                   style key, same architecture as the rest
 *                                   of the app)
 *   createBackendStorage          — prepared adapter: same contract over HTTP
 *                                   (wired when auth lands; falls back to
 *                                   localStorage until then)
 *
 * Versioned keys + a schema version let future migrations upgrade old layouts
 * instead of crashing on them.
 */
import type { PresetId, SavedWorkspace, WorkspaceLayout, WorkspaceStorage } from "./types";
import { LAYOUT_VERSION } from "./engine";

const ACTIVE_KEY = "neural-market-workspace-active-v1";
const SAVED_KEY = "neural-market-workspace-saved-v1";

function readJSON<T>(key: string): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null; // corrupted entry or storage unavailable — treat as absent
  }
}

function writeJSON(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota or privacy mode — persistence is best-effort, the UI keeps working.
  }
}

/** Old layouts whose `version` differs are dropped rather than half-loaded. */
function versionOk(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    "version" in (value as Record<string, unknown>) &&
    (value as Record<string, unknown>).version === LAYOUT_VERSION
  );
}

export const localStorageWorkspaceStorage: WorkspaceStorage = {
  async loadActive(): Promise<Record<PresetId, WorkspaceLayout> | null> {
    const parsed = readJSON<Record<PresetId, WorkspaceLayout>>(ACTIVE_KEY);
    if (!parsed || typeof parsed !== "object") return null;
    const ids: PresetId[] = ["chart-chat", "trading", "research"];
    const ok = ids.every((id) => versionOk(parsed[id]));
    return ok ? parsed : null;
  },
  async saveActive(layouts: Record<PresetId, WorkspaceLayout>): Promise<void> {
    writeJSON(ACTIVE_KEY, layouts);
  },
  async loadSaved(): Promise<SavedWorkspace[]> {
    const parsed = readJSON<SavedWorkspace[]>(SAVED_KEY);
    return Array.isArray(parsed) ? parsed.filter((s) => s && versionOk(s.layout)) : [];
  },
  async saveSaved(workspaces: SavedWorkspace[]): Promise<void> {
    writeJSON(SAVED_KEY, workspaces);
  },
};

/**
 * Prepared backend adapter (spec §15: "prepare for authenticated backend
 * persistence"). Implements the same contract over the existing axios client;
 * the app flips to it by exporting it from `getWorkspaceStorage()` once auth
 * exists. Network failures degrade to localStorage so the UI never blocks.
 */
export function createBackendStorage(baseUrl: string = "/api/workspace"): WorkspaceStorage {
  const call = async (path: string, init?: RequestInit): Promise<Response> => {
    const res = await fetch(`${baseUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
    if (!res.ok) throw new Error(`workspace storage: ${res.status}`);
    return res;
  };
  return {
    async loadActive() {
      try {
        const res = await call("/layouts");
        const data = (await res.json()) as Record<PresetId, WorkspaceLayout>;
        return data ?? null;
      } catch {
        return localStorageWorkspaceStorage.loadActive();
      }
    },
    async saveActive(layouts) {
      try {
        await call("/layouts", { method: "PUT", body: JSON.stringify(layouts) });
      } catch {
        await localStorageWorkspaceStorage.saveActive(layouts);
      }
    },
    async loadSaved() {
      try {
        const res = await call("/saved");
        const data = (await res.json()) as SavedWorkspace[];
        return Array.isArray(data) ? data : [];
      } catch {
        return localStorageWorkspaceStorage.loadSaved();
      }
    },
    async saveSaved(workspaces) {
      try {
        await call("/saved", { method: "PUT", body: JSON.stringify(workspaces) });
      } catch {
        await localStorageWorkspaceStorage.saveSaved(workspaces);
      }
    },
  };
}

/** Active storage — localStorage now; swap the return for the backend later. */
export function getWorkspaceStorage(): WorkspaceStorage {
  return localStorageWorkspaceStorage;
}
