/**
 * Phase 22C — crypto subcategory navigation (spec §1/§2).
 *
 * Each tab maps to a real backend dataset/query — never a colour change:
 *
 *   ALL           → quote + candles + analytics + multi-timeframe (market data)
 *   PRE-MARKET    → /categories/pre-session  (continuous-market boundaries)
 *   INSTITUTIONS  → /categories/institutions/{symbol} (disclosed holdings)
 *   TARGETS       → /targets/{symbol} + /threshold/{symbol} + /on-date/{symbol}
 *   INDUSTRY      → /categories/industry (documented taxonomy + provider categories)
 *
 * A category whose source returns nothing renders `NO DATA AVAILABLE`; it is
 * never filled with invented records.
 */
export type CryptoSubcategory = "ALL" | "PRE-MARKET" | "INSTITUTIONS" | "TARGETS" | "INDUSTRY";

export const CRYPTO_SUBCATEGORIES: { id: CryptoSubcategory; label: string; hint: string }[] = [
  { id: "ALL", label: "ALL", hint: "Real-time market data, analytics and multi-timeframe view" },
  { id: "PRE-MARKET", label: "PRE-MARKET", hint: "Continuous 24/7 session boundaries and upcoming catalysts" },
  { id: "INSTITUTIONS", label: "INSTITUTIONS", hint: "Publicly disclosed institutional holdings and vehicles" },
  { id: "TARGETS", label: "TARGETS", hint: "Analytical target ladder, threshold analysis and history" },
  { id: "INDUSTRY", label: "INDUSTRY", hint: "Documented industry taxonomy and real provider categories" },
];

export function CryptoSubcategoryNav({
  active,
  onChange,
}: {
  active: CryptoSubcategory;
  onChange: (next: CryptoSubcategory) => void;
}) {
  return (
    <nav className="crypto-subnav" aria-label="Crypto subcategories">
      <div className="crypto-subnav-tabs" role="tablist" aria-label="Crypto subcategory">
        {CRYPTO_SUBCATEGORIES.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`crypto-subtab-${item.id}`}
            aria-selected={active === item.id}
            aria-controls={`crypto-subpanel-${item.id}`}
            className={active === item.id ? "active" : undefined}
            title={item.hint}
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </nav>
  );
}

/** Human help text for the active subcategory. */
export function subcategoryHint(id: CryptoSubcategory): string {
  return CRYPTO_SUBCATEGORIES.find((item) => item.id === id)?.hint ?? "";
}

export default CryptoSubcategoryNav;
