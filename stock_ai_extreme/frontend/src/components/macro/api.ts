/**
 * Phase 23A — shared fetch helper for the macro intelligence components.
 *
 * The external-provider details and endpoint paths live behind the backend's
 * versioned API (spec §15); components only speak these helpers. A non-OK
 * response becomes an Error with the backend's own message so the UI can show
 * a real reason rather than a blank panel.
 */
export const MACRO_API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function macroGet<T>(path: string): Promise<T> {
  const response = await fetch(`${MACRO_API_BASE}${path}`);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
