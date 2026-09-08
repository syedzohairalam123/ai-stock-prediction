/** Shared API base + fetch helpers for every page. */
export const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function getJSON<T = any>(path: string, fallback?: T): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function postJSON<T = any>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
    throw new Error(detail);
  }
  return res.json();
}

export const iso = (d: Date) => d.toISOString().slice(0, 10);
export const daysAgo = (n: number) => iso(new Date(Date.now() - n * 86400000));

export function Pct({ v, digits = 2 }: { v: number | null | undefined; digits?: number }) {
  if (v === null || v === undefined) return <span>—</span>;
  return <span className={v >= 0 ? "pos" : "neg"}>{v >= 0 ? "+" : ""}{v.toFixed(digits)}%</span>;
}

export function Money({ v, prefix = "$" }: { v: number | null | undefined; prefix?: string }) {
  if (v === null || v === undefined) return <span>—</span>;
  return <span>{prefix}{v.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>;
}

export function Num({ v, digits = 2 }: { v: number | null | undefined; digits?: number }) {
  if (v === null || v === undefined) return <span>—</span>;
  return <span>{v.toLocaleString(undefined, { maximumFractionDigits: digits })}</span>;
}

/** Renders the `data_meta` block every backend route attaches (status + source). */
export function MetaBadge({ meta }: { meta?: { status?: string; source?: string } | null }) {
  if (!meta?.status) return null;
  return <span className={`freshness ${meta.status.toLowerCase()}`}>{meta.status}{meta.source ? ` · ${meta.source}` : ""}</span>;
}

/** Compact big-number card used by the dashboard-style pages. */
export function StatCard({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return <div className="card"><div className="k">{label}</div><div className="v">{value ?? "—"}</div>{sub && <div className="s">{sub}</div>}</div>;
}
