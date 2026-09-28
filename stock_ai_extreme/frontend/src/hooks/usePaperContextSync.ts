/**
 * Phase 20 — context sync.
 *
 * Any page that shows an instrument publishes it here, and the Quick Order
 * ticket reflects it (spec §2). The hook only writes when a primitive field
 * actually changes, so re-renders cannot cause an update loop.
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { usePaperOrderStore, type PaperContext } from "../store/usePaperOrderStore";

export type PaperContextInput = Omit<PaperContext, "page">;

export function usePaperContextSync(context: PaperContextInput | null | undefined) {
  const setContext = usePaperOrderStore((state) => state.setContext);
  const pathname = useLocation().pathname;

  const symbol = context?.symbol || "";
  const kind = context?.kind;
  const displayName = context?.displayName;
  const currency = context?.currency ?? null;
  const quoteMode = context?.quoteMode;
  const marketId = context?.marketId ?? null;
  const question = context?.question ?? null;
  const closeTime = context?.closeTime ?? null;
  const category = context?.category ?? null;
  const observedPrice = context?.observedPrice ?? null;
  const observedTimestamp = context?.observedTimestamp ?? null;
  const source = context?.source ?? null;
  const probabilityYes = context?.probabilityYes ?? null;
  const probabilityNo = context?.probabilityNo ?? null;

  useEffect(() => {
    if (!symbol) return;
    setContext({
      symbol,
      kind: kind ?? "STOCK",
      displayName,
      currency,
      quoteMode,
      page: pathname,
      marketId,
      question,
      closeTime,
      category,
      observedPrice,
      observedTimestamp,
      source,
      probabilityYes,
      probabilityNo,
    });
    // Deliberately keyed on the primitive fields (never the object identity):
    // pages commonly build the context inline on every render.
  }, [
    symbol,
    kind,
    displayName,
    currency,
    quoteMode,
    pathname,
    marketId,
    question,
    closeTime,
    category,
    observedPrice,
    observedTimestamp,
    source,
    probabilityYes,
    probabilityNo,
    setContext,
  ]);
}
