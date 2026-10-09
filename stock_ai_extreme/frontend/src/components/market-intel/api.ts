/**
 * Phase 23B — shared fetch helper for the market-intelligence components.
 *
 * The backend's versioned API is the only thing components speak. A non-OK
 * response becomes an Error carrying the backend's own message, so the UI can
 * show a real reason instead of a blank panel. Provider credentials never reach
 * the client — the backend strips them, and this layer only ever sees the
 * public payload.
 */
export const MARKET_INTEL_API_BASE =
  import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function parseError(response: Response): Promise<never> {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body?.detail) detail = String(body.detail);
  } catch {
    /* keep the status text */
  }
  throw new Error(detail);
}

export async function marketIntelGet<T>(path: string): Promise<T> {
  const response = await fetch(`${MARKET_INTEL_API_BASE}${path}`);
  if (!response.ok) return parseError(response);
  return response.json() as Promise<T>;
}

export async function marketIntelPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${MARKET_INTEL_API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) return parseError(response);
  return response.json() as Promise<T>;
}

export const formatPrice = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined || Number.isNaN(value)
    ? 'N/A'
    : value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const formatPercent = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined || Number.isNaN(value)
    ? 'N/A'
    : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;

export const formatCompact = (value: number | null | undefined): string => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  return `$${value.toLocaleString()}`;
};
