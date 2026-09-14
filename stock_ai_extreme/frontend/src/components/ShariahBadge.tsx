import { getStockMeta } from "../lib/psxMarket";

/**
 * Shariah-status badge.
 *
 * Only shown for symbols in the known PSX universe, where the screening flag is
 * real reference data (`lib/psxMarket.ts`). For anything else (US tickers,
 * crypto) it renders nothing rather than inventing a compliance claim — a
 * green "Shariah" chip must never appear without a basis for it.
 */
export default function ShariahBadge({ symbol }: { symbol: string }) {
  const meta = getStockMeta(symbol);
  if (!meta) return null;
  const compliant = meta.isIslamic;
  return (
    <span
      className={`shariah-badge ${compliant ? "shariah-yes" : "shariah-no"}`}
      role="img"
      aria-label={compliant ? "Shariah-compliant screening" : "Not flagged as Shariah-compliant"}
      title={
        compliant
          ? "Flagged Shariah-compliant in the PSX screening reference set"
          : "Not flagged Shariah-compliant in the PSX screening reference set"
      }
    >
      <span aria-hidden>{compliant ? "☾" : "○"}</span> {compliant ? "Shariah" : "Conventional"}
    </span>
  );
}
