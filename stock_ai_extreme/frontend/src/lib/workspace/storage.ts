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

/**
 * Phase 12 — is there an authenticated session?
 *
 * Auth is not wired into this build yet, so this reads the token key the app
 * will set (`neural-market-auth-token`). Until then it returns false and every
 * caller keeps using localStorage — which is exactly why no existing behaviour
 * changes.
 */
export function hasAuthSession(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return Boolean(window.localStorage.getItem("neural-market-auth-token"));
  } catch {
    return false;
  }
}

let activeStorage: WorkspaceStorage | null = null;

/**
 * Active storage. Prefers the backend adapter when a session exists (it already
 * degrades to localStorage on any network failure, so no layout is ever lost);
 * otherwise localStorage directly.
 */
export function getWorkspaceStorage(): WorkspaceStorage {
  if (activeStorage) return activeStorage;
  activeStorage = hasAuthSession() ? createBackendStorage() : localStorageWorkspaceStorage;
  return activeStorage;
}

/** Test/seam hook — force a specific storage implementation. */
export function setWorkspaceStorage(storage: WorkspaceStorage | null): void {
  activeStorage = storage;
}

// ---------------------------------------------------------------------------
// Phase 12 — import / export / permalink + custom workspace presets
// ---------------------------------------------------------------------------

export interface WorkspaceExport {
  version: number;
  exportedAt: string;
  workspaces: SavedWorkspace[];
}

const EXPORT_FORMAT_VERSION = 1;

/** Serialize saved workspaces to a portable, self-describing JSON document. */
export function exportWorkspacesJSON(workspaces: readonly SavedWorkspace[]): string {
  const document: WorkspaceExport = {
    version: EXPORT_FORMAT_VERSION,
    exportedAt: new Date().toISOString(),
    workspaces: workspaces.map((workspace) => ({ ...workspace })),
  };
  return JSON.stringify(document, null, 2);
}

/**
 * Parse an exported document back into saved workspaces.
 *
 * Accepts both the wrapped document above and a bare array (someone hand-editing
 * the file should not be punished for dropping the envelope). Throws with an
 * actionable message on anything that is not a valid, current-version layout.
 */
export function parseWorkspacesJSON(raw: string): SavedWorkspace[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("That file is not valid JSON.");
  }

  const candidate = Array.isArray(parsed)
    ? parsed
    : typeof parsed === "object" && parsed !== null && Array.isArray((parsed as WorkspaceExport).workspaces)
      ? (parsed as WorkspaceExport).workspaces
      : null;

  if (!candidate) {
    throw new Error("No workspaces found in that file.");
  }

  const workspaces = candidate.filter(
    (entry): entry is SavedWorkspace =>
      Boolean(entry) &&
      typeof entry === "object" &&
      typeof (entry as SavedWorkspace).id === "string" &&
      typeof (entry as SavedWorkspace).name === "string" &&
      versionOk((entry as SavedWorkspace).layout)
  );

  if (workspaces.length === 0) {
    throw new Error("That file contains no workspaces compatible with this version.");
  }
  return workspaces;
}

/** A shareable link that opens the workspace by id. */
export function buildWorkspacePermalink(workspaceId: string, baseUrl?: string): string {
  const base = baseUrl ?? (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/workspace?ws=${encodeURIComponent(workspaceId)}`;
}

/** Read the `?ws=` share id from a query string (or the current URL). */
export function readWorkspaceIdFromLocation(search?: string): string | null {
  const query = search ?? (typeof window !== "undefined" ? window.location.search : "");
  if (!query) return null;
  const params = new URLSearchParams(query.startsWith("?") ? query : `?${query}`);
  const id = params.get("ws");
  return id && id.trim() ? id.trim() : null;
}

/** Duplicate a saved workspace under a new id/name (custom preset from an existing one). */
export function duplicateSavedWorkspace(record: SavedWorkspace, name?: string): SavedWorkspace {
  const now = new Date().toISOString();
  const copyId = `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    ...record,
    id: copyId,
    name: name?.trim() || `${record.name} copy`,
    layout: { ...record.layout, workspaceId: copyId, updatedAt: now },
    createdAt: now,
    updatedAt: now,
  };
}

/** Rename a saved workspace in place (id and layout are untouched). */
export function renameSavedWorkspace(record: SavedWorkspace, name: string): SavedWorkspace {
  const trimmed = name.trim();
  return { ...record, name: trimmed || record.name, updatedAt: new Date().toISOString() };
}

// ---------------------------------------------------------------------------
// Portable share links
//
// A link that carries only a workspace *id* can only ever resolve on the device
// that saved it (localStorage is per-browser). The payload below is therefore
// self-contained: the layout travels inside the URL, so a link opened on another
// machine imports the workspace and opens it. `?ws=` is kept alongside so a
// same-device link resolves to the existing record instead of duplicating it.
// ---------------------------------------------------------------------------

const SHARE_FORMAT_VERSION = 1;

/** UTF-8-safe base64url (URLs allow neither `+` `/` nor padding `=`). */
function toBase64Url(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/** Encode a workspace into a URL-safe, self-describing payload. */
export function encodeWorkspaceShare(record: SavedWorkspace): string {
  return toBase64Url(JSON.stringify({ v: SHARE_FORMAT_VERSION, workspace: record }));
}

/**
 * A shareable link that opens the workspace — on this device via `ws`, and on
 * any other via the embedded `w` payload.
 */
export function buildWorkspaceShareLink(record: SavedWorkspace, baseUrl?: string): string {
  const base =
    baseUrl ??
    (typeof window !== "undefined" ? `${window.location.origin}${window.location.pathname}` : "");
  return `${base}?ws=${encodeURIComponent(record.id)}&w=${encodeWorkspaceShare(record)}`;
}

/**
 * Decode a shared workspace from a query string, or `null` when absent/invalid.
 * Version and layout are validated so a hand-edited or truncated link is
 * rejected rather than half-loaded.
 */
export function readSharedWorkspace(search?: string): SavedWorkspace | null {
  const query = search ?? (typeof window !== "undefined" ? window.location.search : "");
  if (!query) return null;
  const params = new URLSearchParams(query.startsWith("?") ? query : `?${query}`);
  const encoded = params.get("w");
  if (!encoded) return null;
  try {
    const decoded = JSON.parse(fromBase64Url(encoded)) as { v?: number; workspace?: SavedWorkspace };
    if (decoded?.v !== SHARE_FORMAT_VERSION) return null;
    const workspace = decoded.workspace;
    if (
      !workspace ||
      typeof workspace.id !== "string" ||
      typeof workspace.name !== "string" ||
      !versionOk(workspace.layout)
    ) {
      return null;
    }
    return workspace;
  } catch {
    return null;
  }
}
